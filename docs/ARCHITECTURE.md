# CyberPrompt AI Architecture

## Architectural Style
CyberPrompt AI uses a layered architecture with explicit boundaries:
- `UI layer` (`app/ui/`): Streamlit pages and interaction flow.
- `Service/Application layer` (`app/services/`, `app/jobs/`): use cases, orchestration, and execution pipelines.
- `Domain layer` (`app/domain/`): SQLAlchemy models and Pydantic schemas.
- `Infrastructure layer` (`app/infra/`): database engine/session lifecycle.
- `Adapter layer` (`app/adapters/`): provider-specific request/response integration.
- `Core/Security layer` (`app/core/`): configuration, logging, encryption, redaction, and path safety.

## Runtime Flow
1. `app/main.py` boots config, logging, database, and UI routing.
2. UI actions call services/jobs.
3. Services read/write SQLite through SQLAlchemy.
4. Adapter sends outbound HTTP request with runtime variables and decrypted secrets.
5. Results are persisted, exported, and audited.

## Key Components
- `app/main.py`: app bootstrap and navigation.
- `app/core/config.py`: config loading and defaults.
- `app/core/logging.py`: app/audit logger setup and log level management.
- `app/core/security.py`: key handling, path safety, SSL-related guards.
- `app/core/secrets.py`: secret encryption/decryption and variable resolution.
- `app/adapters/openai_compatible.py`: generic HTTP adapter and response extraction.
- `app/jobs/test_runner.py`: automated test execution (threaded, retry-aware).
- `app/jobs/red_team_runner.py`: red-team execution and evaluator orchestration.

## Storage Model (SQLite)
Main persisted entities include:
- providers
- endpoints
- endpoint_secrets
- settings
- chat_sessions / chat_messages
- test_suites / test_cases / test_runs / test_run_results
- red_team_suites / red_team_cases / red_team_runs / red_team_run_results
- audit_events

## Design Decisions
- Vendor-agnostic endpoint templates (`URL`, `Headers`, `Body`, `JSON PATHs`).
- Secrets separated from endpoint metadata.
- In-app import/export for portability and recovery.
- Runtime variable override support for controlled experiments.
- Automatic result file generation for test evidence.

## Extension Points
- Additional providers via new adapter classes.
- Alternative frontends (FastAPI, React) over same service/domain layers.
- External secret stores (OS keychain, Vault, cloud secret managers).
- AuthN/AuthZ and multi-user access control.
- Job queue/backpressure for high-volume evaluation workloads.
