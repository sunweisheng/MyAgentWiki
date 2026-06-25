from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ONLINE_HOOK_MODULE = "myagentwiki.agent_online_hook"
ONLINE_HOOK_CONFIG_REL_PATH = Path("config") / "llm.local.yml"


@dataclass
class HookExecutionError(Exception):
    message: str
    payload: dict | None = None

    def __str__(self) -> str:
        return self.message


def online_hook_error_message(details: str) -> str:
    config_path = str(ONLINE_HOOK_CONFIG_REL_PATH).replace("\\", "/")
    return (
        "Current task is configured to use the online model hook, but "
        f"`{config_path}` is missing or unusable. {details} "
        f"Please configure `{config_path}` separately for this workspace and do not commit it to Git."
    )


def online_hook_error_payload(details: str) -> dict:
    config_path = str(ONLINE_HOOK_CONFIG_REL_PATH).replace("\\", "/")
    return {
        "error": "online_hook_configuration_error",
        "message": online_hook_error_message(details),
        "config_path": config_path,
        "details": details,
    }


def is_online_hook_command(command: list[str]) -> bool:
    return ONLINE_HOOK_MODULE in command


def parse_online_hook_error(stdout: str, stderr: str) -> HookExecutionError | None:
    for candidate in (stdout, stderr):
        text = (candidate or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("error") != "online_hook_configuration_error":
            continue
        message = str(payload.get("message", "")).strip() or online_hook_error_message("Invalid online hook configuration.")
        return HookExecutionError(message=message, payload=payload)
    return None
