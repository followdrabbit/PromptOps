# Module Guide

## Home
Purpose:
- Show high-level stats and quick access cards.

What to expect:
- Counts for endpoints, chat sessions, suites, and runs.
- Recent executions and endpoints.
- Navigation cards to key modules.

## Configuration
Purpose:
- Central admin area for runtime settings and managed entities.

Sections:
- `General Settings`
- `Provider Settings`
- `Endpoint Settings`
- `Automated Test Settings`
- `Red Teaming Settings`

Each section has dedicated pages and CRUD/import/export flows where applicable.

## Chat
Purpose:
- Conversational testing against one endpoint with persistent history.

Behavior:
- Chat sessions are listed in sidebar (similar workflow to ChatGPT).
- Session title is auto-generated after first interaction and can be renamed inline.
- Messages are persisted in database.
- Prompt is rendered immediately after send.
- Endpoint runtime additional variables can be edited per execution.

## Compare
Purpose:
- Send the same prompt to multiple endpoints at once and compare outputs.

Behavior:
- Supports up to `10` selected endpoints.
- Responses are displayed side-by-side with horizontal scroll.
- Preserves per-endpoint context during the compare session.
- Shows response latency and incomplete-response hints when available.

## Automated Tests
Purpose:
- Repeatable multi-suite prompt execution against a selected endpoint.

Behavior:
- Select one endpoint and enable one or more suites via toggles.
- Uses module settings from `Configuration > Automated Test Settings`:
  - max threads
  - request timeout
  - retries
  - result format (`xlsx` or `json`)
- Exports results automatically after each suite run.
- Output filename pattern:
  - `automated_tests_<endpoint>_<suite>_<timestamp>.<ext>`
- Result fields:
  - `Selected Endpoint`
  - `prompt_sent`
  - `response_received`
  - `latency_ms`
  - `error_message`
  - `status`
  - `timestamp`

## Red Teaming
Purpose:
- Security-oriented validation using a target model and evaluator model.

Behavior:
- Select one or more red-team suites.
- Choose `Target endpoint`.
- Uses evaluator endpoint and evaluator prompt template from `Red Teaming Settings`.
- Uses module settings from `Red Teaming Settings`:
  - max threads
  - request timeout
  - retries
  - result format (`xlsx` or `json`)
- Exports results automatically after each suite run.
- Output filename pattern:
  - `red_teaming_<target_endpoint>_<suite>_<timestamp>.<ext>`
- Includes LLM judge fields in exported results such as:
  - `Evaluator Endpoint`
  - `LLM Judge Veredict`
  - `LLM Judge Veredict Justification`
  - `LLM Judge Score`
  - `LLM Judge Score Justification`
- The duplicate `evaluation_score` column is not exported; use `LLM Judge Score`.

## Documentation
Purpose:
- Make project documentation available inside Streamlit.

Behavior:
- Organized tabs for overview, setup, modules, configuration, operations, architecture, security, and FAQ.
- Markdown files can be downloaded directly from the UI.
