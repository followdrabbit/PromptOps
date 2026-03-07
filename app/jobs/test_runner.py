from __future__ import annotations

from datetime import datetime
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.adapters.registry import get_provider_class
from app.core.logging import get_logger
from app.core.secrets import SecretManager
from app.domain import models
from app.services.audit_service import record_event


logger = get_logger("promptops.test_runner")


def run_test_suite(
    session: Session,
    suite: models.TestSuite,
    endpoint: models.Endpoint,
    tests: list[models.TestCase],
    default_timeout: int | None = None,
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
    provider = provider_class(endpoint, variables, verify_ssl=verify_ssl)

    completed = 0
    enabled_tests = [test for test in tests if test.enabled]
    for test in enabled_tests:
        start = time.time()
        status = "passed"
        response_text = None
        error_message = None
        logger.debug(
            "Executing test run_id=%s test_id=%s test_name=%s",
            run.id,
            test.id,
            test.test_name,
        )
        try:
            params: dict[str, Any] = {}
            if test.temperature is not None:
                params["temperature"] = test.temperature
            if test.max_tokens is not None:
                params["max_tokens"] = test.max_tokens
            if default_timeout is not None:
                params["timeout"] = int(default_timeout)
            payload = [{"role": "user", "content": test.prompt}]
            response = provider.send_prompt(payload, params)
            response_text = response.content
        except Exception as exc:
            logger.exception("Test execution failed for %s", test.test_name)
            status = "error"
            error_message = str(exc)
            run.errors = (run.errors or 0) + 1
        else:
            if response_text:
                run.passed = (run.passed or 0) + 1
            else:
                run.failed = (run.failed or 0) + 1
                status = "failed"
        finally:
            latency = int((time.time() - start) * 1000)
            result = models.TestRunResult(
                run_id=run.id,
                test_id=test.id,
                status=status,
                prompt_sent=test.prompt,
                response_received=response_text,
                latency_ms=latency,
                error_message=error_message,
            )
            session.add(result)
            logger.debug(
                "Finished test run_id=%s test_id=%s status=%s latency_ms=%s",
                run.id,
                test.id,
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
