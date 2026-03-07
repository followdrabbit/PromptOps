from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.security import is_safe_path
from app.domain import models
from app.services.audit_service import record_event


REQUIRED_COLUMNS = ["test_name", "prompt"]


def create_suite(
    session: Session,
    name: str,
    description: str | None,
    source_type: str,
    source_path: str | None = None,
    default_endpoint_id: int | None = None,
) -> models.TestSuite:
    suite = models.TestSuite(
        name=name,
        description=description,
        source_type=source_type,
        source_path=source_path,
        default_endpoint_id=default_endpoint_id,
    )
    session.add(suite)
    session.flush()
    record_event(session, "create", "test_suite", suite.id, after_value={"name": name})
    return suite


def import_tests_from_dataframe(
    session: Session,
    suite: models.TestSuite,
    df: pd.DataFrame,
    mapping: dict[str, str],
) -> int:
    imported = 0
    for _, row in df.iterrows():
        mapped = {field: row.get(col) if col else None for field, col in mapping.items()}
        def _is_missing(value: Any) -> bool:
            return value is None or (isinstance(value, float) and pd.isna(value)) or value == ""

        def _to_bool(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if _is_missing(value):
                return True
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "y"}
            return bool(value)
        if not mapped.get("test_name") or not mapped.get("prompt"):
            continue
        order_value = mapped.get("order")
        temp_value = mapped.get("temperature")
        max_tokens_value = mapped.get("max_tokens")
        test_case = models.TestCase(
            suite_id=suite.id,
            order=int(order_value) if not _is_missing(order_value) else None,
            enabled=_to_bool(mapped.get("enabled", True)),
            test_name=str(mapped.get("test_name")),
            prompt=str(mapped.get("prompt")),
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


def export_run_results(session: Session, run_id: int, output_path: Path) -> Path:
    results = (
        session.query(models.TestRunResult)
        .filter(models.TestRunResult.run_id == run_id)
        .all()
    )
    data = [
        {
            "run_id": r.run_id,
            "test_id": r.test_id,
            "status": r.status,
            "prompt_sent": r.prompt_sent,
            "response_received": r.response_received,
            "latency_ms": r.latency_ms,
            "error_message": r.error_message,
            "timestamp": r.timestamp,
        }
        for r in results
    ]
    df = pd.DataFrame(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)
    return output_path
