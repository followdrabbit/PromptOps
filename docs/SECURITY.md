# CyberPrompt AI Security

## Secret Encryption
CyberPrompt AI encrypts sensitive endpoint credentials before storing them.
- Library: `cryptography` (Fernet authenticated encryption).
- Secrets are stored in `endpoint_secrets` as encrypted blobs.
- Decryption happens only in memory when needed for outbound requests.

## Master Key Management
Set a master key using one of the following:
- `PROMPTOPS_MASTER_KEY` environment variable (recommended).
- Or set `PROMPTOPS_ALLOW_KEYFILE=1` to auto-generate a local key file at `data/.master_key`.

The key file is ignored by git via `.gitignore`.

To generate a Fernet key manually:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode("utf-8"))
PY
```

## Masking and Redaction
- Secret values are masked in UI.
- Logs are filtered with redaction rules that mask common secret fields.
- Authorization headers and tokens are never printed in full.

## Logging & Audit
- Application logs go to `data/logs/app.log`.
- Audit events are stored in the database and mirrored to `data/audit/audit.log`.

## File and Path Safety
- Imports are restricted to the configured import directory.
- Exports are restricted to the configured export directory.
- Only `.xlsx` files are accepted for test imports.

## Limitations (MVP)
- No user authentication or RBAC.
- Master key management is local-only.
- No integration with OS keychains or external vaults.

## Recommended Production Enhancements
- Integrate with OS keychain or cloud secret managers.
- Add user authentication and role-based access control.
- Add request signing and outbound allowlists.
- Implement centralized audit retention and alerting.
