from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from myagentwiki.llm.cli_client import CLILLMClient
from myagentwiki.llm.contracts import get_function_spec, registered_task_names


def test_cli_uses_output_schema_and_image_argument(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png")
    recorded = {}

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003
        recorded["command"] = command
        recorded["input"] = kwargs["input"]
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps({
            "function_name": "submit_image_description",
            "arguments_json": json.dumps({
                "extracted_text": "文字",
                "summary": "图片摘要",
                "confidence": 0.9,
                "reason": "visible",
                "warnings": [],
            }, ensure_ascii=False),
        }, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("myagentwiki.llm.cli_client.subprocess.run", fake_run)
    client = CLILLMClient(tmp_path, timeout_seconds=30, model="test-model")
    result = client.request(
        spec=get_function_spec("describe_image"),
        context={"image_name": "image.png"},
        image_paths=[image_path],
    )
    assert result.function_name == "submit_image_description"
    assert ["-i", str(image_path.resolve())] == recorded["command"][
        recorded["command"].index("-i"):recorded["command"].index("-i") + 2
    ]
    assert ["--sandbox", "read-only"] == recorded["command"][
        recorded["command"].index("--sandbox"):recorded["command"].index("--sandbox") + 2
    ]
    assert "--ask-for-approval" not in recorded["command"]
    assert "--output-schema" in recorded["command"]
    assert "submit_image_description" in recorded["input"]


@pytest.mark.parametrize("task_name", registered_task_names())
def test_every_contract_can_be_registered_with_cli_schema(
    tmp_path: Path,
    monkeypatch,
    task_name: str,
) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003
        schema_path = Path(command[command.index("--output-schema") + 1])
        output_path = Path(command[command.index("--output-last-message") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        function_name = schema["properties"]["function_name"]["const"]
        output_path.write_text(json.dumps({
            "function_name": function_name,
            "arguments_json": "{}",
        }), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("myagentwiki.llm.cli_client.subprocess.run", fake_run)
    spec = get_function_spec(task_name)
    result = CLILLMClient(tmp_path, timeout_seconds=30).request(
        spec=spec,
        context={},
        image_paths=[],
    )

    assert result.function_name == spec.function_name
