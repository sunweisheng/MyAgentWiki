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


def test_claim_role_blocks_procedure_and_example_from_concept_generation(tmp_path: Path) -> None:
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
    assert "procedure" in roles or "example" in roles

    concept_pages = [
        record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if record.get("type") == "concept" and not record.get("removed")
    ]
    assert concept_pages == []


def test_claim_role_can_promote_short_definition_with_quality_clearance(tmp_path: Path) -> None:
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
    assert target_claim.get("knowledge_role") == "definition"
