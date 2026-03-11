# User Guide

This is a task-oriented guide focused on daily use.

## 1) First-Time Setup
1. Open `Configuration > General Settings`.
2. Confirm:
- `Default timeout`
- `Output directory`
- `Import directory`
- `Log level`
3. Save settings.
4. Open `Provider Settings` and create providers.
5. Open `Endpoint Settings` and create your first endpoint.

Validation checklist:
- Endpoint created successfully.
- API token stored (masked in UI).
- `Chat` can send and receive messages.

## 2) Registering an Endpoint Correctly
1. Go to `Endpoint Settings > Create`.
2. Fill endpoint metadata (`Friendly name`, `Provider`, `Endpoint URL`, `Model name`).
3. Choose `API version`:
- `Response` for `/v1/responses`
- `Chat Completion` for `/v1/chat/completions`
4. Add `Headers (JSON)` and `Body (JSON)` templates.
5. Define `Response JSON PATHs` and `Response type`.
6. Add API token.
7. Use `Test endpoint connection` to validate settings without leaving the screen.
8. Save endpoint.

Tip:
- If you need a variation, clone an existing endpoint and change only URL/mode/body.

## 3) Quick Validation with Chat
1. Open `Chat`.
2. Select endpoint in sidebar.
3. Create a new session.
4. Send a simple prompt (for example, "Say hello in one sentence.").
5. Confirm response is shown and persisted.

If response is empty:
- Check `Response JSON PATHs`.
- Check `Response type` (`json` vs `text`).
- Check logs in `data/logs/app.log`.

## 4) Comparing Multiple Endpoints
1. Open `Compare`.
2. Select 2-10 endpoints.
3. Send one prompt.
4. Compare quality, latency, and error cards.

Recommended use:
- Regression checks before switching a production model.

## 5) Running Automated Tests
1. Open `Configuration > Automated Test Settings`.
2. Create/import suites and prompts.
3. Set module options (threads, timeout, retries, result format).
4. Open `Automated Tests`.
5. Select endpoint and enable suites.
6. Run tests.

Output:
- Auto-exported file in output directory:
- `automated_tests_<endpoint>_<suite>_<timestamp>.<xlsx|json>`

## 6) Running Red Teaming
1. Open `Configuration > Red Teaming Settings`.
2. Configure evaluator endpoint and prompt template.
3. Create/import red-team suites.
4. Open `Red Teaming`.
5. Select target endpoint and enable suites.
6. Run execution.

Output:
- Auto-exported file:
- `red_teaming_<endpoint>_<suite>_<timestamp>.<xlsx|json>`
- Contains judge verdict/score and justifications.

## 7) Import/Export for Backup
Providers:
- Import/export in `Provider Settings`.

Endpoints:
- Import/export in `Endpoint Settings`.
- Exported token values remain blank by design.

Suites:
- Import/export in `Automated Test Settings` and `Red Teaming Settings`.

## 8) Security and Audit in Daily Use
Recommended:
1. Keep SSL verification enabled unless required otherwise.
2. Use `INFO` log level for normal usage.
3. Use `DEBUG` for troubleshooting.
4. Set `PROMPTOPS_ACTOR` for clear audit attribution.
5. Review:
- App logs: `data/logs/app.log`
- Audit logs: `data/audit/audit.log`

## 9) Common Problems
`401 Unauthorized`:
- Verify token, auth header, auth prefix, and endpoint URL.

No response text:
- Fix response JSON path or response type.

Import failed:
- Check template columns and JSON validity.

Timeouts:
- Increase module timeout or reduce concurrency.
