from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path | None = None) -> dict:
    # 端到端测试坚持只走命令行入口，这样更接近实际用户和 Agent 的使用方式。
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


def run_cli_text(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "myagentwiki.cli", *args],
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def test_e2e_init_ingest_query_review_and_lint(tmp_path: Path) -> None:
    # 这条 E2E 目标不是把所有边角都覆盖完，而是把“用户第一次上手”的主闭环跑通。
    source_dir = tmp_path / "raw"
    nested_dir = source_dir / "nested" / "topic"
    nested_dir.mkdir(parents=True)
    (nested_dir / "knowledge.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层应该支持从 Wiki 页面回链到 Claim、Chunk 和 Source。\n\n"
        "知识声明层还应该记录自己被多少个页面引用。\n",
        encoding="utf-8",
    )
    (source_dir / "review.md").write_text(
        "# 审核闭环\n\n"
        "系统需要把相互冲突的结论送入 review 队列。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    init_result = run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "E2EWorkflow",
        "--target-dir",
        str(workspace_dir),
    )
    assert Path(init_result["target_dir"]).resolve() == workspace_dir.resolve()
    assert Path(init_result["raw_dir"]).resolve() == source_dir.resolve()
    assert init_result["raw_dir_relative_path"] == "../raw"
    assert init_result["raw_dir_preexisting"] is True
    assert init_result["workspace_summary"]["workspace_dir"] == str(workspace_dir.resolve())
    assert init_result["workspace_summary"]["raw_dir"] == str(source_dir.resolve())
    assert init_result["workspace_summary"]["entry_page_path"] == str((workspace_dir / "wiki" / "index.md").resolve())
    assert not (workspace_dir / "raw").exists()
    tracked_files = set(run_git(workspace_dir, "ls-files").splitlines())
    assert not any(path.startswith("raw/") for path in tracked_files)

    ingest_result = run_cli("ingest", "--target-dir", str(workspace_dir))
    assert ingest_result["summary"]["normalized_count"] >= 2
    assert ingest_result["summary"]["changed_page_count"] >= 1
    assert ingest_result["workspace_summary"]["workspace_dir"] == str(workspace_dir.resolve())
    assert ingest_result["workspace_summary"]["raw_dir"] == str(source_dir.resolve())

    query_result = run_cli("query", "什么是知识声明层", "--target-dir", str(workspace_dir))
    assert query_result["intent"] == "definition"
    assert query_result["results"]
    assert query_result["workspace_summary"]["workspace_dir"] == str(workspace_dir.resolve())
    assert query_result["workspace_summary"]["entry_page_path"] == str((workspace_dir / "wiki" / "index.md").resolve())
    assert query_result["results"][0]["reading_pack"]["query_intent"] == "definition"

    pages = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    concept_pages = [record for record in pages if record.get("type") == "concept-summary"]
    assert len(concept_pages) >= 2

    # 这里手工制造 alias 冲突，再走 review-list / review-apply / ingest / lint 闭环。
    shared_alias = "共享术语"
    concept_pages[0]["aliases"] = sorted(set(concept_pages[0].get("aliases", []) + [shared_alias]))
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + [shared_alias]))
    all_pages = {record["page_id"]: record for record in pages}
    all_pages[concept_pages[0]["page_id"]] = concept_pages[0]
    all_pages[concept_pages[1]["page_id"]] = concept_pages[1]
    (workspace_dir / "state" / "pages.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in all_pages.values()) + "\n",
        encoding="utf-8",
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    review_list = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert review_list["workspace_summary"]["workspace_dir"] == str(workspace_dir.resolve())
    alias_review = next(item for item in review_list["items"] if item["kind"] == "alias_conflict")

    review_apply = run_cli(
        "review-apply",
        alias_review["review_id"],
        "assign_alias",
        "--primary-page-id",
        alias_review["candidate_page_ids"][0],
        "--alias-value",
        shared_alias,
        "--target-dir",
        str(workspace_dir),
    )
    assert review_apply["action"] == "assign_alias"
    assert review_apply["workspace_summary"]["workspace_dir"] == str(workspace_dir.resolve())

    run_cli("ingest", "--target-dir", str(workspace_dir))
    lint_result = run_cli("lint", "--target-dir", str(workspace_dir))
    assert lint_result["summary"]["ok"] is True
    assert lint_result["workspace_summary"]["workspace_dir"] == str(workspace_dir.resolve())
    assert lint_result["workspace_summary"]["lint_report_path"] == str(
        (workspace_dir / "reports" / "lint" / "lint_latest.md").resolve()
    )

    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(item["kind"] == "alias_conflict" and item["status"] == "open" for item in refreshed_reviews["items"])


def test_init_creates_empty_sibling_raw_when_missing(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "LocalKnowledgeWiki"

    init_result = run_cli(
        "init",
        "--project-name",
        "LocalKnowledgeWiki",
        "--target-dir",
        str(workspace_dir),
    )

    raw_dir = tmp_path / "raw"
    assert Path(init_result["target_dir"]).resolve() == workspace_dir.resolve()
    assert Path(init_result["raw_dir"]).resolve() == raw_dir.resolve()
    assert init_result["raw_dir_preexisting"] is False
    assert raw_dir.exists()
    assert raw_dir.is_dir()
    assert not any(raw_dir.iterdir())


def test_cli_text_output_includes_absolute_workspace_paths(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "note.md").write_text("# 示例\n\n这是一条示例资料。\n", encoding="utf-8")

    workspace_dir = tmp_path / "LocalKnowledgeWiki"
    init_stdout = run_cli_text(
        "init",
        "--project-name",
        "LocalKnowledgeWiki",
        "--source-dir",
        str(source_dir),
        "--target-dir",
        str(workspace_dir),
    )
    assert f"Workspace: {workspace_dir.resolve()}" in init_stdout
    assert f"Raw sibling: {source_dir.resolve()}" in init_stdout
    assert f"Entry page: {(workspace_dir / 'wiki' / 'index.md').resolve()}" in init_stdout

    ingest_stdout = run_cli_text("ingest", "--target-dir", str(workspace_dir))
    assert f"Workspace: {workspace_dir.resolve()}" in ingest_stdout
    assert f"Raw sibling: {source_dir.resolve()}" in ingest_stdout
    assert f"Entry page: {(workspace_dir / 'wiki' / 'index.md').resolve()}" in ingest_stdout

    query_stdout = run_cli_text("query", "示例", "--target-dir", str(workspace_dir))
    assert f"Workspace: {workspace_dir.resolve()}" in query_stdout
    assert f"Entry page: {(workspace_dir / 'wiki' / 'index.md').resolve()}" in query_stdout

    answer_ready_stdout = run_cli_text("query", "示例", "--answer-ready", "--target-dir", str(workspace_dir))
    assert f"Workspace: {workspace_dir.resolve()}" in answer_ready_stdout

    review_list_stdout = run_cli_text("review-list", "--target-dir", str(workspace_dir))
    assert f"Workspace: {workspace_dir.resolve()}" in review_list_stdout

    lint_stdout = run_cli_text("lint", "--target-dir", str(workspace_dir))
    assert f"Workspace: {workspace_dir.resolve()}" in lint_stdout
    assert f"Lint report: {(workspace_dir / 'reports' / 'lint' / 'lint_latest.md').resolve()}" in lint_stdout


def test_wiki_index_escapes_paths_with_spaces(tmp_path: Path) -> None:
    # 目录页里的 Markdown 链接需要对空格转义，否则部分查看器会把路径截断。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "#### 2. Chunk Lint\n\n"
        "Chunk Lint 检查 chunk 是否可用： chunk 是否超过 hard max tokens。\n\n"
        "chunk 是否过短且未合并。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "EscapedWikiLinks",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    index_text = (workspace_dir / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "wiki/concepts/" in index_text
    assert "Chunk%20Lint.md" in index_text
