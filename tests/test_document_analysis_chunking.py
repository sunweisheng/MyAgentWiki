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


def test_ingest_applies_document_analysis_to_normalized_and_chunking(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "plain_note.md").write_text(
        "第一段说明系统为什么需要证据层。\n\n"
        "第二段说明语义层不应直接污染证据账本。\n\n"
        "第三段说明 presentation 层只是视图，不是主真相。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "DocumentAnalysisChunking",
        "--target-dir",
        str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    normalized_records = load_jsonl(workspace_dir / "state" / "normalized.jsonl")
    assert len(normalized_records) == 1
    normalized_record = normalized_records[0]
    assert normalized_record["document_kind"] == "note"
    assert normalized_record["structure_quality"] == "mostly_clean"
    assert normalized_record["chunk_strategy_hint"] == "paragraph_first"

    semantic_records = load_jsonl(workspace_dir / "state" / "semantic_decisions.jsonl")
    assert any(record.get("task_type") == "document_analysis" for record in semantic_records)

    chunk_records = load_jsonl(workspace_dir / "state" / "chunks.jsonl")
    assert len(chunk_records) >= 3
    assert all(record.get("chunk_kind") == "paragraph_first" for record in chunk_records)
    assert all(record.get("topicworthiness_hint") == "note" for record in chunk_records)
