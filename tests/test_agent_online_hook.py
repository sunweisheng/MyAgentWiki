from __future__ import annotations

import importlib
import importlib.util
import json
import sys
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
RESPONSES_API_STYLE = MODULE.RESPONSES_API_STYLE
CHAT_COMPLETIONS_API_STYLE = MODULE.CHAT_COMPLETIONS_API_STYLE
client_cache_key = MODULE.client_cache_key
get_openai_client = MODULE.get_openai_client
load_online_hook_config = MODULE.load_online_hook_config
normalize_result = MODULE.normalize_result
request_online_model = MODULE.request_online_model
response_format_for_payload = MODULE.response_format_for_payload
run_online_hook = MODULE.run_online_hook


def write_local_config(workspace_dir: Path, text: str) -> None:
    config_dir = workspace_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "llm.local.yml").write_text(text, encoding="utf-8")


def sample_config(api_style: str = RESPONSES_API_STYLE, verify_ssl: bool = True) -> dict:
    return {
        "protocol": "openai_compatible",
        "base_url": "https://example.com/v1",
        "model": "gpt-test",
        "api_key": "sk-test",
        "timeout_seconds": 60,
        "api_style": api_style,
        "verify_ssl": verify_ssl,
    }


class FakeResponseEvent:
    def __init__(self, event_type: str, delta: str = "") -> None:
        self.type = event_type
        self.delta = delta


class FakeChoiceDelta:
    def __init__(self, content) -> None:  # noqa: ANN001
        self.content = content


class FakeChoice:
    def __init__(self, delta) -> None:  # noqa: ANN001
        self.delta = delta


class FakeChatChunk:
    def __init__(self, content) -> None:  # noqa: ANN001
        self.choices = [FakeChoice(FakeChoiceDelta(content))]


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


def test_load_online_hook_config_defaults_to_responses_and_verify_ssl(tmp_path: Path) -> None:
    write_local_config(
        tmp_path,
        'provider:\n'
        '  protocol: "openai_compatible"\n'
        '  base_url: "https://example.com/v1"\n'
        '  model: "gpt-test"\n'
        '  api_key: "sk-test"\n',
    )
    config = load_online_hook_config(tmp_path)
    assert config["api_style"] == RESPONSES_API_STYLE
    assert config["verify_ssl"] is True


def test_load_online_hook_config_rejects_invalid_api_style(tmp_path: Path) -> None:
    write_local_config(
        tmp_path,
        'provider:\n'
        '  protocol: "openai_compatible"\n'
        '  base_url: "https://example.com/v1"\n'
        '  model: "gpt-test"\n'
        '  api_key: "sk-test"\n'
        'transport:\n'
        '  api_style: "invalid"\n',
    )
    with pytest.raises(OnlineHookConfigError) as exc:
        load_online_hook_config(tmp_path)
    assert "transport.api_style" in str(exc.value)


def test_client_cache_key_changes_with_effective_transport() -> None:
    first = client_cache_key(sample_config())
    second = client_cache_key(sample_config(api_style=CHAT_COMPLETIONS_API_STYLE))
    third = client_cache_key(sample_config(verify_ssl=False))
    assert first != second
    assert first != third


def test_get_openai_client_reuses_singleton_for_same_config() -> None:
    first = get_openai_client(sample_config())
    second = get_openai_client(sample_config())
    assert first is second


def test_get_openai_client_rebuilds_singleton_when_config_changes() -> None:
    first = get_openai_client(sample_config())
    second = get_openai_client(sample_config(api_style=CHAT_COMPLETIONS_API_STYLE))
    assert first is not second


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


def test_request_online_model_uses_responses_stream(monkeypatch) -> None:
    recorded = {}

    class FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003
            recorded.update(kwargs)
            return [
                FakeResponseEvent("response.output_text.delta", '{"summary":"'),
                FakeResponseEvent("response.output_text.delta", 'ok"}'),
            ]

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("myagentwiki.agent_online_hook.get_openai_client", lambda config: FakeClient())
    result = request_online_model(
        sample_config(api_style=RESPONSES_API_STYLE),
        "render_workspace_overview_page",
        {
            "task": "render_workspace_overview_page",
            "instructions": ["Return JSON only."],
            "response_shape": {"summary": "string"},
            "payload": {},
        },
    )
    assert recorded["stream"] is True
    assert recorded["model"] == "gpt-test"
    assert recorded["text"]["format"]["type"] == "json_schema"
    assert result["summary"] == "ok"


def test_request_online_model_uses_chat_completions_stream(monkeypatch) -> None:
    recorded = {}

    class FakeChatCompletions:
        def create(self, **kwargs):  # noqa: ANN003
            recorded.update(kwargs)
            return [
                FakeChatChunk('{"decision":"'),
                FakeChatChunk('skip","reason":"ok"}'),
            ]

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeChatCompletions()

    class FakeClient:
        def __init__(self) -> None:
            self.chat = FakeChat()

    monkeypatch.setattr("myagentwiki.agent_online_hook.get_openai_client", lambda config: FakeClient())
    result = request_online_model(
        sample_config(api_style=CHAT_COMPLETIONS_API_STYLE),
        "claim_stable_promotion",
        {
            "task": "claim_stable_promotion",
            "instructions": ["Return JSON only."],
            "response_shape": {"decision": "string", "reason": "string"},
            "payload": {},
        },
    )
    assert recorded["stream"] is True
    assert recorded["model"] == "gpt-test"
    assert recorded["response_format"]["type"] == "json_schema"
    assert recorded["response_format"]["json_schema"]["schema"]["type"] == "object"
    assert result["decision"] == "skip"


def test_request_online_model_sleeps_after_first_network_request(monkeypatch) -> None:
    sleep_calls = []

    class FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003
            return [FakeResponseEvent("response.output_text.delta", '{"summary":"ok"}')]

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("myagentwiki.agent_online_hook.get_openai_client", lambda config: FakeClient())
    monkeypatch.setattr("myagentwiki.agent_online_hook.time.sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("myagentwiki.agent_online_hook.random.uniform", lambda start, end: 1.5)
    monkeypatch.setattr("myagentwiki.agent_online_hook._NETWORK_REQUEST_COUNT", 0)

    payload = {
        "task": "render_workspace_overview_page",
        "instructions": ["Return JSON only."],
        "response_shape": {"summary": "string"},
        "payload": {},
    }
    request_online_model(sample_config(), "render_workspace_overview_page", payload)
    request_online_model(sample_config(), "render_workspace_overview_page", payload)
    assert sleep_calls == [1.5]


def test_request_online_model_rejects_missing_json_object(monkeypatch) -> None:
    class FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003
            return [FakeResponseEvent("response.output_text.delta", "not json")]

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("myagentwiki.agent_online_hook.get_openai_client", lambda config: FakeClient())
    with pytest.raises(OnlineHookConfigError) as exc:
        request_online_model(
            sample_config(),
            "render_workspace_overview_page",
            {
                "task": "render_workspace_overview_page",
                "instructions": ["Return JSON only."],
                "response_shape": {"summary": "string"},
                "payload": {},
            },
        )
    assert "valid JSON object" in str(exc.value)


def test_run_online_hook_supports_render_and_review_shapes(tmp_path: Path, monkeypatch) -> None:
    write_local_config(
        tmp_path,
        'provider:\n'
        '  protocol: "openai_compatible"\n'
        '  base_url: "https://example.com/v1"\n'
        '  model: "gpt-test"\n'
        '  api_key: "sk-test"\n'
        '  timeout_seconds: 60\n'
        'transport:\n'
        '  api_style: "responses"\n'
        '  verify_ssl: true\n',
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

    monkeypatch.setattr("myagentwiki.agent_online_hook.request_online_model", lambda config, task_key, prompt_payload: next(responses))

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
        '  protocol: "openai_compatible"\n'
        '  base_url: "https://example.com/v1"\n'
        '  model: "gpt-test"\n'
        '  api_key: "sk-test"\n'
        '  timeout_seconds: 60\n'
        'transport:\n'
        '  api_style: "chat_completions"\n'
        '  verify_ssl: false\n',
    )
    monkeypatch.setattr(
        "myagentwiki.agent_online_hook.request_online_model",
        lambda config, task_key, prompt_payload: {
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
