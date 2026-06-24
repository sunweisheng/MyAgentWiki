from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


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


def test_ingest_builds_structure_evidence_and_knowledge_units(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "ops.md").write_text(
        "# 运营工作说明\n\n"
        "## 平台运营组\n\n"
        "负责人：许颖超\n\n"
        "- **支付和支出渠道问题处理**\n\n"
        "对高频或典型故障案例进行系统复盘，提炼标准化处理流程与简易维修方法。\n\n"
        "| 字段 | 值 |\n"
        "| --- | --- |\n"
        "| 小组人数 | 4人 |\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "StructurePipeline",
        "--target-dir",
        str(workspace_dir),
    )

    ingest_result = run_cli("ingest", "--target-dir", str(workspace_dir))
    assert ingest_result["summary"]["structured_count"] == 1

    structure_blocks = load_jsonl(workspace_dir / "state" / "structure_blocks.jsonl")
    evidence_blocks = load_jsonl(workspace_dir / "state" / "evidence_blocks.jsonl")
    knowledge_units = load_jsonl(workspace_dir / "state" / "knowledge_units.jsonl")
    claims = load_jsonl(workspace_dir / "state" / "claims.jsonl")

    assert any(record["block_type"] == "heading" for record in structure_blocks)
    assert any(record["block_type"] == "list_item" for record in structure_blocks)
    assert any(record["block_type"] == "table_row" for record in structure_blocks)

    attached_block = next(
        record
        for record in evidence_blocks
        if record["block_kind"] == "list_item_with_body"
    )
    assert attached_block["local_heading"] == "支付和支出渠道问题处理"
    assert "高频或典型故障案例" in attached_block["text"]
    assert attached_block["content_tags"] == []
    assert {
        (feature["tag"], feature["category"], feature["strength"])
        for feature in attached_block["semantic_features"]
    } >= {("local_heading_body", "structure", "medium")}
    assert len(attached_block["structure_block_ids"]) == 2

    metadata_block = next(
        record
        for record in evidence_blocks
        if record["block_kind"] == "metadata_line"
    )
    assert metadata_block["metadata"] == {"负责人": "许颖超"}
    assert {
        feature["tag"] for feature in metadata_block["semantic_features"]
    } >= {"metadata_fact", "reference_structure", "rules"}

    ku_by_evidence_id = {
        evidence_id: record
        for record in knowledge_units
        for evidence_id in record.get("evidence_block_ids", [])
    }
    attached_ku = ku_by_evidence_id[attached_block["evidence_block_id"]]
    assert attached_ku["unit_kind"] == "statement"
    assert attached_ku["local_heading"] == "支付和支出渠道问题处理"
    assert attached_ku["semantic_projection"]["content_tags"] == []
    assert any(
        feature["tag"] == "local_heading_body"
        for feature in attached_ku["semantic_projection"]["semantic_features"]
    )
    assert attached_ku["source_refs"][0]["start_line"] == attached_block["start_line"]

    metadata_ku = ku_by_evidence_id[metadata_block["evidence_block_id"]]
    assert metadata_ku["unit_kind"] == "metadata_fact"
    metadata_claim = next(
        record
        for record in claims
        if record["evidence_block_ids"] == [metadata_block["evidence_block_id"]]
    )
    assert metadata_claim["claim_type"] == "metadata_fact"
    assert metadata_claim["claim_origin_kind"] == "metadata_fact"
    assert metadata_claim["text"] == "平台运营组 负责人 是 许颖超"
    assert metadata_claim["source_refs"][0]["section_path_parts"] == ["运营工作说明", "平台运营组"]

    attached_claim = next(
        record
        for record in claims
        if "高频或典型故障案例" in record["text"]
    )
    assert attached_claim["knowledge_unit_ids"] == [attached_ku["knowledge_unit_id"]]
    assert attached_claim["evidence_block_ids"] == [attached_block["evidence_block_id"]]
    assert attached_claim["chunk_ids"]
    assert attached_claim["source_refs"][0]["chunk_id"] == attached_claim["chunk_ids"][0]
    assert attached_claim["source_refs"][0]["knowledge_unit_id"] == attached_ku["knowledge_unit_id"]
    assert attached_claim["source_refs"][0]["evidence_block_ids"] == [attached_block["evidence_block_id"]]
    assert attached_claim["source_refs"][0]["section_path_parts"] == ["运营工作说明", "平台运营组"]
    assert all(record["text"] != "支付和支出渠道问题处理" for record in claims)

    lint_result = run_cli("lint", "--target-dir", str(workspace_dir))
    assert lint_result["summary"]["ok"] is True
    assert "structure_coverage" in lint_result
    assert lint_result["structure_coverage"]["rows"]


def test_lint_reports_structure_coverage_rows_and_report_section(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "ops.md").write_text(
        "# 运营工作说明\n\n"
        "## 平台运营组\n\n"
        "负责人：许颖超\n\n"
        "| 字段 | 值 |\n"
        "| --- | --- |\n"
        "| 小组人数 | 4人 |\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "StructureCoverageLint",
        "--target-dir",
        str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    lint_result = run_cli("lint", "--target-dir", str(workspace_dir))

    checks = {item["name"]: item for item in lint_result["checks"]}
    assert checks["structured_pipeline_complete"]["ok"] is True
    assert "structured_claim_coverage_reviewed" in checks

    coverage_rows = lint_result["structure_coverage"]["rows"]
    assert len(coverage_rows) == 1
    coverage_row = coverage_rows[0]
    assert coverage_row["structured_pipeline_complete"] is True
    assert coverage_row["structure_block_count"] > 0
    assert coverage_row["evidence_block_count"] > 0
    assert coverage_row["knowledge_unit_count"] > 0
    assert coverage_row["chunk_count"] > 0
    assert coverage_row["live_claim_count"] > 0

    report_text = (workspace_dir / "reports" / "lint" / "lint_latest.md").read_text(encoding="utf-8")
    assert "## 结构覆盖率 / Structure Coverage" in report_text
    assert "| source_id | status | doc_kind | structure | evidence | knowledge | chunks | live_claims | uncovered_structured_units | pipeline_complete |" in report_text
    assert "### 结构跳过与漏抽分类 / Intentional Skips And Gap Classes" in report_text
    assert "structured_claim_coverage_reviewed" in report_text
    assert "intentional_skips" in report_text
    assert "uncovered_gap_classes" in report_text
    assert "intentional_skip_counts" in lint_result["structure_coverage"]
    assert "uncovered_gap_class_counts" in lint_result["structure_coverage"]
