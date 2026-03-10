# Getting Started

## Requirements
- Python `3.11+` (required because `tomllib` is used).
- OS: Windows, Linux, or macOS.
- Network access to your target AI endpoints.

Python dependencies are listed in `requirements.txt`:
- `streamlit`
- `sqlalchemy`
- `pydantic`
- `pandas`
- `openpyxl`
- `cryptography`
- `requests`

## Installation
```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
```

## Configure Secret Encryption Key
Preferred option:
PowerShell:
```powershell
$env:PROMPTOPS_MASTER_KEY="your_fernet_key"
```

Bash:
```bash
export PROMPTOPS_MASTER_KEY="your_fernet_key"
```

Alternative option (local key file managed by app):
PowerShell:
```powershell
$env:PROMPTOPS_ALLOW_KEYFILE=1
```

Bash:
```bash
export PROMPTOPS_ALLOW_KEYFILE=1
```

To generate a Fernet key:
```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode("utf-8"))
PY
```

## Run the Application
```bash
streamlit run app/main.py
```

Open the URL shown by Streamlit (usually `http://localhost:8501`).

## First-Time Setup Checklist
1. Go to `Configuration > General Settings`.
2. Confirm `Output directory`, `Import directory`, and `Log level`.
3. Create at least one provider in `Provider Settings`.
4. Create at least one endpoint in `Endpoint Settings` and set API token.
5. Import or create test suites in `Automated Test Settings` and/or `Red Teaming Settings`.
6. Validate using `Chat` and `Compare`.

## Default Import Files
Baseline examples are available in `examples/default_imports/`:
- `cyberprompt_ai_default_providers.*`
- `cyberprompt_ai_default_endpoints.*`
- `cyberprompt_ai_default_test_suites.*`
- `cyberprompt_ai_default_red_team_suites.*`

Regenerate them:
```bash
python examples/generate_default_import_files.py
```
