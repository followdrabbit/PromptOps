# PromptOps
PromptOps is a production-oriented MVP for managing AI endpoints, chat sessions, and XLSX-driven prompt tests with strong security defaults.

## Features
- Endpoint registry with secure local credential storage
- Chat sessions with persistent history
- XLSX import and sequential test execution
- XLSX export for test run results
- Logging and audit trails for critical actions

## Quick Start
1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set the master key:

```bash
export PROMPTOPS_MASTER_KEY="your_fernet_key"
```

Or allow PromptOps to create a local key file:

```bash
export PROMPTOPS_ALLOW_KEYFILE=1
```

4. Run the app:

```bash
streamlit run app/main.py
```

## Configuration
Default settings live in `config.toml`. Runtime overrides are stored in the `settings` table and managed from the UI.

## Documentation
- `docs/ARCHITECTURE.md`
- `docs/SECURITY.md`

## Data Storage
Local runtime data is stored under `data/` and ignored by git. This includes:
- SQLite database
- Logs and audit logs
- Imports and exports

## Example Test Suite
Example files can be generated in `examples/` by running:

```bash
python examples/generate_sample_xlsx.py
```

Generated files:
- `examples/sample_tests.xlsx`
- `examples/sample_providers.xlsx`
- `examples/sample_providers.json`
