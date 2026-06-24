from __future__ import annotations

from pathlib import Path
from typing import Callable


def build_intent_page_descriptor(
    *,
    page_intent: str,
    group_topic_label: str,
    canonical_claim_text: str,
    clean_concept_title_text: Callable[[str], str],
    build_concept_canonical_key: Callable[[str], str],
) -> dict:
    base_title = clean_concept_title_text(group_topic_label or canonical_claim_text)

    if page_intent == "guide":
        title = base_title or "指南"
        return {
            "title": title,
            "canonical_id": f"guide:{build_concept_canonical_key(title)}",
            "summary": f"{title} 的操作步骤与执行提示。",
            "section_title": "步骤摘要 / Steps",
        }
    if page_intent == "duty":
        title = base_title or "职责"
        return {
            "title": title,
            "canonical_id": f"duty:{build_concept_canonical_key(title)}",
            "summary": f"{title} 的职责范围、结构元信息与协作边界。",
            "section_title": "职责要点 / Duties",
        }
    if page_intent == "example":
        title = base_title or "示例"
        return {
            "title": title,
            "canonical_id": f"example:{build_concept_canonical_key(title)}",
            "summary": f"{title} 的样例与案例说明。",
            "section_title": "示例内容 / Examples",
        }
    if page_intent == "reference":
        title = base_title or "参考"
        return {
            "title": title,
            "canonical_id": f"reference:{build_concept_canonical_key(title)}",
            "summary": f"{title} 的参考信息、规则条目与检索入口。",
            "section_title": "参考条目 / Reference Notes",
        }
    if page_intent == "timeline":
        title = base_title or "时间线"
        return {
            "title": title,
            "canonical_id": f"timeline:{build_concept_canonical_key(title)}",
            "summary": f"{title} 的时间顺序事实与演变节点。",
            "section_title": "时间节点 / Timeline Notes",
        }

    title = base_title or "主题"
    return {
        "title": title,
        "canonical_id": f"topic:{build_concept_canonical_key(title)}",
        "summary": f"{title} 的主题概览与相关证据入口。",
        "section_title": "主题要点 / Topic Notes",
    }


def prepare_concept_render_inputs(
    *,
    render_claim_records: list[dict],
    canonical_claim: dict,
    group_topic_label: str,
    title: str,
    claim_record_rank_key: Callable[[dict, str], tuple],
    claim_is_topic_shell_text: Callable[[dict, str], bool],
    clean_concept_title_text: Callable[[str], str],
    shorten_title_text: Callable[[str], str],
    extract_primary_section_label: Callable[[dict], str],
    collect_section_label_aliases: Callable[[list[dict]], list[str]],
) -> dict:
    sorted_claims = sorted(
        render_claim_records,
        key=lambda item: claim_record_rank_key(item, group_topic_label),
        reverse=True,
    )
    supporting_claims = [
        claim_record
        for claim_record in sorted_claims
        if claim_record["claim_id"] != canonical_claim["claim_id"]
        and not claim_is_topic_shell_text(claim_record, group_topic_label)
    ]
    key_point_claims = supporting_claims[:4]
    practical_claims = [
        claim_record
        for claim_record in supporting_claims
        if claim_record.get("claim_type") in {"comparison", "causal", "procedure", "warning", "evaluation"}
    ][:3]
    aliases = [
        alias
        for alias in {
            clean_concept_title_text(shorten_title_text(claim_record["text"], limit=36))
            for claim_record in render_claim_records
            if claim_record["text"] != canonical_claim["text"]
        }
        if alias
    ]
    section_alias = extract_primary_section_label(canonical_claim)
    if section_alias and section_alias != title:
        aliases.append(section_alias)
    aliases.extend(collect_section_label_aliases(render_claim_records))
    return {
        "sorted_claims": sorted_claims,
        "key_point_claims": key_point_claims,
        "practical_claims": practical_claims,
        "aliases": aliases,
    }


def prepare_concept_claim_selection(
    *,
    target: Path,
    claim_records: list[dict],
    prepare_page_semantic_context: Callable[[Path, list[dict]], dict],
    filter_claim_records_for_concept_path: Callable[[list[dict]], list[dict]],
    filter_live_stable_claim_records: Callable[[list[dict]], list[dict]],
    choose_group_topic_label: Callable[[list[dict]], str],
    choose_canonical_claim: Callable[[list[dict], str], dict],
) -> dict:
    semantic_context = prepare_page_semantic_context(target, claim_records)
    normalized_claim_records = semantic_context["claim_records"]
    concept_claim_records = filter_claim_records_for_concept_path(normalized_claim_records)
    primary_claim_records = concept_claim_records or normalized_claim_records
    stable_claim_records = filter_live_stable_claim_records(primary_claim_records)
    render_claim_records = stable_claim_records or primary_claim_records
    group_topic_label = choose_group_topic_label(render_claim_records)
    canonical_claim = choose_canonical_claim(render_claim_records, group_topic_label)
    return {
        "claim_records": normalized_claim_records,
        "primary_claim_records": primary_claim_records,
        "stable_claim_records": stable_claim_records,
        "render_claim_records": render_claim_records,
        "group_topic_label": group_topic_label,
        "canonical_claim": canonical_claim,
    }


def prepare_concept_page_title(
    *,
    target: Path,
    config: dict,
    canonical_claim: dict,
    render_claim_records: list[dict],
    group_topic_label: str,
    resolve_concept_title_candidate: Callable[..., tuple[str, str]],
    build_concept_canonical_key: Callable[[str], str],
) -> dict:
    title, title_quality = resolve_concept_title_candidate(
        target=target,
        config=config,
        canonical_claim=canonical_claim,
        claim_records=render_claim_records,
        preferred_section_label=group_topic_label,
    )
    canonical_key = build_concept_canonical_key(title)
    return {
        "title": title,
        "title_quality": title_quality,
        "canonical_key": canonical_key,
        "canonical_id": f"concept:{canonical_key}",
    }


def prepare_concept_page_context(
    *,
    target: Path,
    title: str,
    canonical_claim: dict,
    render_claim_records: list[dict],
    review_records: list[dict],
    page_records_by_id: dict[str, dict],
    prepare_page_semantic_context: Callable[[Path, list[dict]], dict],
    render_claim_as_sentence: Callable[[dict, str], str],
    collect_review_ids_for_claims: Callable[[list[str], list[dict]], list[str]],
    collect_source_summary_pages_for_claims: Callable[[list[dict], dict[str, dict]], list[dict]],
    aggregate_source_refs_for_page: Callable[[list[dict]], list[dict]],
    build_concept_canonical_key: Callable[[str], str],
) -> dict:
    render_semantic_context = prepare_page_semantic_context(target, render_claim_records)
    normalized_claim_records = render_semantic_context["claim_records"]
    return {
        "render_claim_records": normalized_claim_records,
        "review_ids": collect_review_ids_for_claims(
            [claim_record["claim_id"] for claim_record in normalized_claim_records],
            review_records,
        ),
        "source_pages": collect_source_summary_pages_for_claims(normalized_claim_records, page_records_by_id),
        "source_refs": aggregate_source_refs_for_page(normalized_claim_records),
        "semantic_frontmatter": render_semantic_context["semantic_frontmatter"],
        "canonical_display_text": render_claim_as_sentence(canonical_claim, title),
        "canonical_key": build_concept_canonical_key(title),
    }


def build_readable_concept_summary_text(
    *,
    title: str,
    canonical_claim: dict,
    stable_claim_records: list[dict],
    source_refs: list[dict],
    render_claim_as_sentence: Callable[[dict, str], str],
) -> str:
    intro = render_claim_as_sentence(canonical_claim, title)
    if not intro:
        intro = f"{title} 目前已经沉淀出可复用的稳定结论。"
    coverage = f"当前版本基于 {len(stable_claim_records)} 条稳定 Claim、{len(source_refs)} 个来源整理。"
    return f"{intro} {coverage}".strip()


def _collect_page_claim_records(page_record: dict, claim_records_by_id: dict[str, dict]) -> list[dict]:
    return [
        claim_records_by_id[claim_id]
        for claim_id in page_record.get("claim_ids", [])
        if claim_id in claim_records_by_id
    ]


def _count_claim_types(claim_records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for claim_record in claim_records:
        claim_type = str(claim_record.get("claim_type", "unknown"))
        counts[claim_type] = counts.get(claim_type, 0) + 1
    return counts


def _overview_title_parts(page_record: dict) -> list[str]:
    title = str(page_record.get("title", "")).strip()
    if not title:
        return []
    return [part.strip() for part in title.split("/") if part.strip()]


def _overview_theme_family_key(page_record: dict) -> str:
    parts = _overview_title_parts(page_record)
    if len(parts) >= 2:
        return " / ".join(parts[:2]).lower()
    if parts:
        return parts[0].lower()
    return str(page_record.get("page_id", "")).strip().lower()


def _overview_theme_representativeness_score(
    page_record: dict,
    claim_records_by_id: dict[str, dict],
) -> tuple[int, int, int, int, str]:
    claim_records = _collect_page_claim_records(page_record, claim_records_by_id)
    claim_type_counts = _count_claim_types(claim_records)
    foundational_signal = sum(
        claim_type_counts.get(claim_type, 0)
        for claim_type in {"definition", "fact"}
    )
    operational_signal = sum(
        claim_type_counts.get(claim_type, 0)
        for claim_type in {"procedure", "warning", "comparison", "causal", "evaluation"}
    )
    title_parts = _overview_title_parts(page_record)
    source_ref_count = len(page_record.get("source_refs", []))
    claim_count = len(page_record.get("claim_ids", []))
    hierarchy_breadth = -len(title_parts) if title_parts else 0
    semantic_breadth = max(foundational_signal, operational_signal)
    return (
        hierarchy_breadth,
        source_ref_count,
        semantic_breadth,
        claim_count,
        page_record.get("title", "").lower(),
    )


def summarize_concept_page_for_overview(
    *,
    page_record: dict,
    extract_first_sentence: Callable[[str], str],
) -> str:
    sentence = extract_first_sentence(page_record.get("summary", ""))
    if sentence:
        return sentence
    return f"{page_record.get('title', '该主题')} 已经沉淀出稳定结论。"


def build_workspace_overview_key_theme_rows(
    *,
    concept_pages: list[dict],
    claim_records_by_id: dict[str, dict],
    extract_first_sentence: Callable[[str], str],
    limit: int = 10,
) -> list[dict]:
    rows: list[dict] = []
    ranked_pages = sorted(
        concept_pages,
        key=lambda item: _overview_theme_representativeness_score(item, claim_records_by_id),
        reverse=True,
    )
    selected_pages: list[dict] = []
    used_family_keys: set[str] = set()

    for page_record in ranked_pages:
        if len(selected_pages) >= limit:
            break
        family_key = _overview_theme_family_key(page_record)
        if family_key in used_family_keys:
            continue
        selected_pages.append(page_record)
        used_family_keys.add(family_key)

    if len(selected_pages) < limit:
        for page_record in ranked_pages:
            if len(selected_pages) >= limit:
                break
            if any(item.get("page_id") == page_record.get("page_id") for item in selected_pages):
                continue
            selected_pages.append(page_record)

    for page_record in selected_pages:
        claim_records = _collect_page_claim_records(page_record, claim_records_by_id)
        claim_type_counts = _count_claim_types(claim_records)
        foundational_signal = sum(
            claim_type_counts.get(claim_type, 0)
            for claim_type in {"definition", "fact"}
        )
        operational_signal = sum(
            claim_type_counts.get(claim_type, 0)
            for claim_type in {"procedure", "warning", "comparison", "causal", "evaluation"}
        )
        if operational_signal > foundational_signal:
            theme_kind = "operational"
        elif foundational_signal > 0:
            theme_kind = "foundation"
        else:
            theme_kind = "mixed"
        rows.append({
            "page_record": page_record,
            "summary": summarize_concept_page_for_overview(
                page_record=page_record,
                extract_first_sentence=extract_first_sentence,
            ),
            "theme_kind": theme_kind,
            "source_count": len(page_record.get("source_refs", [])),
            "claim_count": len(page_record.get("claim_ids", [])),
            "review_count": len(page_record.get("review_ids", [])),
        })
    return rows


def build_workspace_source_coverage_rows(
    *,
    concept_pages: list[dict],
    source_pages_by_id: dict[str, dict],
    expected_source_summary_page_id: Callable[[str], str],
    append_unique: Callable[[list[str], str], None],
    limit: int = 8,
) -> list[dict]:
    grouped: dict[str, dict] = {}
    for concept_page in concept_pages:
        for source_ref in concept_page.get("source_refs", []):
            source_id = source_ref["source_id"]
            if source_id not in grouped:
                grouped[source_id] = {
                    "source_ref": source_ref,
                    "source_page": source_pages_by_id.get(expected_source_summary_page_id(source_id)),
                    "concept_titles": [],
                    "claim_ids": [],
                    "chunk_ids": [],
                }
            append_unique(grouped[source_id]["concept_titles"], concept_page.get("title", ""))
            for claim_id in source_ref.get("claim_ids", []):
                append_unique(grouped[source_id]["claim_ids"], claim_id)
            for chunk_id in source_ref.get("chunk_ids", []):
                append_unique(grouped[source_id]["chunk_ids"], chunk_id)
    rows = sorted(
        grouped.values(),
        key=lambda item: (
            len(item["concept_titles"]),
            len(item["claim_ids"]),
            item["source_ref"].get("source_id", ""),
        ),
        reverse=True,
    )
    return rows[:limit]


def build_workspace_overview_summary_text(
    *,
    concept_pages: list[dict],
    source_refs: list[dict],
    key_theme_rows: list[dict],
) -> str:
    claim_ids = {
        claim_id
        for page_record in concept_pages
        for claim_id in page_record.get("claim_ids", [])
    }
    key_theme_titles = [
        item["page_record"].get("title", "")
        for item in key_theme_rows
        if item["page_record"].get("title")
    ]
    key_theme_text = "、".join(key_theme_titles[:3]) if key_theme_titles else "若干稳定主题"
    operational_theme_count = sum(1 for item in key_theme_rows if item["theme_kind"] == "operational")
    summary_parts = [
        f"{key_theme_text} 是当前工作区里已经沉淀出的稳定主题。",
        f"这些主题当前覆盖 {len(claim_ids)} 条稳定 Claim 和 {len(source_refs)} 个来源。",
    ]
    if operational_theme_count:
        summary_parts.append(f"其中有 {operational_theme_count} 个主题带有更强的操作或判断信号。")
    else:
        summary_parts.append("这些主题目前以基础概念和事实定义为主。")
    return " ".join(summary_parts)


def prepare_workspace_overview_context(
    *,
    concept_pages: list[dict],
    page_records_by_id: dict[str, dict],
    claim_records_by_id: dict[str, dict],
    aggregate_source_refs_for_pages: Callable[[list[dict]], list[dict]],
    is_live_page_record: Callable[[dict], bool],
    expected_source_summary_page_id: Callable[[str], str],
    append_unique: Callable[[list[str], str], None],
    extract_first_sentence: Callable[[str], str],
    key_theme_limit: int = 10,
    source_coverage_limit: int = 8,
) -> dict:
    source_refs = aggregate_source_refs_for_pages(concept_pages)
    source_pages_by_id = {
        page_record["page_id"]: page_record
        for page_record in page_records_by_id.values()
        if is_live_page_record(page_record) and page_record.get("type") == "source-summary"
    }
    claim_ids = sorted({
        claim_id
        for page_record in concept_pages
        for claim_id in page_record.get("claim_ids", [])
    })
    review_ids = sorted({
        review_id
        for page_record in concept_pages
        for review_id in page_record.get("review_ids", [])
    })
    key_theme_rows = build_workspace_overview_key_theme_rows(
        concept_pages=concept_pages,
        claim_records_by_id=claim_records_by_id,
        extract_first_sentence=extract_first_sentence,
        limit=key_theme_limit,
    )
    source_coverage_rows = build_workspace_source_coverage_rows(
        concept_pages=concept_pages,
        source_pages_by_id=source_pages_by_id,
        expected_source_summary_page_id=expected_source_summary_page_id,
        append_unique=append_unique,
        limit=source_coverage_limit,
    )
    summary_text = build_workspace_overview_summary_text(
        concept_pages=concept_pages,
        source_refs=source_refs,
        key_theme_rows=key_theme_rows[:3],
    )
    return {
        "source_refs": source_refs,
        "claim_ids": claim_ids,
        "review_ids": review_ids,
        "key_theme_rows": key_theme_rows,
        "source_coverage_rows": source_coverage_rows,
        "summary_text": summary_text,
    }


def prepare_workspace_overview_render_inputs(
    *,
    key_theme_rows: list[dict],
) -> dict:
    operational_rows = [item for item in key_theme_rows if item["theme_kind"] == "operational"]
    foundational_rows = [item for item in key_theme_rows if item["theme_kind"] != "operational"]
    deterministic_reading_path_rows: list[dict] = []
    if foundational_rows:
        deterministic_reading_path_rows.append({"page_record": foundational_rows[0]["page_record"]})
    if operational_rows:
        deterministic_reading_path_rows.append({"page_record": operational_rows[0]["page_record"]})
    if key_theme_rows:
        densest_page = max(
            key_theme_rows,
            key=lambda item: (item["source_count"], item["claim_count"], item["review_count"]),
        )["page_record"]
        if all(item["page_record"]["page_id"] != densest_page["page_id"] for item in deterministic_reading_path_rows):
            deterministic_reading_path_rows.append({"page_record": densest_page})
    return {
        "operational_rows": operational_rows,
        "foundational_rows": foundational_rows,
        "deterministic_reading_path_rows": deterministic_reading_path_rows,
    }


def finalize_workspace_overview_render_result(
    *,
    assisted_render: dict | None,
    requested_render_mode: str,
    summary_text: str,
) -> dict:
    rendered_summary_text = assisted_render.get("summary") if assisted_render else ""
    if not rendered_summary_text:
        rendered_summary_text = summary_text
    rendered_theme_rows = assisted_render.get("theme_rows", []) if assisted_render else []
    rendered_reading_path = assisted_render.get("reading_path", []) if assisted_render else []
    render_status = (
        "llm_assisted"
        if assisted_render
        else "deterministic_fallback"
        if requested_render_mode == "llm_assisted"
        else "deterministic"
    )
    return {
        "rendered_summary_text": rendered_summary_text,
        "rendered_theme_rows": rendered_theme_rows,
        "rendered_reading_path": rendered_reading_path,
        "render_status": render_status,
    }


def finalize_concept_render_result(
    *,
    assisted_render: dict | None,
    requested_render_mode: str,
    summary_text: str,
) -> dict:
    rendered_summary_text = assisted_render.get("summary") if assisted_render else ""
    if not rendered_summary_text:
        rendered_summary_text = summary_text
    rendered_key_points = assisted_render.get("key_points", []) if assisted_render else []
    rendered_practical_notes = assisted_render.get("practical_notes", []) if assisted_render else []
    render_status = (
        "llm_assisted"
        if assisted_render
        else "deterministic_fallback"
        if requested_render_mode == "llm_assisted"
        else "deterministic"
    )
    return {
        "rendered_summary_text": rendered_summary_text,
        "rendered_key_points": rendered_key_points,
        "rendered_practical_notes": rendered_practical_notes,
        "render_status": render_status,
    }


def build_concept_page_output(
    *,
    page_id: str,
    title: str,
    render_target: str,
    canonical_id: str,
    review_ids: list[str],
    requested_render_mode: str,
    render_status: str,
    stable_claim_count: int,
    source_refs: list[dict],
    semantic_frontmatter: dict,
    bucket_key: str,
    canonical_key: str,
    canonical_display_text: str,
    render_claim_records: list[dict],
    rendered_summary_text: str,
    canonical_claim: dict,
    rendered_key_points: list[dict],
    key_point_claims: list[dict],
    rendered_practical_notes: list[dict],
    practical_claims: list[dict],
    sorted_claims: list[dict],
    source_pages: list[dict],
    page_rel_path: Path,
    format_claim_reference: Callable[[Path, dict], str],
    format_claim_type_label: Callable[[str | None], str],
    render_claim_as_sentence: Callable[[dict, str], str],
    format_source_page_label: Callable[[Path, dict], str],
    format_workspace_file_reference: Callable[[Path, str], str],
    format_source_page_meta: Callable[[dict | None, dict], str],
    format_chunk_reference: Callable[[Path, str, dict], str],
    append_frontmatter_list: Callable[[list[str], str, list[str]], None],
    utc_now_iso: Callable[[], str],
    title_quality: str,
    aliases: list[str],
) -> tuple[str, dict]:
    lines = [
        "---",
        f'page_id: "{page_id}"',
        f'title: "{title}"',
        'type: "concept"',
        f'render_target: "{render_target}"',
        f'canonical_id: "{canonical_id}"',
        f'status: "{"needs_review" if review_ids else "stable"}"',
        'automation_level: "auto_with_log"',
        f'render_mode: "{requested_render_mode}"',
        f'render_status: "{render_status}"',
        f'claim_count: {stable_claim_count}',
        f'source_count: {len(source_refs)}',
    ]
    append_frontmatter_list(lines, "content_tags", semantic_frontmatter["content_tags"])
    append_frontmatter_list(lines, "semantic_feature_tags", semantic_frontmatter["semantic_feature_tags"])
    lines.extend([
        "---",
        "",
        f"# {title}",
        "",
        "## 概念摘要 / Concept Summary",
        "",
        f"- 规范概念键: `{canonical_key}`",
        f"- 聚类键: `{bucket_key}`",
        f"- 代表陈述: {canonical_display_text}",
        f"- 关联 Claim 数量: `{len(render_claim_records)}`",
        f"- 关联来源数量: `{len(source_refs)}`",
        f"- 关联审核项数量: `{len(review_ids)}`",
        "",
        "## 摘要 / Summary",
        "",
        rendered_summary_text,
        "",
        "## 核心定义 / Core Definition",
        "",
        canonical_display_text,
        "",
        f"支撑 Claim: {format_claim_reference(page_rel_path, canonical_claim)} {format_claim_type_label(canonical_claim.get('claim_type'))}",
        "",
        "## 核心陈述 / Canonical Claim",
        "",
        f"- {format_claim_reference(page_rel_path, canonical_claim)} {format_claim_type_label(canonical_claim.get('claim_type'))} {canonical_display_text}",
        "",
        "## 关键要点 / Key Points",
        "",
    ])

    if rendered_key_points:
        for item in rendered_key_points:
            lines.append(f"- {item['text']} ({format_claim_reference(page_rel_path, item['claim_record'])})")
    elif key_point_claims:
        for claim_record in key_point_claims:
            lines.append(
                f"- {render_claim_as_sentence(claim_record, title)} "
                f"({format_claim_reference(page_rel_path, claim_record)})"
            )
    else:
        lines.append(f"- {canonical_display_text} ({format_claim_reference(page_rel_path, canonical_claim)})")

    lines.extend([
        "",
        "## 使用提示 / Practical Notes",
        "",
    ])
    if rendered_practical_notes:
        for item in rendered_practical_notes:
            lines.append(f"- {item['text']} ({format_claim_reference(page_rel_path, item['claim_record'])})")
    elif practical_claims:
        for claim_record in practical_claims:
            lines.append(
                f"- {render_claim_as_sentence(claim_record, title)} "
                f"({format_claim_reference(page_rel_path, claim_record)})"
            )
    else:
        lines.append("- 当前稳定结论以概念定义和基础事实为主，尚未整理出更多操作性提示。")

    lines.extend([
        "",
        "## 支撑声明 / Supporting Claims",
        "",
    ])
    for claim_record in sorted_claims:
        lines.append(
            f"- {format_claim_reference(page_rel_path, claim_record)} {format_claim_type_label(claim_record.get('claim_type'))} {claim_record['text']} "
            f"(sources={len(claim_record.get('source_ids', []))}, chunks={len(claim_record.get('chunk_ids', []))})"
        )

    lines.extend([
        "",
        "## 来源页面 / Source Pages",
        "",
    ])
    if source_pages:
        source_pages_by_id = {source_page["page_id"]: source_page for source_page in source_pages}
        for source_ref in source_refs:
            source_page = source_pages_by_id.get(f"page_src_{source_ref['source_id']}")
            if source_page is None:
                continue
            lines.append(f"- 来源摘要页: {format_source_page_label(page_rel_path, source_page)}")
            lines.append(f"  原始文件: {format_workspace_file_reference(page_rel_path, source_ref['source_path'])}")
            lines.append(f"  标识: {format_source_page_meta(source_page, source_ref)}")
    else:
        lines.append("- 当前还没有可链接的来源摘要页。")

    lines.extend([
        "",
        "## 证据入口 / Evidence Trail",
        "",
    ])
    for source_ref in source_refs:
        source_page = next(
            (item for item in source_pages if item["page_id"] == f"page_src_{source_ref['source_id']}"),
            None,
        )
        source_label = (
            format_source_page_label(page_rel_path, source_page)
            if source_page is not None
            else "`未生成来源摘要页`"
        )
        lines.append(
            f"- {source_label} | 原始文件: {format_workspace_file_reference(page_rel_path, source_ref['source_path'])} | "
            f"claims={len(source_ref['claim_ids'])}, chunks={len(source_ref['chunk_ids'])}"
        )
        lines.append(f"  标识: {format_source_page_meta(source_page, source_ref)}")
        if source_ref.get("chunks"):
            lines.append("  证据切块:")
            for chunk_ref in source_ref["chunks"][:6]:
                lines.append(f"  - {format_chunk_reference(page_rel_path, source_ref['source_id'], chunk_ref)}")
            if len(source_ref["chunks"]) > 6:
                lines.append(f"  - ... 其余 {len(source_ref['chunks']) - 6} 个 chunk")

    lines.extend([
        "",
        "## 维护状态 / Maintenance",
        "",
        f"- 页面状态: `{'needs_review' if review_ids else 'stable'}`",
        f"- 聚合 Claim 数量: `{len(render_claim_records)}`",
        f"- 稳定 Claim 数量: `{stable_claim_count}`",
        f"- 覆盖来源数量: `{len(source_refs)}`",
        f"- 关联审核项数量: `{len(review_ids)}`",
    ])
    if review_ids:
        lines.append("- 当前已有稳定结论，但仍有未关闭的审核项，阅读时请结合证据页一起查看。")
    else:
        lines.append("- 当前页面由稳定 Claim 自动编译，适合作为优先阅读入口。")

    page_text = "\n".join(lines).strip() + "\n"
    page_record = {
        "page_id": page_id,
        "title": title,
        "type": "concept",
        "render_target": render_target,
        "canonical_id": canonical_id,
        "status": "needs_review" if review_ids else "stable",
        "lifecycle_status": "active",
        "automation_level": "auto_with_log",
        "render_mode": requested_render_mode,
        "render_status": render_status,
        "concept_title_quality": title_quality,
        "review_reason": "claim_reviews_attached" if review_ids else None,
        "summary": rendered_summary_text,
        "aliases": sorted(set(alias for alias in aliases if alias and alias != title))[:8],
        "redirect_to": None,
        "claim_ids": [claim_record["claim_id"] for claim_record in render_claim_records],
        "review_ids": review_ids,
        "source_refs": source_refs,
        "content_tags": semantic_frontmatter["content_tags"],
        "semantic_feature_tags": semantic_frontmatter["semantic_feature_tags"],
        "created": utc_now_iso(),
        "updated": utc_now_iso(),
        "archived_at": None,
    }
    return page_text, page_record


def build_intent_routed_page_output(
    *,
    page_id: str,
    title: str,
    page_intent: str,
    canonical_id: str,
    review_ids: list[str],
    claim_records: list[dict],
    source_refs: list[dict],
    source_pages: list[dict],
    semantic_frontmatter: dict,
    summary: str,
    section_title: str,
    page_rel_path: Path,
    format_source_page_label: Callable[[Path, dict], str],
    format_workspace_file_reference: Callable[[Path, str], str],
    render_claim_as_sentence: Callable[[dict, str], str],
    format_claim_reference: Callable[[Path, dict], str],
    append_frontmatter_list: Callable[[list[str], str, list[str]], None],
    utc_now_iso: Callable[[], str],
) -> tuple[str, dict]:
    lines = [
        "---",
        f'page_id: "{page_id}"',
        f'title: "{title}"',
        f'type: "{page_intent}"',
        f'canonical_id: "{canonical_id}"',
        f'status: "{"needs_review" if review_ids else "stable"}"',
        'automation_level: "auto_with_log"',
        f'claim_count: {len(claim_records)}',
        f'source_count: {len(source_refs)}',
    ]
    append_frontmatter_list(lines, "content_tags", semantic_frontmatter["content_tags"])
    append_frontmatter_list(lines, "semantic_feature_tags", semantic_frontmatter["semantic_feature_tags"])
    lines.extend([
        "---",
        "",
        f"# {title}",
        "",
        "## 摘要 / Summary",
        "",
        summary,
        "",
        f"## {section_title}",
        "",
    ])
    for claim_record in claim_records[:6]:
        lines.append(
            f"- {render_claim_as_sentence(claim_record, title)} "
            f"({format_claim_reference(page_rel_path, claim_record)})"
        )
    if page_intent == "timeline":
        lines.extend([
            "",
            "## 时间线来源 / Timeline Sources",
            "",
        ])
        for source_ref in source_refs[:8]:
            lines.append(
                f"- {source_ref.get('section_path') or '未标注章节'} | "
                f"{format_workspace_file_reference(page_rel_path, source_ref['source_path'])}"
            )

    lines.extend([
        "",
        "## 证据入口 / Evidence Trail",
        "",
    ])
    for source_ref in source_refs:
        source_page = next(
            (item for item in source_pages if item["page_id"] == f"page_src_{source_ref['source_id']}"),
            None,
        )
        source_label = (
            format_source_page_label(page_rel_path, source_page)
            if source_page is not None
            else "`未生成来源摘要页`"
        )
        lines.append(
            f"- {source_label} | 原始文件: {format_workspace_file_reference(page_rel_path, source_ref['source_path'])}"
        )

    if page_intent == "duty":
        metadata_rows: list[str] = []
        seen_rows: set[tuple[str, str]] = set()
        for claim_record in claim_records:
            for source_ref in claim_record.get("source_refs", []):
                if not isinstance(source_ref, dict):
                    continue
                section_title_value = str(source_ref.get("section_title", "")).strip()
                if section_title_value:
                    row = ("对象", section_title_value)
                    if row not in seen_rows:
                        seen_rows.add(row)
                        metadata_rows.append(f"- 对象: `{section_title_value}`")
        if metadata_rows:
            lines.extend([
                "",
                "## 结构元信息 / Structured Metadata",
                "",
                *metadata_rows[:8],
            ])

    page_text = "\n".join(lines).strip() + "\n"
    page_record = {
        "page_id": page_id,
        "title": title,
        "type": page_intent,
        "canonical_id": canonical_id,
        "status": "needs_review" if review_ids else "stable",
        "lifecycle_status": "active",
        "automation_level": "auto_with_log",
        "review_reason": "claim_reviews_attached" if review_ids else None,
        "page_intent": page_intent,
        "summary": summary,
        "aliases": [],
        "redirect_to": None,
        "claim_ids": [claim_record["claim_id"] for claim_record in claim_records],
        "review_ids": review_ids,
        "source_refs": source_refs,
        "content_tags": semantic_frontmatter["content_tags"],
        "semantic_feature_tags": semantic_frontmatter["semantic_feature_tags"],
        "created": utc_now_iso(),
        "updated": utc_now_iso(),
        "archived_at": None,
    }
    return page_text, page_record


def build_workspace_overview_page_output(
    *,
    page_id: str,
    title: str,
    render_target: str,
    canonical_id: str,
    review_ids: list[str],
    requested_render_mode: str,
    render_status: str,
    claim_ids: list[str],
    source_refs: list[dict],
    rendered_summary_text: str,
    rendered_theme_rows: list[dict],
    foundational_rows: list[dict],
    operational_rows: list[dict],
    key_theme_rows: list[dict],
    rendered_reading_path: list[dict],
    source_coverage_rows: list[dict],
    concept_pages: list[dict],
    semantic_frontmatter: dict,
    page_rel_path: Path,
    format_page_label: Callable[[Path, dict], str],
    summarize_concept_page_for_overview: Callable[[dict], str],
    format_source_page_label: Callable[[Path, dict], str],
    format_workspace_file_reference: Callable[[Path, str], str],
    append_frontmatter_list: Callable[[list[str], str, list[str]], None],
    utc_now_iso: Callable[[], str],
) -> tuple[str, dict]:
    lines = [
        "---",
        f'page_id: "{page_id}"',
        f'title: "{title}"',
        'type: "overview"',
        f'render_target: "{render_target}"',
        f'canonical_id: "{canonical_id}"',
        f'status: "{"needs_review" if review_ids else "stable"}"',
        'automation_level: "auto_with_log"',
        f'render_mode: "{requested_render_mode}"',
        f'render_status: "{render_status}"',
        f'claim_count: {len(claim_ids)}',
        f'source_count: {len(source_refs)}',
    ]
    append_frontmatter_list(lines, "content_tags", semantic_frontmatter["content_tags"])
    append_frontmatter_list(lines, "semantic_feature_tags", semantic_frontmatter["semantic_feature_tags"])
    lines.extend([
        "---",
        "",
        f"# {title}",
        "",
        "## 工作区综述 / Workspace Overview",
        "",
        rendered_summary_text,
        "",
        "## 主题导览 / Theme Map",
        "",
    ])

    if rendered_theme_rows:
        for item in rendered_theme_rows:
            concept_page = item["page_record"]
            lines.append(f"- {format_page_label(page_rel_path, concept_page)} | {item['text']}")
    elif foundational_rows:
        lines.append("- 先读这些基础主题：")
        for item in foundational_rows[:3]:
            concept_page = item["page_record"]
            lines.append(
                f"  - {format_page_label(page_rel_path, concept_page)} | {item['summary']} "
                f"(claims={item['claim_count']}, sources={item['source_count']})"
            )
    if operational_rows:
        lines.append("- 再看这些更偏操作或判断的主题：")
        for item in operational_rows[:3]:
            concept_page = item["page_record"]
            lines.append(
                f"  - {format_page_label(page_rel_path, concept_page)} | {item['summary']} "
                f"(claims={item['claim_count']}, sources={item['source_count']})"
            )
    if not key_theme_rows:
        lines.append("- 当前还没有足够的稳定主题可用于生成综述。")

    lines.extend([
        "",
        "## 推荐阅读路径 / Suggested Reading Path",
        "",
    ])
    if rendered_reading_path:
        for item in rendered_reading_path:
            concept_page = item["page_record"]
            lines.append(f"- {item['text']} ({format_page_label(page_rel_path, concept_page)})")
    else:
        if foundational_rows:
            first_page = foundational_rows[0]["page_record"]
            lines.append(f"- 如果你想先建立全局认识，建议先读 {format_page_label(page_rel_path, first_page)}。")
        if operational_rows:
            first_operational_page = operational_rows[0]["page_record"]
            lines.append(f"- 如果你更关心做法、风险或取舍，接着读 {format_page_label(page_rel_path, first_operational_page)}。")
        if key_theme_rows:
            densest_page = max(
                key_theme_rows,
                key=lambda item: (item["source_count"], item["claim_count"], item["review_count"]),
            )["page_record"]
            lines.append(f"- 如果你想追证据覆盖面，优先从 {format_page_label(page_rel_path, densest_page)} 往下钻。")

    lines.extend([
        "",
        "## 全部主题 / All Themes",
        "",
    ])
    for concept_page in sorted(concept_pages, key=lambda item: item.get("title", "").lower()):
        lines.append(
            f"- {format_page_label(page_rel_path, concept_page)} | {summarize_concept_page_for_overview(concept_page)} "
            f"(claims={len(concept_page.get('claim_ids', []))}, sources={len(concept_page.get('source_refs', []))})"
        )

    if render_status == "llm_assisted":
        lines.extend([
            "",
            "## 改写回绑 / Rewrite Traceability",
            "",
            "<details>",
            "<summary>查看 overview 改写句与其回绑页面</summary>",
            "",
        ])
        if rendered_summary_text:
            lines.append(
                f"- 工作区综述摘要 -> 基于这些主题页聚合改写: "
                f"{', '.join(format_page_label(page_rel_path, item['page_record']) for item in key_theme_rows[:3]) or '`无可用主题页`'}"
            )
        for item in rendered_theme_rows:
            lines.append(f"- 主题导览句: `{item['text']}` -> {format_page_label(page_rel_path, item['page_record'])}")
        for item in rendered_reading_path:
            lines.append(f"- 推荐阅读句: `{item['text']}` -> {format_page_label(page_rel_path, item['page_record'])}")
        if not rendered_summary_text and not rendered_theme_rows and not rendered_reading_path:
            lines.append("- 当前没有可展示的 overview 改写回绑项。")
        lines.extend([
            "",
            "</details>",
        ])

    lines.extend([
        "",
        "## 来源覆盖 / Source Coverage",
        "",
    ])
    for row in source_coverage_rows:
        source_ref = row["source_ref"]
        source_page = row["source_page"]
        source_label = (
            format_source_page_label(page_rel_path, source_page)
            if source_page is not None
            else "`未生成来源摘要页`"
        )
        lines.append(
            f"- 来源页: {source_label} | 原始文件: {format_workspace_file_reference(page_rel_path, source_ref['source_path'])} | "
            f"concepts={len(row['concept_titles'])}, claims={len(row['claim_ids'])}, chunks={len(row['chunk_ids'])}"
        )
        if row["concept_titles"]:
            lines.append(f"  关联主题: {', '.join(row['concept_titles'][:4])}")

    lines.extend([
        "",
        "## 维护状态 / Maintenance",
        "",
        f"- 可读概念页数量: `{len(concept_pages)}`",
        f"- 稳定 Claim 数量: `{len(claim_ids)}`",
        f"- 覆盖来源数量: `{len(source_refs)}`",
        f"- 关联审核项数量: `{len(review_ids)}`",
    ])
    if review_ids:
        lines.append("- 当前综述仍关联未关闭审核项，阅读时请优先回到对应概念页与证据页确认边界。")
    else:
        lines.append("- 当前综述由稳定概念页自动汇总，适合作为工作区级入口。")

    page_text = "\n".join(lines).strip() + "\n"
    page_record = {
        "page_id": page_id,
        "title": title,
        "type": "overview",
        "render_target": render_target,
        "canonical_id": canonical_id,
        "status": "needs_review" if review_ids else "stable",
        "lifecycle_status": "active",
        "automation_level": "auto_with_log",
        "render_mode": requested_render_mode,
        "render_status": render_status,
        "review_reason": "claim_reviews_attached" if review_ids else None,
        "summary": rendered_summary_text,
        "aliases": [],
        "redirect_to": None,
        "claim_ids": claim_ids,
        "review_ids": review_ids,
        "source_refs": source_refs,
        "content_tags": semantic_frontmatter["content_tags"],
        "semantic_feature_tags": semantic_frontmatter["semantic_feature_tags"],
        "created": utc_now_iso(),
        "updated": utc_now_iso(),
        "archived_at": None,
    }
    return page_text, page_record
