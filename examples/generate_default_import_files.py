from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _to_xlsx_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, (dict, list)):
                row[key] = json.dumps(value, ensure_ascii=False)
            else:
                row[key] = value
        rows.append(row)
    return rows


def _write_json_xlsx(records: list[dict[str, Any]], json_path: Path, xlsx_path: Path) -> None:
    json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(_to_xlsx_rows(records)).to_excel(xlsx_path, index=False)


def _default_providers() -> list[dict[str, Any]]:
    return [
        {"name": "OpenAI", "notes": "Default provider for OpenAI-compatible endpoints."},
        {"name": "Anthropic", "notes": "Default provider for Anthropic Messages API."},
        {"name": "Google Gemini", "notes": "Default provider for Gemini REST endpoints."},
        {"name": "Azure Foundry", "notes": "Default provider for Azure AI Foundry endpoints."},
    ]


def _default_endpoints() -> list[dict[str, Any]]:
    return [
        {
            "name": "OpenAI Responses - GPT 4.1 Mini",
            "provider": "OpenAI",
            "endpoint_url": "https://api.openai.com/v1/responses",
            "model_name": "gpt-4.1-mini",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer {{API_TOKEN}}",
            },
            "body": {
                "model": "{{MODEL_NAME}}",
                "input": "{{PROMPT}}",
                "max_output_tokens": 1000,
                "temperature": 0.7,
            },
            "response_paths": "$output[1].content[0].text",
            "response_type": "json",
            "additional_variables": {},
            "api_token": "",
        },
        {
            "name": "Anthropic Messages - Sonnet",
            "provider": "Anthropic",
            "endpoint_url": "https://api.anthropic.com/v1/messages",
            "model_name": "claude-sonnet-4-5",
            "headers": {
                "Content-Type": "application/json",
                "x-api-key": "{{API_TOKEN}}",
                "anthropic-version": "2023-06-01",
            },
            "body": {
                "model": "{{MODEL_NAME}}",
                "messages": [
                    {
                        "role": "user",
                        "content": "{{PROMPT}}",
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.7,
            },
            "response_paths": "$content[0].text",
            "response_type": "json",
            "additional_variables": {},
            "api_token": "",
        },
        {
            "name": "Gemini Generate Content - Flash",
            "provider": "Google Gemini",
            "endpoint_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={{API_TOKEN}}",
            "model_name": "gemini-2.0-flash",
            "headers": {
                "Content-Type": "application/json",
            },
            "body": {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": "{{PROMPT}}",
                            }
                        ]
                    }
                ]
            },
            "response_paths": "$candidates[0].content.parts[0].text",
            "response_type": "json",
            "additional_variables": {},
            "api_token": "",
        },
    ]


def _default_test_suites() -> list[dict[str, Any]]:
    return [
        {
            "Suite Name": "Smoke Suite",
            "Suite Description": "Quick sanity checks for endpoint readiness.",
            "Prompt": "Say hello in one sentence.",
            "Notes": "Basic connectivity prompt",
        },
        {
            "Suite Name": "Smoke Suite",
            "Suite Description": "Quick sanity checks for endpoint readiness.",
            "Prompt": "Summarize PromptOps in two short sentences.",
            "Notes": "Basic summarization",
        },
        {
            "Suite Name": "PT-BR Validation",
            "Suite Description": "Portuguese language validation prompts.",
            "Prompt": "Explique em duas frases o que e PromptOps.",
            "Notes": "Idioma portugues",
        },
    ]


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "default_imports"
    output_dir.mkdir(parents=True, exist_ok=True)

    providers = _default_providers()
    endpoints = _default_endpoints()
    suites = _default_test_suites()

    _write_json_xlsx(
        providers,
        output_dir / "promptops_default_providers.json",
        output_dir / "promptops_default_providers.xlsx",
    )
    _write_json_xlsx(
        endpoints,
        output_dir / "promptops_default_endpoints.json",
        output_dir / "promptops_default_endpoints.xlsx",
    )
    _write_json_xlsx(
        suites,
        output_dir / "promptops_default_test_suites.json",
        output_dir / "promptops_default_test_suites.xlsx",
    )

    print(f"Default import files generated at: {output_dir}")


if __name__ == "__main__":
    main()
