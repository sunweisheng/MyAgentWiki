from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from myagentwiki.cli import build_parser
from myagentwiki.debug_trace import (
    DebugTraceError,
    DebugTracer,
    entity_reference,
    list_debug_runs,
    load_debug_run,
    prune_expired_debug_runs,
    trace_lineage,
    trace_step,
)
from myagentwiki.llm.cli_client import CLILLMClient
from myagentwiki.llm.contracts import get_function_spec
from myagentwiki.llm.errors import LLMClientError, LLMRouteError
from myagentwiki.llm.repair import RawFunctionCall
from myagentwiki.llm.router import LLMRouter, LLMSettings
from myagentwiki.runtime_env import SKILL_ROOT_ENVIRONMENT_VARIABLE


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, llm_mode: str = "deterministic") -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "myagentwiki.cli", *args, "--json"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "MYAGENTWIKI_LLM_MODE": llm_mode,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_debug_config(workspace: Path, *, logs_path: str = "logs", retention_days: int = 7) -> None:
    config_dir = workspace / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yml").write_text(
        f'paths:\n  logs: "{logs_path}"\ndebug:\n  retention_days: {retention_days}\n',
        encoding="utf-8",
    )


def test_debug_tracer_records_nested_steps_full_snapshots_and_redacts_secrets(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_debug_config(workspace)
    secret = "secret-value-12345"
    access_token = "access-token-67890"
    skill_root = tmp_path / "skill-root"
    skill_root.mkdir()
    (skill_root / ".env").write_text(
        f'MYAGENTWIKI_LLM_API_KEY="{secret}"\nGITHUB_TOKEN="{access_token}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SKILL_ROOT_ENVIRONMENT_VARIABLE, str(skill_root))

    tracer = DebugTracer(workspace, "query", {"text": "测试", "api_key": secret}).start()
    try:
        with trace_step("command.query", kind="command", input_data={"token": access_token}) as parent:
            trace_lineage(
                operation="generated",
                reason="test_source_flow",
                inputs=[entity_reference(
                    "source",
                    "source-1",
                    value={"source_id": "source-1", "text": "完整输入", "api_key": secret},
                    source_id="source-1",
                )],
                outputs=[entity_reference(
                    "claim",
                    "claim-1",
                    value={"source_ids": ["source-1"], "text": "完整输出"},
                )],
                snapshot_name="source_1_flow",
            )
            trace_lineage(
                operation="generated",
                reason="similar_source_id_must_not_match",
                inputs=[entity_reference(
                    "source",
                    "source-10",
                    value={"source_id": "source-10", "text": "其他输入"},
                    source_id="source-10",
                )],
                outputs=[],
                snapshot_name="source_10_flow",
            )
            with trace_step("query.rank", kind="query_stage", input_data={"query": "测试"}) as child:
                child.set_output({"result": "ok", "authorization": f"Bearer {secret}"})
                with trace_step("query.read_evidence", kind="query_stage"):
                    pass
            tracer.write_llm_record("request-1", {
                "status": "success",
                "headers": {"x-api-key": secret},
                "attempts": [{
                    "status": "success",
                    "usage": {"available": True, "input_tokens": 4, "output_tokens": 2},
                }],
            })
            parent.set_output({"ok": True})
        summary = tracer.finalize(status="success")
    finally:
        tracer.close_context()

    assert summary["status"] == "success"
    assert summary["record_complete"] is True
    assert summary["step_count"] == 3
    assert summary["llm_request_count"] == 1
    run = json.loads((tracer.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["record_complete"] is True
    assert run["trace_incomplete"] is False
    assert run["statistics"]["operation_counts"] == {"generated": 2}
    assert (tracer.run_dir / "report.md").is_file()

    source_view = load_debug_run(workspace, tracer.run_id, source_id="source-1")
    assert [record["reason"] for record in source_view["lineage"]] == ["test_source_flow"]
    assert source_view["snapshots"]
    source_snapshot = source_view["snapshots"][source_view["lineage"][0]["snapshot"]]
    serialized_snapshot = json.dumps(source_snapshot, ensure_ascii=False)
    assert "完整输入" in serialized_snapshot
    assert "完整输出" in serialized_snapshot

    parent_step = next(
        record for record in load_jsonl(tracer.steps_path)
        if record["name"] == "command.query"
    )
    step_view = load_debug_run(workspace, tracer.run_id, step_id=parent_step["step_id"])
    assert {record["name"] for record in step_view["steps"]} == {
        "command.query",
        "query.rank",
        "query.read_evidence",
    }
    assert len(step_view["snapshots"]) >= 3

    all_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tracer.run_dir.rglob("*")
        if path.is_file()
    )
    assert secret not in all_text
    assert access_token not in all_text
    assert "[REDACTED]" in all_text


def test_non_debug_trace_payloads_are_not_built() -> None:
    built: list[str] = []

    with trace_step(
        "disabled.step",
        input_data=lambda: built.append("step_input"),
    ) as step:
        step.set_output(lambda: built.append("step_output"))
        trace_lineage(
            operation="generated",
            reason="disabled_trace",
            inputs=lambda: built.append("lineage_input"),
            outputs=lambda: built.append("lineage_output"),
        )

    assert built == []


def test_finalize_failure_marks_run_as_incomplete(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_debug_config(workspace)
    tracer = DebugTracer(workspace, "lint", {}).start()
    tracer.report_path.mkdir()

    try:
        with pytest.raises(DebugTraceError, match="could not be finalized"):
            tracer.finalize(status="success")
    finally:
        tracer.close_context()

    run = json.loads((tracer.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "trace_incomplete"
    assert run["trace_incomplete"] is True
    assert run["record_complete"] is False


def test_report_counts_entities_instead_of_only_lineage_rows(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_debug_config(workspace)
    tracer = DebugTracer(workspace, "ingest", {}).start()
    try:
        trace_lineage(
            operation="generated",
            reason="two_outputs",
            inputs=lambda: [entity_reference("source", "source-1")],
            outputs=lambda: [
                entity_reference("chunk", "chunk-1"),
                entity_reference("chunk", "chunk-2"),
            ],
        )
        trace_lineage(
            operation="removed",
            reason="three_inputs",
            inputs=lambda: [
                entity_reference("claim", "claim-1"),
                entity_reference("claim", "claim-2"),
                entity_reference("claim", "claim-3"),
            ],
            outputs=lambda: [],
        )
        tracer.finalize(status="success")
    finally:
        tracer.close_context()

    run = json.loads((tracer.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["statistics"]["operation_counts"] == {"generated": 2, "removed": 3}
    assert run["statistics"]["lineage_record_counts"] == {"generated": 1, "removed": 1}
    assert run["statistics"]["entity_type_operation_counts"] == {
        "generated": {"chunk": 2},
        "removed": {"claim": 3},
    }


def test_prune_removes_only_expired_completed_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_debug_config(workspace)
    debug_root = workspace / "logs" / "debug"
    debug_root.mkdir(parents=True)
    now = datetime.now(timezone.utc)

    def add_run(name: str, *, status: str, expires_at: datetime) -> Path:
        run_dir = debug_root / name
        run_dir.mkdir()
        (run_dir / "run.json").write_text(json.dumps({
            "run_id": name,
            "status": status,
            "expires_at": expires_at.isoformat(),
        }), encoding="utf-8")
        return run_dir

    expired = add_run("expired", status="success", expires_at=now - timedelta(seconds=1))
    recent = add_run("recent", status="success", expires_at=now + timedelta(days=1))
    running = add_run("running", status="running", expires_at=now - timedelta(days=1))
    malformed = debug_root / "malformed"
    malformed.mkdir()
    (malformed / "run.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.json").write_text(json.dumps({
        "run_id": "outside-link",
        "status": "success",
        "expires_at": (now + timedelta(days=1)).isoformat(),
    }), encoding="utf-8")
    (debug_root / "outside-link").symlink_to(outside, target_is_directory=True)

    assert prune_expired_debug_runs(workspace, now=now) == ["expired"]
    assert not expired.exists()
    assert recent.exists()
    assert running.exists()
    assert malformed.exists()
    assert outside.exists()
    assert {run["run_id"] for run in list_debug_runs(workspace)} == {"recent", "running"}


def test_debug_start_fails_before_run_when_logs_path_is_a_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "blocked").write_text("not a directory", encoding="utf-8")
    write_debug_config(workspace, logs_path="blocked")

    with pytest.raises(DebugTraceError):
        DebugTracer(workspace, "query", {}).start()


@pytest.mark.parametrize(
    "arguments",
    [
        ["ingest"],
        ["lint"],
        ["query", "问题"],
        ["answer-query", "问题"],
        ["render-page", "--render-target", "readable_concept"],
        ["semantic-batch", "--task", "document_analysis"],
        ["claim-set-status", "claim-1", "draft"],
        ["review-list"],
        ["review-auto"],
        ["review-apply", "review-1", "keep_both"],
    ],
)
def test_every_workspace_business_command_accepts_debug(arguments: list[str]) -> None:
    args = build_parser().parse_args([*arguments, "--debug"])
    assert args.debug is True


@pytest.mark.parametrize("command", ["init", "doctor", "bootstrap"])
def test_non_workspace_commands_do_not_accept_debug(command: str) -> None:
    arguments = [command]
    if command == "init":
        arguments.extend(["--project-name", "Test"])
    with pytest.raises(SystemExit):
        build_parser().parse_args([*arguments, "--debug"])


class SequenceOnline:
    results: list[RawFunctionCall | Exception] = []

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):  # noqa: ANN002
        return None

    def request(self, **kwargs):  # noqa: ANN003
        result = type(self).results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class SequenceCLI:
    result: RawFunctionCall | Exception

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        pass

    def request(self, **kwargs):  # noqa: ANN003
        if isinstance(type(self).result, Exception):
            raise type(self).result
        return type(self).result


def debug_llm_settings() -> LLMSettings:
    return LLMSettings(
        primary_max_retries=1,
        retry_backoff_seconds=(0.01,),
        retry_jitter_max_seconds=0.0,
        document_max_chars=24000,
        image_max_bytes=1024,
        image_mime_types=frozenset({"image/png"}),
        cli_timeout_seconds=30,
        cli_model="",
    )


def request_stable_promotion(router: LLMRouter) -> dict:
    return router.request(
        task_name="claim_stable_promotion",
        payload={"task": "claim_stable_promotion", "claim": {"claim_id": "claim-1"}},
    )


def test_debug_llm_record_covers_retry_cli_fallback_validation_and_tokens(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_debug_config(workspace)
    secret = "debug-api-secret"
    skill_root = tmp_path / "skill-root"
    skill_root.mkdir()
    (skill_root / ".env").write_text(
        f'MYAGENTWIKI_LLM_API_KEY="{secret}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SKILL_ROOT_ENVIRONMENT_VARIABLE, str(skill_root))
    invalid_call = RawFunctionCall(
        "submit_claim_promotion_decision",
        '{"decision":"unsupported","confidence":0.8,"reason":"bad"}',
        debug={
            "request": {"headers": {"authorization": f"Bearer {secret}"}},
            "raw_response": {"id": "response-invalid"},
            "usage": {"available": True, "input_tokens": 8, "output_tokens": 3},
        },
    )
    SequenceOnline.results = [invalid_call, invalid_call]
    SequenceCLI.result = RawFunctionCall(
        "submit_claim_promotion_decision",
        '{"decision":"skip","confidence":0.8,"reason":"ok"}',
        debug={
            "events": [{"type": "turn.completed"}],
            "raw_output": "valid cli output",
            "usage": {"available": True, "input_tokens": 12, "output_tokens": 4},
        },
    )

    tracer = DebugTracer(workspace, "semantic-batch", {}).start()
    try:
        router = LLMRouter(
            workspace,
            settings=debug_llm_settings(),
            sleep=lambda _: None,
            random_uniform=lambda _start, _end: 0.0,
            online_client_factory=SequenceOnline,
            cli_client_factory=SequenceCLI,
        )
        assert request_stable_promotion(router)["decision"] == "skip"
        tracer.finalize(status="success")
    finally:
        tracer.close_context()

    records = list(tracer.llm_dir.glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["backend"] == "cli"
    assert len(record["attempts"]) == 3
    assert record["attempts"][0]["validation"]["schema_check"] == "failed"
    assert record["attempts"][0]["backoff_ms"] == 10
    assert record["attempts"][2]["validation"]["business_check"] == "success"
    assert record["attempts"][2]["usage"]["input_tokens"] == 12
    assert all(attempt["started_at"] and attempt["finished_at"] for attempt in record["attempts"])
    assert secret not in records[0].read_text(encoding="utf-8")

    summary_log = load_jsonl(workspace / "logs" / "llm_requests.jsonl")[-1]
    assert summary_log["run_id"] == tracer.run_id
    assert "raw_response" not in summary_log


def test_debug_llm_record_covers_online_success_json_repair_and_provider_usage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_debug_config(workspace)
    SequenceOnline.results = [RawFunctionCall(
        "submit_claim_promotion_decision",
        "{'decision':'skip','confidence':0.8,'reason':'ok'}",
        debug={
            "provider_request_id": "response-online-1",
            "raw_response": {"id": "response-online-1"},
            "usage": {"available": True, "input_tokens": 9, "output_tokens": 3},
        },
    )]
    SequenceCLI.result = AssertionError("CLI fallback must not run")

    tracer = DebugTracer(workspace, "semantic-batch", {}).start()
    try:
        router = LLMRouter(
            workspace,
            settings=debug_llm_settings(),
            sleep=lambda _: None,
            random_uniform=lambda _start, _end: 0.0,
            online_client_factory=SequenceOnline,
            cli_client_factory=SequenceCLI,
        )
        assert request_stable_promotion(router)["decision"] == "skip"
        tracer.finalize(status="success")
    finally:
        tracer.close_context()

    record = json.loads(next(tracer.llm_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert record["backend"] == "online"
    assert len(record["attempts"]) == 1
    attempt = record["attempts"][0]
    assert attempt["provider_request_id"] == "response-online-1"
    assert attempt["repaired"] is True
    assert attempt["validation"]["json_repair"] == "repaired"
    assert attempt["usage"]["input_tokens"] == 9
    run = json.loads((tracer.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["statistics"]["llm"]["input_tokens"] == 9
    report = (tracer.run_dir / "report.md").read_text(encoding="utf-8")
    assert "在线尝试耗时" in report
    assert "已提供用量的输入 token 合计" in report


def test_cli_debug_mode_extracts_jsonl_events_and_token_usage(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_debug_config(workspace)
    captured_command: list[str] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003
        captured_command.extend(command)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps({
            "function_name": "submit_claim_promotion_decision",
            "arguments_json": '{"decision":"skip","confidence":0.8,"reason":"ok"}',
        }), encoding="utf-8")
        stdout = json.dumps({
            "type": "turn.completed",
            "usage": {
                "input_tokens": 21,
                "output_tokens": 5,
                "cached_input_tokens": 4,
            },
        })
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("myagentwiki.llm.cli_client.subprocess.run", fake_run)
    tracer = DebugTracer(workspace, "semantic-batch", {}).start()
    try:
        raw_call = CLILLMClient(workspace, timeout_seconds=30).request(
            spec=get_function_spec("claim_stable_promotion"),
            context={"claim": {"claim_id": "claim-1"}},
            image_paths=[],
        )
        tracer.finalize(status="success")
    finally:
        tracer.close_context()

    assert "--json" in captured_command
    assert raw_call.debug["events"][0]["type"] == "turn.completed"
    assert raw_call.debug["usage"] == {
        "available": True,
        "input_tokens": 21,
        "output_tokens": 5,
        "total_tokens": 26,
        "cached_input_tokens": 4,
    }


def test_debug_llm_record_is_written_when_both_routes_fail(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_debug_config(workspace)
    online_error = LLMClientError(
        "online unavailable",
        backend="online",
        kind="connection_error",
        retryable=True,
    )
    SequenceOnline.results = [online_error, online_error]
    SequenceCLI.result = LLMClientError(
        "cli unavailable",
        backend="cli",
        kind="process_error",
        retryable=False,
    )

    tracer = DebugTracer(workspace, "semantic-batch", {}).start()
    try:
        router = LLMRouter(
            workspace,
            settings=debug_llm_settings(),
            sleep=lambda _: None,
            random_uniform=lambda _start, _end: 0.0,
            online_client_factory=SequenceOnline,
            cli_client_factory=SequenceCLI,
        )
        with pytest.raises(LLMRouteError):
            request_stable_promotion(router)
        tracer.finalize(status="failed")
    finally:
        tracer.close_context()

    record_path = next(tracer.llm_dir.glob("*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert [attempt["backend"] for attempt in record["attempts"]] == ["online", "online", "cli"]


def test_debug_ingest_records_first_reuse_and_changed_source_runs(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "knowledge.md"
    raw_path.write_text(
        "# 调试链路\n\n"
        "调试链路需要保留来源、证据和页面之间的真实关系。\n\n"
        "调试报告由脚本统计每个阶段的实际耗时。\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(raw_dir),
        "--project-name",
        "DebugTraceWorkspace",
        "--target-dir",
        str(workspace),
    )
    config_text = (workspace / "config" / "project.yml").read_text(encoding="utf-8")
    gitignore_text = (workspace / ".gitignore").read_text(encoding="utf-8")
    agents_text = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "debug:\n  retention_days: 7" in config_text
    assert "logs/debug/" in gitignore_text
    assert "--debug" in agents_text

    run_cli("query", "未导入", "--target-dir", str(workspace))
    assert not (workspace / "logs" / "debug").exists()

    first = run_cli("ingest", "--target-dir", str(workspace), "--debug")
    assert first["debug_run"]["status"] == "success"
    first_dir = Path(first["debug_run"]["run_dir"])
    assert first_dir.is_dir()
    assert first["debug_run"]["llm_request_count"] == 0
    source_id = load_jsonl(workspace / "state" / "sources.jsonl")[0]["source_id"]
    first_lineage = load_jsonl(first_dir / "lineage.jsonl")
    source_records = [
        record for record in first_lineage
        if any(
            source_id in entity.get("source_ids", [])
            for side in ("inputs", "outputs")
            for entity in record.get(side, [])
            if isinstance(entity, dict)
        )
    ]
    entity_types = {
        entity["entity_type"]
        for record in source_records
        for side in ("inputs", "outputs")
        for entity in record.get(side, [])
        if isinstance(entity, dict)
    }
    assert {
        "source",
        "normalized",
        "structure_block",
        "evidence_block",
        "knowledge_unit",
        "chunk",
        "claim",
        "semantic_decision",
        "page",
    }.issubset(entity_types)

    second = run_cli("ingest", "--target-dir", str(workspace), "--debug")
    second_lineage = load_jsonl(Path(second["debug_run"]["run_dir"]) / "lineage.jsonl")
    assert any(record["operation"] in {"reused", "skipped"} for record in second_lineage)
    assert any(
        record["reason"] == "no_upstream_changes_and_no_missing_pages"
        for record in second_lineage
    )

    raw_path.write_text(
        "# 调试链路\n\n"
        "修改后的资料需要保存旧产物、替换原因和新页面之间的完整关系。\n\n"
        "调试报告仍由脚本计算所有数量和耗时。\n",
        encoding="utf-8",
    )
    changed = run_cli("ingest", "--target-dir", str(workspace), "--debug")
    changed_dir = Path(changed["debug_run"]["run_dir"])
    changed_lineage = load_jsonl(changed_dir / "lineage.jsonl")
    assert any(
        record["operation"] == "replaced"
        and record["reason"] == "source_content_or_normalizer_changed"
        for record in changed_lineage
    )
    removed = next(
        record for record in changed_lineage
        if record["reason"] == "source_changed_old_derived_artifacts_removed_before_rebuild"
    )
    removed_snapshot = json.loads((changed_dir / removed["snapshot"]).read_text(encoding="utf-8"))
    assert "调试链路需要保留来源" in json.dumps(removed_snapshot, ensure_ascii=False)
    assert any(
        entity["entity_type"] in {"normalized", "chunk", "claim", "historical_claim"}
        for record in changed_lineage
        for side in ("inputs", "outputs")
        for entity in record.get(side, [])
        if isinstance(entity, dict)
    )

    shown = run_cli(
        "debug-show",
        "--target-dir",
        str(workspace),
        "--run-id",
        changed["debug_run"]["run_id"],
        "--source-id",
        source_id,
    )
    assert shown["lineage"]
    assert shown["snapshots"]
