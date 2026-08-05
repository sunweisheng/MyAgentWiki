from __future__ import annotations

from typing import Any


class LLMClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        backend: str,
        kind: str,
        retryable: bool,
        http_status: int | None = None,
        repaired: bool = False,
        debug_details: dict[str, Any] | None = None,
        guidance: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.backend = backend
        self.kind = kind
        self.retryable = retryable
        self.http_status = http_status
        self.repaired = repaired
        self.debug_details = debug_details or {}
        self.guidance = guidance or {}

    def as_record(self) -> dict[str, Any]:
        record = {
            "backend": self.backend,
            "kind": self.kind,
            "retryable": self.retryable,
            "http_status": self.http_status,
            "repaired": self.repaired,
            "message": self.message,
        }
        if self.guidance:
            record["guidance"] = self.guidance
        return record


class LLMConfigurationError(LLMClientError):
    def __init__(
        self,
        message: str,
        *,
        backend: str = "online",
        guidance: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            backend=backend,
            kind="configuration_error",
            retryable=False,
            guidance=guidance,
        )


class LLMResponseError(LLMClientError):
    def __init__(
        self,
        message: str,
        *,
        backend: str,
        repaired: bool = False,
        debug_details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            backend=backend,
            kind="invalid_response",
            retryable=backend == "online",
            repaired=repaired,
            debug_details=debug_details,
        )


class LLMRouteError(Exception):
    def __init__(
        self,
        message: str,
        *,
        request_id: str,
        task_name: str,
        attempts: list[dict[str, Any]],
        configuration_guidance: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id
        self.task_name = task_name
        self.attempts = attempts
        self.payload = {
            "error": "llm_request_failed",
            "message": message,
            "request_id": request_id,
            "task_name": task_name,
            "attempts": attempts,
        }
        if configuration_guidance:
            self.payload["configuration_guidance"] = configuration_guidance


class LLMProjectConfigurationError(Exception):
    def __init__(self, message: str, *, config_path: str) -> None:
        super().__init__(message)
        self.message = message
        self.payload = {
            "error": "llm_configuration_migration_required",
            "message": message,
            "config_path": config_path,
        }


def legacy_command_migration_message(*, location: str, command: list[str]) -> str:
    command_text = " ".join(command)
    if "myagentwiki.agent_online_hook" in command_text:
        suggestion = (
            "Remove `command`, set the task to `llm_assisted`, and keep the user's online "
            "provider settings in the MyAgentWiki Skill root `.env`; online is now the primary route."
        )
    elif "myagentwiki.agent_cli_hook" in command_text:
        suggestion = (
            "Remove `command` and set the task to `llm_assisted`; Codex CLI is now the automatic "
            "fallback route and is not selected per task."
        )
    elif "myagentwiki.agent_hook" in command_text:
        suggestion = (
            "Remove `command` and set the task to `deterministic` to preserve the old local behavior, "
            "or use `llm_assisted` to adopt the new primary/fallback route."
        )
    else:
        suggestion = (
            "Custom LLM commands cannot be migrated automatically. Remove `command` and choose "
            "`llm_assisted` or `deterministic` explicitly after reviewing the custom integration."
        )
    return f"Legacy LLM command configuration found at `{location}`. {suggestion}"
