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


def test_query_returns_alias_hits_and_canonical_targets(tmp_path: Path) -> None:
    # 这条回归验证 query_normalizer 已经真正接入：
    # 用 alias 命中时，不只返回页面，还要回传 alias/canonical 线索。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层应该支持从 Wiki 页面反查到 Claim、Chunk 和 Source。\n\n"
        "知识声明层还应该记录自己被多少个页面引用。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AliasQueryRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli("query", "知识声明层", "--target-dir", str(workspace_dir))

    assert result["summary"]["returned_page_count"] >= 1
    assert result["alias_hits"]
    assert result["canonical_targets"]
    assert result["intent"] == "lookup"
    assert any(target["canonical_id"].startswith("concept:") for target in result["canonical_targets"])
    assert result["results"][0]["exact_match_boost"] >= 1.2


def test_query_detects_definition_intent_and_prefers_concept_pages(tmp_path: Path) -> None:
    # “什么是...” 这类问法应该识别为 definition，并把概念页轻微前推。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "IntentQueryRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli("query", "什么是知识声明层", "--target-dir", str(workspace_dir))

    assert result["intent"] == "definition"
    assert result["results"]
    assert result["results"][0]["type"] == "concept-summary"
    assert result["results"][0]["intent_boost"] >= 1.0


def test_concept_page_title_and_path_are_human_readable_for_question_headings(tmp_path: Path) -> None:
    # FAQ 风格标题不应把编号、问句尾巴和内部 page_id 暴露成最终页面主标题。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 1. Claim 是什么\n\n"
        "Claim 是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "Claim 用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ConceptTitleRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(record for record in page_records if record.get("type") == "concept-summary")

    assert concept_page["title"] == "Claim"
    assert concept_page["canonical_id"] == "concept:claim"
    assert concept_page["page_path"].startswith(f"wiki/concepts/{concept_page['page_id']}/")
    assert concept_page["page_path"].endswith("/Claim.md")
    assert "__page_cpt_" not in concept_page["page_path"]

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "# Claim" in page_text
    assert "规范概念键: `claim`" in page_text


def test_concept_page_ignores_yaml_examples_inside_definition_section(tmp_path: Path) -> None:
    # “Claim 是什么”小节里的 YAML 示例不应被当成真正的 claim 并抢占代表陈述。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "## 问题 9：知识声明 Claim 层如何在第一版实现\n\n"
        "### 1. Claim 是什么\n\n"
        "Claim 是从 chunk 中抽取出来的一条相对原子的知识声明。\n\n"
        "它不是普通摘要，也不是整段原文。\n\n"
        "例如：\n\n"
        "```yaml\n"
        "claim_id: claim_20260527_bm25_001\n"
        "text: BM25 是一种用于关键词检索的相关性排序算法。\n"
        "claim_type: definition\n"
        "```\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ClaimExampleRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(
        record
        for record in page_records
        if record.get("type") == "concept-summary" and record.get("canonical_id") == "concept:claim"
    )

    assert concept_page["summary"] == "Claim 是从 chunk 中抽取出来的一条相对原子的知识声明"
    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "代表陈述: Claim 是从 chunk 中抽取出来的一条相对原子的知识声明" in page_text
    assert "BM25 是一种用于关键词检索的相关性排序算法。" not in page_text


def test_query_evidence_intent_boosts_source_refs_field(tmp_path: Path) -> None:
    # “来源/证据”类问题应识别为 evidence，并让 source_refs 字段真正参与更强排序。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 证据回链\n\n"
        "系统需要把 Wiki 结论回链到 Claim、Chunk 和 Source。\n\n"
        "来源证据应能在查询结果里被优先读取。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "EvidenceQueryRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli("query", "这个结论的来源证据是什么", "--target-dir", str(workspace_dir))

    assert result["intent"] == "evidence"
    assert result["results"]
    top_result = result["results"][0]
    assert top_result["type"] == "source-summary"
    assert top_result["intent_boost_reason"] == "intent_evidence_prefers_source"
    assert top_result["reading_pack"]["query_intent"] == "evidence"


def test_lint_passes_and_writes_report_for_initialized_workspace(tmp_path: Path) -> None:
    # lint 现在除了返回 JSON，还应把最新报告写到 reports/lint/lint_latest.md。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Git 版本管理\n\n"
        "系统需要使用 Git 管理本地版本历史。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "LintRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli("lint", "--target-dir", str(workspace_dir))

    assert result["summary"]["ok"] is True
    report_path = workspace_dir / "reports" / "lint" / "lint_latest.md"
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "Lint Report" in report_text
    assert "search_index_covers_live_pages" in report_text


def test_init_creates_alias_index_file(tmp_path: Path) -> None:
    # 初始化后的工作区应该直接带 alias registry，占位也好过缺文件。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text("知识库需要来源追踪。", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    result = run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AliasIndexInit",
        "--target-dir", str(workspace_dir),
    )

    assert Path(result["target_dir"]).resolve() == workspace_dir.resolve()
    alias_index_path = workspace_dir / "indexes" / "aliases.json"
    assert alias_index_path.exists()
    alias_index = json.loads(alias_index_path.read_text(encoding="utf-8"))
    assert alias_index["index_version"] == "aliases_v1"


def test_ingest_creates_alias_conflict_review_when_alias_registry_collides(tmp_path: Path) -> None:
    # 这个回归直接验证 alias registry 不只是“发现冲突”，
    # 而是真的会把冲突送进 review 队列。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text(
        "# Alpha 术语\n\n"
        "Alpha 术语是用于管理版本状态的概念。\n",
        encoding="utf-8",
    )
    (source_dir / "beta.md").write_text(
        "# Beta 术语\n\n"
        "Beta 术语是用于管理审核状态的概念。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AliasConflictReview",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept-summary"]
    assert len(concept_pages) >= 2

    first = concept_pages[0]
    second = concept_pages[1]
    shared_alias = "共享术语"
    first["aliases"] = sorted(set(first.get("aliases", []) + [shared_alias]))
    second["aliases"] = sorted(set(second.get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    # 再次 ingest 会刷新 pages -> aliases -> reviews。
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    review_records = [
        json.loads(line)
        for line in reviews_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    alias_reviews = [record for record in review_records if record.get("kind") == "alias_conflict"]

    assert alias_reviews
    assert any(shared_alias in json.dumps(record.get("evidence", []), ensure_ascii=False) for record in alias_reviews)


def test_review_apply_assign_alias_updates_page_alias_overrides(tmp_path: Path) -> None:
    # alias_conflict 的细动作应能把某个 alias 指定给目标页，并写入可持久化的覆盖层。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是用于管理版本状态的概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是用于管理审核状态的概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AssignAliasReview",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept-summary"]
    shared_alias = "共享术语"
    concept_pages[0]["aliases"] = sorted(set(concept_pages[0].get("aliases", []) + [shared_alias]))
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    primary_page_id = alias_review["candidate_page_ids"][0]

    result = run_cli(
        "review-apply",
        alias_review["review_id"],
        "assign_alias",
        "--primary-page-id", primary_page_id,
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    assert result["action"] == "assign_alias"
    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert shared_alias in overrides["page_aliases"][primary_page_id]["aliases"]


def test_review_apply_remove_alias_clears_alias_from_overrides(tmp_path: Path) -> None:
    # remove_alias 应能把冲突 alias 从覆盖层里移掉，适合人工决定“先都别用这个别名”。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是用于管理版本状态的概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是用于管理审核状态的概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "RemoveAliasReview",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept-summary"]
    shared_alias = "共享术语"
    concept_pages[0]["aliases"] = sorted(set(concept_pages[0].get("aliases", []) + [shared_alias]))
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    primary_page_id = alias_review["candidate_page_ids"][0]
    run_cli(
        "review-apply",
        alias_review["review_id"],
        "remove_alias",
        "--primary-page-id", primary_page_id,
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    for page_id in alias_review["candidate_page_ids"]:
        assert shared_alias not in overrides["page_aliases"][page_id]["aliases"]


def test_assign_alias_persists_after_reingest_and_clears_open_alias_conflict(tmp_path: Path) -> None:
    # assign_alias 后重新 ingest，不应因为自动页面重建而把同一冲突重新打开。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AssignAliasPersistence",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept-summary"]
    shared_alias = "共享术语"
    concept_pages[0]["aliases"] = sorted(set(concept_pages[0].get("aliases", []) + [shared_alias]))
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    primary_page_id = alias_review["candidate_page_ids"][0]

    run_cli(
        "review-apply",
        alias_review["review_id"],
        "assign_alias",
        "--primary-page-id", primary_page_id,
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert shared_alias in overrides["page_aliases"][primary_page_id]["aliases"]

    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_remove_alias_persists_after_reingest(tmp_path: Path) -> None:
    # remove_alias 后再次 ingest，冲突 alias 不应重新回到人工覆盖层里。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "RemoveAliasPersistence",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept-summary"]
    shared_alias = "共享术语"
    concept_pages[0]["aliases"] = sorted(set(concept_pages[0].get("aliases", []) + [shared_alias]))
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")

    run_cli(
        "review-apply",
        alias_review["review_id"],
        "remove_alias",
        "--primary-page-id", alias_review["candidate_page_ids"][0],
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_assign_alias_keeps_existing_page_aliases(tmp_path: Path) -> None:
    # assign_alias 不应该把页面原本已有的其他 alias 一起抹掉。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AssignAliasKeepsExistingAliases",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept-summary"]
    primary_page = concept_pages[0]
    secondary_page = concept_pages[1]
    original_alias = "原有别名"
    shared_alias = "共享术语"
    primary_page["aliases"] = sorted(set(primary_page.get("aliases", []) + [original_alias, shared_alias]))
    secondary_page["aliases"] = sorted(set(secondary_page.get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    refreshed_pages_before_apply = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    primary_page_id = next(
        record["page_id"]
        for record in refreshed_pages_before_apply
        if original_alias in record.get("aliases", []) and record["page_id"] in alias_review["candidate_page_ids"]
    )

    run_cli(
        "review-apply",
        alias_review["review_id"],
        "assign_alias",
        "--primary-page-id", primary_page_id,
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    refreshed_pages = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    refreshed_primary = next(record for record in refreshed_pages if record.get("page_id") == primary_page_id)
    assert original_alias in refreshed_primary.get("aliases", [])
    assert shared_alias in refreshed_primary.get("aliases", [])


def test_query_how_to_and_compare_set_reading_pack_focus(tmp_path: Path) -> None:
    # 不同 query intent 至少应在 reading_pack 上体现出不同的关注重点。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 操作与对比\n\n"
        "步骤一：先建立来源追踪。\n\n"
        "步骤二：然后生成 claim 与 wiki 页面。\n\n"
        "Alpha 方案相比 Beta 方案更强调人工审核闭环。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "IntentFocusRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    how_to = run_cli("query", "如何建立来源追踪", "--target-dir", str(workspace_dir))
    compare = run_cli("query", "Alpha 和 Beta 的区别", "--target-dir", str(workspace_dir))

    assert how_to["intent"] == "how_to"
    assert how_to["results"][0]["reading_pack"]["focus"] == "procedural_chunks"
    assert compare["intent"] == "compare"
    assert compare["results"][0]["reading_pack"]["focus"] == "compare_claims"


def test_query_timeline_sets_timeline_focus_and_sources(tmp_path: Path) -> None:
    # timeline query 应返回时间线 focus，并把命中的 chunk 按来源做一层分组。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "timeline.md").write_text(
        "# 时间线\n\n"
        "2024 年：系统完成原始资料标准化。\n\n"
        "2025 年：系统补齐 claim 与 review 闭环。\n\n"
        "2026 年：系统增加 query intent 与 alias conflict review。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "TimelineFocusRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    timeline = run_cli("query", "系统的时间线", "--target-dir", str(workspace_dir))

    assert timeline["intent"] == "timeline"
    assert timeline["results"]
    reading_pack = timeline["results"][0]["reading_pack"]
    assert reading_pack["focus"] == "timeline_evidence"
    assert reading_pack["timeline_sources"]
