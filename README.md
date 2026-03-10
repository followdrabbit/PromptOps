# CyberPrompt AI
CyberPrompt AI is a production-oriented MVP for managing AI endpoints, chat sessions, and XLSX-driven prompt tests with strong security defaults.

## Features
- Endpoint registry with secure local credential storage
- Chat sessions with persistent history
- XLSX import and sequential test execution
- XLSX export for test run results
- Red Teaming suites with evaluator-model analysis
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

Or allow CyberPrompt AI to create a local key file:

```bash
export PROMPTOPS_ALLOW_KEYFILE=1
```

4. Run the app:

```bash
streamlit run app/main.py
```

## Configuration
Default settings live in `config.toml`. Runtime overrides are stored in the `settings` table and managed from the UI.

Automated Tests module settings (in `Configuration > Automated Test Settings`) include:
- parallel thread count (`tests_max_threads`)
- request timeout (`tests_request_timeout`)
- default result export format (`tests_result_format`: `xlsx` or `json`)

Red Teaming module settings (in `Configuration > Red Teaming Settings`) include:
- parallel thread count (`redteam_max_threads`)
- request timeout (`redteam_request_timeout`)
- default result export format (`redteam_result_format`: `xlsx` or `json`)
- evaluator endpoint (`redteam_evaluator_endpoint_id`)
- optional evaluator prompt template (`redteam_evaluator_prompt_template`) with variables:
  `{{PROMPT}}`, `{{PURPOSE}}`, `{{EXPECTED_RESULT}}`, `{{RELEVANCE}}`, `{{MODEL_RESPONSE}}`, `{{SUITE_NAME}}`

Endpoint `Additional variables (JSON)` supports typed entries, for example:

```json
{
  "REASONING": { "value": { "effort": "medium" }, "type": "json" },
  "MAX_OUTPUT_TOKENS": { "value": 1000, "type": "number" },
  "USE_CACHE": { "value": true, "type": "boolean" },
  "ORG_ID": { "value": "acme", "type": "string" }
}
```

These types are reflected in runtime editors in `Chat`, `Automated Tests`, and `Red Teaming`.

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
- `examples/sample_tests.json`
- `examples/sample_providers.xlsx`
- `examples/sample_providers.json`
- `examples/sample_endpoints.xlsx`
- `examples/sample_endpoints.json`

`sample_tests.*` uses the suite import/export format:
- `Suite Name` (required)
- `Suite Description` (optional)
- `Prompt` (required)
- `Notes` (optional)

## Default Import Files
Default baseline files for quick import are available in `examples/default_imports/`.
The test suite template buttons in the UI use `cyberprompt_ai_default_test_suites.*` as the default example source.

To regenerate:

```bash
python examples/generate_default_import_files.py
```

Generated default files:
- `examples/default_imports/cyberprompt_ai_default_providers.xlsx`
- `examples/default_imports/cyberprompt_ai_default_providers.json`
- `examples/default_imports/cyberprompt_ai_default_endpoints.xlsx`
- `examples/default_imports/cyberprompt_ai_default_endpoints.json`
- `examples/default_imports/cyberprompt_ai_default_test_suites.xlsx`
- `examples/default_imports/cyberprompt_ai_default_test_suites.json`
- `examples/default_imports/cyberprompt_ai_default_red_team_suites.xlsx`
- `examples/default_imports/cyberprompt_ai_default_red_team_suites.json`

Compatibility note:
- Existing environment variables remain `PROMPTOPS_*`.
