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


def test_page_intent_routes_workflow_to_guide_page(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text(
        "# Guide\n\n"
        "首先扫描 raw 目录。\n\n"
        "然后生成 normalized 文档。\n\n"
        "最后写入 chunk 与 claim。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "GuideIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl") if not record.get("removed")]
    assert any(record.get("type") == "guide" for record in pages)


def test_page_intent_routes_example_content_to_example_page(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "example.md").write_text(
        "# Example\n\n"
        "例如，Claim 可以承载定义句。\n\n"
        "比如，一个概念页可以引用多个 Claim。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "ExampleIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl") if not record.get("removed")]
    assert any(record.get("type") == "example" for record in pages)


def test_page_intent_routes_reference_content_to_reference_page(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "reference.md").write_text(
        "# FAQ Reference\n\n"
        "参数列表用于说明系统的关键配置项。\n\n"
        "规则清单用于列出处理约束。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "ReferenceIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl") if not record.get("removed")]
    assert any(record.get("type") == "reference" for record in pages)


def test_page_intent_routes_timeline_content_to_timeline_page(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "timeline.md").write_text(
        "# Timeline\n\n"
        "起初系统只支持 source-summary。\n\n"
        "随后加入 claim 层。\n\n"
        "后来引入 semantic batch。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "TimelineIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl") if not record.get("removed")]
    assert any(record.get("type") == "timeline" for record in pages)


def test_page_intent_reject_blocks_question_shell_pages(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "questions.md").write_text(
        "# Questions\n\n"
        "为什么要做知识库？\n\n"
        "如何才能整理页面？\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "RejectIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [
        record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if not record.get("removed") and record.get("type") in {"concept-summary", "concept", "guide", "example", "topic", "reference", "timeline"}
    ]
    assert pages == []
