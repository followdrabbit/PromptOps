from __future__ import annotations

from pathlib import Path
import json

import pandas as pd


def _generate_sample_tests(output_dir: Path) -> tuple[Path, Path]:
    data = [
        {
            "Suite Name": "Smoke Suite",
            "Suite Description": "Basic health-check prompts.",
            "Prompt": "Say hello in one sentence.",
            "Notes": "Basic greeting",
        },
        {
            "Suite Name": "Smoke Suite",
            "Suite Description": "Basic health-check prompts.",
            "Prompt": "Summarize: PromptOps manages AI endpoints and tests.",
            "Notes": "",
        },
        {
            "Suite Name": "PT-BR Suite",
            "Suite Description": "Portuguese prompts for quick checks.",
            "Prompt": "Explique em duas frases o que e PromptOps.",
            "Notes": "Idioma portugues",
        },
    ]
    df = pd.DataFrame(data)
    xlsx_path = output_dir / "sample_tests.xlsx"
    json_path = output_dir / "sample_tests.json"
    df.to_excel(xlsx_path, index=False)
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return xlsx_path, json_path


def _generate_sample_providers(output_dir: Path) -> tuple[Path, Path]:
    data = [
        {
            "name": "OpenAI",
            "notes": "Primary provider for GPT models.",
        },
        {
            "name": "Anthropic",
            "notes": "Provider for Claude model family.",
        },
        {
            "name": "AzureFoundry",
            "notes": "Internal Azure AI Foundry integration.",
        },
    ]
    df = pd.DataFrame(data)
    xlsx_path = output_dir / "sample_providers.xlsx"
    json_path = output_dir / "sample_providers.json"
    df.to_excel(xlsx_path, index=False)
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return xlsx_path, json_path


def _generate_sample_endpoints(output_dir: Path) -> tuple[Path, Path]:
    json_records = [
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
                "system": "{{SYSTEM_PROMPT}}",
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
            "additional_variables": {"SYSTEM_PROMPT": "You are a helpful assistant."},
            "api_token": "",
        },
    ]

    xlsx_records: list[dict[str, object]] = []
    for record in json_records:
        xlsx_records.append(
            {
                "name": record["name"],
                "provider": record["provider"],
                "endpoint_url": record["endpoint_url"],
                "model_name": record["model_name"],
                "headers": json.dumps(record["headers"], ensure_ascii=False),
                "body": json.dumps(record["body"], ensure_ascii=False),
                "response_paths": record["response_paths"],
                "response_type": record["response_type"],
                "additional_variables": json.dumps(record["additional_variables"], ensure_ascii=False),
                "api_token": "",
            }
        )

    xlsx_path = output_dir / "sample_endpoints.xlsx"
    json_path = output_dir / "sample_endpoints.json"
    pd.DataFrame(xlsx_records).to_excel(xlsx_path, index=False)
    json_path.write_text(json.dumps(json_records, indent=2, ensure_ascii=False), encoding="utf-8")
    return xlsx_path, json_path


def main() -> None:
    output_dir = Path(__file__).resolve().parent

    tests_xlsx_path, tests_json_path = _generate_sample_tests(output_dir)
    providers_xlsx_path, providers_json_path = _generate_sample_providers(output_dir)
    endpoints_xlsx_path, endpoints_json_path = _generate_sample_endpoints(output_dir)

    print(f"Sample tests XLSX written to {tests_xlsx_path}")
    print(f"Sample tests JSON written to {tests_json_path}")
    print(f"Sample providers XLSX written to {providers_xlsx_path}")
    print(f"Sample providers JSON written to {providers_json_path}")
    print(f"Sample endpoints XLSX written to {endpoints_xlsx_path}")
    print(f"Sample endpoints JSON written to {endpoints_json_path}")


if __name__ == "__main__":
    main()
