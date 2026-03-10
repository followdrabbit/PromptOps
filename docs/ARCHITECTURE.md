# CyberPrompt AI Architecture

## Overview
CyberPrompt AI is organized into clear layers to keep responsibilities separated and make future growth easier:
- UI layer: Streamlit pages under `app/ui/`
- Application/services layer: domain operations in `app/services/` and jobs in `app/jobs/`
- Domain layer: SQLAlchemy models and Pydantic schemas under `app/domain/`
- Infrastructure layer: database setup and session management in `app/infra/`
- Provider adapters: pluggable adapters in `app/adapters/`
- Security layer: encryption, redaction, and configuration utilities in `app/core/`

## Data Flow
1. Streamlit UI triggers service functions.
2. Services load and validate data, then persist via SQLAlchemy.
3. Provider adapters execute outbound requests to AI endpoints.
4. Logs are written to `data/logs/` and audit events to `data/audit/`.

## Key Components
- `app/main.py`: App entry point, initializes config, logging, database, and UI routing.
- `app/core/security.py`: Encryption service and path validation helpers.
- `app/core/secrets.py`: Secret storage manager (encrypt/decrypt).
- `app/adapters/openai_compatible.py`: Generic OpenAI-compatible REST adapter.
- `app/jobs/test_runner.py`: Sequential test execution engine.

## Database
SQLite is used for the MVP. The schema covers:
- Settings
- Endpoints and encrypted secrets
- Chat sessions and messages
- Test suites, cases, runs, results
- Audit events

## Future Growth
This architecture is designed to expand to:
- Multiple UI frontends (Streamlit + FastAPI)
- External secret stores (Vault, cloud KMS)
- Multi-user RBAC and authentication
