from __future__ import annotations

import json
from pathlib import Path

import pytest

from myagentwiki.llm.errors import LLMClientError, LLMRouteError
from myagentwiki.llm.repair import RawFunctionCall
from myagentwiki.llm.router import LLMRouter, LLMSettings


VALID_CALL = RawFunctionCall(
    "submit_claim_promotion_decision",
    '{"decision":"skip","confidence":0.8,"reason":"ok"}',
)


def settings() -> LLMSettings:
    return LLMSettings(
        primary_max_retries=2,
        retry_backoff_seconds=(1.0, 2.0),
        retry_jitter_max_seconds=0.25,
        document_max_chars=24000,
        image_max_bytes=1024,
        image_mime_types=frozenset({"image/png"}),
        cli_timeout_seconds=30,
        cli_model="",
    )


class FakeOnline:
    results = []
    calls = 0
    instances = 0
    closed = 0

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        type(self).instances += 1

    def __enter__(self):
        return self

    def __exit__(self, *args):  # noqa: ANN002
        type(self).closed += 1
        return None

    def request(self, **kwargs):  # noqa: ANN003
        type(self).calls += 1
        result = type(self).results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeCLI:
    result = VALID_CALL
    calls = 0

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        pass

    def request(self, **kwargs):  # noqa: ANN003
        type(self).calls += 1
        if isinstance(type(self).result, Exception):
            raise type(self).result
        return type(self).result


def configure_fakes(online_results, cli_result=VALID_CALL) -> None:  # noqa: ANN001
    FakeOnline.results = list(online_results)
    FakeOnline.calls = 0
    FakeOnline.instances = 0
    FakeOnline.closed = 0
    FakeCLI.result = cli_result
    FakeCLI.calls = 0


def fake_router(workspace: Path, **kwargs) -> LLMRouter:  # noqa: ANN003
    return LLMRouter(
        workspace,
        online_client_factory=FakeOnline,
        cli_client_factory=FakeCLI,
        **kwargs,
    )


def request(router: LLMRouter) -> dict:
    return router.request(
        task_name="claim_stable_promotion",
        payload={"task": "claim_stable_promotion", "claim": {"claim_id": "c1"}},
    )


def test_online_retries_twice_then_succeeds_without_cli(tmp_path: Path) -> None:
    retryable = LLMClientError("retry", backend="online", kind="http_error", retryable=True, http_status=500)
    configure_fakes([retryable, retryable, VALID_CALL])
    sleeps = []
    router = fake_router(tmp_path, settings=settings(), sleep=sleeps.append, random_uniform=lambda a, b: 0.0)
    assert request(router)["decision"] == "skip"
    assert FakeOnline.calls == 3
    assert FakeCLI.calls == 0
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize("http_status", [403, 404])
def test_non_retryable_http_error_uses_cli_once(tmp_path: Path, http_status: int) -> None:
    forbidden = LLMClientError(
        "not retryable",
        backend="online",
        kind="http_error",
        retryable=False,
        http_status=http_status,
    )
    configure_fakes([forbidden])
    assert request(fake_router(tmp_path, settings=settings(), sleep=lambda _: None))["decision"] == "skip"
    assert FakeOnline.calls == 1
    assert FakeCLI.calls == 1


@pytest.mark.parametrize("http_status", [429, 503])
def test_retryable_http_error_exhausts_online_before_cli(tmp_path: Path, http_status: int) -> None:
    retryable = LLMClientError(
        "retry",
        backend="online",
        kind="http_error",
        retryable=True,
        http_status=http_status,
    )
    configure_fakes([retryable, retryable, retryable])
    sleeps: list[float] = []
    assert request(fake_router(
        tmp_path,
        settings=settings(),
        sleep=sleeps.append,
        random_uniform=lambda a, b: 0.0,
    ))["decision"] == "skip"
    assert FakeOnline.calls == 3
    assert FakeCLI.calls == 1
    assert sleeps == [1.0, 2.0]


def test_invalid_online_function_call_retries_current_request(tmp_path: Path) -> None:
    configure_fakes([
        RawFunctionCall("wrong_function", "{}"),
        VALID_CALL,
    ])
    sleeps: list[float] = []
    assert request(fake_router(
        tmp_path,
        settings=settings(),
        sleep=sleeps.append,
        random_uniform=lambda a, b: 0.0,
    ))["decision"] == "skip"
    assert FakeOnline.calls == 2
    assert FakeCLI.calls == 0
    assert sleeps == [1.0]


def test_separate_logical_requests_create_and_close_separate_clients_without_delay(tmp_path: Path) -> None:
    configure_fakes([VALID_CALL, VALID_CALL])
    sleeps: list[float] = []
    router = fake_router(tmp_path, settings=settings(), sleep=sleeps.append)

    assert request(router)["decision"] == "skip"
    assert request(router)["decision"] == "skip"

    assert FakeOnline.instances == 2
    assert FakeOnline.closed == 2
    assert FakeOnline.calls == 2
    assert FakeCLI.calls == 0
    assert sleeps == []


def test_both_routes_failed_raises_and_writes_sanitized_log(tmp_path: Path) -> None:
    online_error = LLMClientError("down", backend="online", kind="connection_error", retryable=True)
    cli_error = LLMClientError("cli down", backend="cli", kind="process_error", retryable=False)
    configure_fakes([online_error, online_error, online_error], cli_error)
    with pytest.raises(LLMRouteError) as exc:
        request(fake_router(tmp_path, settings=settings(), sleep=lambda _: None, random_uniform=lambda a, b: 0.0))
    assert exc.value.payload["error"] == "llm_request_failed"
    assert FakeOnline.calls == 3
    assert FakeCLI.calls == 1
    log_records = [json.loads(line) for line in (tmp_path / "logs" / "llm_requests.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log_records[-1]["status"] == "failed"
    assert "run_id" not in log_records[-1]
    assert "api_key" not in json.dumps(log_records[-1])
