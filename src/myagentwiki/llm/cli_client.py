from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from json_repair import loads as repair_loads
from jsonschema import Draft202012Validator

from .contracts import LLMFunctionSpec, cli_result_schema
from .errors import LLMClientError, LLMResponseError
from .repair import RawFunctionCall


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


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
            "--ask-for-approval",
            "never",
            "--cd",
            str(self.workspace),
        ]
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
                    input=self.build_prompt(spec=spec, context=context),
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
                ) from exc
            except OSError as exc:
                raise LLMClientError(
                    f"Codex CLI could not start: {exc}",
                    backend=self.backend,
                    kind="unavailable",
                    retryable=False,
                ) from exc
            if completed.returncode != 0:
                raise LLMClientError(
                    f"Codex CLI failed with exit code {completed.returncode}.",
                    backend=self.backend,
                    kind="process_error",
                    retryable=False,
                )
            raw_output = output_path.read_text(encoding="utf-8") if output_path.exists() else completed.stdout
        try:
            envelope = repair_loads(raw_output)
        except Exception as exc:
            raise LLMResponseError(f"CLI function envelope could not be repaired: {exc}", backend=self.backend) from exc
        if not isinstance(envelope, dict):
            raise LLMResponseError("CLI function envelope must be an object.", backend=self.backend)
        errors = sorted(
            Draft202012Validator(result_schema).iter_errors(envelope),
            key=lambda item: list(item.absolute_path),
        )
        if errors:
            raise LLMResponseError(f"CLI function envelope is invalid: {errors[0].message}", backend=self.backend)
        return RawFunctionCall(
            function_name=str(envelope["function_name"]),
            arguments_json=str(envelope["arguments_json"]),
        )
