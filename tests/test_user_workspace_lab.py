from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path | None = None) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "myagentwiki.cli", *args, "--json"],
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_lab(tmp_path: Path, scenario: str) -> dict:
    runtime_root = tmp_path / "runtime"
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "user_project_lab"
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_user_workspace_lab.py"),
            "--fixture-root",
            str(fixture_root),
            "--runtime-root",
            str(runtime_root),
            "--scenario",
            scenario,
            "--clean",
        ],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_query_link_expansion_exposes_linked_pages_and_context(tmp_path: Path) -> None:
    report = run_lab(tmp_path, "baseline")
    query_payload = report["queries"]["backlink_lookup"]
    assert query_payload["results"]
    top_result = query_payload["results"][0]
    reading_pack = top_result["reading_pack"]
    assert "linked_pages" in reading_pack
    assert reading_pack["retrieval_context"]["link_expansion_used"] is True
    assert reading_pack["retrieval_context"]["link_expansion_reason"] in {
        "same_canonical_family",
        "outgoing_link",
        "incoming_link",
        "related_page",
    }
    assert reading_pack["retrieval_context"]["linked_page_paths"]


def test_page_links_index_is_generated_and_written_to_runtime_workspace(tmp_path: Path) -> None:
    report = run_lab(tmp_path, "baseline")
    workspace_dir = Path(report["init"]["target_dir"])
    page_links_path = workspace_dir / "indexes" / "page_links.json"
    assert page_links_path.exists()
    payload = json.loads(page_links_path.read_text(encoding="utf-8"))
    assert payload["index_version"] == "page_links_v1"
    assert payload["page_count"] >= 1
    assert payload["pages"]


def test_update_raw_scenario_changes_pages_and_keeps_workspace_runnable(tmp_path: Path) -> None:
    report = run_lab(tmp_path, "update_raw")
    assert report["ingest"]["summary"]["changed_page_count"] >= 1
    query_payload = report["queries"]["definition_claim"]
    assert query_payload["results"]
    assert query_payload["results"][0]["reading_pack"]["matched_claims"]


def test_add_raw_scenario_increases_coverage_and_keeps_lint_ok(tmp_path: Path) -> None:
    report = run_lab(tmp_path, "add_raw")
    assert report["ingest"]["summary"]["normalized_count"] >= 1
    assert report["lint"]["summary"]["ok"] is True


def test_markdown_table_and_image_fixture_flow_into_structure_and_query(tmp_path: Path) -> None:
    report = run_lab(tmp_path, "update_table_content")
    workspace_dir = Path(report["init"]["target_dir"])
    structure_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "structure_blocks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(record["block_type"] == "table_row" for record in structure_records)
    normalized_dir = workspace_dir / "normalized"
    normalized_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in normalized_dir.rglob("*.md")
    )
    assert "OCR 文本" in normalized_text or "LLM 图片理解" in normalized_text or "图片仅生成元数据级 normalized 文档" in normalized_text
