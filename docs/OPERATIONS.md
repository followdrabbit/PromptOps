# Operations Guide

## Logging
Application logs:
- File: `data/logs/app.log`
- Level controlled by `General Settings > Log level`

Audit logs:
- File: `data/audit/audit.log`
- Database table: `audit_events`

Recommended operational usage:
- `INFO` for daily usage.
- `DEBUG` for troubleshooting request formatting/response behavior.
- `ERROR`/`CRITICAL` for noisy production-like environments.

How to apply log level:
1. Open `Configuration > General Settings`.
2. Choose the desired level in `Log level`.
3. Click `Save settings`.
4. Execute a flow (chat, compare, automated tests, or red teaming).
5. Review `data/logs/app.log`.

Quick PowerShell tail:
```powershell
Get-Content data/logs/app.log -Wait
```

## Audit Events
The application records audit events for critical actions, including:
- endpoint create/update/delete
- secret create/update/rotation
- provider import/export and endpoint import/export
- suite import/export
- chat/test/red-team execution events
- configuration updates

Where to inspect:
- Flat log file: `data/audit/audit.log`
- Database table: `audit_events` in `data/promptops.db`

Quick PowerShell tail:
```powershell
Get-Content data/audit/audit.log -Wait
```

Optional SQL inspection example:
```sql
SELECT actor, action, entity_type, entity_id, timestamp
FROM audit_events
ORDER BY timestamp DESC
LIMIT 50;
```

## Generated Results
Automated Tests:
- Auto-exported after each suite run.
- Filename format:
  - `automated_tests_<endpoint>_<suite>_<timestamp>.<xlsx|json>`

Red Teaming:
- Auto-exported after each suite run.
- Filename format:
  - `red_teaming_<endpoint>_<suite>_<timestamp>.<xlsx|json>`

Recent generated files are listed in the UI with an `Open file` action.

## Backup and Restore
Recommended backup scope:
- `data/promptops.db`
- `data/logs/`
- `data/audit/`
- `data/exports/` (if evidence needs retention)

For configuration portability, use import/export tabs:
- Providers (`xlsx`/`json`)
- Endpoints (`xlsx`/`json`, without secrets)
- Automated test suites (`xlsx`/`json`)
- Red-team suites (`xlsx`/`json`)

After endpoint import, rotate/update API tokens before execution.

## Troubleshooting
Common checks:
1. Verify endpoint URL and headers/body placeholders.
2. Verify API token is configured and not expired.
3. Confirm `Response JSON PATHs` matches provider response shape.
4. Confirm SSL verification setting for your environment.
5. Switch log level to `DEBUG` and inspect request/response traces.

## Upgrade Hygiene
- Keep `requirements.txt` dependencies up to date.
- Re-run template generation when default examples change:
  - `python examples/generate_default_import_files.py`
- Keep documentation and template field definitions synchronized after schema/UI changes.
