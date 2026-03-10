# CyberPrompt AI Overview

CyberPrompt AI is an operations and security-focused platform for managing AI endpoints and evaluating model behavior.

## Core Goals
- Centralize AI endpoint registration and configuration.
- Run interactive conversations (`Chat`) and side-by-side comparisons (`Compare`).
- Execute structured prompt suites (`Automated Tests`) with automatic result export.
- Execute adversarial/security suites (`Red Teaming`) with LLM-as-a-judge evaluation.
- Keep strong local security defaults: encrypted secrets, audit trail, and redacted logs.

## Main Modules
- `Home`: operational snapshot and quick navigation.
- `Configuration`: runtime settings and CRUD/import/export for Providers, Endpoints, Test Suites, and Red Team suites.
- `Chat`: persistent sessions against one endpoint at a time.
- `Compare`: same prompt to up to 10 endpoints, rendered side by side.
- `Automated Tests`: run one or more suites against one endpoint using module-level execution settings.
- `Red Teaming`: run one or more red-team suites with a target endpoint and evaluator endpoint.
- `Documentation`: in-app reference to all project documentation.

## What Is Stored
- Providers, endpoints, sessions, messages, suites, runs, and results in SQLite.
- Endpoint secrets encrypted at rest in a dedicated table.
- Technical logs in `data/logs/` and audit logs in `data/audit/`.
- Generated result files in the configured output directory.

## Typical Workflow
1. Configure global settings and directories.
2. Register providers.
3. Register endpoints and API tokens.
4. Create/import suites.
5. Use `Chat`/`Compare` for exploratory checks.
6. Use `Automated Tests` and `Red Teaming` for repeatable evaluation and evidence generation.
