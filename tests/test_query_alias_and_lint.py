from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


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


def run_cli_expect_exit(*args: str, expected_exit_code: int, cwd: Path | None = None) -> dict:
    command = [sys.executable, "-m", "myagentwiki.cli", *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == expected_exit_code, completed.stdout or completed.stderr
    return json.loads(completed.stdout)


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def configure_llm_assisted_readable_concept(workspace_dir: Path, script_path: Path) -> None:
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "rendering:\n"
        + "  readable_concept:\n"
        + '    mode: "llm_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{script_path}"\n'
        + "    timeout_seconds: 20\n",
        encoding="utf-8",
    )


def configure_llm_assisted_overview(workspace_dir: Path, script_path: Path) -> None:
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "rendering:\n"
        + "  overview:\n"
        + '    mode: "llm_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{script_path}"\n'
        + "    timeout_seconds: 20\n",
        encoding="utf-8",
    )


def create_workspace_with_two_concepts(tmp_path: Path, project_name: str) -> Path:
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
        "--source-dir", str(source_dir),
        "--project-name", project_name,
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim_ids = [
        record["claim_id"]
        for record in claim_records
        if record.get("claim_type") == "definition"
    ]
    assert len(definition_claim_ids) >= 2
    for claim_id in definition_claim_ids:
        run_cli(
            "claim-set-status",
            claim_id,
            "stable",
            "--target-dir", str(workspace_dir),
        )
    return workspace_dir


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


def test_query_answer_ready_returns_agent_consumable_summary(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerReadyQueryRegression")

    result = run_cli(
        "query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert result["query_contract_version"] == "query_answer_handoff/v1"
    assert result["selected_result"]["title"]
    assert result["selected_result"]["ready_state"] == "summary_ready"
    assert result["agent_brief"]["answer_mode"] == "summary_first"
    assert result["agent_brief"]["fallback_action"] == "answer_from_summary_and_claims"
    assert result["answer_context"]["page_summary"]
    assert result["answer_context"]["key_claims"]


def test_answer_query_matches_query_answer_ready_view(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryAliasRegression")

    answer_ready_from_query = run_cli(
        "query",
        "Claim 和 Chunk 的区别",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
        "--reading-depth", "deep",
    )
    answer_ready_from_alias = run_cli(
        "answer-query",
        "Claim 和 Chunk 的区别",
        "--target-dir", str(workspace_dir),
        "--reading-depth", "deep",
    )

    assert answer_ready_from_alias == answer_ready_from_query


def test_answer_query_prompt_format_returns_prompt_text(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryPromptRegression")

    result = run_cli(
        "answer-query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--format", "prompt",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert "prompt_text" in result
    assert "## Query" in result["prompt_text"]
    assert "## Answer Instruction" in result["prompt_text"]
    assert "user_query: 什么是 Claim" in result["prompt_text"]


def test_query_answer_ready_prompt_matches_answer_query_prompt(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "QueryAnswerReadyPromptParity")

    from_query = run_cli(
        "query",
        "这个结论的来源证据是什么",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
        "--format", "prompt",
        "--reading-depth", "deep",
    )
    from_alias = run_cli(
        "answer-query",
        "这个结论的来源证据是什么",
        "--target-dir", str(workspace_dir),
        "--format", "prompt",
        "--reading-depth", "deep",
    )

    assert from_query == from_alias


def test_answer_query_messages_format_returns_api_ready_messages(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryMessagesRegression")

    result = run_cli(
        "answer-query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--format", "messages",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert "messages" in result
    assert len(result["messages"]) == 2
    assert result["messages"][0]["role"] == "system"
    assert result["messages"][1]["role"] == "user"
    assert "## Query" in result["messages"][1]["content"]


def test_answer_query_chatml_format_returns_chatml_and_messages(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryChatMLRegression")

    result = run_cli(
        "answer-query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--format", "chatml",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert "messages" in result
    assert "chatml_text" in result
    assert "<|im_start|>system" in result["chatml_text"]
    assert "<|im_start|>user" in result["chatml_text"]


def test_query_answer_ready_messages_matches_answer_query_messages(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "QueryAnswerReadyMessagesParity")

    from_query = run_cli(
        "query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
        "--format", "messages",
    )
    from_alias = run_cli(
        "answer-query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--format", "messages",
    )

    assert from_query == from_alias


def test_answer_query_no_match_returns_fallback_brief(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryNoMatchRegression")

    result = run_cli(
        "answer-query",
        "完全不存在的主题 xyz",
        "--target-dir", str(workspace_dir),
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert result["selected_result"]["ready_state"] == "answer_with_uncertainty"
    assert result["agent_brief"]["fallback_action"] in {"answer_with_uncertainty", "broaden_or_rephrase_query"}
    assert result["agent_brief"]["should_surface_uncertainty"] is True
    assert result["agent_brief"]["risk_flags"]


def test_claim_set_status_stable_generates_readable_concept_page(tmp_path: Path) -> None:
    # 第二阶段里，stable claim 应额外生成更适合人阅读的 concept 页，
    # 同时保留原来的 concept-summary 证据页。
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
        "--project-name", "ReadableConceptGeneration",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    concept_summary_page = next(record for record in page_records if record.get("type") == "concept-summary")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")

    assert readable_concept_page["canonical_id"] == concept_summary_page["canonical_id"]
    assert readable_concept_page["status"] == "stable"
    assert readable_concept_page["page_path"].endswith("/index.md")
    assert readable_concept_page["claim_ids"] == [definition_claim["claim_id"]]

    page_text = (workspace_dir / readable_concept_page["page_path"]).read_text(encoding="utf-8")
    assert "# 知识声明层" in page_text
    assert "## 摘要 / Summary" in page_text
    assert "## 关键要点 / Key Points" in page_text
    assert "当前版本基于 1 条稳定 Claim、1 个来源整理。" in page_text


def test_query_definition_prefers_readable_concept_once_stable_page_exists(tmp_path: Path) -> None:
    # 一旦 stable claim 产出了 concept 页，定义类问题应优先命中可读页，而不是证据摘要页。
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
        "--project-name", "ReadableConceptQueryPreference",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    result = run_cli("query", "什么是知识声明层", "--target-dir", str(workspace_dir))

    assert result["intent"] == "definition"
    assert result["results"]
    assert result["results"][0]["type"] == "concept"
    assert result["results"][0]["status"] == "stable"
    assert result["results"][0]["intent_boost_reason"] == "intent_definition_prefers_readable_concept"
    assert any(item["type"] == "concept-summary" for item in result["results"])


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


def test_concept_page_title_keeps_full_date_headings(tmp_path: Path) -> None:
    # 日期标题不应被当作“编号前缀”裁成 05-24 这种残缺标题。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 2026-05-24\n\n"
        "<!-- turn_id: t001, speaker: Alice, time: 10:03 -->\n\n"
        "Alice: 我们需要先定义 source_id。\n\n"
        "Bob: 然后再确定 chunk_id 的生成规则。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "DateHeadingRegression",
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

    assert concept_page["title"] == "2026-05-24"
    assert concept_page["page_path"].endswith("/2026-05-24.md")


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


def test_concept_page_prefers_standalone_definition_over_dependent_clause(tmp_path: Path) -> None:
    # 概念页的代表陈述应优先选择可独立理解的定义句，而不是被长句切出来的从句残片。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# LLM Wiki\n\n"
        "**一种利用 LLM 构建个人知识库的模式。**\n\n"
        "这是一份思路文件，旨在复制粘贴到你自己的 LLM Agent 中"
        "（如 OpenAI Codex、Claude Code、OpenCode / Pi 等）。"
        "它的目标是传达高层思想，具体细节由你的 Agent 与你共同构建。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "CanonicalClaimReadabilityRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(
        record
        for record in page_records
        if record.get("type") == "concept-summary" and record.get("canonical_id") == "concept:llm_wiki"
    )

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "代表陈述: LLM Wiki 一种利用 LLM 构建个人知识库的模式" in page_text
    assert "## 核心陈述 / Canonical Claim" in page_text
    assert "旨在复制粘贴到你自己的 LLM Agent 中" in page_text
    assert "具体细节由你的 Agent 与你共同构建" in page_text


def test_concept_page_prefers_claim_aligned_with_section_topic(tmp_path: Path) -> None:
    # 同一来源里即使出现共享词汇的其他陈述，概念页代表陈述也应优先贴合当前 section 主题。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# BM25 和向量检索的差异\n\n"
        "BM25 和向量检索的差异在于，BM25 主要依赖关键词匹配和词频统计。\n\n"
        "向量检索主要依赖语义相似度，因此更适合补充语义召回。\n\n"
        "这句话语义上仍然是在问 raw/wiki 分离，但字面词不完全一样。这时向量检索可以补充召回。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ConceptTopicAlignmentRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(
        record
        for record in page_records
        if record.get("type") == "concept-summary" and record.get("canonical_id") == "concept:bm25_和向量检索的差异"
    )

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "# BM25 和向量检索的差异" in page_text
    assert "代表陈述: BM25 和向量检索的差异在于，BM25 主要依赖关键词匹配和词频统计" in page_text
    assert "代表陈述: 这句话语义上仍然是在问 raw/wiki 分离" not in page_text


def test_concept_page_claim_type_label_is_not_rendered_as_markdown_link(tmp_path: Path) -> None:
    # claim_type 应显示为代码标签，而不是 [definition] 这种容易被查看器误判为链接的写法。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Chunk Lint\n\n"
        "Chunk Lint 检查 chunk 是否可用： chunk 是否超过 hard max tokens。\n\n"
        "chunk 是否过短且未合并。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ClaimTypeLabelRegression",
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

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "`definition`" in page_text
    assert "[definition]" not in page_text


def test_concept_page_links_claim_ids_to_claim_json_files(tmp_path: Path) -> None:
    # 概念页里的 claim_id 应该能直接跳到 claims/<claim_id>.json，方便继续下钻证据链。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Chunk Lint\n\n"
        "Chunk Lint 检查 chunk 是否可用： chunk 是否超过 hard max tokens。\n\n"
        "chunk 是否过短且未合并。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ClaimReferenceRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(record for record in page_records if record.get("type") == "concept-summary")
    concept_page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")

    claim_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    linked_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    assert linked_claim["claim_file_path"] == f"claims/{linked_claim['claim_id']}.json"
    assert f"[`{linked_claim['claim_id']}`](../../../claims/{linked_claim['claim_id']}.json)" in concept_page_text


def test_concept_page_links_source_pages_raw_sources_and_chunks(tmp_path: Path) -> None:
    # 概念页应能继续下钻到来源摘要页、原始来源文件和对应 chunk 文件，
    # 并以更适合人阅读的标签呈现这些入口。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    source_path = source_dir / "topic.md"
    source_path.write_text(
        "# Chunk Lint\n\n"
        "Chunk Lint 检查 chunk 是否可用： chunk 是否超过 hard max tokens。\n\n"
        "chunk 是否过短且未合并。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "SourceEvidenceLinkRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(record for record in page_records if record.get("type") == "concept-summary")
    source_page = next(record for record in page_records if record.get("type") == "source-summary")
    concept_page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")

    claim_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    linked_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    source_ref = linked_claim["source_refs"][0]
    concept_page_path = Path(concept_page["page_path"])
    expected_source_page_link = quote(
        os.path.relpath(source_page["page_path"], start=concept_page_path.parent).replace(os.sep, "/"),
        safe="/._-~",
    )
    expected_source_path_link = quote(
        os.path.relpath(source_ref["source_path"], start=concept_page_path.parent).replace(os.sep, "/"),
        safe="/._-~",
    )
    expected_chunk_link = quote(
        os.path.relpath(f"chunks/{source_ref['source_id']}.jsonl", start=concept_page_path.parent).replace(os.sep, "/"),
        safe="/._-~",
    )

    assert "来源摘要页:" in concept_page_text
    assert "原始文件:" in concept_page_text
    assert "证据切块:" in concept_page_text
    assert f"[{source_page['title']}]({expected_source_page_link})" in concept_page_text
    assert f"[`{source_ref['source_path']}`]({expected_source_path_link})" in concept_page_text
    assert f"[`{source_ref['chunk_id']}`]({expected_chunk_link})" in concept_page_text


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
    assert result["contract_version"] == "query_answer_handoff/v1"
    assert top_result["reading_pack"]["contract_version"] == "query_answer_handoff/v1"
    assert top_result["reading_pack"]["query"]["intent"] == "evidence"
    assert top_result["reading_pack"]["retrieval_context"]["focus"] == "source_evidence"
    assert top_result["reading_pack"]["answer_guardrails"]["must_read_sources"] is True
    assert top_result["reading_pack"]["answer_guardrails"]["cite_expectation"] == "strong"
    assert top_result["reading_pack"]["answer_handoff"]["answer_mode"] == "sources_first"
    assert top_result["reading_pack"]["answer_handoff"]["should_cite_sources"] is True
    assert top_result["reading_pack"]["answer_handoff"]["required_evidence_paths"][-1] == "evidence_context.source_trail"


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


def test_lint_allows_concept_and_concept_summary_to_share_canonical_id(tmp_path: Path) -> None:
    # 第二阶段会让 concept 与 concept-summary 同时在线；
    # lint 应认可这种“同 canonical、不同页型”的页面家族结构。
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
        "--project-name", "CanonicalPageFamilyRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    shared_canonical_pages = [
        record
        for record in page_records
        if record.get("canonical_id") == "concept:知识声明层"
    ]
    assert {record["type"] for record in shared_canonical_pages} == {"concept", "concept-summary"}

    result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {item["name"]: item for item in result["checks"]}

    assert result["summary"]["ok"] is True
    assert checks["canonical_page_family_valid"]["ok"] is True


def test_llm_assisted_readable_concept_page_uses_grounded_rewrite_when_enabled(tmp_path: Path) -> None:
    # 第三阶段允许对 concept 阅读页做 LLM 辅助润色，
    # 但只应在显式开启配置后生效，而且改写内容必须仍然绑在 stable claim 上。
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
        "--project-name", "LLMAssistedReadableConcept",
        "--target-dir", str(workspace_dir),
    )

    rewriter_script = tmp_path / "rewrite_readable_concept.py"
    rewriter_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "payload = json.load(sys.stdin)\n"
        "canonical = payload['canonical_claim']\n"
        "claim_id = canonical['claim_id']\n"
        "title = payload['title']\n"
        "practical_claim_id = next(\n"
        "    (\n"
        "        item['claim_id']\n"
        "        for item in payload['stable_claims']\n"
        "        if '用于承载可追踪、可合并、可审计的结论' in item['text']\n"
        "    ),\n"
        "    claim_id,\n"
        ")\n"
        "json.dump({\n"
        "    'summary': f'{title} 是位于 chunk 与 wiki 之间的独立知识声明层，可作为知识沉淀的稳定阅读入口。',\n"
        "    'key_points': [\n"
        "        {\n"
        "            'claim_id': claim_id,\n"
        "            'text': f'{title} 是位于 chunk 与 wiki 之间的独立知识声明层。',\n"
        "        }\n"
        "    ],\n"
        "    'practical_notes': [\n"
        "        {\n"
        "            'claim_id': practical_claim_id,\n"
        "            'text': f'{title} 用于承载可追踪、可合并、可审计的结论。',\n"
        "        }\n"
        "    ],\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_readable_concept(workspace_dir, rewriter_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    stable_claim_ids = [record["claim_id"] for record in claim_records]
    for claim_id in stable_claim_ids:
        run_cli(
            "claim-set-status",
            claim_id,
            "stable",
            "--target-dir", str(workspace_dir),
        )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")
    page_text = (workspace_dir / readable_concept_page["page_path"]).read_text(encoding="utf-8")

    assert readable_concept_page["summary"] == "知识声明层 是位于 chunk 与 wiki 之间的独立知识声明层，可作为知识沉淀的稳定阅读入口。"
    assert "知识声明层 是位于 chunk 与 wiki 之间的独立知识声明层，可作为知识沉淀的稳定阅读入口。" in page_text
    assert "- 知识声明层 是位于 chunk 与 wiki 之间的独立知识声明层。" in page_text
    assert "- 知识声明层 用于承载可追踪、可合并、可审计的结论。" in page_text


def test_llm_assisted_readable_concept_page_falls_back_when_rewrite_is_ungrounded(tmp_path: Path) -> None:
    # 如果 LLM 输出没有绑定到允许的 claim 或内容明显跑偏，应自动回退到第二阶段的确定性模板。
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
        "--project-name", "LLMAssistedFallback",
        "--target-dir", str(workspace_dir),
    )

    rewriter_script = tmp_path / "rewrite_readable_concept_bad.py"
    rewriter_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "json.load(sys.stdin)\n"
        "json.dump({\n"
        "    'summary': '这是一个完全脱离 claim 的新说法。',\n"
        "    'key_points': [\n"
        "        {'claim_id': 'claim_fake', 'text': '这个系统主要依赖向量数据库。'}\n"
        "    ],\n"
        "    'practical_notes': [\n"
        "        {'claim_id': 'claim_fake', 'text': '应该直接跳过证据页。'}\n"
        "    ],\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_readable_concept(workspace_dir, rewriter_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")
    page_text = (workspace_dir / readable_concept_page["page_path"]).read_text(encoding="utf-8")

    assert readable_concept_page["summary"] == "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。 当前版本基于 1 条稳定 Claim、1 个来源整理。"
    assert "这是一个完全脱离 claim 的新说法。" not in page_text
    assert "这个系统主要依赖向量数据库。" not in page_text
    assert "## 关键要点 / Key Points" in page_text


def test_render_readable_concept_command_returns_render_metadata_and_page_text(tmp_path: Path) -> None:
    # 第四/五阶段把 readable concept 渲染收口成正式 CLI 命令，
    # 并进一步抽成通用 render-page 入口，便于后续接更多页面类型。
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
        "--project-name", "ReadableConceptRenderCommand",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")

    result = run_cli(
        "render-readable-concept",
        "--page-id", readable_concept_page["page_id"],
        "--target-dir", str(workspace_dir),
    )

    assert result["summary"]["page_count"] == 1
    assert result["pages"][0]["page_id"] == readable_concept_page["page_id"]
    assert result["pages"][0]["render_target"] == "readable_concept"
    assert result["pages"][0]["render_mode"] == "llm_assisted"
    assert result["pages"][0]["render_status"] == "deterministic_fallback"
    assert "# 知识声明层" in result["page_text"]
    assert "## 摘要 / Summary" in result["page_text"]


def test_render_page_command_supports_generic_render_target_selector(tmp_path: Path) -> None:
    # 第五阶段开始，通用 render-page 应能按 render_target 统一查看页面，
    # 而不是每种页面类型都各开一个平行命令。
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
        "--project-name", "GenericRenderPageCommand",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    result = run_cli(
        "render-page",
        "--render-target", "readable_concept",
        "--claim-id", definition_claim["claim_id"],
        "--target-dir", str(workspace_dir),
    )

    assert result["render_target"] == "readable_concept"
    assert result["summary"]["page_count"] == 1
    assert result["pages"][0]["render_target"] == "readable_concept"
    assert result["pages"][0]["canonical_id"] == "concept:知识声明层"
    assert "# 知识声明层" in result["page_text"]


def test_stable_multi_concept_workspace_generates_overview_page(tmp_path: Path) -> None:
    # 第六阶段引入 overview，先验证当工作区里已有多个稳定可读概念页时，
    # 系统会自动补出一个工作区级综述入口。
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "WorkspaceOverviewGeneration")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    overview_page = next(record for record in page_records if record.get("type") == "overview")

    assert overview_page["render_target"] == "overview"
    assert overview_page["status"] == "stable"
    assert overview_page["canonical_id"] == "overview:workspace"
    assert overview_page["page_path"] == "wiki/overview/index.md"
    assert len(overview_page["claim_ids"]) >= 2

    page_text = (workspace_dir / overview_page["page_path"]).read_text(encoding="utf-8")
    assert "## 工作区综述 / Workspace Overview" in page_text
    assert "## 主题导览 / Theme Map" in page_text
    assert "## 推荐阅读路径 / Suggested Reading Path" in page_text
    assert "## 来源覆盖 / Source Coverage" in page_text
    assert "来源页:" in page_text
    assert "Claim" in page_text
    assert "Chunk" in page_text


def test_render_page_command_supports_overview_render_target(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "WorkspaceOverviewRender")

    result = run_cli(
        "render-page",
        "--render-target", "overview",
        "--canonical-id", "overview:workspace",
        "--target-dir", str(workspace_dir),
    )

    assert result["render_target"] == "overview"
    assert result["summary"]["page_count"] == 1
    assert result["pages"][0]["render_target"] == "overview"
    assert result["pages"][0]["canonical_id"] == "overview:workspace"
    assert "## 工作区综述 / Workspace Overview" in result["page_text"]


def test_query_overview_intent_prefers_overview_page_for_macro_question(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "WorkspaceOverviewQuery")

    result = run_cli("query", "这个工作区主要讲什么", "--target-dir", str(workspace_dir))

    assert result["intent"] == "overview"
    assert result["results"]
    assert result["results"][0]["type"] == "overview"
    assert result["results"][0]["canonical_id"] == "overview:workspace"
    assert result["results"][0]["intent_boost_reason"] == "intent_overview_prefers_overview_page"
    assert result["results"][0]["reading_pack"]["focus"] == "workspace_overview"


def test_llm_assisted_overview_page_uses_grounded_rewrite_when_enabled(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "LLMAssistedOverview")

    rewriter_script = tmp_path / "rewrite_overview.py"
    rewriter_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "payload = json.load(sys.stdin)\n"
        "first_theme = payload['theme_rows'][0]\n"
        "second_theme = payload['theme_rows'][1]\n"
        "json.dump({\n"
        "    'summary': '这个工作区主要围绕 Claim 和 Chunk 两个稳定主题展开。',\n"
        "    'theme_rows': [\n"
        "        {\n"
        "            'page_id': first_theme['page_id'],\n"
        "            'text': '这个主题解释了 Claim 作为独立知识声明层的定位。',\n"
        "        },\n"
        "        {\n"
        "            'page_id': second_theme['page_id'],\n"
        "            'text': '这个主题说明了 Chunk 作为证据切片单元的作用。',\n"
        "        },\n"
        "    ],\n"
        "    'reading_path': [\n"
        "        {\n"
        "            'page_id': first_theme['page_id'],\n"
        "            'text': '如果你想先建立全局认识，先读 Claim 主题。',\n"
        "        },\n"
        "        {\n"
        "            'page_id': second_theme['page_id'],\n"
        "            'text': '如果你想继续追证据结构，再看 Chunk 主题。',\n"
        "        },\n"
        "    ],\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_overview(workspace_dir, rewriter_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    overview_page = next(record for record in page_records if record.get("type") == "overview")
    page_text = (workspace_dir / overview_page["page_path"]).read_text(encoding="utf-8")

    assert overview_page["render_status"] == "llm_assisted"
    assert overview_page["summary"] == "这个工作区主要围绕 Claim 和 Chunk 两个稳定主题展开。"
    assert "这个主题解释了 Claim 作为独立知识声明层的定位。" in page_text
    assert "如果你想先建立全局认识，先读 Claim 主题。" in page_text
    assert "## 改写回绑 / Rewrite Traceability" in page_text
    assert "<summary>查看 overview 改写句与其回绑页面</summary>" in page_text
    assert "主题导览句: `这个主题解释了 Claim 作为独立知识声明层的定位。`" in page_text
    assert "推荐阅读句: `如果你想先建立全局认识，先读 Claim 主题。`" in page_text


def test_llm_assisted_overview_page_falls_back_when_rewrite_is_ungrounded(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "LLMAssistedOverviewFallback")

    rewriter_script = tmp_path / "rewrite_overview_bad.py"
    rewriter_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "json.load(sys.stdin)\n"
        "json.dump({\n"
        "    'summary': '这个工作区的核心是向量数据库和外部缓存。',\n"
        "    'theme_rows': [\n"
        "        {\n"
        "            'page_id': 'page_fake',\n"
        "            'text': '这个主题主要讲多代理调度系统。',\n"
        "        }\n"
        "    ],\n"
        "    'reading_path': [\n"
        "        {\n"
        "            'page_id': 'page_fake',\n"
        "            'text': '建议先读缓存系统设计。',\n"
        "        }\n"
        "    ],\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_overview(workspace_dir, rewriter_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    overview_page = next(record for record in page_records if record.get("type") == "overview")
    page_text = (workspace_dir / overview_page["page_path"]).read_text(encoding="utf-8")

    assert overview_page["render_status"] == "deterministic_fallback"
    assert "这个工作区的核心是向量数据库和外部缓存。" not in page_text
    assert "建议先读缓存系统设计。" not in page_text
    assert "## 推荐阅读路径 / Suggested Reading Path" in page_text


def test_lint_accepts_generated_overview_page_render_metadata(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "WorkspaceOverviewLint")

    result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {item["name"]: item for item in result["checks"]}

    assert result["summary"]["ok"] is True
    assert checks["overview_render_metadata_present"]["ok"] is True
    assert checks["overview_pages_grounded"]["ok"] is True
    assert checks["alias_conflicts_absent"]["ok"] is True


def test_lint_flags_overview_page_when_manual_edit_breaks_grounding(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "OverviewGroundingLint")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    overview_page = next(record for record in page_records if record.get("type") == "overview")
    page_path = workspace_dir / overview_page["page_path"]
    page_text = page_path.read_text(encoding="utf-8")
    page_text = page_text.replace(
        "Claim、Chunk 是当前工作区里已经沉淀出的稳定主题。",
        "这份综述主要讲向量数据库、缓存和多代理调度。",
    )
    page_path.write_text(page_text, encoding="utf-8")

    result = run_cli_expect_exit("lint", "--target-dir", str(workspace_dir), expected_exit_code=1)
    checks = {item["name"]: item for item in result["checks"]}

    assert result["summary"]["ok"] is False
    assert checks["overview_pages_grounded"]["ok"] is False


def test_lint_flags_readable_concept_page_when_manual_edit_breaks_grounding(tmp_path: Path) -> None:
    # 第四阶段 lint 应能发现可读页被手工改坏、开始脱离其 claim 证据边界的情况。
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
        "--project-name", "ReadableConceptGroundingLint",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")
    page_path = workspace_dir / readable_concept_page["page_path"]
    page_text = page_path.read_text(encoding="utf-8")
    page_text = page_text.replace(
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。 当前版本基于 1 条稳定 Claim、1 个来源整理。",
        "这个页面现在主要讲向量数据库和外部缓存系统。",
    )
    page_path.write_text(page_text, encoding="utf-8")

    result = run_cli_expect_exit("lint", "--target-dir", str(workspace_dir), expected_exit_code=1)
    checks = {item["name"]: item for item in result["checks"]}

    assert result["summary"]["ok"] is False
    assert checks["readable_concept_pages_grounded"]["ok"] is False
    assert "summary_not_grounded" in checks["readable_concept_pages_grounded"]["details"]


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


def test_review_apply_text_output_includes_absolute_workspace_path(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReviewApplyTextOutput",
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

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "myagentwiki.cli",
            "review-apply",
            alias_review["review_id"],
            "assign_alias",
            "--primary-page-id", primary_page_id,
            "--alias-value", shared_alias,
            "--target-dir", str(workspace_dir),
        ],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"Workspace: {workspace_dir.resolve()}" in completed.stdout


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
    assert how_to["results"][0]["reading_pack"]["answer_guardrails"]["must_read_chunks"] is True
    assert how_to["results"][0]["reading_pack"]["answer_guardrails"]["can_answer_from_summary_only"] is False
    assert how_to["results"][0]["reading_pack"]["answer_handoff"]["answer_mode"] == "chunks_first"
    assert compare["intent"] == "compare"
    assert compare["results"][0]["reading_pack"]["focus"] == "compare_claims"
    assert compare["results"][0]["reading_pack"]["answer_guardrails"]["must_read_claims"] is True
    assert compare["results"][0]["reading_pack"]["answer_guardrails"]["must_read_sources"] is False
    assert compare["results"][0]["reading_pack"]["answer_handoff"]["answer_mode"] == "claims_first"


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
    assert reading_pack["answer_guardrails"]["must_read_sources"] is True
    assert reading_pack["answer_guardrails"]["cite_expectation"] == "strong"
    assert reading_pack["answer_handoff"]["answer_mode"] == "sources_first"
    assert "evidence_context.timeline_sources" in reading_pack["answer_handoff"]["required_evidence_paths"]


def test_query_reading_depth_deep_returns_thicker_reading_pack(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识沉淀流程\n\n"
        "如何生成 wiki 页面：第一步先标准化原始资料。\n\n"
        "第二步再切 chunk，确保来源可追踪。\n\n"
        "第三步继续抽取 claim，沉淀稳定结论。\n\n"
        "第四步最后生成 wiki 页面，并检查阅读入口。\n\n"
        "补充说明：review 流程用于处理冲突与不确定项。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReadingDepthRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    standard = run_cli("query", "如何生成 wiki 页面", "--target-dir", str(workspace_dir))
    deep = run_cli("query", "如何生成 wiki 页面", "--target-dir", str(workspace_dir), "--reading-depth", "deep")

    assert standard["reading_depth"] == "standard"
    assert standard["reading_depth_limits"] == {"claim_limit": 3, "chunk_limit": 2}
    assert standard["results"][0]["reading_pack"]["reading_depth"] == "standard"

    assert deep["reading_depth"] == "deep"
    assert deep["reading_depth_limits"] == {"claim_limit": 6, "chunk_limit": 5}
    assert deep["results"][0]["reading_pack"]["reading_depth"] == "deep"
    assert len(deep["results"][0]["reading_pack"]["matched_chunks"]) >= len(standard["results"][0]["reading_pack"]["matched_chunks"])
    assert standard["results"][0]["reading_pack"]["source_trail"] == []
    assert deep["results"][0]["reading_pack"]["source_trail"]
    assert deep["results"][0]["reading_pack"]["source_trail"][0]["source_path"].endswith("topic.md")


def test_query_definition_contract_exposes_page_and_guardrails(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "DefinitionContractRegression")

    result = run_cli("query", "什么是 Claim", "--target-dir", str(workspace_dir))

    assert result["contract_version"] == "query_answer_handoff/v1"
    assert result["results"]
    reading_pack = result["results"][0]["reading_pack"]
    assert reading_pack["page_context"]["title"]
    assert reading_pack["query"]["normalized_text"]
    assert reading_pack["retrieval_context"]["matched_fields"]
    assert reading_pack["evidence_context"]["matched_claims"] == reading_pack["matched_claims"]
    assert reading_pack["answer_guardrails"]["can_answer_from_summary_only"] is True
    assert reading_pack["answer_guardrails"]["must_read_sources"] is False
    assert reading_pack["answer_handoff"]["answer_mode"] == "summary_first"
    assert reading_pack["answer_handoff"]["fallback_action"] == "answer_from_summary_and_claims"


def test_query_contract_risk_flags_drive_uncertainty_handoff(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 风险回答\n\n"
        "系统需要保留待审核状态，避免把不稳定结论伪装成确定答案。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "RiskGuardrailRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    for record in page_records:
        if record.get("status") != "removed":
            record["status"] = "needs_review"
    pages_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in page_records),
        encoding="utf-8",
    )
    search_index_path = workspace_dir / "indexes" / "search_pages.jsonl"
    index_records = load_jsonl(search_index_path)
    for record in index_records:
        if record.get("status") != "removed":
            record["status"] = "needs_review"
    search_index_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in index_records),
        encoding="utf-8",
    )

    result = run_cli("query", "系统需要保留什么状态", "--target-dir", str(workspace_dir))

    reading_pack = result["results"][0]["reading_pack"]
    assert "page_needs_review" in reading_pack["answer_guardrails"]["risk_flags"]
    assert reading_pack["answer_handoff"]["should_surface_uncertainty"] is True
    assert reading_pack["answer_handoff"]["fallback_action"] == "answer_with_uncertainty"
