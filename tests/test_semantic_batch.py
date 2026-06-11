from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from myagentwiki.cli import load_semantic_task_config, load_workspace_config
from myagentwiki.semantic import build_semantic_decision_id, fingerprint_payload


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path | None = None) -> dict:
    command = [sys.executable, "-m", "myagentwiki.cli", *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
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


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_init_creates_semantic_scaffold(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "note.md").write_text("# Note\n\nClaim 是独立知识声明层。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    result = run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "SemanticScaffold",
        "--target-dir",
        str(workspace_dir),
    )

    created = set(result["created_directories"])
    assert str((workspace_dir / "semantic").resolve()) in created
    assert str((workspace_dir / "semantic" / "batches").resolve()) in created
    assert (workspace_dir / "state" / "semantic_decisions.jsonl").exists()
    assert (workspace_dir / "state" / "migration_decisions.jsonl").exists()
    assert (workspace_dir / "state" / "migration_followups.jsonl").exists()
    assert (workspace_dir / "state" / "migration_runs.jsonl").exists()
    assert (workspace_dir / "state" / "schema_confirmations.jsonl").exists()

    config_text = (workspace_dir / "config" / "project.yml").read_text(encoding="utf-8")
    assert 'schema_version: "v1"' in config_text
    assert "workspace:" in config_text
    assert "semantic:" in config_text
    assert "batch_scheduler:" in config_text
    assert "document_analysis:" in config_text
    assert "claim_candidate_quality:" in config_text
    assert "claim_role:" in config_text
    assert "page_intent:" in config_text

    tracked_files = {
        line.strip()
        for line in subprocess.run(
            ["git", "ls-files"],
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        if line.strip()
    }
    assert "state/schema_confirmations.jsonl" in tracked_files


def test_semantic_batch_writes_and_reuses_decisions(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "concept.md").write_text(
        "# 概念\n\n"
        "Claim 是位于 chunk 与 wiki 之间的独立知识声明层。\n"
        "例如，Claim 可以承载定义句和事实句。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "SemanticBatch",
        "--target-dir",
        str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    first = run_cli("semantic-batch", "--task", "claim_role", "--target-dir", str(workspace_dir))
    assert first["summary"]["item_count"] >= 1
    first_records = load_jsonl(workspace_dir / "state" / "semantic_decisions.jsonl")
    assert any(record.get("task_type") == "claim_role" for record in first_records)
    assert first["summary"]["cache_hits"] >= 1
    assert first["summary"]["written_decision_count"] == 0

    second = run_cli("semantic-batch", "--task", "claim_role", "--target-dir", str(workspace_dir))
    assert second["summary"]["cache_hits"] >= 1
    assert second["summary"]["written_decision_count"] == 0


def test_semantic_batch_dry_run_does_not_persist(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text(
        "# Guide\n\n"
        "如何进行切块。\n"
        "首先按标题切分，然后按段落切分。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "SemanticDryRun",
        "--target-dir",
        str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    before = load_jsonl(workspace_dir / "state" / "semantic_decisions.jsonl")
    result = run_cli("semantic-batch", "--task", "document_analysis", "--dry-run", "--target-dir", str(workspace_dir))
    after = load_jsonl(workspace_dir / "state" / "semantic_decisions.jsonl")

    assert result["summary"]["dry_run"] is True
    assert result["summary"]["item_count"] >= 1
    assert after == before


def test_semantic_batch_claim_candidate_quality_writes_short_claim_decisions(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "shorts.md").write_text(
        "# 短句\n\n"
        "系统必须保留回链。\n\n"
        "保留回链。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "SemanticShortClaimQuality",
        "--target-dir",
        str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    semantic_records = load_jsonl(workspace_dir / "state" / "semantic_decisions.jsonl")
    assert any(record.get("task_type") == "claim_candidate_quality" for record in semantic_records)

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    assert any(record.get("quality_decision_source") == "semantic_batch" for record in claim_records)
    assert any(record.get("quality_safe_auto_ready") is True for record in claim_records if record.get("text") == "保留回链")


def test_page_intent_cache_recomputes_after_claim_role_change(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "concept.md").write_text(
        "# 概念\n\n"
        "Claim 是位于 chunk 与 wiki 之间的独立知识声明层。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "SemanticDependencyRefresh",
        "--target-dir",
        str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    initial_pages = [
        record
        for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if not record.get("removed")
    ]
    assert any(record.get("type") == "concept" for record in initial_pages)

    claim_record = next(
        record
        for record in load_jsonl(workspace_dir / "state" / "claims.jsonl")
        if record.get("lifecycle_status", "active") == "active"
    )
    claim_role_config = load_semantic_task_config(
        load_workspace_config(workspace_dir),
        "claim_role",
    )
    claim_role_payload = {
        "item_id": claim_record["claim_id"],
        "claim_id": claim_record["claim_id"],
        "text": claim_record.get("text", ""),
        "claim_type": claim_record.get("claim_type"),
        "quality_label": claim_record.get("quality_label"),
        "quality_reason": claim_record.get("quality_reason"),
        "quality_safe_auto_ready": claim_record.get("quality_safe_auto_ready"),
        "source_ids": claim_record.get("source_ids", []),
        "source_refs": claim_record.get("source_refs", []),
    }
    input_fingerprint = fingerprint_payload(
        task_name="claim_role",
        item_payloads=[claim_role_payload],
        prompt_version=claim_role_config.prompt_version,
        schema_version=claim_role_config.schema_version,
    )
    append_jsonl(
        workspace_dir / "state" / "semantic_decisions.jsonl",
        {
            "decision_id": build_semantic_decision_id("claim_role", input_fingerprint),
            "task_type": "claim_role",
            "item_type": "claim",
            "item_ids": [claim_record["claim_id"]],
            "decision": {
                "knowledge_role": "procedure",
                "page_intent_hints": ["guide"],
                "concept_candidate_score": 0.2,
            },
            "confidence": 0.99,
            "reason_code": "test_claim_role_override",
            "prompt_version": claim_role_config.prompt_version,
            "model_key": claim_role_config.model_key,
            "schema_version": claim_role_config.schema_version,
            "input_fingerprint": input_fingerprint,
            "created_at": "9999-01-01T00:00:00Z",
            "superseded_by": [],
        },
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    refreshed_pages = [
        record
        for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if not record.get("removed")
    ]
    assert any(record.get("type") == "guide" for record in refreshed_pages)
    assert all(record.get("type") != "concept" for record in refreshed_pages)

    lint_result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {item["name"]: item for item in lint_result["checks"]}
    assert checks["page_semantic_consistency"]["ok"] is True
