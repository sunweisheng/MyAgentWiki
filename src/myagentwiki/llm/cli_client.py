from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from json_repair import loads as repair_loads
from jsonschema import Draft202012Validator

from ..debug_trace import current_debug_tracer, file_metadata
from .contracts import LLMFunctionSpec, cli_result_schema
from .errors import LLMClientError, LLMResponseError
from .repair import RawFunctionCall


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _codex_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _codex_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if any(key in value for key in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens")):
                candidates.append(value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(events)
    if not candidates:
        return {"available": False}
    usage = candidates[-1]
    input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    return {
        "available": True,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or input_tokens + output_tokens),
        "cached_input_tokens": int(usage.get("cached_input_tokens", 0) or 0),
    }


class CLILLMClient:
    backend = "cli"

    def __init__(
        self,
        workspace: Path,
        *,
        timeout_seconds: int,
        model: str = "",
        executable: str = "codex",
    ) -> None:
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        self.model = model or _env("MYAGENTWIKI_CODEX_MODEL")
        self.executable = executable or _env("MYAGENTWIKI_CODEX_BIN", "codex")

    def build_command(
        self,
        *,
        output_path: Path,
        schema_path: Path,
        image_paths: list[Path],
    ) -> list[str]:
        command = [
            self.executable,
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--cd",
            str(self.workspace),
        ]
        if current_debug_tracer() is not None:
            command.append("--json")
        if self.model:
            command.extend(["--model", self.model])
        for image_path in image_paths:
            command.extend(["-i", str(image_path.resolve())])
        command.extend([
            "--output-last-message",
            str(output_path),
            "--output-schema",
            str(schema_path),
            "-",
        ])
        return command

    def build_prompt(self, *, spec: LLMFunctionSpec, context: dict[str, Any]) -> str:
        return "\n".join([
            "You are the MyAgentWiki CLI LLM client.",
            f"Complete the task by submitting the function result `{spec.function_name}`.",
            spec.description,
            spec.instructions,
            "The supplied output schema is the function result envelope. Serialize the function parameters as JSON in `arguments_json`.",
            "Task context:",
            json.dumps(context, ensure_ascii=False, sort_keys=True),
        ])

    def request(
        self,
        *,
        spec: LLMFunctionSpec,
        context: dict[str, Any],
        image_paths: list[Path],
    ) -> RawFunctionCall:
        result_schema = cli_result_schema(spec)
        prompt = self.build_prompt(spec=spec, context=context)
        debug_enabled = current_debug_tracer() is not None
        debug_base = {
            "model": self.model,
            "prompt": prompt,
            "function": {
                "name": spec.function_name,
                "parameters_schema": spec.parameters_schema,
                "result_schema": result_schema,
            },
            "context": context,
            "images": [file_metadata(path) for path in image_paths],
        } if debug_enabled else {}
        with tempfile.TemporaryDirectory(prefix="myagentwiki-llm-cli-") as tmpdir:
            output_path = Path(tmpdir) / "function_result.json"
            schema_path = Path(tmpdir) / "function_result.schema.json"
            schema_path.write_text(json.dumps(result_schema, ensure_ascii=False), encoding="utf-8")
            command = self.build_command(
                output_path=output_path,
                schema_path=schema_path,
                image_paths=image_paths,
            )
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.workspace,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise LLMClientError(
                    "Codex CLI request timed out.",
                    backend=self.backend,
                    kind="timeout",
                    retryable=False,
                    debug_details={
                        **debug_base,
                        "command": command,
                        "stdout": _text(exc.stdout),
                        "stderr": _text(exc.stderr),
                    } if debug_enabled else None,
                ) from exc
            except OSError as exc:
                raise LLMClientError(
                    f"Codex CLI could not start: {exc}",
                    backend=self.backend,
                    kind="unavailable",
                    retryable=False,
                    debug_details={**debug_base, "command": command} if debug_enabled else None,
                ) from exc
            if completed.returncode != 0:
                raise LLMClientError(
                    f"Codex CLI failed with exit code {completed.returncode}.",
                    backend=self.backend,
                    kind="process_error",
                    retryable=False,
                    debug_details={
                        **debug_base,
                        "command": command,
                        "exit_code": completed.returncode,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                        "events": _codex_events(completed.stdout),
                    } if debug_enabled else None,
                )
            raw_output = output_path.read_text(encoding="utf-8") if output_path.exists() else completed.stdout
            events = _codex_events(completed.stdout) if debug_enabled else []
            debug_result = {
                **debug_base,
                "command": command,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "events": events,
                "usage": _codex_usage(events),
                "raw_output": raw_output,
            } if debug_enabled else {}
        try:
            envelope = repair_loads(raw_output)
        except Exception as exc:
            raise LLMResponseError(
                f"CLI function envelope could not be repaired: {exc}",
                backend=self.backend,
                debug_details=debug_result,
            ) from exc
        if not isinstance(envelope, dict):
            raise LLMResponseError(
                "CLI function envelope must be an object.",
                backend=self.backend,
                debug_details=debug_result,
            )
        errors = sorted(
            Draft202012Validator(result_schema).iter_errors(envelope),
            key=lambda item: list(item.absolute_path),
        )
        if errors:
            raise LLMResponseError(
                f"CLI function envelope is invalid: {errors[0].message}",
                backend=self.backend,
                debug_details=debug_result,
            )
        return RawFunctionCall(
            function_name=str(envelope["function_name"]),
            arguments_json=str(envelope["arguments_json"]),
            debug=debug_result,
        )
