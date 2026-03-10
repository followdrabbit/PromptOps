from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.domain import models
from app.services.audit_service import record_event


RED_TEAM_SUITE_NAME_COLUMNS = [
    "Read Team Suite Name",
    "Red Team Suite Name",
    "read_team_suite_name",
    "red_team_suite_name",
    "suite_name",
    "Suite Name",
    "suite",
    "name",
]
RED_TEAM_SUITE_DESCRIPTION_COLUMNS = [
    "Read Team Suite Description",
    "Red Team Suite Description",
    "read_team_suite_description",
    "red_team_suite_description",
    "suite_description",
    "Suite Description",
    "description",
]
RED_TEAM_PROMPT_COLUMNS = ["Prompt", "prompt"]
RED_TEAM_PURPOSE_COLUMNS = ["Purpose of the test", "purpose_of_the_test", "purpose", "Purpose"]
RED_TEAM_EXPECTED_RESULT_COLUMNS = ["Expected Result", "expected_result", "expected"]
RED_TEAM_RELEVANCE_COLUMNS = ["Relevance", "relevance"]
RED_TEAM_NOTES_COLUMNS = ["Notes", "notes"]


def _normalize_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _validate_suite_name(name: str) -> str:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("suite_name_required")
    if len(normalized_name) > 200:
        raise ValueError("suite_name_too_long")
    return normalized_name


def _validate_relevance(value: int | float | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("relevance_invalid") from exc
    if parsed < 0 or parsed > 10:
        raise ValueError("relevance_out_of_range")
    return parsed


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, float) and pd.isna(value))


def _read_value(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and not _is_missing(row.get(key)):
            return row.get(key)
    return None


def list_red_team_suites(session: Session) -> list[models.RedTeamSuite]:
    return session.query(models.RedTeamSuite).order_by(models.RedTeamSuite.created_at.desc()).all()


def get_red_team_suite(session: Session, suite_id: int) -> models.RedTeamSuite | None:
    return session.query(models.RedTeamSuite).filter(models.RedTeamSuite.id == suite_id).one_or_none()


def create_red_team_suite(session: Session, name: str, description: str | None) -> models.RedTeamSuite:
    suite = models.RedTeamSuite(
        name=_validate_suite_name(name),
        description=_normalize_text(description),
    )
    session.add(suite)
    session.flush()
    record_event(session, "create", "red_team_suite", suite.id, after_value={"name": suite.name})
    return suite


def update_red_team_suite(
    session: Session,
    suite: models.RedTeamSuite,
    name: str,
    description: str | None,
) -> models.RedTeamSuite:
    before = {"name": suite.name, "description": suite.description}
    suite.name = _validate_suite_name(name)
    suite.description = _normalize_text(description)
    session.add(suite)
    record_event(
        session,
        "update",
        "red_team_suite",
        suite.id,
        before_value=before,
        after_value={"name": suite.name, "description": suite.description},
    )
    return suite


def delete_red_team_suite(session: Session, suite: models.RedTeamSuite) -> None:
    record_event(
        session,
        "delete",
        "red_team_suite",
        suite.id,
        before_value={"name": suite.name},
    )
    session.delete(suite)


def list_red_team_cases(session: Session, suite: models.RedTeamSuite) -> list[models.RedTeamCase]:
    return (
        session.query(models.RedTeamCase)
        .filter(models.RedTeamCase.suite_id == suite.id)
        .order_by(models.RedTeamCase.order.asc().nullslast(), models.RedTeamCase.id.asc())
        .all()
    )


def create_red_team_case(
    session: Session,
    suite: models.RedTeamSuite,
    prompt: str,
    purpose: str | None,
    expected_result: str | None,
    relevance: int | float | str | None,
    notes: str | None,
) -> models.RedTeamCase:
    prompt_value = _normalize_text(prompt)
    if not prompt_value:
        raise ValueError("prompt_required")

    next_order = session.query(models.RedTeamCase).filter(models.RedTeamCase.suite_id == suite.id).count() + 1
    case = models.RedTeamCase(
        suite_id=suite.id,
        order=next_order,
        prompt=prompt_value,
        purpose=_normalize_text(purpose),
        expected_result=_normalize_text(expected_result),
        relevance=_validate_relevance(relevance),
        notes=_normalize_text(notes),
    )
    session.add(case)
    session.flush()
    record_event(
        session,
        "create",
        "red_team_case",
        case.id,
        after_value={"suite_id": suite.id, "prompt": prompt_value},
    )
    return case


def update_red_team_case(
    session: Session,
    case: models.RedTeamCase,
    prompt: str,
    purpose: str | None,
    expected_result: str | None,
    relevance: int | float | str | None,
    notes: str | None,
) -> models.RedTeamCase:
    prompt_value = _normalize_text(prompt)
    if not prompt_value:
        raise ValueError("prompt_required")

    before = {
        "prompt": case.prompt,
        "purpose": case.purpose,
        "expected_result": case.expected_result,
        "relevance": case.relevance,
        "notes": case.notes,
    }
    case.prompt = prompt_value
    case.purpose = _normalize_text(purpose)
    case.expected_result = _normalize_text(expected_result)
    case.relevance = _validate_relevance(relevance)
    case.notes = _normalize_text(notes)
    session.add(case)
    record_event(
        session,
        "update",
        "red_team_case",
        case.id,
        before_value=before,
        after_value={
            "prompt": case.prompt,
            "purpose": case.purpose,
            "expected_result": case.expected_result,
            "relevance": case.relevance,
            "notes": case.notes,
        },
    )
    return case


def delete_red_team_case(session: Session, case: models.RedTeamCase) -> None:
    record_event(
        session,
        "delete",
        "red_team_case",
        case.id,
        before_value={"suite_id": case.suite_id, "prompt": case.prompt},
    )
    session.delete(case)


def load_red_team_records_from_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        dataframe = pd.read_excel(path)
        return dataframe.to_dict(orient="records")

    if suffix == ".json":
        content = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            suites = content.get("suites")
            if isinstance(suites, list):
                records: list[dict[str, Any]] = []
                for suite in suites:
                    if not isinstance(suite, dict):
                        raise ValueError("invalid_json_suites")
                    suite_name = _read_value(suite, RED_TEAM_SUITE_NAME_COLUMNS)
                    suite_description = _read_value(suite, RED_TEAM_SUITE_DESCRIPTION_COLUMNS)
                    suite_cases = suite.get("cases")
                    if suite_cases is None:
                        suite_cases = suite.get("tests")
                    if suite_cases is None:
                        suite_cases = suite.get("prompts")
                    if suite_cases is None:
                        records.append(
                            {
                                "suite_name": suite_name,
                                "suite_description": suite_description,
                                "prompt": _read_value(suite, RED_TEAM_PROMPT_COLUMNS),
                                "purpose": _read_value(suite, RED_TEAM_PURPOSE_COLUMNS),
                                "expected_result": _read_value(suite, RED_TEAM_EXPECTED_RESULT_COLUMNS),
                                "relevance": _read_value(suite, RED_TEAM_RELEVANCE_COLUMNS),
                                "notes": _read_value(suite, RED_TEAM_NOTES_COLUMNS),
                            }
                        )
                        continue
                    if not isinstance(suite_cases, list):
                        raise ValueError("invalid_json_suite_cases")
                    for case_row in suite_cases:
                        if not isinstance(case_row, dict):
                            raise ValueError("invalid_json_suite_cases")
                        records.append(
                            {
                                "suite_name": suite_name,
                                "suite_description": suite_description,
                                "prompt": _read_value(case_row, RED_TEAM_PROMPT_COLUMNS),
                                "purpose": _read_value(case_row, RED_TEAM_PURPOSE_COLUMNS),
                                "expected_result": _read_value(case_row, RED_TEAM_EXPECTED_RESULT_COLUMNS),
                                "relevance": _read_value(case_row, RED_TEAM_RELEVANCE_COLUMNS),
                                "notes": _read_value(case_row, RED_TEAM_NOTES_COLUMNS),
                            }
                        )
                return records
            content = [content]

        if not isinstance(content, list):
            raise ValueError("invalid_json_root")
        if not all(isinstance(item, dict) for item in content):
            raise ValueError("invalid_json_records")
        return [dict(item) for item in content]

    raise ValueError("unsupported_file_type")


def validate_red_team_import_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []

    for row_index, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {row_index}: invalid row format (expected object)")
            continue

        suite_name_raw = _read_value(row, RED_TEAM_SUITE_NAME_COLUMNS + ["suite_name"])
        suite_description_raw = _read_value(row, RED_TEAM_SUITE_DESCRIPTION_COLUMNS + ["suite_description"])
        prompt_raw = _read_value(row, RED_TEAM_PROMPT_COLUMNS + ["prompt"])
        purpose_raw = _read_value(row, RED_TEAM_PURPOSE_COLUMNS + ["purpose"])
        expected_result_raw = _read_value(row, RED_TEAM_EXPECTED_RESULT_COLUMNS + ["expected_result"])
        relevance_raw = _read_value(row, RED_TEAM_RELEVANCE_COLUMNS + ["relevance"])
        notes_raw = _read_value(row, RED_TEAM_NOTES_COLUMNS + ["notes"])

        suite_name = "" if _is_missing(suite_name_raw) else str(suite_name_raw).strip()
        suite_description = "" if _is_missing(suite_description_raw) else str(suite_description_raw).strip()
        prompt = "" if _is_missing(prompt_raw) else str(prompt_raw).strip()
        purpose = "" if _is_missing(purpose_raw) else str(purpose_raw).strip()
        expected_result = "" if _is_missing(expected_result_raw) else str(expected_result_raw).strip()
        notes = "" if _is_missing(notes_raw) else str(notes_raw).strip()

        if not suite_name and not suite_description and not prompt and not purpose and not expected_result and not notes:
            continue

        if not suite_name:
            errors.append(f"row {row_index}: 'suite_name' is required")
            continue
        if len(suite_name) > 200:
            errors.append(f"row {row_index}: 'suite_name' exceeds 200 characters")
            continue
        if not prompt:
            errors.append(f"row {row_index}: 'prompt' is required")
            continue
        try:
            relevance = _validate_relevance(relevance_raw)
        except ValueError:
            errors.append(f"row {row_index}: 'relevance' must be an integer between 0 and 10")
            continue

        normalized.append(
            {
                "suite_name": suite_name,
                "suite_description": suite_description or None,
                "prompt": prompt,
                "purpose": purpose or None,
                "expected_result": expected_result or None,
                "relevance": relevance,
                "notes": notes or None,
            }
        )

    if not normalized and not errors:
        errors.append("no valid red team records found")

    return normalized, errors


def import_red_team_records(session: Session, records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        suite_name = str(record["suite_name"]).strip()
        key = suite_name.lower()
        grouped_suite = grouped.get(key)
        if not grouped_suite:
            grouped_suite = {"name": suite_name, "description": record.get("suite_description"), "cases": []}
            grouped[key] = grouped_suite
        elif not grouped_suite.get("description") and record.get("suite_description"):
            grouped_suite["description"] = record.get("suite_description")

        grouped_suite["cases"].append(
            {
                "prompt": record.get("prompt"),
                "purpose": record.get("purpose"),
                "expected_result": record.get("expected_result"),
                "relevance": record.get("relevance"),
                "notes": record.get("notes"),
            }
        )

    existing_name_keys = {suite.name.strip().lower() for suite in session.query(models.RedTeamSuite).all()}
    created_suites = 0
    imported_cases = 0
    skipped_existing = 0
    skipped_existing_names: list[str] = []

    for suite_key, grouped_suite in grouped.items():
        if suite_key in existing_name_keys:
            skipped_existing += 1
            skipped_existing_names.append(grouped_suite["name"])
            continue

        suite = create_red_team_suite(session, grouped_suite["name"], grouped_suite.get("description"))
        for case_row in grouped_suite["cases"]:
            create_red_team_case(
                session=session,
                suite=suite,
                prompt=str(case_row.get("prompt") or ""),
                purpose=case_row.get("purpose"),
                expected_result=case_row.get("expected_result"),
                relevance=case_row.get("relevance"),
                notes=case_row.get("notes"),
            )
            imported_cases += 1
        created_suites += 1
        existing_name_keys.add(suite_key)

    return {
        "created_suites": created_suites,
        "imported_cases": imported_cases,
        "skipped_existing": skipped_existing,
        "skipped_existing_names": skipped_existing_names,
    }


def red_team_suites_to_records(session: Session, suites: list[models.RedTeamSuite]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for suite in suites:
        cases = (
            session.query(models.RedTeamCase)
            .filter(models.RedTeamCase.suite_id == suite.id)
            .order_by(models.RedTeamCase.order.asc().nullslast(), models.RedTeamCase.id.asc())
            .all()
        )
        for case in cases:
            records.append(
                {
                    "Read Team Suite Name": suite.name,
                    "Read Team Suite Description": suite.description or "",
                    "Prompt": case.prompt,
                    "Purpose of the test": case.purpose or "",
                    "Expected Result": case.expected_result or "",
                    "Relevance": case.relevance,
                    "Notes": case.notes or "",
                }
            )
    return records


def export_red_team_run_results(
    session: Session,
    run_id: int,
    output_path: Path,
    export_format: str = "xlsx",
) -> Path:
    session.flush()
    run = session.query(models.RedTeamRun).filter(models.RedTeamRun.id == run_id).one_or_none()
    target_name = ""
    evaluator_name = ""
    if run is not None:
        target_endpoint = session.query(models.Endpoint).filter(models.Endpoint.id == run.target_endpoint_id).one_or_none()
        evaluator_endpoint = (
            session.query(models.Endpoint).filter(models.Endpoint.id == run.evaluator_endpoint_id).one_or_none()
        )
        if target_endpoint is not None:
            target_name = target_endpoint.name
        if evaluator_endpoint is not None:
            evaluator_name = evaluator_endpoint.name

    results = (
        session.query(models.RedTeamRunResult)
        .filter(models.RedTeamRunResult.run_id == run_id)
        .order_by(models.RedTeamRunResult.id.asc())
        .all()
    )
    case_map = {
        case.id: case
        for case in session.query(models.RedTeamCase)
        .filter(models.RedTeamCase.id.in_([result.case_id for result in results]))
        .all()
    }

    rows: list[dict[str, Any]] = []
    for result in results:
        case = case_map.get(result.case_id)
        rows.append(
            {
                "Selected Endpoint": target_name,
                "Evaluator Endpoint": evaluator_name,
                "prompt_sent": result.prompt_sent,
                "purpose_of_test": case.purpose if case else None,
                "expected_result": case.expected_result if case else None,
                "relevance": case.relevance if case else None,
                "response_received": result.response_received,
                "LLM Judge Veredict": "Pass" if str(result.evaluation_verdict or "").lower() == "pass" else "Fail",
                "LLM Judge Veredict Justification": (
                    result.evaluation_verdict_justification or result.evaluation_summary
                ),
                "LLM Judge Score": result.evaluation_score,
                "LLM Judge Score Justification": result.evaluation_score_justification,
                "evaluation_summary": result.evaluation_summary,
                "error_message": result.error_message,
                "timestamp": result.timestamp,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_format = (export_format or "xlsx").strip().lower()
    if normalized_format == "json":
        serializable = [
            {**row, "timestamp": row["timestamp"].isoformat() if row.get("timestamp") else None}
            for row in rows
        ]
        output_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        pd.DataFrame(rows).to_excel(output_path, index=False)
    return output_path
