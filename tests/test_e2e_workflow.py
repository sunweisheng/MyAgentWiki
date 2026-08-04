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
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"), "MYAGENTWIKI_LLM_MODE": "deterministic"},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_cli_text(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "myagentwiki.cli", *args],
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"), "MYAGENTWIKI_LLM_MODE": "deterministic"},
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


def inject_shared_alias_override(workspace_dir: Path, shared_alias: str) -> list[str]:
    live_pages = [
        record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if not record.get("removed")
        and record.get("lifecycle_status", "active") == "active"
        and record.get("type") in {"concept", "topic", "guide", "example"}
    ]
    page_ids = [record["page_id"] for record in live_pages[:2]]
    assert len(page_ids) >= 2

    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = {"page_aliases": {}}
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    page_aliases = overrides.setdefault("page_aliases", {})
    live_page_map = {record["page_id"]: record for record in live_pages}

    for page_id in page_ids:
        page_record = live_page_map[page_id]
        page_override = page_aliases.setdefault(page_id, {})
        aliases = sorted(set(page_override.get("aliases", page_record.get("aliases", []))))
        if shared_alias not in aliases:
            aliases.append(shared_alias)
        page_override["aliases"] = sorted(set(aliases))

    overrides_path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return page_ids


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
    assert init_result["workspace_summary"]["lint_report_exists"] is False
    assert init_result["workspace_summary"]["schema_version"] == "v1"
    assert init_result["workspace_summary"]["schema_guard"]["status"] == "supported"
    assert not (workspace_dir / "raw").exists()
    tracked_files = set(run_git(workspace_dir, "ls-files").splitlines())
    assert not any(path.startswith("raw/") for path in tracked_files)

    ingest_result = run_cli("ingest", "--target-dir", str(workspace_dir))
    assert ingest_result["summary"]["normalized_count"] >= 2
    assert ingest_result["summary"]["changed_page_count"] >= 1
    assert ingest_result["workspace_summary"]["workspace_dir"] == str(workspace_dir.resolve())
    assert ingest_result["workspace_summary"]["raw_dir"] == str(source_dir.resolve())

    query_result = run_cli("query", "什么是知识声明层", "--target-dir", str(workspace_dir), "--intent", "definition")
    assert query_result["intent"] == "definition"
    assert query_result["results"]
    assert query_result["workspace_summary"]["workspace_dir"] == str(workspace_dir.resolve())
    assert query_result["workspace_summary"]["entry_page_path"] == str((workspace_dir / "wiki" / "index.md").resolve())
    assert query_result["results"][0]["reading_pack"]["query_intent"] == "definition"

    # 这里手工制造 alias 冲突，再走 review-list / review-apply / ingest / lint 闭环。
    shared_alias = "共享术语"
    inject_shared_alias_override(workspace_dir, shared_alias)

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
    assert lint_result["workspace_summary"]["lint_report_exists"] is True

    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(item["kind"] == "alias_conflict" and item["status"] == "open" for item in refreshed_reviews["items"])


def test_ingest_refreshes_outdated_normalized_record_without_raw_change(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    raw_path = source_dir / "versioned.md"
    raw_path.write_text("# 当前内容\n\n标准化器升级后应重新处理这份资料。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "NormalizerUpgrade",
        "--target-dir",
        str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    normalized_state_path = workspace_dir / "state" / "normalized.jsonl"
    normalized_records = load_jsonl(normalized_state_path)
    assert len(normalized_records) == 1
    outdated_record = dict(normalized_records[0])
    outdated_record["normalizer_version"] = "normalize_v1"
    normalized_state_path.write_text(
        json.dumps(outdated_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    normalized_file_path = workspace_dir / outdated_record["normalized_path"]
    normalized_file_path.write_text("# 过期结果\n", encoding="utf-8")

    ingest_result = run_cli("ingest", "--target-dir", str(workspace_dir))

    refreshed_records = load_jsonl(normalized_state_path)
    assert ingest_result["summary"]["normalized_count"] == 1
    assert len(refreshed_records) == 1
    assert refreshed_records[0]["normalizer_version"] == "normalize_v2"
    refreshed_text = normalized_file_path.read_text(encoding="utf-8")
    assert "标准化器升级后应重新处理这份资料" in refreshed_text
    assert "过期结果" not in refreshed_text


def test_init_enables_post_ingest_review_auto_by_default(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "note.md").write_text("# 示例\n\n这是一条示例资料。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "PostIngestDefault",
        "--target-dir",
        str(workspace_dir),
    )

    config_text = (workspace_dir / "config" / "project.yml").read_text(encoding="utf-8")
    assert "post_ingest:" in config_text
    assert "review_auto: true" in config_text
    assert (workspace_dir / ".env.example").exists()
    assert not (workspace_dir / ".env").exists()
    gitignore_text = (workspace_dir / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore_text
    agents_text = (workspace_dir / "AGENTS.md").read_text(encoding="utf-8")
    assert "`.env`" in agents_text
    assert not (workspace_dir / "CLAUDE.md").exists()


def test_ingest_runs_post_ingest_review_auto_by_default(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Topic\n\n"
        "为什么 LLM-Wiki 不等于没有检索。\n"
        "为什么 LLM-Wiki 必须重视 Chunking。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "PostIngestReviewAuto",
        "--target-dir",
        str(workspace_dir),
    )

    ingest_result = run_cli("ingest", "--target-dir", str(workspace_dir))

    assert "post_ingest_review_auto" in ingest_result
    assert ingest_result["post_ingest_review_auto"]["summary"]["applied_count"] >= 1
    review_list = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(item["status"] == "open" for item in review_list["items"])


def test_init_default_llm_tasks_generate_pages_in_explicit_test_mode(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "claim.md").write_text(
        "# Claim\n\n"
        "Claim 是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "Claim 用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )
    (source_dir / "chunk.md").write_text(
        "# Chunk\n\n"
        "Chunk 是用于承载局部原文切片的证据单元。\n\n"
        "Chunk 用于把原始资料拆成可追踪、可回链的阅读片段。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "DefaultLLMRouting",
        "--target-dir",
        str(workspace_dir),
    )

    config_text = (workspace_dir / "config" / "project.yml").read_text(encoding="utf-8")
    assert 'review_auto:\n    strategy: "llm_assisted"' in config_text
    assert 'stable_promotion:\n    strategy: "llm_assisted"' in config_text
    assert 'primary: "online"' in config_text
    assert 'fallback: "cli"' in config_text
    assert "command:" not in config_text
    assert "hook" not in config_text.lower()

    ingest_result = run_cli("ingest", "--target-dir", str(workspace_dir))
    assert ingest_result["post_ingest_review_auto"]["summary"]["promoted_claim_count"] >= 2

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    concept_pages = [record for record in page_records if record.get("type") == "concept"]
    overview_pages = [record for record in page_records if record.get("type") == "overview"]

    assert len(concept_pages) >= 2
    assert len(overview_pages) == 1
    assert all(record["render_mode"] == "deterministic" for record in concept_pages)
    assert all(record["render_status"] == "deterministic" for record in concept_pages)
    assert overview_pages[0]["render_mode"] == "deterministic"
    assert overview_pages[0]["render_status"] == "deterministic"

    concept_text = (workspace_dir / concept_pages[0]["page_path"]).read_text(encoding="utf-8")
    overview_text = (workspace_dir / overview_pages[0]["page_path"]).read_text(encoding="utf-8")
    assert "## 摘要 / Summary" in concept_text
    assert "## 工作区综述 / Workspace Overview" in overview_text
    assert "## 维护状态 / Maintenance" in overview_text


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
    assets_dir = tmp_path / "assets"
    assert Path(init_result["target_dir"]).resolve() == workspace_dir.resolve()
    assert Path(init_result["raw_dir"]).resolve() == raw_dir.resolve()
    assert Path(init_result["assets_dir"]).resolve() == assets_dir.resolve()
    assert init_result["raw_dir_preexisting"] is False
    assert init_result["assets_dir_preexisting"] is False
    assert raw_dir.exists()
    assert raw_dir.is_dir()
    assert assets_dir.exists()
    assert assets_dir.is_dir()
    assert not any(raw_dir.iterdir())
    assert not any(assets_dir.iterdir())


def test_init_templates_constrain_agent_prechecks_to_known_raw(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "note.md").write_text("# 示例\n\n资料在这里。\n", encoding="utf-8")

    workspace_dir = tmp_path / "ScopedRawWiki"
    run_cli(
        "init",
        "--project-name",
        "ScopedRawWiki",
        "--source-dir",
        str(source_dir),
        "--target-dir",
        str(workspace_dir),
    )

    agents_text = (workspace_dir / "AGENTS.md").read_text(encoding="utf-8")
    expected_line = (
        "默认只检查这个目录本身；不要为了确认导入范围先读取它的父目录、其他兄弟目录或整库内容"
    )
    assert expected_line in agents_text
    assert not (workspace_dir / "CLAUDE.md").exists()


def test_skill_and_default_prompt_constrain_prechecks_to_known_raw() -> None:
    skill_text = Path("SKILL.md").read_text(encoding="utf-8")
    openai_agent_text = Path("agents/openai.yaml").read_text(encoding="utf-8")
    assert "默认就把这个顶层 `raw/` 当作唯一资料源" in skill_text
    assert "treat that top-level raw directory as the only default source" in openai_agent_text
    assert "默认检查范围也应限制在该 `raw/` 内" in skill_text
    assert "restrict pre-init and pre-ingest file checks to that raw directory" in openai_agent_text
    assert "不要主动探测附近已有工作区、兄弟目录或父目录来替用户猜测来源" in skill_text
    assert "do not probe nearby workspaces, sibling folders, or parent folders to guess one" in openai_agent_text


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
    assert (
        f"Lint report: {(workspace_dir / 'reports' / 'lint' / 'lint_latest.md').resolve()} "
        "(will be created after the first lint run)"
    ) in init_stdout

    ingest_stdout = run_cli_text("ingest", "--target-dir", str(workspace_dir))
    assert f"Workspace: {workspace_dir.resolve()}" in ingest_stdout
    assert f"Raw sibling: {source_dir.resolve()}" in ingest_stdout
    assert f"Entry page: {(workspace_dir / 'wiki' / 'index.md').resolve()}" in ingest_stdout
    assert "Ingest: normalized=" in ingest_stdout
    assert "Auto review: applied=" in ingest_stdout

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


def test_ingest_skips_hidden_files_and_hidden_directories_in_raw(tmp_path: Path) -> None:
    # raw 下所有 . 开头的文件和目录都不应进入 ingest。
    source_dir = tmp_path / "raw"
    visible_nested_dir = source_dir / "notes"
    hidden_dir = source_dir / ".obsidian"
    hidden_nested_dir = source_dir / "topic" / ".drafts"
    visible_nested_dir.mkdir(parents=True)
    hidden_dir.mkdir(parents=True)
    hidden_nested_dir.mkdir(parents=True)

    (source_dir / "visible.md").write_text("# 可见资料\n\n这条资料应该被摄取。\n", encoding="utf-8")
    (source_dir / ".DS_Store").write_text("ignore me", encoding="utf-8")
    (visible_nested_dir / ".secret.md").write_text("# 隐藏资料\n\n这条不应被摄取。\n", encoding="utf-8")
    (hidden_dir / "workspace.json").write_text("{}", encoding="utf-8")
    (hidden_nested_dir / "draft.md").write_text("# 草稿\n\n这条也不应被摄取。\n", encoding="utf-8")
    (visible_nested_dir / "kept.md").write_text("# 保留资料\n\n这条也应该被摄取。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "SkipHiddenRawEntries",
        "--target-dir",
        str(workspace_dir),
    )
    ingest_result = run_cli("ingest", "--target-dir", str(workspace_dir))

    ingested_paths = {
        record["source_path"]
        for record in load_jsonl(workspace_dir / "state" / "sources.jsonl")
    }
    assert ingested_paths == {"../raw/notes/kept.md", "../raw/visible.md"}
    assert ingest_result["summary"]["created_count"] == 2


def test_ingest_does_not_follow_symlinked_files_outside_raw(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    outside_dir = tmp_path / "outside_docs"
    outside_dir.mkdir()
    (source_dir / "visible.md").write_text("# Visible\n\n这条资料应被摄取。\n", encoding="utf-8")
    outside_file = outside_dir / "external.md"
    outside_file.write_text("# External\n\n这条资料不应被摄取。\n", encoding="utf-8")
    os.symlink(outside_file, source_dir / "linked_external.md")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "NoOutsideSymlinkRead",
        "--target-dir",
        str(workspace_dir),
    )

    ingest_result = run_cli("ingest", "--target-dir", str(workspace_dir))

    ingested_paths = {
        record["source_path"]
        for record in load_jsonl(workspace_dir / "state" / "sources.jsonl")
    }
    assert ingested_paths == {"../raw/visible.md"}
    assert ingest_result["summary"]["created_count"] == 1
