# Configuration Reference

## General Settings
Available runtime settings:
- `Application language`: `en` or `pt-BR`
- `Log level`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- `Default timeout (seconds)`: fallback request timeout
- `Output directory`: where result files are written
- `Import directory`: approved directory for imports
- `Verify SSL certificates`: global outbound SSL verification toggle
- `Log retention (days)`: retention policy indicator for operations
- `Secure storage`: currently `fernet`
- `Audit verbosity`: `standard` or `verbose`

Notes:
- Changes are persisted in the `settings` table.
- UI reads runtime settings on each page render.

## Provider Settings
Provider records are metadata for organization/filtering/reporting.

Fields:
- `Provider name` (required, unique)
- `Notes` (optional)

Capabilities:
- Create / Edit / Delete
- Import / Export (`xlsx` and `json`)
- Template download in both formats
- Import prevents overwriting existing provider names

## Endpoint Settings
Endpoint records define how requests are built and parsed.

Primary fields:
- `Endpoint Name`
- `Provider`
- `Endpoint URL`
- `Model Name`
- `API version` (`Response` or `Chat Completion`)
- `Headers (JSON)`
- `Body (JSON)`
- `Response JSON PATHs`
- `Response type` (`json` | `text`)
- `Timeout (seconds)`
- `Retry count`
- `Additional variables (JSON)` (typed custom placeholders)
- `API token` (encrypted secret)

Reserved placeholders:
- `{{API_TOKEN}}`: sourced from encrypted token field
- `{{MODEL_NAME}}`: sourced from endpoint model name
- `{{PROMPT}}`: sourced from runtime input (chat/test/red-team prompt)

API version:
- `Response`: optimized for endpoints like `/v1/responses` (payload usually uses `input`).
- `Chat Completion`: optimized for endpoints like `/v1/chat/completions` (payload uses `messages`).
- The selected mode is applied automatically in `Chat`, `Automated Tests`, and `Red Teaming` for the selected endpoint.

Additional variables format:
```json
{
  "REASONING": { "value": { "effort": "medium" }, "type": "json" },
  "MAX_OUTPUT_TOKENS": { "value": 1000, "type": "number" },
  "USE_CACHE": { "value": true, "type": "boolean" },
  "ORG_ID": { "value": "acme", "type": "string" }
}
```

Capabilities:
- Create / Edit / Delete
- Clone (duplicate endpoint configuration and variables, then adjust only required fields)
- Test endpoint connection directly in Create/Edit (without changing module)
- Import / Export (`xlsx` and `json`)
- Template download in both formats
- Export does not include secret values

## Automated Test Settings
Contains two groups:

1. Module settings:
- `Max threads`
- `Request timeout`
- `Retries`
- `Result format` (`xlsx` or `json`)

2. Test suite management:
- Suite CRUD (`name`, `description`)
- Prompt CRUD within suite (`Prompt`, `Notes`)
- Import / Export suites (`xlsx` and `json`)
- Template download in both formats

Suite import/export logical fields:
- `Suite Name`
- `Suite Description`
- `Prompt`
- `Notes`

## Red Teaming Settings
Contains two groups:

1. Module settings:
- `Max threads`
- `Request timeout`
- `Retries`
- `Result format` (`xlsx` or `json`)
- `Evaluator endpoint`
- `Evaluator prompt template`
- `Reset evaluator prompt template` (back to default)

2. Red-team suite management:
- Red-team suite CRUD
- Red-team case CRUD
- Import / Export suites (`xlsx` and `json`)
- Template download in both formats

Red-team logical fields:
- `Read Team Suite Name`
- `Read Team Suite Description`
- `Prompt`
- `Purpose of the test`
- `Expected Result`
- `Relevance` (0-10)
- `Notes`

## Configuration Best Practices
- Keep provider names stable; use them as reporting taxonomy.
- Keep endpoint templates vendor-agnostic with placeholders.
- Store only non-sensitive defaults in headers/body templates.
- Use `Additional variables` for model-specific knobs instead of hard-coding.
- Keep retries conservative (avoid accidental retry storms).
- Keep SSL verification enabled unless you fully trust the target network.
