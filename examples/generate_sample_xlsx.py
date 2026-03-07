from __future__ import annotations

from pathlib import Path

import pandas as pd


def main() -> None:
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
    output_dir = Path(__file__).resolve().parent
    output_path = output_dir / "sample_tests.xlsx"
    df.to_excel(output_path, index=False)
    print(f"Sample XLSX written to {output_path}")


if __name__ == "__main__":
    main()
