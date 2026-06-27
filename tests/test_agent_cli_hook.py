from __future__ import annotations

import json
from pathlib import Path

from myagentwiki.agent_cli_hook import (
    build_agent_command,
    normalize_agent_stdout,
    semantic_agent_prompt,
    semantic_decisions_schema,
)


def test_agent_cli_prompt_includes_contract_and_structure_priority() -> None:
    prompt = semantic_agent_prompt(
        {
            "task_name": "claim_role",
            "items": [
                {
                    "item_id": "clm_1",
                    "text": "团队整理历史数据用于分析转化趋势。",
                    "structure_context": {"semantic_feature_counts": {"metrics": 1}},
                }
            ],
        }
    )

    assert "Required decision fields: knowledge_role, page_intent_hints, concept_candidate_score" in prompt
    assert "Prefer structure_context" in prompt
    assert "Do not single-vote Chinese keywords" in prompt
    assert "历史" in prompt


def test_build_codex_command_uses_headless_structured_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MYAGENTWIKI_CODEX_BIN", "codex-test")
    monkeypatch.setenv("MYAGENTWIKI_CODEX_MODEL", "gpt-test")
    output_path = tmp_path / "out.json"
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(semantic_decisions_schema()), encoding="utf-8")

    command, stdin_text = build_agent_command(
        "codex",
        "return json",
        output_path=output_path,
        schema_path=schema_path,
    )

    assert command[:2] == ["codex-test", "exec"]
    assert ["--model", "gpt-test"] == command[command.index("--model"):command.index("--model") + 2]
    assert ["--output-last-message", str(output_path)] == command[
        command.index("--output-last-message"):command.index("--output-last-message") + 2
    ]
    assert ["--output-schema", str(schema_path)] == command[
        command.index("--output-schema"):command.index("--output-schema") + 2
    ]
    assert command[-1] == "-"
    assert stdin_text == "return json"


def test_normalize_agent_stdout_extracts_decisions_from_envelopes() -> None:
    codex_output = "prefix\n{\"decisions\":[{\"item_id\":\"a\",\"decision\":{\"page_intent\":\"topic\"},\"confidence\":0.8,\"reason_code\":\"ok\"}]}\n"
    codex_output_nested = json.dumps({
        "type": "result",
        "structured_output": {
            "decisions": [
                {
                    "item_id": "b",
                    "decision": {"knowledge_role": "fact"},
                    "confidence": 0.81,
                    "reason_code": "ok",
                }
            ]
        },
    })

    assert normalize_agent_stdout(codex_output)["decisions"][0]["item_id"] == "a"
    assert normalize_agent_stdout(codex_output_nested)["decisions"][0]["item_id"] == "b"
