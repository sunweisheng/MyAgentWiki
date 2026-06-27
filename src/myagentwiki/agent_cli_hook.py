from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .semantic import semantic_task_contract


AGENT_PROVIDERS = {"codex"}


def env_value(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def semantic_decisions_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "decision": {
                            "anyOf": [
                                {"type": "object"},
                                {"type": "string", "enum": ["abstain"]},
                            ],
                        },
                        "decision_status": {
                            "type": "string",
                            "enum": ["accepted", "abstained", "rejected"],
                        },
                        "confidence": {"type": "number"},
                        "reason_code": {"type": "string"},
                        "risk_flags": {"type": "array", "items": {"type": "string"}},
                        "supporting_ids": {"type": "array", "items": {"type": "string"}},
                        "abstain_reason": {"type": "string"},
                    },
                    "required": ["item_id", "decision", "confidence", "reason_code"],
                    "additionalProperties": True,
                },
            }
        },
        "required": ["decisions"],
        "additionalProperties": True,
    }


def semantic_agent_prompt(payload: dict) -> str:
    task_name = str(payload.get("task_name", "")).strip()
    contract = semantic_task_contract(task_name)
    required_fields = ", ".join(contract.get("decision_fields", ())) or "(none)"
    optional_fields = ", ".join(contract.get("optional_decision_fields", ())) or "(none)"
    return "\n".join([
        "You are MyAgentWiki's structure-first semantic compiler.",
        "Return only one valid JSON object matching this shape:",
        '{"decisions":[{"item_id":"...","decision":{...},"decision_status":"accepted","confidence":0.0,"reason_code":"...","risk_flags":[],"supporting_ids":[]}]}',
        "Use decision_status='abstained' and decision='abstain' when evidence is insufficient.",
        "Prefer structure_context, group_context, semantic_features, evidence ids, and section paths over isolated keywords.",
        "Do not single-vote Chinese keywords such as 案例, 规则, 历史, 如何, 用于.",
        f"Task: {task_name}",
        f"Required decision fields: {required_fields}",
        f"Optional decision fields: {optional_fields}",
        "Payload JSON:",
        json.dumps(payload, ensure_ascii=False),
    ])


def parse_json_object_from_text(text: str) -> dict | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(stripped[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def find_decisions_payload(value: Any) -> dict | None:
    if isinstance(value, dict):
        decisions = value.get("decisions")
        if isinstance(decisions, list):
            return {"decisions": [item for item in decisions if isinstance(item, dict)]}
        for key in ("structured_output", "result", "content", "message", "data"):
            found = find_decisions_payload(value.get(key))
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = find_decisions_payload(item)
            if found is not None:
                return found
    if isinstance(value, str):
        parsed = parse_json_object_from_text(value)
        if parsed is not None:
            return find_decisions_payload(parsed)
    return None


def normalize_agent_stdout(stdout: str) -> dict:
    parsed = parse_json_object_from_text(stdout)
    found = find_decisions_payload(parsed)
    return found if found is not None else {"decisions": []}


def split_command_env(value: str) -> list[str]:
    return shlex.split(value) if value.strip() else []


def provider_from_env() -> str:
    provider = env_value("MYAGENTWIKI_AGENT_CLI", "codex").lower()
    return provider if provider in AGENT_PROVIDERS else "codex"


def build_agent_command(
    provider: str,
    prompt: str,
    output_path: Path | None = None,
    schema_path: Path | None = None,
) -> tuple[list[str], str | None]:
    custom_command = split_command_env(env_value("MYAGENTWIKI_AGENT_CLI_COMMAND"))
    if custom_command:
        return custom_command, prompt

    command = [
        env_value("MYAGENTWIKI_CODEX_BIN", "codex"),
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
    ]
    model = env_value("MYAGENTWIKI_CODEX_MODEL")
    if model:
        command.extend(["--model", model])
    if output_path is not None:
        command.extend(["--output-last-message", str(output_path)])
    if schema_path is not None:
        command.extend(["--output-schema", str(schema_path)])
    command.append("-")
    return command, prompt


def run_agent_cli(payload: dict) -> dict:
    provider = provider_from_env()
    prompt = semantic_agent_prompt(payload)
    timeout_seconds = int(env_value("MYAGENTWIKI_AGENT_CLI_TIMEOUT_SECONDS", "120") or "120")
    with tempfile.TemporaryDirectory(prefix="myagentwiki-agent-cli-") as tmpdir:
        output_path = Path(tmpdir) / "semantic_decisions.json"
        schema_path = Path(tmpdir) / "semantic_decisions.schema.json"
        schema_path.write_text(json.dumps(semantic_decisions_schema(), ensure_ascii=False), encoding="utf-8")
        command, stdin_text = build_agent_command(provider, prompt, output_path, schema_path)
        try:
            completed = subprocess.run(
                command,
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"decisions": []}
        output_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    if completed.returncode != 0:
        return {"decisions": []}
    return normalize_agent_stdout(output_text or completed.stdout)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    result = run_agent_cli(payload if isinstance(payload, dict) else {})
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
