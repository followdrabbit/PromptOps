# Module Guide

This document explains what each module does, when to use it, and the minimum steps to operate it.

## Home
Use this module to quickly understand system status.

What you can do:
- Review total endpoints, sessions, suites, and runs.
- Open navigation cards to main modules.
- Inspect recent runs and recent endpoints.

When to use:
- At startup, to validate the environment is ready.
- After operations, to confirm runs were registered.

## Configuration
Use this module to set runtime behavior and maintain core records.

Sections:
- `General Settings`
- `Provider Settings`
- `Endpoint Settings`
- `Automated Test Settings`
- `Red Teaming Settings`

When to use:
- First-time setup.
- Any time behavior or assets (providers/endpoints/suites) must change.

## General Settings
Purpose:
- Control language, logging, directories, SSL verification, and runtime defaults.

How to use:
1. Open `Configuration > General Settings`.
2. Set `Log level`, `Default timeout`, and directory paths.
3. Save and re-run your operation (chat/test/red-team) to validate the change.

Expected result:
- Settings are persisted and used by all modules.

## Provider Settings
Purpose:
- Register provider metadata used for endpoint classification/reporting.

How to use:
1. Create providers with `Provider name` and optional `Notes`.
2. Edit/delete providers as needed.
3. Use import/export for backup or migration.

Expected result:
- Provider list is available in endpoint forms.

## Endpoint Settings
Purpose:
- Define request/response templates for each AI endpoint.

Required fields:
- `Friendly name`
- `Provider`
- `Endpoint URL`
- `Model name`
- `API version` (`Response` or `Chat Completion`)
- `Headers (JSON)`
- `Body (JSON)`
- `Response JSON PATHs`
- `Response type`

How to use:
1. Create endpoint with placeholders such as `{{API_TOKEN}}`, `{{MODEL_NAME}}`, `{{PROMPT}}`.
2. Set `API version`:
- `Response` for `/v1/responses` style APIs.
- `Chat Completion` for `/v1/chat/completions` style APIs.
3. Configure `Additional variables (JSON)` for model-specific parameters.
4. Use `Test endpoint connection` to validate endpoint config on the same screen.
5. Save and validate in `Chat`.

Clone workflow:
1. Open `Endpoint Settings > Edit`.
2. Select the source endpoint.
3. Use `Clone Endpoint`.
4. Change only fields that differ (for example, switch API version and URL path).

Expected result:
- Endpoint can be used immediately by `Chat`, `Compare`, `Automated Tests`, and `Red Teaming`.

## Chat
Purpose:
- Run interactive conversations against one endpoint with persistent history.

How to use:
1. Open `Chat`.
2. In sidebar, choose endpoint and (optionally) runtime variable overrides.
3. Create/select a session.
4. Send prompt.
5. Review response and latency metadata.

Expected result:
- User and assistant messages are saved in database.
- Session can be renamed or deleted from sidebar.

## Compare
Purpose:
- Send one prompt to up to 10 endpoints and compare responses side by side.

How to use:
1. Open `Compare`.
2. Select endpoints in sidebar (up to 10).
3. Send a prompt.
4. Compare response content, errors, and latency cards.

Expected result:
- Responses are rendered in horizontal-scroll cards.
- Per-endpoint conversation context is preserved for the current compare session.

## Automated Tests
Purpose:
- Execute reusable prompt suites against a selected endpoint.

Prerequisites:
- At least one endpoint.
- At least one suite with prompts.

How to use:
1. Configure module settings in `Configuration > Automated Test Settings`:
- max threads
- request timeout
- retries
- result format (`xlsx` or `json`)
2. Open `Automated Tests`.
3. Select endpoint.
4. Enable one or more suites (or `Enable all suites`).
5. Run tests.

Expected result:
- Runs are persisted.
- Results are auto-exported after each suite with filename:
- `automated_tests_<endpoint>_<suite>_<timestamp>.<ext>`

## Red Teaming
Purpose:
- Validate security behavior with target prompts and evaluator-based judgment.

Prerequisites:
- Target endpoint configured.
- Evaluator endpoint configured.
- At least one red-team suite/case.

How to use:
1. Configure module settings in `Configuration > Red Teaming Settings`:
- max threads
- request timeout
- retries
- result format
- evaluator endpoint
- evaluator prompt template (optional custom)
2. Open `Red Teaming`.
3. Select target endpoint.
4. Enable one or more suites.
5. Run red-team execution.

Expected result:
- Runs and case results are persisted.
- Auto-exported output includes evaluator verdict/score fields.

## Documentation
Purpose:
- Provide in-app access to all guides.

How to use:
1. Open `Documentation` from sidebar.
2. Select the tab matching your need (setup, modules, security, operations, FAQ).
3. Download Markdown if you need an offline copy.
