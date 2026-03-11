from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import re
import time
from types import SimpleNamespace
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.adapters.registry import get_provider_class
from app.core.logging import get_logger
from app.core.red_team_prompts import DEFAULT_EVALUATOR_PROMPT_TEMPLATE
from app.core.secrets import SecretManager
from app.domain import models
from app.services.audit_service import record_event


logger = get_logger("promptops.red_team_runner")


def _build_endpoint_config(endpoint: models.Endpoint) -> Any:
    return SimpleNamespace(
        name=endpoint.name,
        provider=endpoint.provider,
        base_url=endpoint.base_url,
        endpoint_path=endpoint.endpoint_path,
        model_name=endpoint.model_name,
        auth_type=endpoint.auth_type,
        auth_header=endpoint.auth_header,
        auth_prefix=endpoint.auth_prefix,
        custom_headers=endpoint.custom_headers,
        default_params=endpoint.default_params,
        request_mode=getattr(endpoint, "request_mode", "responses"),
        timeout=endpoint.timeout,
        retry_count=endpoint.retry_count,
        response_paths=endpoint.response_paths,
        response_type=endpoint.response_type,
    )


def _build_evaluator_prompt(
    case_spec: dict[str, Any],
    model_response: str,
    evaluator_prompt_template: str | None = None,
) -> str:
    template = (evaluator_prompt_template or "").strip() or DEFAULT_EVALUATOR_PROMPT_TEMPLATE
    rendered_prompt = template
    replacements = {
        "{{PROMPT}}": str(case_spec.get("prompt") or ""),
        "{{PURPOSE}}": str(case_spec.get("purpose") or ""),
        "{{EXPECTED_RESULT}}": str(case_spec.get("expected_result") or ""),
        "{{RELEVANCE}}": str(case_spec.get("relevance") if case_spec.get("relevance") is not None else ""),
        "{{MODEL_RESPONSE}}": str(model_response or ""),
        "{{SUITE_NAME}}": str(case_spec.get("suite_name") or ""),
    }
    for marker, value in replacements.items():
        rendered_prompt = rendered_prompt.replace(marker, value)
    return rendered_prompt


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_verdict(value: Any) -> str:
    verdict = str(value or "").strip().lower()
    if verdict in {"pass", "passed"}:
        return "pass"
    if verdict in {"fail", "failed"}:
        return "fail"
    return "fail"


def _normalize_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return 0.0
    if parsed > 100:
        return 100.0
    return parsed


def _execute_red_team_case(
    target_provider_class: type,
    evaluator_provider_class: type,
    target_endpoint_config: Any,
    evaluator_endpoint_config: Any,
    target_variables: dict[str, Any],
    evaluator_variables: dict[str, Any],
    verify_ssl: bool,
    case_spec: dict[str, Any],
    default_timeout: int | None,
    max_retries: int,
    evaluator_prompt_template: str | None,
) -> dict[str, Any]:
    status = "error"
    response_text = None
    error_message = None
    latency_ms = None
    evaluation_latency_ms = None
    evaluator_response = None
    evaluation_summary = None
    evaluation_score = None
    evaluation_verdict = None
    evaluation_verdict_justification = None
    evaluation_score_justification = None

    logger.debug(
        "Executing red team case case_id=%s suite=%s",
        case_spec["case_id"],
        case_spec.get("suite_name"),
    )

    request_params: dict[str, Any] = {}
    if default_timeout is not None:
        request_params["timeout"] = int(default_timeout)

    for attempt in range(max_retries + 1):
        try:
            target_provider = target_provider_class(target_endpoint_config, target_variables, verify_ssl=verify_ssl)
            target_response = target_provider.send_prompt(
                [{"role": "user", "content": case_spec["prompt"]}],
                request_params,
            )
            response_text = target_response.content
            latency_ms = target_response.latency_ms

            evaluator_prompt = _build_evaluator_prompt(
                case_spec,
                response_text or "",
                evaluator_prompt_template=evaluator_prompt_template,
            )
            evaluator_provider = evaluator_provider_class(
                evaluator_endpoint_config,
                evaluator_variables,
                verify_ssl=verify_ssl,
            )
            evaluator_result = evaluator_provider.send_prompt(
                [{"role": "user", "content": evaluator_prompt}],
                request_params,
            )
            evaluator_response = evaluator_result.content
            evaluation_latency_ms = evaluator_result.latency_ms

            parsed_eval = _extract_json_payload(evaluator_response or "")
            if parsed_eval is None:
                evaluation_verdict = "fail"
                evaluation_summary = "Evaluator did not return valid JSON."
                evaluation_verdict_justification = "Evaluator response did not match the required JSON schema."
                evaluation_score_justification = "Score unavailable because evaluator JSON parsing failed."
                status = "failed"
            else:
                evaluation_verdict = _normalize_verdict(parsed_eval.get("verdict"))
                evaluation_score = _normalize_score(parsed_eval.get("score"))
                evaluation_summary = str(parsed_eval.get("summary") or "").strip() or None
                evaluation_verdict_justification = (
                    str(parsed_eval.get("verdict_justification") or "").strip() or evaluation_summary
                )
                evaluation_score_justification = str(parsed_eval.get("score_justification") or "").strip() or None
                status = "passed" if evaluation_verdict == "pass" else "failed"
            break
        except Exception as exc:
            if attempt < max_retries:
                logger.warning(
                    "Red team execution failed, retrying case_id=%s attempt=%s/%s error=%s",
                    case_spec["case_id"],
                    attempt + 2,
                    max_retries + 1,
                    exc,
                )
                time.sleep(0.4 * (attempt + 1))
                continue
            logger.exception("Red team execution failed for case_id=%s", case_spec["case_id"])
            status = "error"
            error_message = str(exc)
            break

    return {
        "case_id": case_spec["case_id"],
        "prompt": case_spec["prompt"],
        "status": status,
        "response_text": response_text,
        "latency_ms": latency_ms,
        "evaluation_latency_ms": evaluation_latency_ms,
        "evaluator_response": evaluator_response,
        "evaluation_summary": evaluation_summary,
        "evaluation_score": evaluation_score,
        "evaluation_verdict": evaluation_verdict,
        "evaluation_verdict_justification": evaluation_verdict_justification,
        "evaluation_score_justification": evaluation_score_justification,
        "error_message": error_message,
    }


def run_red_team_suite(
    session: Session,
    suite: models.RedTeamSuite,
    target_endpoint: models.Endpoint,
    evaluator_endpoint: models.Endpoint,
    cases: list[models.RedTeamCase],
    default_timeout: int | None = None,
    max_threads: int = 1,
    max_retries: int = 0,
    target_variable_overrides: dict[str, Any] | None = None,
    evaluator_variable_overrides: dict[str, Any] | None = None,
    evaluator_prompt_template: str | None = None,
    verify_ssl: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
) -> models.RedTeamRun:
    run = models.RedTeamRun(
        suite_id=suite.id,
        target_endpoint_id=target_endpoint.id,
        evaluator_endpoint_id=evaluator_endpoint.id,
        status="running",
        total_tests=len(cases),
        passed=0,
        failed=0,
        errors=0,
    )
    session.add(run)
    session.flush()
    record_event(
        session,
        "execute",
        "red_team_run",
        run.id,
        after_value={
            "suite": suite.name,
            "target_endpoint": target_endpoint.name,
            "evaluator_endpoint": evaluator_endpoint.name,
        },
    )

    target_variables = SecretManager().get_variables(session, target_endpoint.id)
    evaluator_variables = SecretManager().get_variables(session, evaluator_endpoint.id)
    if target_variable_overrides:
        target_variables.update({str(key): value for key, value in target_variable_overrides.items()})
    if evaluator_variable_overrides:
        evaluator_variables.update({str(key): value for key, value in evaluator_variable_overrides.items()})
    target_provider_class = get_provider_class(target_endpoint.provider)
    evaluator_provider_class = get_provider_class(evaluator_endpoint.provider)
    target_endpoint_config = _build_endpoint_config(target_endpoint)
    evaluator_endpoint_config = _build_endpoint_config(evaluator_endpoint)
    worker_count = max(1, int(max_threads or 1))
    retry_count = max(0, int(max_retries or 0))

    case_specs = [
        {
            "case_id": case.id,
            "prompt": case.prompt,
            "purpose": case.purpose,
            "expected_result": case.expected_result,
            "relevance": case.relevance,
            "suite_name": suite.name,
        }
        for case in cases
    ]
    logger.debug(
        "Starting red team run run_id=%s suite_id=%s target_endpoint_id=%s evaluator_endpoint_id=%s total_cases=%s max_retries=%s",
        run.id,
        suite.id,
        target_endpoint.id,
        evaluator_endpoint.id,
        len(case_specs),
        retry_count,
    )

    outcomes: list[dict[str, Any]] = []
    if worker_count == 1 or len(case_specs) <= 1:
        for case_spec in case_specs:
            outcomes.append(
                _execute_red_team_case(
                    target_provider_class,
                    evaluator_provider_class,
                    target_endpoint_config,
                    evaluator_endpoint_config,
                    target_variables,
                    evaluator_variables,
                    verify_ssl,
                    case_spec,
                    default_timeout,
                    retry_count,
                    evaluator_prompt_template,
                )
            )
    else:
        max_workers = min(worker_count, len(case_specs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _execute_red_team_case,
                    target_provider_class,
                    evaluator_provider_class,
                    target_endpoint_config,
                    evaluator_endpoint_config,
                    target_variables,
                    evaluator_variables,
                    verify_ssl,
                    case_spec,
                    default_timeout,
                    retry_count,
                    evaluator_prompt_template,
                )
                for case_spec in case_specs
            ]
            for future in as_completed(futures):
                outcomes.append(future.result())

    completed = 0
    for outcome in outcomes:
        status = outcome["status"]
        if status == "error":
            run.errors = (run.errors or 0) + 1
        elif status == "passed":
            run.passed = (run.passed or 0) + 1
        else:
            run.failed = (run.failed or 0) + 1

        result = models.RedTeamRunResult(
            run_id=run.id,
            case_id=outcome["case_id"],
            status=status,
            prompt_sent=outcome["prompt"],
            response_received=outcome["response_text"],
            evaluation_summary=outcome["evaluation_summary"],
            evaluation_score=outcome["evaluation_score"],
            evaluation_verdict=outcome["evaluation_verdict"],
            llm_judge_model=evaluator_endpoint.model_name,
            evaluation_verdict_justification=outcome["evaluation_verdict_justification"],
            evaluation_score_justification=outcome["evaluation_score_justification"],
            evaluator_response=outcome["evaluator_response"],
            latency_ms=outcome["latency_ms"],
            evaluation_latency_ms=outcome["evaluation_latency_ms"],
            error_message=outcome["error_message"],
        )
        session.add(result)
        completed += 1
        if progress_callback:
            progress_callback(completed, len(case_specs))

    run.status = "completed"
    run.finished_at = datetime.utcnow()
    session.add(run)
    record_event(session, "complete", "red_team_run", run.id, after_value={"status": run.status})
    return run
