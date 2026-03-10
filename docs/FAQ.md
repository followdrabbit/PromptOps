# FAQ

## Why are environment variables still `PROMPTOPS_*`?
These keys are kept for backward compatibility. Product branding is CyberPrompt AI, but runtime key names remain stable to avoid breaking existing environments.

## Are API keys stored in plaintext?
No. API tokens are encrypted using Fernet before being persisted.

## Where are secrets stored?
Secrets are stored in `endpoint_secrets` as encrypted blobs, separate from endpoint metadata.

## Can I use non-OpenAI providers?
Yes. Endpoint registration is template-driven (`URL`, `Headers`, `Body`, `Response JSON PATHs`) and supports vendor-agnostic request/response mappings.

## How do Additional variables work?
Define typed variables in endpoint configuration and reference them in headers/body using placeholders. At runtime (Chat/Automated Tests/Red Teaming) you can override values without changing saved endpoint defaults.

## Why does my response not show in Chat/Compare?
Check:
- endpoint credentials
- response JSON path
- request timeout/retries
- provider response type (`json` vs `text`)
- logs at `DEBUG` level

## Which formats are supported for import/export?
- Providers: `xlsx`, `json`
- Endpoints: `xlsx`, `json` (without secrets on export)
- Automated test suites: `xlsx`, `json`
- Red-team suites: `xlsx`, `json`

## How do I reset red-team evaluator instructions?
Use `Configuration > Red Teaming Settings` and click reset for the evaluator prompt template.

## Can I run all suites at once?
Yes. Automated Tests and Red Teaming support an "enable all suites" toggle.

## Is this enterprise-ready?
It is an MVP with enterprise-oriented structure. For production hardening, add RBAC/authentication, external secret managers, centralized audit retention, and stronger multi-user isolation.
