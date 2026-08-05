from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from myagentwiki.llm.errors import LLMConfigurationError
from myagentwiki.llm.contracts import get_function_spec, registered_task_names
from myagentwiki.llm.online_client import (
    CHAT_COMPLETIONS_API_STYLE,
    ONLINE_ENVIRONMENT_KEYS,
    RESPONSES_API_STYLE,
    OnlineLLMClient,
    _status_is_retryable,
    load_online_config,
)
from myagentwiki.runtime_env import SKILL_ROOT_ENVIRONMENT_VARIABLE


def client_with_fake_api(api_style: str, api) -> OnlineLLMClient:  # noqa: ANN001
    client = object.__new__(OnlineLLMClient)
    client.workspace = None
    client.config = {"model": "test-model", "api_style": api_style}
    client.image_max_bytes = 1024
    client.image_mime_types = {"image/png"}
    client._client = api
    return client


def test_online_config_reads_local_env_and_allows_process_overrides(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    for name in ONLINE_ENVIRONMENT_KEYS.values():
        monkeypatch.delenv(name, raising=False)
    skill_root = tmp_path / "skill-root"
    skill_root.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (skill_root / ".env").write_text(
        'MYAGENTWIKI_LLM_BASE_URL="https://example.com/v1"\n'
        'MYAGENTWIKI_LLM_MODEL="env-model"\n'
        'MYAGENTWIKI_LLM_API_KEY="env-key"\n'
        'MYAGENTWIKI_LLM_API_STYLE="chat_completions"\n',
        encoding="utf-8",
    )
    (workspace / ".env").write_text(
        'MYAGENTWIKI_LLM_BASE_URL="https://workspace.example/v1"\n'
        'MYAGENTWIKI_LLM_MODEL="workspace-model"\n'
        'MYAGENTWIKI_LLM_API_KEY="workspace-key"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SKILL_ROOT_ENVIRONMENT_VARIABLE, str(skill_root))
    monkeypatch.setenv("MYAGENTWIKI_LLM_MODEL", "process-model")

    config = load_online_config(workspace)

    assert config["protocol"] == "openai_compatible"
    assert config["base_url"] == "https://example.com/v1"
    assert config["model"] == "process-model"
    assert config["api_style"] == CHAT_COMPLETIONS_API_STYLE
    assert config["api_key"] == "env-key"


def test_online_config_missing_env_explains_required_settings(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    for name in ONLINE_ENVIRONMENT_KEYS.values():
        monkeypatch.delenv(name, raising=False)
    skill_root = tmp_path / "skill-root"
    skill_root.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (skill_root / ".env.example").write_text("# template\n", encoding="utf-8")
    (workspace / ".env").write_text(
        'MYAGENTWIKI_LLM_BASE_URL="https://workspace.example/v1"\n'
        'MYAGENTWIKI_LLM_MODEL="workspace-model"\n'
        'MYAGENTWIKI_LLM_API_KEY="workspace-key"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SKILL_ROOT_ENVIRONMENT_VARIABLE, str(skill_root))

    with pytest.raises(LLMConfigurationError) as exc:
        load_online_config(workspace)

    guidance = exc.value.as_record()["guidance"]
    assert guidance["status"] == "missing_env_file"
    assert guidance["scope"] == "skill_root"
    assert guidance["skill_root"] == str(skill_root)
    assert guidance["env_file"] == str(skill_root / ".env")
    assert guidance["example_file"] == str(skill_root / ".env.example")
    assert guidance["required_variables"] == [
        ONLINE_ENVIRONMENT_KEYS["base_url"],
        ONLINE_ENVIRONMENT_KEYS["model"],
        ONLINE_ENVIRONMENT_KEYS["api_key"],
    ]
    assert guidance["missing_variables"] == guidance["required_variables"]
    assert "Skill 根目录" in exc.value.message
    assert "`.env.example`" in exc.value.message


def test_responses_uses_forced_non_streaming_function_call() -> None:
    recorded = {}

    class Responses:
        def create(self, **kwargs):  # noqa: ANN003
            recorded.update(kwargs)
            return SimpleNamespace(output=[SimpleNamespace(
                type="function_call",
                name="submit_claim_promotion_decision",
                arguments='{"decision":"skip","confidence":0.8,"reason":"ok"}',
            )])

    raw = client_with_fake_api(
        RESPONSES_API_STYLE,
        SimpleNamespace(responses=Responses()),
    ).request(
        spec=get_function_spec("claim_stable_promotion"),
        context={"claim": {"claim_id": "c1"}},
        image_paths=[],
    )
    assert raw.function_name == "submit_claim_promotion_decision"
    assert recorded["stream"] is False
    assert recorded["parallel_tool_calls"] is False
    assert recorded["tool_choice"]["name"] == raw.function_name
    assert recorded["tools"][0]["strict"] is True
    assert "text" not in recorded


def test_chat_completions_uses_forced_non_streaming_function_call() -> None:
    recorded = {}

    class Completions:
        def create(self, **kwargs):  # noqa: ANN003
            recorded.update(kwargs)
            function = SimpleNamespace(
                name="submit_claim_promotion_decision",
                arguments='{"decision":"skip","confidence":0.8,"reason":"ok"}',
            )
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)])
            )])

    raw = client_with_fake_api(
        CHAT_COMPLETIONS_API_STYLE,
        SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
    ).request(
        spec=get_function_spec("claim_stable_promotion"),
        context={"claim": {"claim_id": "c1"}},
        image_paths=[],
    )
    assert recorded["stream"] is False
    assert recorded["parallel_tool_calls"] is False
    assert recorded["tool_choice"]["function"]["name"] == raw.function_name
    assert "response_format" not in recorded


def test_http_retry_classification() -> None:
    assert _status_is_retryable(408)
    assert _status_is_retryable(409)
    assert _status_is_retryable(429)
    assert _status_is_retryable(500)
    assert not _status_is_retryable(403)
    assert not _status_is_retryable(404)


def test_online_image_request_uses_detected_mime_data_url(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (2, 2), color="white").save(image_path, format="PNG")
    recorded = {}

    class Responses:
        def create(self, **kwargs):  # noqa: ANN003
            recorded.update(kwargs)
            return SimpleNamespace(output=[SimpleNamespace(
                type="function_call",
                name="submit_image_description",
                arguments='{"extracted_text":"","summary":"visible","confidence":0.9,"reason":"ok","warnings":[]}',
            )])

    client = client_with_fake_api(
        RESPONSES_API_STYLE,
        SimpleNamespace(responses=Responses()),
    )
    client.image_max_bytes = 20 * 1024 * 1024
    client.request(
        spec=get_function_spec("describe_image"),
        context={"image_name": "sample.png"},
        image_paths=[image_path],
    )

    image_item = recorded["input"][0]["content"][1]
    assert image_item["type"] == "input_image"
    assert image_item["image_url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("task_name", registered_task_names())
def test_every_contract_can_be_registered_on_responses_api(task_name: str) -> None:
    recorded = {}

    class Responses:
        def create(self, **kwargs):  # noqa: ANN003
            recorded.update(kwargs)
            function_name = kwargs["tools"][0]["name"]
            return SimpleNamespace(output=[SimpleNamespace(
                type="function_call",
                name=function_name,
                arguments="{}",
            )])

    spec = get_function_spec(task_name)
    raw = client_with_fake_api(
        RESPONSES_API_STYLE,
        SimpleNamespace(responses=Responses()),
    ).request(spec=spec, context={}, image_paths=[])

    assert raw.function_name == spec.function_name
    assert recorded["tool_choice"]["name"] == spec.function_name
    assert recorded["stream"] is False
