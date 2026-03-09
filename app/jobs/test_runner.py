from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
from types import SimpleNamespace
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.adapters.registry import get_provider_class
from app.core.logging import get_logger
from app.core.secrets import SecretManager
from app.domain import models
from app.services.audit_service import record_event


logger = get_logger("promptops.test_runner")


def _execute_test_case(
    provider_class: type,
    endpoint_config: Any,
    variables: dict[str, str],
    verify_ssl: bool,
    test_spec: dict[str, Any],
    default_timeout: int | None,
) -> dict[str, Any]:
    start = time.time()
    status = "passed"
    response_text = None
    error_message = None
    logger.debug(
        "Executing test run_case test_id=%s test_name=%s",
        test_spec["test_id"],
        test_spec["test_name"],
    )
    try:
        provider = provider_class(endpoint_config, variables, verify_ssl=verify_ssl)
        params: dict[str, Any] = {}
        if test_spec.get("temperature") is not None:
            params["temperature"] = test_spec["temperature"]
        if test_spec.get("max_tokens") is not None:
            params["max_tokens"] = test_spec["max_tokens"]
        if default_timeout is not None:
            params["timeout"] = int(default_timeout)
        payload = [{"role": "user", "content": test_spec["prompt"]}]
        response = provider.send_prompt(payload, params)
        response_text = response.content
    except Exception as exc:
        logger.exception("Test execution failed for %s", test_spec["test_name"])
        status = "error"
        error_message = str(exc)
    else:
        if not response_text:
            status = "failed"

    latency = int((time.time() - start) * 1000)
    return {
        "test_id": test_spec["test_id"],
        "prompt": test_spec["prompt"],
        "status": status,
        "response_text": response_text,
        "error_message": error_message,
        "latency_ms": latency,
    }


def run_test_suite(
    session: Session,
    suite: models.TestSuite,
    endpoint: models.Endpoint,
    tests: list[models.TestCase],
    default_timeout: int | None = None,
    max_threads: int = 1,
    verify_ssl: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
) -> models.TestRun:
    run = models.TestRun(
        suite_id=suite.id,
        endpoint_id=endpoint.id,
        status="running",
        total_tests=len([test for test in tests if test.enabled]),
        passed=0,
        failed=0,
        errors=0,
    )
    session.add(run)
    session.flush()
    record_event(session, "execute", "test_run", run.id, after_value={"suite": suite.name})
    logger.debug(
        "Starting test run run_id=%s suite_id=%s endpoint_id=%s total_enabled=%s",
        run.id,
        suite.id,
        endpoint.id,
        run.total_tests,
    )

    variables = SecretManager().get_variables(session, endpoint.id)
    provider_class = get_provider_class(endpoint.provider)
    endpoint_config = SimpleNamespace(
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
        timeout=endpoint.timeout,
        retry_count=endpoint.retry_count,
        response_paths=endpoint.response_paths,
        response_type=endpoint.response_type,
    )
    worker_count = max(1, int(max_threads or 1))
    logger.debug(
        "Test run execution settings run_id=%s timeout=%s max_threads=%s verify_ssl=%s",
        run.id,
        default_timeout,
        worker_count,
        verify_ssl,
    )

    completed = 0
    enabled_tests = [test for test in tests if test.enabled]
    test_specs = [
        {
            "test_id": test.id,
            "test_name": test.test_name,
            "prompt": test.prompt,
            "temperature": test.temperature,
            "max_tokens": test.max_tokens,
        }
        for test in enabled_tests
    ]

    outcomes: list[dict[str, Any]] = []
    if worker_count == 1 or len(test_specs) <= 1:
        for test_spec in test_specs:
            outcomes.append(
                _execute_test_case(
                    provider_class,
                    endpoint_config,
                    variables,
                    verify_ssl,
                    test_spec,
                    default_timeout,
                )
            )
    else:
        max_workers = min(worker_count, len(test_specs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _execute_test_case,
                    provider_class,
                    endpoint_config,
                    variables,
                    verify_ssl,
                    test_spec,
                    default_timeout,
                )
                for test_spec in test_specs
            ]
            for future in as_completed(futures):
                outcomes.append(future.result())

    for outcome in outcomes:
        status = outcome["status"]
        response_text = outcome["response_text"]
        error_message = outcome["error_message"]
        latency = outcome["latency_ms"]
        if status == "error":
            run.errors = (run.errors or 0) + 1
        elif status == "passed":
            run.passed = (run.passed or 0) + 1
        else:
            run.failed = (run.failed or 0) + 1

        result = models.TestRunResult(
            run_id=run.id,
            test_id=outcome["test_id"],
            status=status,
            prompt_sent=outcome["prompt"],
            response_received=response_text,
            latency_ms=latency,
            error_message=error_message,
        )
        session.add(result)
        logger.debug(
            "Finished test run_id=%s test_id=%s status=%s latency_ms=%s",
            run.id,
            outcome["test_id"],
            status,
            latency,
        )
        completed += 1
        if progress_callback:
            progress_callback(completed, len(enabled_tests))

    run.status = "completed"
    run.finished_at = datetime.utcnow()
    session.add(run)
    record_event(session, "complete", "test_run", run.id, after_value={"status": run.status})
    return run
