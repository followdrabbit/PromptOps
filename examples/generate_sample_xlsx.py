from __future__ import annotations

from pathlib import Path
import json

import pandas as pd


def _generate_sample_tests(output_dir: Path) -> Path:
    data = [
        {
            "order": 1,
            "enabled": True,
            "test_name": "Greeting test",
            "prompt": "Say hello in one sentence.",
            "expected_result": "Hello",
            "validation_type": "contains",
            "tags": "smoke",
            "temperature": 0.7,
            "max_tokens": 64,
            "notes": "Basic greeting",
        },
        {
            "order": 2,
            "enabled": True,
            "test_name": "Summarization test",
            "prompt": "Summarize: PromptOps manages AI endpoints and tests.",
            "expected_result": "PromptOps",
            "validation_type": "contains",
            "tags": "summary",
            "temperature": 0.5,
            "max_tokens": 128,
            "notes": "",
        },
    ]
    df = pd.DataFrame(data)
    output_path = output_dir / "sample_tests.xlsx"
    df.to_excel(output_path, index=False)
    return output_path


def _generate_sample_providers(output_dir: Path) -> tuple[Path, Path]:
    data = [
        {
            "name": "OpenAI",
            "notes": "Primary provider for GPT models.",
            "is_active": True,
        },
        {
            "name": "Anthropic",
            "notes": "Provider for Claude model family.",
            "is_active": True,
        },
        {
            "name": "AzureFoundry",
            "notes": "Internal Azure AI Foundry integration.",
            "is_active": False,
        },
    ]
    df = pd.DataFrame(data)
    xlsx_path = output_dir / "sample_providers.xlsx"
    json_path = output_dir / "sample_providers.json"
    df.to_excel(xlsx_path, index=False)
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return xlsx_path, json_path


def main() -> None:
    output_dir = Path(__file__).resolve().parent

    tests_path = _generate_sample_tests(output_dir)
    providers_xlsx_path, providers_json_path = _generate_sample_providers(output_dir)

    print(f"Sample tests XLSX written to {tests_path}")
    print(f"Sample providers XLSX written to {providers_xlsx_path}")
    print(f"Sample providers JSON written to {providers_json_path}")


if __name__ == "__main__":
    main()
