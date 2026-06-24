from __future__ import annotations

from pathlib import Path

from myagentwiki.app_services.page_render_helpers import (
    build_readable_concept_summary_text,
    build_concept_page_output,
    build_intent_page_descriptor,
    build_intent_routed_page_output,
    build_workspace_overview_page_output,
    finalize_concept_render_result,
    finalize_workspace_overview_render_result,
    prepare_concept_claim_selection,
    prepare_concept_page_context,
    prepare_concept_page_title,
    prepare_concept_render_inputs,
    prepare_workspace_overview_render_inputs,
)


def test_build_concept_page_output_renders_frontmatter_and_maintenance() -> None:
    page_text, page_record = build_concept_page_output(
        page_id="page_1",
        title="Claim",
        render_target="readable_concept",
        canonical_id="concept:claim",
        review_ids=[],
        requested_render_mode="deterministic",
        render_status="deterministic",
        stable_claim_count=1,
        source_refs=[{"source_id": "src_1", "source_path": "raw/topic.md", "claim_ids": ["cl_1"], "chunk_ids": ["chk_1"], "chunks": []}],
        semantic_frontmatter={"content_tags": ["ops"], "semantic_feature_tags": ["rules"]},
        bucket_key="claim",
        canonical_key="claim",
        canonical_display_text="Claim 是一个知识声明层。",
        render_claim_records=[{"claim_id": "cl_1", "text": "Claim 是一个知识声明层。", "claim_type": "fact", "source_ids": ["src_1"], "chunk_ids": ["chk_1"]}],
        rendered_summary_text="Claim 的摘要。",
        canonical_claim={"claim_id": "cl_1", "claim_type": "fact"},
        rendered_key_points=[],
        key_point_claims=[],
        rendered_practical_notes=[],
        practical_claims=[],
        sorted_claims=[{"claim_id": "cl_1", "text": "Claim 是一个知识声明层。", "claim_type": "fact", "source_ids": ["src_1"], "chunk_ids": ["chk_1"]}],
        source_pages=[],
        page_rel_path=Path("wiki/concepts/page_1/Claim.md"),
        format_claim_reference=lambda path, claim_record: f"`{claim_record['claim_id']}`",
        format_claim_type_label=lambda claim_type: f"`{claim_type}`",
        render_claim_as_sentence=lambda claim_record, title: claim_record.get("text", ""),
        format_source_page_label=lambda path, source_page: source_page["title"],
        format_workspace_file_reference=lambda path, source_path: f"`{source_path}`",
        format_source_page_meta=lambda source_page, source_ref: f"source=`{source_ref['source_id']}`",
        format_chunk_reference=lambda path, source_id, chunk_ref: f"`{chunk_ref['chunk_id']}`",
        append_frontmatter_list=lambda lines, key, values: lines.extend([f"{key}:"] + [f'  - "{value}"' for value in values]),
        utc_now_iso=lambda: "2026-06-24T00:00:00+00:00",
        title_quality="exact",
        aliases=["知识声明层"],
    )

    assert 'content_tags:' in page_text
    assert 'semantic_feature_tags:' in page_text
    assert "## 维护状态 / Maintenance" in page_text
    assert page_record["content_tags"] == ["ops"]
    assert page_record["semantic_feature_tags"] == ["rules"]
    assert page_record["aliases"] == ["知识声明层"]


def test_build_intent_routed_page_output_renders_duty_metadata_section() -> None:
    page_text, page_record = build_intent_routed_page_output(
        page_id="page_duty_1",
        title="平台运营组",
        page_intent="duty",
        canonical_id="duty:平台运营组",
        review_ids=[],
        claim_records=[
            {
                "claim_id": "cl_1",
                "text": "平台运营组负责平台系统配置。",
                "source_refs": [{"source_id": "src_1", "source_path": "raw/org.md", "section_title": "平台运营组"}],
            }
        ],
        source_refs=[{"source_id": "src_1", "source_path": "raw/org.md"}],
        source_pages=[],
        semantic_frontmatter={"content_tags": [], "semantic_feature_tags": ["metadata_fact"]},
        summary="职责摘要。",
        section_title="职责要点 / Duties",
        page_rel_path=Path("wiki/duties/page_duty_1/平台运营组.md"),
        format_source_page_label=lambda path, source_page: source_page["title"],
        format_workspace_file_reference=lambda path, source_path: f"`{source_path}`",
        render_claim_as_sentence=lambda claim_record, title: claim_record.get("text", ""),
        format_claim_reference=lambda path, claim_record: f"`{claim_record['claim_id']}`",
        append_frontmatter_list=lambda lines, key, values: lines.extend([f"{key}:"] + [f'  - "{value}"' for value in values]),
        utc_now_iso=lambda: "2026-06-24T00:00:00+00:00",
    )

    assert "## 结构元信息 / Structured Metadata" in page_text
    assert "- 对象: `平台运营组`" in page_text
    assert page_record["page_intent"] == "duty"
    assert page_record["semantic_feature_tags"] == ["metadata_fact"]


def test_build_intent_page_descriptor_maps_page_intent_to_copy() -> None:
    descriptor = build_intent_page_descriptor(
        page_intent="reference",
        group_topic_label="参数列表",
        canonical_claim_text="参数列表用于检索",
        clean_concept_title_text=lambda text: text.strip(),
        build_concept_canonical_key=lambda title: title.lower(),
    )

    assert descriptor == {
        "title": "参数列表",
        "canonical_id": "reference:参数列表",
        "summary": "参数列表 的参考信息、规则条目与检索入口。",
        "section_title": "参考条目 / Reference Notes",
    }


def test_prepare_concept_render_inputs_collects_aliases_and_ranked_claims() -> None:
    canonical_claim = {"claim_id": "cl_1", "text": "Claim 是知识声明层。", "claim_type": "fact", "section_label": "Claim"}
    other_claim = {"claim_id": "cl_2", "text": "知识声明层用于承载结论。", "claim_type": "procedure", "section_label": "知识声明层"}
    result = prepare_concept_render_inputs(
        render_claim_records=[canonical_claim, other_claim],
        canonical_claim=canonical_claim,
        group_topic_label="Claim",
        title="Claim",
        claim_record_rank_key=lambda claim_record, topic: (2 if claim_record["claim_id"] == "cl_1" else 1, claim_record["claim_id"]),
        claim_is_topic_shell_text=lambda claim_record, topic: False,
        clean_concept_title_text=lambda text: text.strip(),
        shorten_title_text=lambda text, limit=36: text[:limit],
        extract_primary_section_label=lambda claim_record: claim_record.get("section_label", ""),
        collect_section_label_aliases=lambda claim_records: ["知识声明层"],
    )

    assert [item["claim_id"] for item in result["sorted_claims"]] == ["cl_1", "cl_2"]
    assert [item["claim_id"] for item in result["key_point_claims"]] == ["cl_2"]
    assert [item["claim_id"] for item in result["practical_claims"]] == ["cl_2"]
    assert "知识声明层" in result["aliases"]


def test_prepare_concept_claim_selection_prefers_stable_concept_claims() -> None:
    normalized_claims = [
        {"claim_id": "cl_1", "text": "Topic 定义。", "status": "stable"},
        {"claim_id": "cl_2", "text": "Topic 操作。", "status": "draft"},
    ]
    result = prepare_concept_claim_selection(
        target=Path("/tmp/workspace"),
        claim_records=[{"claim_id": "raw"}],
        prepare_page_semantic_context=lambda target, claim_records: {"claim_records": normalized_claims},
        filter_claim_records_for_concept_path=lambda claim_records: list(claim_records),
        filter_live_stable_claim_records=lambda claim_records: [claim_records[0]],
        choose_group_topic_label=lambda claim_records: "Topic",
        choose_canonical_claim=lambda claim_records, topic: claim_records[0],
    )

    assert result["claim_records"] == normalized_claims
    assert result["primary_claim_records"] == normalized_claims
    assert result["stable_claim_records"] == [normalized_claims[0]]
    assert result["render_claim_records"] == [normalized_claims[0]]
    assert result["group_topic_label"] == "Topic"
    assert result["canonical_claim"] == normalized_claims[0]


def test_prepare_concept_page_context_collects_render_metadata() -> None:
    canonical_claim = {"claim_id": "cl_1", "text": "Claim 是知识声明层。", "claim_type": "fact"}
    render_claim_records = [
        canonical_claim,
        {"claim_id": "cl_2", "text": "知识声明层用于承载结论。", "claim_type": "procedure"},
    ]
    result = prepare_concept_page_context(
        target=Path("/tmp/workspace"),
        title="Claim",
        canonical_claim=canonical_claim,
        render_claim_records=render_claim_records,
        review_records=[{"review_id": "rv_1", "claim_ids": ["cl_2"]}],
        page_records_by_id={"page_src_src_1": {"page_id": "page_src_src_1", "title": "来源页"}},
        prepare_page_semantic_context=lambda target, claim_records: {
            "claim_records": list(claim_records),
            "semantic_frontmatter": {"content_tags": ["ops"], "semantic_feature_tags": ["rules"]},
        },
        render_claim_as_sentence=lambda claim_record, title: f"{title}: {claim_record['text']}",
        collect_review_ids_for_claims=lambda claim_ids, review_records: ["rv_1"] if "cl_2" in claim_ids else [],
        collect_source_summary_pages_for_claims=lambda claim_records, page_records_by_id: [page_records_by_id["page_src_src_1"]],
        aggregate_source_refs_for_page=lambda claim_records: [{"source_id": "src_1", "source_path": "raw/topic.md"}],
        build_concept_canonical_key=lambda title: title.lower(),
    )

    assert result == {
        "render_claim_records": render_claim_records,
        "review_ids": ["rv_1"],
        "source_pages": [{"page_id": "page_src_src_1", "title": "来源页"}],
        "source_refs": [{"source_id": "src_1", "source_path": "raw/topic.md"}],
        "semantic_frontmatter": {"content_tags": ["ops"], "semantic_feature_tags": ["rules"]},
        "canonical_display_text": "Claim: Claim 是知识声明层。",
        "canonical_key": "claim",
    }


def test_prepare_concept_page_title_collects_title_quality_and_canonical_ids() -> None:
    result = prepare_concept_page_title(
        target=Path("/tmp/workspace"),
        config={"project": {"name": "demo"}},
        canonical_claim={"claim_id": "cl_1"},
        render_claim_records=[{"claim_id": "cl_1"}],
        group_topic_label="Topic",
        resolve_concept_title_candidate=lambda **kwargs: ("Topic", "exact"),
        build_concept_canonical_key=lambda title: title.lower(),
    )

    assert result == {
        "title": "Topic",
        "title_quality": "exact",
        "canonical_key": "topic",
        "canonical_id": "concept:topic",
    }


def test_build_readable_concept_summary_text_prefers_rendered_intro() -> None:
    summary = build_readable_concept_summary_text(
        title="Claim",
        canonical_claim={"claim_id": "cl_1", "text": "Claim 是知识声明层。"},
        stable_claim_records=[{"claim_id": "cl_1"}, {"claim_id": "cl_2"}],
        source_refs=[{"source_id": "src_1"}],
        render_claim_as_sentence=lambda claim_record, title: f"{title}: {claim_record['text']}",
    )

    assert summary == "Claim: Claim 是知识声明层。 当前版本基于 2 条稳定 Claim、1 个来源整理。"


def test_build_workspace_overview_page_output_renders_expected_sections() -> None:
    page_text, page_record = build_workspace_overview_page_output(
        page_id="page_overview",
        title="Demo 综述",
        render_target="overview",
        canonical_id="overview:workspace",
        review_ids=[],
        requested_render_mode="deterministic",
        render_status="deterministic",
        claim_ids=["cl_1", "cl_2"],
        source_refs=[{"source_id": "src_1", "source_path": "raw/topic.md"}],
        rendered_summary_text="这是综述摘要。",
        rendered_theme_rows=[],
        foundational_rows=[{"page_record": {"page_id": "p1", "title": "Claim"}, "summary": "基础主题", "claim_count": 2, "source_count": 1}],
        operational_rows=[],
        key_theme_rows=[{"page_record": {"page_id": "p1", "title": "Claim"}, "source_count": 1, "claim_count": 2, "review_count": 0}],
        rendered_reading_path=[],
        source_coverage_rows=[{"source_ref": {"source_path": "raw/topic.md"}, "source_page": None, "concept_titles": ["Claim"], "claim_ids": ["cl_1"], "chunk_ids": ["chk_1"]}],
        concept_pages=[{"page_id": "p1", "title": "Claim", "claim_ids": ["cl_1"], "source_refs": [{"source_id": "src_1"}], "summary": "概念摘要"}],
        semantic_frontmatter={"content_tags": ["ops"], "semantic_feature_tags": ["rules"]},
        page_rel_path=Path("wiki/overview/index.md"),
        format_page_label=lambda path, page_record: page_record["title"],
        summarize_concept_page_for_overview=lambda page_record: page_record.get("summary", ""),
        format_source_page_label=lambda path, source_page: source_page["title"],
        format_workspace_file_reference=lambda path, source_path: f"`{source_path}`",
        append_frontmatter_list=lambda lines, key, values: lines.extend([f"{key}:"] + [f'  - "{value}"' for value in values]),
        utc_now_iso=lambda: "2026-06-24T00:00:00+00:00",
    )

    assert "## 工作区综述 / Workspace Overview" in page_text
    assert "## 主题导览 / Theme Map" in page_text
    assert "## 推荐阅读路径 / Suggested Reading Path" in page_text
    assert "## 来源覆盖 / Source Coverage" in page_text
    assert "content_tags:" in page_text
    assert "semantic_feature_tags:" in page_text
    assert page_record["type"] == "overview"
    assert page_record["render_target"] == "overview"
    assert page_record["content_tags"] == ["ops"]
    assert page_record["semantic_feature_tags"] == ["rules"]


def test_prepare_workspace_overview_render_inputs_groups_theme_rows() -> None:
    result = prepare_workspace_overview_render_inputs(
        key_theme_rows=[
            {"page_record": {"page_id": "p1"}, "theme_kind": "foundational", "source_count": 1, "claim_count": 2, "review_count": 0},
            {"page_record": {"page_id": "p2"}, "theme_kind": "operational", "source_count": 3, "claim_count": 4, "review_count": 1},
        ]
    )

    assert [item["page_record"]["page_id"] for item in result["foundational_rows"]] == ["p1"]
    assert [item["page_record"]["page_id"] for item in result["operational_rows"]] == ["p2"]
    assert [item["page_record"]["page_id"] for item in result["deterministic_reading_path_rows"]] == ["p1", "p2"]


def test_finalize_workspace_overview_render_result_applies_summary_fallback() -> None:
    fallback = finalize_workspace_overview_render_result(
        assisted_render=None,
        requested_render_mode="llm_assisted",
        summary_text="默认摘要",
    )
    assisted = finalize_workspace_overview_render_result(
        assisted_render={
            "summary": "改写摘要",
            "theme_rows": [{"text": "主题句"}],
            "reading_path": [{"text": "阅读句"}],
        },
        requested_render_mode="llm_assisted",
        summary_text="默认摘要",
    )

    assert fallback == {
        "rendered_summary_text": "默认摘要",
        "rendered_theme_rows": [],
        "rendered_reading_path": [],
        "render_status": "deterministic_fallback",
    }
    assert assisted == {
        "rendered_summary_text": "改写摘要",
        "rendered_theme_rows": [{"text": "主题句"}],
        "rendered_reading_path": [{"text": "阅读句"}],
        "render_status": "llm_assisted",
    }


def test_finalize_concept_render_result_applies_summary_and_bullets_fallback() -> None:
    fallback = finalize_concept_render_result(
        assisted_render=None,
        requested_render_mode="llm_assisted",
        summary_text="默认摘要",
    )
    assisted = finalize_concept_render_result(
        assisted_render={
            "summary": "改写摘要",
            "key_points": [{"text": "关键句"}],
            "practical_notes": [{"text": "提示句"}],
        },
        requested_render_mode="llm_assisted",
        summary_text="默认摘要",
    )

    assert fallback == {
        "rendered_summary_text": "默认摘要",
        "rendered_key_points": [],
        "rendered_practical_notes": [],
        "render_status": "deterministic_fallback",
    }
    assert assisted == {
        "rendered_summary_text": "改写摘要",
        "rendered_key_points": [{"text": "关键句"}],
        "rendered_practical_notes": [{"text": "提示句"}],
        "render_status": "llm_assisted",
    }
