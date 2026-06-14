from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from myagentwiki.cli import (
    collect_semantic_task_items,
    load_semantic_task_config,
    load_workspace_config,
    normalize_semantic_batch_results,
)
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

    config_text = (workspace_dir / "config" / "project.yml").read_text(encoding="utf-8")
    assert 'schema_version: "v1"' in config_text
    assert "workspace:" in config_text
    assert "semantic:" in config_text
    assert "agent_cli_hook:" in config_text
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
    assert "state/semantic_decisions.jsonl" in tracked_files


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
    claim_role_decisions = [
        record for record in first_records
        if record.get("task_type") == "claim_role"
    ]
    assert claim_role_decisions
    assert all(record.get("decision_status") == "accepted" for record in claim_role_decisions)
    assert all("risk_flags" in record for record in claim_role_decisions)
    assert all("supporting_ids" in record for record in claim_role_decisions)
    assert all("abstain_reason" in record for record in claim_role_decisions)
    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    projected_claims = [
        record for record in claim_records
        if record.get("semantic_projection", {}).get("knowledge_role")
    ]
    assert projected_claims
    assert any(
        decision["decision_id"] in claim.get("semantic_decision_ids", [])
        for decision in claim_role_decisions
        for claim in projected_claims
    )
    assert all(
        claim["semantic_projection"]["knowledge_role"] == claim.get("knowledge_role")
        for claim in projected_claims
    )
    assert first["summary"]["cache_hits"] >= 1
    assert first["summary"]["written_decision_count"] == 0

    second = run_cli("semantic-batch", "--task", "claim_role", "--target-dir", str(workspace_dir))
    assert second["summary"]["cache_hits"] >= 1
    assert second["summary"]["written_decision_count"] == 0


def test_semantic_batch_contract_skips_abstain_and_malformed_decisions(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "notes.md").write_text("# 笔记\n\n系统需要保留来源回链。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "SemanticContract",
        "--target-dir",
        str(workspace_dir),
    )
    config = load_semantic_task_config(load_workspace_config(workspace_dir), "claim_role")
    batch_items = [
        {
            "item_id": "claim-accepted",
            "claim_id": "claim-accepted",
            "text": "系统需要保留来源回链。",
        },
        {
            "item_id": "claim-abstain",
            "claim_id": "claim-abstain",
            "text": "来源回链。",
        },
        {
            "item_id": "claim-malformed",
            "claim_id": "claim-malformed",
            "text": "示例文本。",
        },
    ]
    normalized, skipped = normalize_semantic_batch_results(
        "claim_role",
        {
            "decisions": [
                {
                    "item_id": "claim-accepted",
                    "decision": {
                        "knowledge_role": "fact",
                        "page_intent_hints": ["topic"],
                        "concept_candidate_score": 0.45,
                    },
                    "confidence": config.min_confidence,
                    "reason_code": "test_contract_accept",
                    "risk_flags": ["ambiguous_chinese_marker"],
                    "supporting_ids": ["evidence-1"],
                },
                {
                    "item_id": "claim-abstain",
                    "decision": "abstain",
                    "confidence": config.min_confidence,
                    "reason_code": "test_contract_abstain",
                    "abstain_reason": "insufficient_context",
                },
                {
                    "item_id": "claim-malformed",
                    "decision": {"knowledge_role": "fact"},
                    "confidence": config.min_confidence,
                    "reason_code": "test_contract_missing_fields",
                },
            ],
        },
        batch_items,
        config,
    )

    assert [record["item_ids"] for record in normalized] == [["claim-accepted"]]
    accepted = normalized[0]
    assert accepted["decision_status"] == "accepted"
    assert accepted["risk_flags"] == ["ambiguous_chinese_marker"]
    assert accepted["supporting_ids"] == ["evidence-1"]
    assert accepted["abstain_reason"] == ""
    assert {record["item_id"] for record in skipped} == {"claim-abstain", "claim-malformed"}
    malformed = next(record for record in skipped if record["item_id"] == "claim-malformed")
    assert malformed["decision_status"] == "rejected"
    assert "semantic_decision_missing_required_fields" in malformed["risk_flags"]
    assert sorted(malformed["missing_fields"]) == ["concept_candidate_score", "page_intent_hints"]


def test_semantic_batch_items_include_structure_context(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "ops.md").write_text(
        "# 运营手册\n\n"
        "## 支付问题\n\n"
        "- **渠道故障案例复盘**\n\n"
        "对典型故障案例进行复盘，沉淀处理流程。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "SemanticStructureContext",
        "--target-dir",
        str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_role_items = collect_semantic_task_items(workspace_dir, "claim_role")
    target_item = next(
        item for item in claim_role_items
        if "典型故障案例" in item.get("text", "")
    )
    structure_context = target_item["structure_context"]
    assert structure_context["section_path_parts"] == ["运营手册", "支付问题"]
    assert structure_context["section_title"] == "支付问题"
    assert structure_context["local_headings"] == ["渠道故障案例复盘"]
    assert structure_context["unit_kind_counts"] == {"statement": 1}
    assert structure_context["evidence_block_kind_counts"] == {"list_item_with_body": 1}
    assert structure_context["content_tag_counts"] == {}
    assert "cases" not in structure_context["semantic_feature_counts"]
    assert structure_context["semantic_feature_counts"]["local_heading_body"] >= 1
    assert structure_context["semantic_feature_strength_counts"]["medium"] >= 1
    assert structure_context["knowledge_unit_ids"]
    assert structure_context["evidence_block_ids"]

    page_intent_items = collect_semantic_task_items(workspace_dir, "page_intent")
    grouped_item = next(
        item for item in page_intent_items
        if target_item["claim_id"] in item.get("claim_ids", [])
    )
    group_context = grouped_item["group_context"]
    assert group_context["content_tag_counts"] == {}
    assert group_context["semantic_feature_counts"]["local_heading_body"] >= 1
    assert group_context["unit_kind_counts"] == {"statement": 1}
    assert group_context["evidence_block_kind_counts"] == {"list_item_with_body": 1}
    assert group_context["section_path_counts"] == {"运营手册 > 支付问题": 1}
    assert group_context["representative_local_headings"] == ["渠道故障案例复盘"]


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
    assert not any(record.get("quality_safe_auto_ready") is True for record in claim_records if record.get("text") == "保留回链")
    quality_claim = next(record for record in claim_records if record.get("text") == "保留回链")
    assert quality_claim["semantic_decision_ids"]
    assert quality_claim["semantic_projection"]["quality_safe_auto_ready"] is not True
    assert quality_claim["semantic_projection"]["quality_label"] == quality_claim["quality_label"]


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
    claim_role_payload = next(
        item for item in collect_semantic_task_items(workspace_dir, "claim_role")
        if item.get("claim_id") == claim_record["claim_id"]
    )
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
            "decision_status": "accepted",
            "confidence": 0.99,
            "reason_code": "test_claim_role_override",
            "risk_flags": [],
            "supporting_ids": [claim_record["claim_id"]],
            "abstain_reason": "",
            "prompt_version": claim_role_config.prompt_version,
            "model_key": claim_role_config.model_key,
            "schema_version": claim_role_config.schema_version,
            "input_fingerprint": input_fingerprint,
            "created_at": "9999-01-01T00:00:00Z",
            "superseded_by": [],
        },
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    refreshed_claim = next(
        record
        for record in load_jsonl(workspace_dir / "state" / "claims.jsonl")
        if record.get("claim_id") == claim_record["claim_id"]
    )
    assert refreshed_claim.get("knowledge_role") == "procedure"
    assert refreshed_claim.get("page_intent_hints") == ["guide"]
    assert refreshed_claim["semantic_projection"]["knowledge_role"] == "procedure"

    lint_result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {item["name"]: item for item in lint_result["checks"]}
    assert checks["page_semantic_consistency"]["ok"] is False
    assert "topic_page_semantically_thin:procedure" in checks["page_semantic_consistency"]["details"]
