from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.security import is_safe_path
from app.domain import models
from app.services.audit_service import record_event


REQUIRED_COLUMNS = ["prompt"]


def _validate_suite_fields(name: str, source_type: str, source_path: str | None) -> tuple[str, str, str | None]:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("suite_name_required")

    normalized_source_type = (source_type or "").strip().lower()
    if normalized_source_type not in {"file", "directory"}:
        raise ValueError("source_type_required")

    normalized_source_path = (source_path or "").strip() or None
    if normalized_source_type == "directory" and not normalized_source_path:
        raise ValueError("source_path_required")

    return normalized_name, normalized_source_type, normalized_source_path


def create_suite(
    session: Session,
    name: str,
    description: str | None,
    source_type: str,
    source_path: str | None = None,
    default_endpoint_id: int | None = None,
) -> models.TestSuite:
    normalized_name, normalized_source_type, normalized_source_path = _validate_suite_fields(
        name,
        source_type,
        source_path,
    )

    suite = models.TestSuite(
        name=normalized_name,
        description=(description or "").strip() or None,
        source_type=normalized_source_type,
        source_path=normalized_source_path,
        default_endpoint_id=default_endpoint_id,
    )
    session.add(suite)
    session.flush()
    record_event(session, "create", "test_suite", suite.id, after_value={"name": normalized_name})
    return suite


def update_suite(
    session: Session,
    suite: models.TestSuite,
    name: str,
    description: str | None,
    source_type: str,
    source_path: str | None = None,
    default_endpoint_id: int | None = None,
    is_active: bool = True,
) -> models.TestSuite:
    normalized_name, normalized_source_type, normalized_source_path = _validate_suite_fields(
        name,
        source_type,
        source_path,
    )
    before = {
        "name": suite.name,
        "description": suite.description,
        "source_type": suite.source_type,
        "source_path": suite.source_path,
        "default_endpoint_id": suite.default_endpoint_id,
        "is_active": suite.is_active,
    }
    suite.name = normalized_name
    suite.description = (description or "").strip() or None
    suite.source_type = normalized_source_type
    suite.source_path = normalized_source_path
    suite.default_endpoint_id = default_endpoint_id
    suite.is_active = bool(is_active)
    session.add(suite)
    record_event(
        session,
        "update",
        "test_suite",
        suite.id,
        before_value=before,
        after_value={
            "name": suite.name,
            "description": suite.description,
            "source_type": suite.source_type,
            "source_path": suite.source_path,
            "default_endpoint_id": suite.default_endpoint_id,
            "is_active": suite.is_active,
        },
    )
    return suite


def delete_suite(session: Session, suite: models.TestSuite) -> None:
    record_event(
        session,
        "delete",
        "test_suite",
        suite.id,
        before_value={"name": suite.name},
    )
    session.delete(suite)


def list_suite_test_cases(session: Session, suite: models.TestSuite) -> list[models.TestCase]:
    return (
        session.query(models.TestCase)
        .filter(models.TestCase.suite_id == suite.id)
        .order_by(models.TestCase.order.asc().nullslast(), models.TestCase.id.asc())
        .all()
    )


def create_suite_prompt(
    session: Session,
    suite: models.TestSuite,
    prompt: str,
    notes: str | None = None,
) -> models.TestCase:
    prompt_value = (prompt or "").strip()
    if not prompt_value:
        raise ValueError("prompt_required")

    next_index = session.query(models.TestCase).filter(models.TestCase.suite_id == suite.id).count() + 1
    test_case = models.TestCase(
        suite_id=suite.id,
        order=next_index,
        enabled=True,
        test_name=f"Prompt {next_index}",
        prompt=prompt_value,
        notes=(notes or "").strip() or None,
    )
    session.add(test_case)
    session.flush()
    record_event(
        session,
        "create",
        "test_case",
        test_case.id,
        after_value={"suite_id": suite.id, "prompt": prompt_value, "notes": test_case.notes},
    )
    return test_case


def update_suite_prompt(
    session: Session,
    test_case: models.TestCase,
    prompt: str,
    notes: str | None = None,
) -> models.TestCase:
    prompt_value = (prompt or "").strip()
    if not prompt_value:
        raise ValueError("prompt_required")

    before = {"prompt": test_case.prompt, "notes": test_case.notes}
    test_case.prompt = prompt_value
    test_case.notes = (notes or "").strip() or None
    session.add(test_case)
    record_event(
        session,
        "update",
        "test_case",
        test_case.id,
        before_value=before,
        after_value={"prompt": test_case.prompt, "notes": test_case.notes},
    )
    return test_case


def delete_suite_prompt(session: Session, test_case: models.TestCase) -> None:
    record_event(
        session,
        "delete",
        "test_case",
        test_case.id,
        before_value={"suite_id": test_case.suite_id, "prompt": test_case.prompt},
    )
    session.delete(test_case)


def import_tests_from_dataframe(
    session: Session,
    suite: models.TestSuite,
    df: pd.DataFrame,
    mapping: dict[str, str],
) -> int:
    imported = 0
    for row_index, (_, row) in enumerate(df.iterrows(), start=1):
        mapped = {field: row.get(col) if col else None for field, col in mapping.items()}
        def _is_missing(value: Any) -> bool:
            return value is None or (isinstance(value, float) and pd.isna(value)) or value == ""
        if _is_missing(mapped.get("prompt")):
            continue
        order_value = mapped.get("order")
        temp_value = mapped.get("temperature")
        max_tokens_value = mapped.get("max_tokens")
        raw_prompt = mapped.get("prompt")
        if _is_missing(raw_prompt):
            continue
        prompt_value = str(raw_prompt)
        raw_test_name = mapped.get("test_name")
        generated_name = f"Prompt {row_index}"
        test_name = generated_name if _is_missing(raw_test_name) else str(raw_test_name)
        test_case = models.TestCase(
            suite_id=suite.id,
            order=int(order_value) if not _is_missing(order_value) else None,
            enabled=True,
            test_name=test_name,
            prompt=prompt_value,
            expected_result=str(mapped.get("expected_result")) if not _is_missing(mapped.get("expected_result")) else None,
            validation_type=str(mapped.get("validation_type")) if not _is_missing(mapped.get("validation_type")) else None,
            tags=str(mapped.get("tags")) if not _is_missing(mapped.get("tags")) else None,
            temperature=float(temp_value) if not _is_missing(temp_value) else None,
            max_tokens=int(max_tokens_value) if not _is_missing(max_tokens_value) else None,
            notes=str(mapped.get("notes")) if not _is_missing(mapped.get("notes")) else None,
        )
        session.add(test_case)
        imported += 1
    record_event(session, "import", "test_cases", suite.id, after_value={"count": imported})
    return imported


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, float) and pd.isna(value))


def _read_value(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and not _is_missing(row.get(key)):
            return row.get(key)
    return None


def load_suite_records_from_file(path: Path) -> list[dict[str, Any]]:
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
                    suite_name = _read_value(suite, ["suite_name", "Suite Name", "suite name", "name"])
                    suite_description = _read_value(
                        suite,
                        ["suite_description", "Suite Description", "suite description", "description"],
                    )
                    suite_tests = suite.get("tests")
                    if suite_tests is None:
                        suite_tests = suite.get("prompts")
                    if suite_tests is None:
                        records.append(
                            {
                                "suite_name": suite_name,
                                "suite_description": suite_description,
                                "prompt": _read_value(suite, ["prompt", "Prompt"]),
                                "notes": _read_value(suite, ["notes", "Notes"]),
                            }
                        )
                        continue
                    if not isinstance(suite_tests, list):
                        raise ValueError("invalid_json_suite_tests")
                    for test_row in suite_tests:
                        if not isinstance(test_row, dict):
                            raise ValueError("invalid_json_suite_tests")
                        records.append(
                            {
                                "suite_name": suite_name,
                                "suite_description": suite_description,
                                "prompt": _read_value(test_row, ["prompt", "Prompt"]),
                                "notes": _read_value(test_row, ["notes", "Notes"]),
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


def validate_suite_import_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []

    for row_index, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {row_index}: invalid row format (expected object)")
            continue

        suite_name_raw = _read_value(row, ["suite_name", "Suite Name", "suite name", "suite", "Suite", "name"])
        suite_description_raw = _read_value(
            row,
            ["suite_description", "Suite Description", "suite description", "description", "Description"],
        )
        prompt_raw = _read_value(row, ["prompt", "Prompt"])
        notes_raw = _read_value(row, ["notes", "Notes"])

        suite_name = "" if _is_missing(suite_name_raw) else str(suite_name_raw).strip()
        suite_description = "" if _is_missing(suite_description_raw) else str(suite_description_raw).strip()
        prompt = "" if _is_missing(prompt_raw) else str(prompt_raw).strip()
        notes = "" if _is_missing(notes_raw) else str(notes_raw).strip()

        if not suite_name and not suite_description and not prompt and not notes:
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

        normalized.append(
            {
                "suite_name": suite_name,
                "suite_description": suite_description or None,
                "prompt": prompt,
                "notes": notes or None,
            }
        )

    if not normalized and not errors:
        errors.append("no valid suite records found")

    return normalized, errors


def import_suite_records(session: Session, records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        name = str(record["suite_name"]).strip()
        name_key = name.lower()
        grouped_suite = grouped.get(name_key)
        if not grouped_suite:
            grouped_suite = {
                "name": name,
                "description": record.get("suite_description"),
                "tests": [],
            }
            grouped[name_key] = grouped_suite
        elif not grouped_suite.get("description") and record.get("suite_description"):
            grouped_suite["description"] = record.get("suite_description")

        grouped_suite["tests"].append({"prompt": record["prompt"], "notes": record.get("notes")})

    existing_name_keys = {suite.name.strip().lower() for suite in session.query(models.TestSuite).all()}
    created_suites = 0
    imported_tests = 0
    skipped_existing = 0
    skipped_existing_names: list[str] = []

    for suite_key, grouped_suite in grouped.items():
        if suite_key in existing_name_keys:
            skipped_existing += 1
            skipped_existing_names.append(grouped_suite["name"])
            continue

        suite = create_suite(
            session,
            grouped_suite["name"],
            grouped_suite.get("description"),
            "file",
            None,
            None,
        )
        suite_df = pd.DataFrame(grouped_suite["tests"])
        mapping = {"prompt": "prompt", "notes": "notes"}
        imported_tests += import_tests_from_dataframe(session, suite, suite_df, mapping)
        created_suites += 1
        existing_name_keys.add(suite_key)

    return {
        "created_suites": created_suites,
        "imported_tests": imported_tests,
        "skipped_existing": skipped_existing,
        "skipped_existing_names": skipped_existing_names,
    }


def load_xlsx(path: Path, import_base: Path) -> pd.DataFrame:
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Only .xlsx files are supported")
    if not is_safe_path(path, import_base):
        raise ValueError("File path is outside the approved import directory")
    return pd.read_excel(path)


def scan_directory(directory: Path, import_base: Path) -> list[Path]:
    if not is_safe_path(directory, import_base):
        raise ValueError("Directory is outside the approved import directory")
    if not directory.exists():
        raise ValueError("Directory does not exist")
    return sorted([p for p in directory.glob("*.xlsx") if p.is_file()])


def validate_columns(df: pd.DataFrame, required: list[str] | None = None) -> list[str]:
    required = required or REQUIRED_COLUMNS
    missing = [col for col in required if col not in df.columns]
    return missing


def suite_test_cases_to_records(session: Session, suite: models.TestSuite) -> list[dict[str, Any]]:
    test_cases = (
        session.query(models.TestCase)
        .filter(models.TestCase.suite_id == suite.id)
        .order_by(models.TestCase.order.asc().nullslast(), models.TestCase.id.asc())
        .all()
    )
    return [
        {
            "Prompt": test_case.prompt,
            "Notes": test_case.notes,
        }
        for test_case in test_cases
    ]


def suites_to_records(session: Session, suites: list[models.TestSuite]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for suite in suites:
        test_cases = (
            session.query(models.TestCase)
            .filter(models.TestCase.suite_id == suite.id)
            .order_by(models.TestCase.order.asc().nullslast(), models.TestCase.id.asc())
            .all()
        )
        for test_case in test_cases:
            records.append(
                {
                    "Suite Name": suite.name,
                    "Suite Description": suite.description or "",
                    "Prompt": test_case.prompt,
                    "Notes": test_case.notes or "",
                }
            )
    return records


def export_run_results(
    session: Session,
    run_id: int,
    output_path: Path,
    export_format: str = "xlsx",
) -> Path:
    # Ensure pending TestRun/TestRunResult rows are persisted before querying,
    # so auto-export right after execution uses the same data as manual export.
    session.flush()
    run = session.query(models.TestRun).filter(models.TestRun.id == run_id).one_or_none()
    endpoint_name = ""
    if run is not None:
        endpoint = session.query(models.Endpoint).filter(models.Endpoint.id == run.endpoint_id).one_or_none()
        if endpoint is not None:
            endpoint_name = endpoint.name

    results = (
        session.query(models.TestRunResult)
        .filter(models.TestRunResult.run_id == run_id)
        .all()
    )
    data = [
        {
            "Selected Endpoint": endpoint_name,
            "prompt_sent": r.prompt_sent,
            "response_received": r.response_received,
            "latency_ms": r.latency_ms,
            "error_message": r.error_message,
            "status": r.status,
            "timestamp": r.timestamp,
        }
        for r in results
    ]
    output_columns = [
        "Selected Endpoint",
        "prompt_sent",
        "response_received",
        "latency_ms",
        "error_message",
        "status",
        "timestamp",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_format = (export_format or "xlsx").strip().lower()
    if normalized_format == "json":
        serializable = [
            {**row, "timestamp": row["timestamp"].isoformat() if row.get("timestamp") else None}
            for row in data
        ]
        output_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        pd.DataFrame(data, columns=output_columns).to_excel(output_path, index=False)
    return output_path
