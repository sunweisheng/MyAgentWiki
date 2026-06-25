from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .agent_cli_hook import parse_json_object_from_text
from .hook_protocol import (
    ONLINE_HOOK_CONFIG_REL_PATH,
    online_hook_error_payload,
)
from .runtime_env import load_simple_yaml
from .semantic import (
    SEMANTIC_DECISION_STATUS_ABSTAINED,
    SEMANTIC_DECISION_STATUS_ACCEPTED,
    SEMANTIC_TASK_CONTRACTS,
    semantic_decision_missing_fields,
)

OPENAI_COMPATIBLE = "openai_compatible"
ANTHROPIC_COMPATIBLE = "anthropic_compatible"
SUPPORTED_PROTOCOLS = {OPENAI_COMPATIBLE, ANTHROPIC_COMPATIBLE}
ANTHROPIC_VERSION = "2023-06-01"


class OnlineHookConfigError(ValueError):
    pass


def load_online_hook_config(cwd: Path | None = None) -> dict:
    root = (cwd or Path.cwd()).resolve()
    path = root / ONLINE_HOOK_CONFIG_REL_PATH
    if not path.exists():
        raise OnlineHookConfigError(
            f"Missing required local config file at `{ONLINE_HOOK_CONFIG_REL_PATH.as_posix()}`."
        )
    try:
        config = load_simple_yaml(path)
    except Exception as exc:  # pragma: no cover - defensive
        raise OnlineHookConfigError(
            f"Failed to parse `{ONLINE_HOOK_CONFIG_REL_PATH.as_posix()}`: {exc}"
        ) from exc
    provider = config.get("provider", {})
    if not isinstance(provider, dict):
        raise OnlineHookConfigError("`provider` must be a mapping.")
    protocol = str(provider.get("protocol", "")).strip()
    base_url = str(provider.get("base_url", "")).strip()
    model = str(provider.get("model", "")).strip()
    api_key = str(provider.get("api_key", "")).strip()
    timeout_raw = provider.get("timeout_seconds", 120)
    try:
        timeout_seconds = max(int(timeout_raw), 5)
    except (TypeError, ValueError):
        raise OnlineHookConfigError("`provider.timeout_seconds` must be an integer >= 5.")
    missing = [
        field
        for field, value in (
            ("provider.protocol", protocol),
            ("provider.base_url", base_url),
            ("provider.model", model),
            ("provider.api_key", api_key),
        )
        if not value
    ]
    if missing:
        raise OnlineHookConfigError(f"Missing required field(s): {', '.join(missing)}.")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise OnlineHookConfigError(
            f"Unsupported provider protocol `{protocol}`. Expected one of: {', '.join(sorted(SUPPORTED_PROTOCOLS))}."
        )
    return {
        "protocol": protocol,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key": api_key,
        "timeout_seconds": timeout_seconds,
    }


def response_format_for_payload(payload: dict) -> tuple[str, dict]:
    task = str(payload.get("task", "")).strip()
    task_name = str(payload.get("task_name", "")).strip()
    if task.startswith("review_") and task_name:
        required_fields = SEMANTIC_TASK_CONTRACTS.get(task_name, {}).get("decision_fields", ())
        optional_fields = SEMANTIC_TASK_CONTRACTS.get(task_name, {}).get("optional_decision_fields", ())
        instructions = [
            "Return JSON only.",
            "Use this exact top-level shape:",
            '{"decisions":[{"item_id":"...","decision":{...},"decision_status":"accepted","confidence":0.0,"reason_code":"...","risk_flags":[],"supporting_ids":[],"abstain_reason":""}]}',
            "If evidence is insufficient, set decision_status to abstained and decision to abstain.",
            f"Required decision fields: {', '.join(required_fields) or '(none)'}",
            f"Optional decision fields: {', '.join(optional_fields) or '(none)'}",
        ]
        return (
            "semantic_batch",
            {
                "task_name": task_name,
                "instructions": instructions,
                "payload": payload,
            },
        )
    task_shapes = {
        "review_auto_decision": {
            "response_shape": {
                "decision": "auto_apply|escalate|skip",
                "action": "merge|keep_both|archive_one|edit_then_resume|assign_alias|remove_alias",
                "primary_claim_id": "string when needed",
                "secondary_claim_id": "string when needed",
                "primary_page_id": "string when needed",
                "alias_value": "string when needed",
                "confidence": 0.0,
                "reason": "string",
            },
            "instructions": [
                "Return JSON only.",
                "Only choose an action allowed by review.allowed_actions.",
                "If uncertain, return decision=escalate.",
            ],
        },
        "claim_stable_promotion": {
            "response_shape": {
                "decision": "promote|skip",
                "confidence": 0.0,
                "reason": "string",
            },
            "instructions": [
                "Return JSON only.",
                "Only return decision=promote when the claim is clearly safe to promote.",
            ],
        },
        "review_concept_candidate": {
            "response_shape": {
                "decision": "accept|reject|rename",
                "suggested_title": "string when decision=rename",
                "reason": "string",
                "confidence": 0.0,
            },
            "instructions": [
                "Return JSON only.",
                "Judge whether the title is a reusable concept title rather than a structural heading.",
            ],
        },
        "render_readable_concept_page": {
            "response_shape": {
                "summary": "string",
                "key_points": [{"claim_id": "string", "text": "string"}],
                "practical_notes": [{"claim_id": "string", "text": "string"}],
            },
            "instructions": [
                "Return JSON only.",
                "Only rewrite for readability. Do not add new facts.",
                "Every bullet must remain grounded in the referenced claim_id.",
            ],
        },
        "render_workspace_overview_page": {
            "response_shape": {
                "summary": "string",
                "theme_rows": [{"page_id": "string", "text": "string"}],
                "reading_path": [{"page_id": "string", "text": "string"}],
            },
            "instructions": [
                "Return JSON only.",
                "Only rewrite for readability. Do not add new facts.",
                "Every row must remain grounded in the referenced page_id.",
            ],
        },
    }
    if task not in task_shapes:
        raise OnlineHookConfigError(f"Unsupported online hook task `{task}`.")
    task_spec = task_shapes[task]
    return (
        task,
        {
            "task": task,
            "instructions": task_spec["instructions"],
            "response_shape": task_spec["response_shape"],
            "payload": payload,
        },
    )


def build_openai_request(config: dict, prompt_payload: dict) -> tuple[str, dict, bytes]:
    url = config["base_url"]
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    body = {
        "model": config["model"],
        "messages": [
            {
                "role": "system",
                "content": "You are MyAgentWiki's online hook. Return only valid JSON matching the requested shape.",
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    return url, headers, json.dumps(body, ensure_ascii=False).encode("utf-8")


def build_anthropic_request(config: dict, prompt_payload: dict) -> tuple[str, dict, bytes]:
    url = config["base_url"]
    if not url.endswith("/messages"):
        url = f"{url}/messages"
    body = {
        "model": config["model"],
        "max_tokens": 4096,
        "temperature": 0,
        "system": "You are MyAgentWiki's online hook. Return only valid JSON matching the requested shape.",
        "messages": [
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False),
            }
        ],
    }
    headers = {
        "x-api-key": config["api_key"],
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    return url, headers, json.dumps(body, ensure_ascii=False).encode("utf-8")


def extract_openai_response_text(payload: dict) -> str:
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        raise OnlineHookConfigError("OpenAI-compatible response missing `choices`.")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        return "\n".join(texts)
    return ""


def extract_anthropic_response_text(payload: dict) -> str:
    content = payload.get("content", [])
    if not isinstance(content, list):
        raise OnlineHookConfigError("Anthropic-compatible response missing `content`.")
    texts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text", "")
        if isinstance(text, str) and text.strip():
            texts.append(text)
    return "\n".join(texts)


def request_online_model(config: dict, prompt_payload: dict) -> dict:
    if config["protocol"] == OPENAI_COMPATIBLE:
        url, headers, body = build_openai_request(config, prompt_payload)
        extractor = extract_openai_response_text
    else:
        url, headers, body = build_anthropic_request(config, prompt_payload)
        extractor = extract_anthropic_response_text

    request = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=config["timeout_seconds"]) as response:
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        status = exc.code
        if status in {401, 403}:
            raise OnlineHookConfigError(
                f"Online model request was rejected with HTTP {status}. Verify `provider.base_url`, `provider.model`, and `provider.api_key` in `{ONLINE_HOOK_CONFIG_REL_PATH.as_posix()}`."
            ) from exc
        raise OnlineHookConfigError(
            f"Online model request failed with HTTP {status}. Response: {detail or 'empty body'}"
        ) from exc
    except urllib.error.URLError as exc:
        raise OnlineHookConfigError(
            f"Online model request failed: {exc.reason}."
        ) from exc

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise OnlineHookConfigError("Online model response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise OnlineHookConfigError("Online model response root must be a JSON object.")
    content = extractor(parsed).strip()
    parsed_output = parse_json_object_from_text(content)
    if parsed_output is None:
        raise OnlineHookConfigError("Online model response did not contain a valid JSON object.")
    return parsed_output


def normalize_semantic_result(task_name: str, result: dict) -> dict:
    decisions = result.get("decisions", [])
    if not isinstance(decisions, list):
        raise OnlineHookConfigError("Semantic batch response must contain `decisions` as a list.")
    normalized: list[dict] = []
    for item in decisions:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", "")).strip()
        if not item_id:
            raise OnlineHookConfigError("Semantic batch decision is missing `item_id`.")
        decision_status = str(item.get("decision_status", SEMANTIC_DECISION_STATUS_ACCEPTED)).strip().lower()
        decision = item.get("decision", {})
        if decision_status == SEMANTIC_DECISION_STATUS_ABSTAINED:
            decision = "abstain"
        elif not isinstance(decision, dict):
            raise OnlineHookConfigError(f"Semantic decision for `{item_id}` must contain an object `decision`.")
        if isinstance(decision, dict):
            missing_fields = semantic_decision_missing_fields(task_name, decision)
            if decision_status == SEMANTIC_DECISION_STATUS_ACCEPTED and missing_fields:
                raise OnlineHookConfigError(
                    f"Semantic decision for `{item_id}` is missing required fields: {', '.join(missing_fields)}."
                )
        normalized.append({
            "item_id": item_id,
            "decision": decision,
            "decision_status": decision_status,
            "confidence": float(item.get("confidence", 0.0) or 0.0),
            "reason_code": str(item.get("reason_code", "")).strip() or "online_hook_result",
            "risk_flags": item.get("risk_flags", []),
            "supporting_ids": item.get("supporting_ids", []),
            "abstain_reason": str(item.get("abstain_reason", "")).strip(),
        })
    return {"decisions": normalized}


def validate_shape(value: Any, required_fields: tuple[str, ...], shape_name: str) -> dict:
    if not isinstance(value, dict):
        raise OnlineHookConfigError(f"{shape_name} response must be a JSON object.")
    missing = [field for field in required_fields if field not in value]
    if missing:
        raise OnlineHookConfigError(f"{shape_name} response is missing required field(s): {', '.join(missing)}.")
    return value


def normalize_result(task_key: str, payload: dict, raw_result: dict) -> dict:
    if task_key == "semantic_batch":
        return normalize_semantic_result(str(payload.get("task_name", "")).strip(), raw_result)
    if task_key == "review_auto_decision":
        return validate_shape(raw_result, ("decision", "reason"), "review_auto_decision")
    if task_key == "claim_stable_promotion":
        return validate_shape(raw_result, ("decision", "reason"), "claim_stable_promotion")
    if task_key == "review_concept_candidate":
        return validate_shape(raw_result, ("decision", "reason"), "review_concept_candidate")
    if task_key == "render_readable_concept_page":
        return validate_shape(raw_result, ("summary", "key_points", "practical_notes"), "render_readable_concept_page")
    if task_key == "render_workspace_overview_page":
        return validate_shape(raw_result, ("summary", "theme_rows", "reading_path"), "render_workspace_overview_page")
    raise OnlineHookConfigError(f"Unsupported task key `{task_key}`.")


def run_online_hook(payload: dict, cwd: Path | None = None) -> dict:
    config = load_online_hook_config(cwd=cwd)
    task_key, prompt_payload = response_format_for_payload(payload)
    raw_result = request_online_model(config, prompt_payload)
    return normalize_result(task_key, payload, raw_result)


def emit_error_and_exit(message: str) -> int:
    json.dump(online_hook_error_payload(message), sys.stdout, ensure_ascii=False)
    return 1


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    try:
        result = run_online_hook(payload if isinstance(payload, dict) else {})
    except OnlineHookConfigError as exc:
        return emit_error_and_exit(str(exc))
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
