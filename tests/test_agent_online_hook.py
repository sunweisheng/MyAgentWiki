from __future__ import annotations

import json
import importlib
import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
PACKAGE_SPEC = importlib.util.spec_from_file_location(
    "myagentwiki",
    REPO_ROOT / "src" / "myagentwiki" / "__init__.py",
    submodule_search_locations=[str(REPO_ROOT / "src" / "myagentwiki")],
)
assert PACKAGE_SPEC is not None and PACKAGE_SPEC.loader is not None
PACKAGE_MODULE = importlib.util.module_from_spec(PACKAGE_SPEC)
sys.modules["myagentwiki"] = PACKAGE_MODULE
PACKAGE_SPEC.loader.exec_module(PACKAGE_MODULE)
MODULE = importlib.import_module("myagentwiki.agent_online_hook")

OnlineHookConfigError = MODULE.OnlineHookConfigError
build_anthropic_request = MODULE.build_anthropic_request
build_openai_request = MODULE.build_openai_request
load_online_hook_config = MODULE.load_online_hook_config
normalize_result = MODULE.normalize_result
request_online_model = MODULE.request_online_model
response_format_for_payload = MODULE.response_format_for_payload
run_online_hook = MODULE.run_online_hook


def write_local_config(workspace_dir: Path, text: str) -> None:
    config_dir = workspace_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "llm.local.yml").write_text(text, encoding="utf-8")


def test_load_online_hook_config_requires_local_file(tmp_path: Path) -> None:
    with pytest.raises(OnlineHookConfigError) as exc:
        load_online_hook_config(tmp_path)
    assert "config/llm.local.yml" in str(exc.value)


def test_load_online_hook_config_requires_fields(tmp_path: Path) -> None:
    write_local_config(
        tmp_path,
        'provider:\n  protocol: "openai_compatible"\n  base_url: ""\n  model: ""\n  api_key: ""\n',
    )
    with pytest.raises(OnlineHookConfigError) as exc:
        load_online_hook_config(tmp_path)
    assert "provider.base_url" in str(exc.value)


def test_build_openai_request_uses_chat_completions_and_bearer_auth() -> None:
    url, headers, body = build_openai_request(
        {
            "protocol": "openai_compatible",
            "base_url": "https://example.com/v1",
            "model": "gpt-test",
            "api_key": "sk-test",
            "timeout_seconds": 60,
        },
        {"task": "render_readable_concept_page"},
    )
    assert url == "https://example.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test"
    payload = json.loads(body)
    assert payload["model"] == "gpt-test"
    assert payload["response_format"] == {"type": "json_object"}


def test_build_anthropic_request_uses_messages_api_and_api_key_header() -> None:
    url, headers, body = build_anthropic_request(
        {
            "protocol": "anthropic_compatible",
            "base_url": "https://anthropic.example.com",
            "model": "claude-test",
            "api_key": "key-test",
            "timeout_seconds": 60,
        },
        {"task": "render_workspace_overview_page"},
    )
    assert url == "https://anthropic.example.com/messages"
    assert headers["x-api-key"] == "key-test"
    payload = json.loads(body)
    assert payload["model"] == "claude-test"
    assert payload["messages"][0]["role"] == "user"


def test_request_online_model_rejects_401(monkeypatch) -> None:
    class UnauthorizedResponse:
        def read(self) -> bytes:
            return b'{"error":"unauthorized"}'

        def close(self) -> None:
            return None

    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=UnauthorizedResponse(),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(OnlineHookConfigError) as exc:
        request_online_model(
            {
                "protocol": "openai_compatible",
                "base_url": "https://example.com/v1",
                "model": "gpt-test",
                "api_key": "sk-test",
                "timeout_seconds": 10,
            },
            {"task": "render_readable_concept_page"},
        )
    assert "HTTP 401" in str(exc.value)
    assert "config/llm.local.yml" in str(exc.value)


def test_request_online_model_rejects_non_json_response(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        def read(self) -> bytes:
            return b"not json"

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    with pytest.raises(OnlineHookConfigError) as exc:
        request_online_model(
            {
                "protocol": "openai_compatible",
                "base_url": "https://example.com/v1",
                "model": "gpt-test",
                "api_key": "sk-test",
                "timeout_seconds": 10,
            },
            {"task": "render_readable_concept_page"},
        )
    assert "not valid JSON" in str(exc.value)


def test_response_format_for_payload_supports_semantic_batch_contract() -> None:
    task_key, prompt_payload = response_format_for_payload(
        {
            "task": "review_claim_role_batch",
            "task_name": "claim_role",
            "items": [{"item_id": "claim-1"}],
        }
    )
    assert task_key == "semantic_batch"
    assert prompt_payload["task_name"] == "claim_role"


def test_normalize_result_validates_semantic_required_fields() -> None:
    with pytest.raises(OnlineHookConfigError) as exc:
        normalize_result(
            "semantic_batch",
            {"task_name": "claim_role"},
            {
                "decisions": [
                    {
                        "item_id": "claim-1",
                        "decision": {"knowledge_role": "fact"},
                        "decision_status": "accepted",
                        "confidence": 0.9,
                        "reason_code": "missing_fields",
                    }
                ]
            },
        )
    assert "missing required fields" in str(exc.value)


def test_run_online_hook_supports_render_and_review_shapes(tmp_path: Path, monkeypatch) -> None:
    write_local_config(
        tmp_path,
        'provider:\n'
        '  protocol: "openai_compatible"\n'
        '  base_url: "https://example.com/v1"\n'
        '  model: "gpt-test"\n'
        '  api_key: "sk-test"\n'
        '  timeout_seconds: 60\n',
    )

    responses = iter([
        {"decision": "auto_apply", "action": "keep_both", "confidence": 0.9, "reason": "ok"},
        {"decision": "promote", "confidence": 0.91, "reason": "ok"},
        {"decision": "rename", "suggested_title": "更清楚的标题", "reason": "ok", "confidence": 0.8},
        {
            "summary": "概念摘要",
            "key_points": [{"claim_id": "c1", "text": "要点"}],
            "practical_notes": [{"claim_id": "c1", "text": "实践提示"}],
        },
        {
            "summary": "综述摘要",
            "theme_rows": [{"page_id": "p1", "text": "主题"}],
            "reading_path": [{"page_id": "p1", "text": "阅读路径"}],
        },
    ])

    monkeypatch.setattr("myagentwiki.agent_online_hook.request_online_model", lambda config, prompt_payload: next(responses))

    review_result = run_online_hook({"task": "review_auto_decision", "review": {"allowed_actions": ["keep_both"]}}, cwd=tmp_path)
    assert review_result["decision"] == "auto_apply"

    promote_result = run_online_hook({"task": "claim_stable_promotion", "claim": {"claim_id": "c1"}}, cwd=tmp_path)
    assert promote_result["decision"] == "promote"

    concept_title_result = run_online_hook({"task": "review_concept_candidate", "candidate_title": "示例"}, cwd=tmp_path)
    assert concept_title_result["decision"] == "rename"

    concept_render_result = run_online_hook({"task": "render_readable_concept_page"}, cwd=tmp_path)
    assert concept_render_result["summary"] == "概念摘要"

    overview_render_result = run_online_hook({"task": "render_workspace_overview_page"}, cwd=tmp_path)
    assert overview_render_result["summary"] == "综述摘要"


def test_run_online_hook_supports_semantic_batch(tmp_path: Path, monkeypatch) -> None:
    write_local_config(
        tmp_path,
        'provider:\n'
        '  protocol: "anthropic_compatible"\n'
        '  base_url: "https://example.com"\n'
        '  model: "claude-test"\n'
        '  api_key: "key-test"\n'
        '  timeout_seconds: 60\n',
    )
    monkeypatch.setattr(
        "myagentwiki.agent_online_hook.request_online_model",
        lambda config, prompt_payload: {
            "decisions": [
                {
                    "item_id": "claim-1",
                    "decision": {
                        "knowledge_role": "fact",
                        "page_intent_hints": ["topic"],
                        "concept_candidate_score": 0.41,
                    },
                    "decision_status": "accepted",
                    "confidence": 0.89,
                    "reason_code": "online_ok",
                }
            ]
        },
    )
    result = run_online_hook(
        {
            "task": "review_claim_role_batch",
            "task_name": "claim_role",
            "items": [{"item_id": "claim-1"}],
        },
        cwd=tmp_path,
    )
    assert result["decisions"][0]["item_id"] == "claim-1"
