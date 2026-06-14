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


def test_claim_role_does_not_route_chinese_procedure_or_example_words(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "workflow.md").write_text(
        "# 工作流\n\n"
        "如何执行资料导入。\n\n"
        "首先扫描 raw 目录。\n\n"
        "然后生成 normalized 文档。\n\n"
        "例如，可以先处理 Markdown 文件。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "ClaimRoleConceptFilter",
        "--target-dir",
        str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    assert claim_records
    roles = {record.get("knowledge_role") for record in claim_records}
    assert "procedure" not in roles
    assert "example" not in roles

    concept_pages = [
        record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if record.get("type") == "concept" and not record.get("removed")
    ]
    assert concept_pages


def test_claim_role_does_not_promote_short_chinese_definition_marker(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "short_definition.md").write_text(
        "# 定义\n\n"
        "用于保留回链。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "ShortDefinitionRole",
        "--target-dir",
        str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    target_claim = next(record for record in claim_records if record.get("text") == "用于保留回链")
    assert target_claim.get("quality_decision_source") == "semantic_batch"
    assert target_claim.get("knowledge_role") == "fact"
    assert target_claim.get("page_intent_hints") == ["topic"]


def test_claim_role_does_not_promote_ambiguous_chinese_markers(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "ambiguous.md").write_text(
        "# 项目复盘\n\n"
        "团队整理历史数据用于分析转化趋势。\n\n"
        "我们沉淀案例库，方便新人学习常见问题。\n\n"
        "产品规则在这次迭代中需要继续完善。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "AmbiguousClaimRole",
        "--target-dir",
        str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    by_text = {record.get("text"): record for record in claim_records}

    history_claim = by_text["团队整理历史数据用于分析转化趋势"]
    assert history_claim.get("knowledge_role") == "fact"
    assert history_claim.get("page_intent_hints") == ["topic"]

    case_claim = by_text["我们沉淀案例库，方便新人学习常见问题"]
    assert case_claim.get("knowledge_role") == "fact"
    assert case_claim.get("page_intent_hints") == ["topic"]

    rules_claim = by_text["产品规则在这次迭代中需要继续完善"]
    assert rules_claim.get("knowledge_role") == "fact"
    assert rules_claim.get("page_intent_hints") == ["topic"]

    semantic_records = load_jsonl(workspace_dir / "state" / "semantic_decisions.jsonl")
    role_records = [
        record for record in semantic_records
        if record.get("task_type") == "claim_role"
    ]
    assert not any("ambiguous_case_keyword" in record.get("risk_flags", []) for record in role_records)
    assert not any("ambiguous_reference_keyword" in record.get("risk_flags", []) for record in role_records)


def test_claim_role_uses_structure_evidence_for_reference(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "reference.md").write_text(
        "# 配置参考\n\n"
        "| 字段 | 值 |\n"
        "| --- | --- |\n"
        "| timeout_seconds | 45 |\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "StructuredReferenceRole",
        "--target-dir",
        str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    table_claim = next(record for record in claim_records if "timeout_seconds" in record.get("text", ""))
    assert table_claim.get("knowledge_role") == "fact"
    assert table_claim.get("page_intent_hints") == ["reference"]
