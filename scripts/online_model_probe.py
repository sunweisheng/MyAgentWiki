from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from openai import APIStatusError

from myagentwiki.llm.contracts import build_task_context, get_function_spec
from myagentwiki.llm.errors import LLMClientError
from myagentwiki.llm.online_client import RESPONSES_API_STYLE, OnlineLLMClient
from myagentwiki.llm.repair import repair_and_validate
from myagentwiki.llm.router import load_llm_settings


class ProbeHTTPError(Exception):
    def __init__(self, *, status_code: int | None, provider_message: str) -> None:
        self.status_code = status_code
        self.provider_message = provider_message


def provider_message(error: APIStatusError, *, api_key: str) -> str:
    response = getattr(error, "response", None)
    value = str(getattr(response, "text", "") or "").strip()
    if api_key:
        value = value.replace(api_key, "<redacted>")
    return value[:1000] or "Provider did not return an error body."


def load_probe(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Probe configuration cannot be read: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("Probe configuration must be a JSON object.")
    task_name = value.get("task_name")
    payload = value.get("payload")
    if not isinstance(task_name, str) or not task_name.strip():
        raise ValueError("Probe configuration requires a non-empty task_name.")
    if not isinstance(payload, dict):
        raise ValueError("Probe configuration requires an object payload.")
    return value


def run_probe(*, workspace: Path, probe: dict[str, Any]) -> dict[str, Any]:
    task_name = str(probe["task_name"]).strip()
    payload = probe["payload"]
    spec = get_function_spec(task_name)
    settings = load_llm_settings(workspace)
    context = build_task_context(
        spec,
        payload,
        document_max_chars=settings.document_max_chars,
    )
    with OnlineLLMClient(
        workspace,
        image_max_bytes=settings.image_max_bytes,
        image_mime_types=set(settings.image_mime_types),
    ) as client:
        try:
            if client.api_style == RESPONSES_API_STYLE:
                response = client._request_responses(spec=spec, context=context, image_paths=[])
                raw_call = client._extract_responses_call(response, spec)
            else:
                response = client._request_chat_completions(spec=spec, context=context, image_paths=[])
                raw_call = client._extract_chat_call(response, spec)
        except APIStatusError as exc:
            raise ProbeHTTPError(
                status_code=getattr(exc, "status_code", None),
                provider_message=provider_message(exc, api_key=str(client.config["api_key"])),
            ) from exc
        validated = repair_and_validate(
            spec=spec,
            raw_call=raw_call,
            payload=payload,
            backend=client.backend,
        )
        return {
            "status": "success",
            "backend": client.backend,
            "api_style": client.api_style,
            "task_name": task_name,
            "function_name": raw_call.function_name,
            "contract_valid": validated.validation,
            "decision_count": len(validated.arguments.get("decisions", [])),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe the configured MyAgentWiki online model route.")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_probe(workspace=args.workspace.resolve(), probe=load_probe(args.probe.resolve()))
    except ProbeHTTPError as exc:
        result = {
            "status": "failed",
            "error": {
                "backend": "online",
                "kind": "http_error",
                "http_status": exc.status_code,
                "provider_message": exc.provider_message,
            },
        }
    except LLMClientError as exc:
        result = {"status": "failed", "error": exc.as_record()}
    except (KeyError, ValueError) as exc:
        result = {"status": "failed", "error": {"kind": "probe_configuration", "message": str(exc)}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
