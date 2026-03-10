# CyberPrompt AI Security

## Quick Links
- Master key setup: [`docs/GETTING_STARTED.md`](GETTING_STARTED.md#configure-secret-encryption-key)
- Log operations: [`docs/OPERATIONS.md`](OPERATIONS.md#logging)
- Audit operations: [`docs/OPERATIONS.md`](OPERATIONS.md#audit-events)

## Security Model (MVP)
CyberPrompt AI is local-first and secure-by-default for an MVP:
- encrypts endpoint secrets at rest
- redacts sensitive values in logs
- records audit events for critical actions
- constrains import/export paths to approved directories

## Secret Encryption
- Algorithm/library: `cryptography` Fernet (authenticated encryption).
- Secret values are not stored in plaintext.
- Endpoint metadata and encrypted secret blobs are separated.
- Decryption occurs only at runtime when building outbound requests.

## Master Key Management
Supported options:
- `PROMPTOPS_MASTER_KEY` (recommended).
- `PROMPTOPS_ALLOW_KEYFILE=1` to auto-generate `data/.master_key`.

How to use:
1. Generate a Fernet key.
2. Set `PROMPTOPS_MASTER_KEY` in the same terminal session used to run Streamlit.
3. Start the app and create/update endpoint API tokens normally in `Endpoint Settings`.

PowerShell example:
```powershell
$env:PROMPTOPS_MASTER_KEY = "your_fernet_key_here"
streamlit run app/main.py
```

Bash example:
```bash
export PROMPTOPS_MASTER_KEY="your_fernet_key_here"
streamlit run app/main.py
```

Fallback (local key file):
```powershell
$env:PROMPTOPS_ALLOW_KEYFILE = "1"
streamlit run app/main.py
```

Operational guidance:
- Never commit key material.
- Restrict file permissions to the app operator.
- Rotate tokens in endpoint settings when credentials change.

## Logging and Redaction
Security principles applied:
- API tokens and authorization values are masked.
- Common sensitive header names are redacted.
- Secret values are never printed in full.
- Debug logs include request/response diagnostics with masking.

Log locations:
- app log: `data/logs/app.log`
- audit log: `data/audit/audit.log`

How to configure log level:
1. Open `Configuration > General Settings`.
2. Set `Log level` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
3. Save settings.
4. Re-run the action (chat/test/red team) and inspect `data/logs/app.log`.

## Audit Trail
Audit events include:
- create/update/delete for providers/endpoints/suites
- secret create/update/rotation
- imports/exports
- chat/test/red-team executions
- settings changes

Each event tracks actor, action, entity, timestamp, and before/after values when available.

How to use audit trail:
1. Perform actions in the app (create/update/delete/import/export/run).
2. Inspect file log at `data/audit/audit.log`.
3. Optionally query table `audit_events` in SQLite for structured analysis.

Optional actor attribution:
- Set `PROMPTOPS_ACTOR` before launching the app to stamp audit records.
- PowerShell:
  - `$env:PROMPTOPS_ACTOR = "raphael.local"`
- Bash:
  - `export PROMPTOPS_ACTOR="raphael.local"`

## Input and File Safety
- Import and export operations are validated against project-approved base paths.
- File extension validation is enforced by module importers.
- Export writes only to configured output directory.
- Endpoint exports intentionally omit secret values.

## Data Protection in Exports
Automated and red-team result exports include safe operational data (prompt, response, status, timings, evaluator outputs) and never include API tokens.

## Known MVP Limitations
- No user authentication/RBAC.
- Local-only key management.
- No centralized SIEM integration.
- No multi-tenant isolation boundary.

## Recommended Production Hardening
- Integrate external secret managers (Vault, AWS/Azure/GCP).
- Add authentication, RBAC, and per-user audit attribution.
- Add outbound allowlists and stricter TLS policy controls.
- Add centralized log/audit shipping and alerting.
- Add data retention/erasure policies by workspace/project.
