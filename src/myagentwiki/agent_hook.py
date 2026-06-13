from __future__ import annotations

import json
import re
import sys
from pathlib import Path


NOISY_ALIAS_VALUES = {
    "draft",
    "一句话总结",
    "什么",
    "文档开始",
    "注意",
}

SHORT_FRAGMENT_MARKERS = (
    "问题",
    "模板",
    "例如",
    "比如",
    "注意",
    "什么是",
    "如何",
    "但",
    "并且",
    "同时",
    "以及",
)

COMPACT_TEXT_RE = re.compile(r"[\s，。；：！？、,.!?:;\"'“”‘’（）()\[\]【】`]+")
QUESTION_PREFIXES = ("问题", "为什么", "如何", "怎么", "是否")
IMAGE_SLOT_ALIAS_RE = re.compile(
    r"^(?:内嵌图片\s*)?(?:image|img|figure|fig|photo|picture|插图|图片)[-_ ]?[a-z0-9]+$",
    re.IGNORECASE,
)

PROCEDURE_MARKERS = ("步骤", "首先", "然后", "最后", "第一步", "第二步", "第三步")
HOWTO_MARKERS = ("如何", "怎么")
TIMELINE_MARKERS = ("时间线", "演变", "历史阶段", "历程", "起初", "随后", "后来")
REFERENCE_MARKERS = ("FAQ", "清单", "列表", "参考", "规则", "参数", "字段", "配置项")
EXAMPLE_MARKERS = ("例如", "比如", "示例", "案例")
DEFINITION_MARKERS = ("是", "用于", "意味着", "是一种")
CONCEPT_MARKERS = ("承担", "职责", "机制", "能力", "模型", "系统", "设计", "定义")

REFERENCE_STRUCTURE_MARKERS = ("参数表", "字段表", "配置表", "规则表", "术语表", "FAQ", "常见问题")
EXAMPLE_STRUCTURE_MARKERS = ("案例：", "示例：", "场景：", "输入", "过程", "结果", "复盘")
AMBIGUOUS_EXAMPLE_CONTEXT_MARKERS = ("案例库", "案例素材", "案例培训", "复盘案例", "管理案例", "分析案例", "整理案例", "典型案例进行")
AMBIGUOUS_REFERENCE_CONTEXT_MARKERS = ("制定", "执行", "落地", "运营规则", "产品规则", "完善规则", "规则在")
AMBIGUOUS_TIMELINE_CONTEXT_MARKERS = ("历史数据", "历史运营数据", "历史指标", "历史记录")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def sentence_score(text: str) -> tuple[int, int, int]:
    cleaned = normalize_text(text)
    punctuation_bonus = sum(cleaned.count(marker) for marker in ("。", "；", "：", "，"))
    definition_bonus = sum(cleaned.count(marker) for marker in ("是", "用于", "负责", "意味着"))
    return (
        len(cleaned),
        punctuation_bonus,
        definition_bonus,
    )


def text_looks_fragmentary(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    if cleaned.endswith(("？", "?", "：", ":")):
        return True
    return any(cleaned.startswith(marker) for marker in SHORT_FRAGMENT_MARKERS)


def compact_text(text: str) -> str:
    return COMPACT_TEXT_RE.sub("", normalize_text(text))


def text_is_question_like(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    if cleaned.endswith(("？", "?")):
        return True
    if ("？" in cleaned or "?" in cleaned) and any(prefix in cleaned for prefix in QUESTION_PREFIXES):
        return True
    return any(cleaned.startswith(prefix) for prefix in QUESTION_PREFIXES)


def text_contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def normalize_counter_payload(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, raw_count in value.items():
        text = normalize_text(str(key))
        if not text:
            continue
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            normalized[text] = count
    return normalized


def structure_counter(item: dict, key: str) -> dict[str, int]:
    context = item.get("structure_context", {})
    if not isinstance(context, dict):
        return {}
    return normalize_counter_payload(context.get(key, {}))


def counter_has_any(counter_payload: dict[str, int], values: tuple[str, ...]) -> bool:
    return any(counter_payload.get(value, 0) > 0 for value in values)


def evidence_block_kinds(item: dict) -> dict[str, int]:
    return structure_counter(item, "evidence_block_kind_counts")


def unit_kinds(item: dict) -> dict[str, int]:
    return structure_counter(item, "unit_kind_counts")


def structure_content_tags(item: dict) -> dict[str, int]:
    return structure_counter(item, "content_tag_counts")


def semantic_content_tags(text: str) -> list[str]:
    tags: list[str] = []
    if text_contains_any(text, EXAMPLE_MARKERS):
        tags.append("cases")
    if text_contains_any(text, REFERENCE_MARKERS):
        tags.append("rules")
    if text_contains_any(text, (*PROCEDURE_MARKERS, *HOWTO_MARKERS)):
        tags.append("procedural_language")
    if text_contains_any(text, TIMELINE_MARKERS):
        tags.append("temporal_language")
    if text_contains_any(text, DEFINITION_MARKERS):
        tags.append("definition_language")
    return tags


def ambiguous_keyword_risk_flags(text: str) -> list[str]:
    flags: list[str] = []
    if text_contains_any(text, EXAMPLE_MARKERS) and not strong_example_signal(text):
        flags.append("ambiguous_case_keyword")
    if text_contains_any(text, REFERENCE_MARKERS) and not strong_reference_signal(text):
        flags.append("ambiguous_reference_keyword")
    if text_contains_any(text, TIMELINE_MARKERS) and not strong_timeline_signal(text):
        flags.append("ambiguous_timeline_keyword")
    if text_contains_any(text, HOWTO_MARKERS) and not strong_procedure_signal(text):
        flags.append("ambiguous_howto_keyword")
    return flags


def strong_procedure_signal(text: str) -> bool:
    marker_count = sum(1 for marker in PROCEDURE_MARKERS if marker in text)
    return (
        marker_count >= 2
        or bool(re.search(r"(?:步骤|第一步|第二步|第三步|最后)[:：]", text))
        or bool(re.match(r"^(?:首先|然后|最后|第一步|第二步|第三步)", normalize_text(text)))
    )


def strong_timeline_signal(text: str) -> bool:
    if text_contains_any(text, AMBIGUOUS_TIMELINE_CONTEXT_MARKERS):
        return False
    temporal_markers = sum(1 for marker in ("起初", "随后", "后来", "阶段", "年：", "年:") if marker in text)
    return temporal_markers >= 2 or "时间线" in text or "演变经历" in text


def strong_reference_signal(text: str) -> bool:
    if text_contains_any(text, AMBIGUOUS_REFERENCE_CONTEXT_MARKERS):
        return False
    if "常见问题" in text and not text_contains_any(text, ("FAQ", "清单", "列表", "参数", "字段", "配置项")):
        return False
    return text_contains_any(text, REFERENCE_STRUCTURE_MARKERS) or (
        text_contains_any(text, ("参数", "字段", "配置项"))
        and text_contains_any(text, ("包含", "列出", "说明"))
    )


def strong_example_signal(text: str) -> bool:
    if text_contains_any(text, AMBIGUOUS_EXAMPLE_CONTEXT_MARKERS):
        return False
    return (
        bool(re.search(r"(?:例如|比如|示例|案例)[,，:：]", text))
        or text_contains_any(text, ("输入", "过程", "结果", "场景"))
        and text_contains_any(text, ("案例", "示例", "复盘"))
    )


def strong_definition_signal(text: str, quality_label: str) -> bool:
    if quality_label in {"fragment", "title_shell", "noise"} or text_looks_fragmentary(text):
        return False
    cleaned = normalize_text(text)
    if "是一种" in cleaned or "意味着" in cleaned:
        return True
    if re.search(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,24}\s*是", cleaned):
        return True
    used_for_match = re.search(r"^([A-Za-z0-9_\-\u4e00-\u9fff]{2,16})\s*用于", cleaned)
    if used_for_match:
        subject = used_for_match.group(1)
        if (
            re.search(r"[A-Za-z0-9_-]", subject)
            or subject.endswith(("层", "模块", "系统", "机制", "模型", "组件", "字段", "页面", "索引", "流程"))
        ):
            return True
    return len(cleaned) <= 12 and cleaned.startswith("用于")


def claim_role_structure_hints(item: dict) -> tuple[str | None, list[str], str | None]:
    block_kinds = evidence_block_kinds(item)
    knowledge_kinds = unit_kinds(item)
    tags = structure_content_tags(item)
    if counter_has_any(block_kinds, ("table_row",)) or counter_has_any(knowledge_kinds, ("table_fact",)):
        return "fact", ["reference"], "agent_hook_claim_role_structure_reference_evidence"
    if counter_has_any(block_kinds, ("code_example",)) or counter_has_any(knowledge_kinds, ("code_example",)):
        return "example", ["example"], "agent_hook_claim_role_structure_example_evidence"
    if tags.get("cases", 0) >= 2:
        return "example", ["example"], "agent_hook_claim_role_structure_case_cluster"
    if tags.get("rules", 0) >= 2:
        return "fact", ["reference"], "agent_hook_claim_role_structure_rule_cluster"
    return None, [], None


def candidate_pages_by_canonical(candidate_pages: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for page in candidate_pages:
        canonical_id = page.get("canonical_id") or page.get("page_id")
        if not canonical_id:
            continue
        grouped.setdefault(canonical_id, []).append(page)
    return grouped


def pick_preferred_page_id(
    review: dict,
    candidate_pages: list[dict],
) -> str | None:
    if not candidate_pages:
        return None
    page_ids = review.get("candidate_page_ids", [])
    ranked_pages = sorted(
        candidate_pages,
        key=lambda page: (
            1 if page.get("type") == "concept" else 0,
            1 if page.get("status") == "stable" else 0,
            page_ids.index(page.get("page_id")) if page.get("page_id") in page_ids else 10**6,
        ),
        reverse=True,
    )
    return ranked_pages[0].get("page_id")


def alias_looks_like_image_slot(alias_value: str) -> bool:
    return bool(IMAGE_SLOT_ALIAS_RE.match(normalize_text(alias_value)))


def choose_alias_conflict_owner(review: dict, candidate_pages: list[dict], alias_value: str) -> str | None:
    normalized_alias = normalize_text(alias_value)
    if not normalized_alias:
        return None

    grouped = candidate_pages_by_canonical(candidate_pages)
    title_matches = [
        canonical_id
        for canonical_id, pages in grouped.items()
        if any(normalize_text(page.get("title", "")) == normalized_alias for page in pages)
    ]
    if len(title_matches) != 1:
        return None

    target_canonical_id = title_matches[0]
    target_pages = grouped.get(target_canonical_id, [])
    concept_like_pages = [page for page in target_pages if page.get("type") == "concept"]
    preferred_pages = concept_like_pages or target_pages
    return pick_preferred_page_id(review, preferred_pages)


def choose_keep_both_conflict_reason(candidate_claims: list[dict]) -> str | None:
    texts = [normalize_text(item.get("text", "")) for item in candidate_claims if item.get("text")]
    if len(texts) != 2:
        return None

    if all(text_is_question_like(text) for text in texts):
        compacted = [compact_text(text) for text in texts]
        if compacted[0] != compacted[1]:
            return "agent_hook_kept_distinct_question_claims"

    if not any(text_is_question_like(text) for text in texts):
        left_compact, right_compact = [compact_text(text) for text in texts]
        if left_compact and right_compact and left_compact != right_compact:
            shared_tokens = set(re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", texts[0])) & set(
                re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", texts[1])
            )
            if shared_tokens and not (left_compact in right_compact or right_compact in left_compact):
                return "agent_hook_kept_complementary_conflict_claims"

    return None


def choose_weaker_conflict_claim(candidate_claims: list[dict]) -> tuple[dict | None, str | None]:
    if len(candidate_claims) != 2:
        return None, None

    first, second = candidate_claims
    fragment_flags = [
        text_looks_fragmentary(first.get("text", "")),
        text_looks_fragmentary(second.get("text", "")),
    ]
    if fragment_flags.count(True) == 1:
        weaker = first if fragment_flags[0] else second
        return weaker, "agent_hook_archived_fragmentary_conflict_claim"

    first_text = normalize_text(first.get("text", ""))
    second_text = normalize_text(second.get("text", ""))
    shorter, longer = (
        (first, second)
        if len(first_text) <= len(second_text)
        else (second, first)
    )
    short_compact = compact_text(shorter.get("text", ""))
    long_compact = compact_text(longer.get("text", ""))
    if (
        short_compact
        and len(short_compact) >= 12
        and short_compact in long_compact
        and len(short_compact) <= int(len(long_compact) * 0.75)
    ):
        return shorter, "agent_hook_archived_contained_conflict_claim"

    return None, None


def choose_primary_claim_id(candidate_claims: list[dict]) -> str | None:
    ranked = sorted(
        candidate_claims,
        key=lambda item: (
            sentence_score(item.get("text", "")),
            item.get("source_count", 0),
            item.get("source_ref_count", 0),
            item.get("confidence", 0.0) or 0.0,
        ),
        reverse=True,
    )
    return ranked[0].get("claim_id") if ranked else None


def handle_review_auto(payload: dict) -> dict:
    review = payload.get("review", {})
    kind = review.get("kind")
    candidate_claims = payload.get("candidate_claims", [])
    candidate_pages = payload.get("candidate_pages", [])

    if kind == "alias_conflict":
        evidence = review.get("evidence", [])
        alias_value = normalize_text(evidence[0].get("alias", "")) if evidence else ""
        owner_page_id = choose_alias_conflict_owner(review, candidate_pages, alias_value)
        if owner_page_id and "assign_alias" in review.get("allowed_actions", []):
            return {
                "decision": "auto_apply",
                "action": "assign_alias",
                "primary_page_id": owner_page_id,
                "alias_value": alias_value,
                "confidence": 0.96,
                "reason": (
                    "agent_hook_assigned_noisy_alias_to_title_owner"
                    if alias_value in NOISY_ALIAS_VALUES
                    else "agent_hook_assigned_alias_to_unique_title_owner"
                ),
            }
        if (
            alias_looks_like_image_slot(alias_value)
            and "keep_both" in review.get("allowed_actions", [])
        ):
            return {
                "decision": "auto_apply",
                "action": "keep_both",
                "confidence": 0.94,
                "reason": "agent_hook_kept_generated_image_aliases_distinct",
            }
        if alias_value in NOISY_ALIAS_VALUES and "remove_alias" in review.get("allowed_actions", []):
            normalized_titles = {normalize_text(page.get("title", "")) for page in candidate_pages}
            if alias_value in normalized_titles:
                return {"decision": "escalate", "reason": "alias_matches_page_title"}
            return {"decision": "escalate", "reason": "noisy_alias_still_requires_explicit_owner_decision"}
        return {"decision": "escalate", "reason": "alias_still_needs_human_judgment"}

    if kind == "claim_conflict":
        weaker, reason = choose_weaker_conflict_claim(candidate_claims)
        if weaker is not None and "archive_one" in review.get("allowed_actions", []):
            return {
                "decision": "auto_apply",
                "action": "archive_one",
                "primary_claim_id": weaker.get("claim_id"),
                "confidence": 0.93,
                "reason": reason,
            }
        keep_both_reason = choose_keep_both_conflict_reason(candidate_claims)
        if keep_both_reason and "keep_both" in review.get("allowed_actions", []):
            return {
                "decision": "auto_apply",
                "action": "keep_both",
                "confidence": 0.9,
                "reason": keep_both_reason,
            }
        return {"decision": "escalate", "reason": "conflict_still_needs_human_judgment"}

    if kind == "claim_duplicate":
        if len(candidate_claims) >= 3 and "archive_one" in review.get("allowed_actions", []):
            fragments = [item for item in candidate_claims if text_looks_fragmentary(item.get("text", ""))]
            non_fragments = [item for item in candidate_claims if not text_looks_fragmentary(item.get("text", ""))]
            if len(fragments) == 1 and non_fragments:
                return {
                    "decision": "auto_apply",
                    "action": "archive_one",
                    "primary_claim_id": fragments[0].get("claim_id"),
                    "confidence": 0.91,
                    "reason": "agent_hook_archived_fragmentary_duplicate_claim",
                }
            if len(non_fragments) >= 2 and "merge" in review.get("allowed_actions", []):
                primary_claim_id = choose_primary_claim_id(non_fragments)
                if primary_claim_id:
                    secondary_candidates = [
                        item for item in non_fragments
                        if item.get("claim_id") != primary_claim_id
                    ]
                    secondary_claim_id = choose_primary_claim_id(secondary_candidates)
                    if secondary_claim_id:
                        return {
                            "decision": "auto_apply",
                            "action": "merge",
                            "primary_claim_id": primary_claim_id,
                            "secondary_claim_id": secondary_claim_id,
                            "confidence": 0.9,
                            "reason": "agent_hook_merged_best_supported_duplicate_pair",
                        }
        return {"decision": "escalate", "reason": "duplicate_still_needs_human_judgment"}

    return {"decision": "skip", "reason": "unsupported_review_kind"}


def handle_stable_promotion(payload: dict) -> dict:
    claim = payload.get("claim", {})
    text = normalize_text(claim.get("text", ""))
    source_ids = claim.get("source_ids", [])
    if len(source_ids) >= 2:
        return {
            "decision": "promote",
            "confidence": 0.96,
            "reason": "agent_hook_promoted_multi_source_claim",
        }
    if (
        len(text) >= 28
        and any(marker in text for marker in ("是", "用于", "意味着", "核心", "关键"))
        and not text_looks_fragmentary(text)
    ):
        return {
            "decision": "promote",
            "confidence": 0.9,
            "reason": "agent_hook_promoted_well_formed_definition_like_claim",
        }
    return {"decision": "skip", "reason": "claim_not_confident_enough_for_promotion"}


def handle_review_concept_candidate(payload: dict) -> dict:
    candidate_title = normalize_text(payload.get("candidate_title", ""))
    preferred_section_label = normalize_text(payload.get("preferred_section_label", ""))
    canonical_claim = payload.get("canonical_claim", {}) or {}
    supporting_claims = payload.get("supporting_claims", []) or []
    merged_text = " ".join(
        text for text in [
            normalize_text(canonical_claim.get("text", "")),
            *[normalize_text(item.get("text", "")) for item in supporting_claims[:4]],
        ]
        if text
    )

    generic_titles = {
        "示例", "总结", "小结", "说明", "作用", "原因", "背景", "方法",
        "流程", "步骤", "注意", "补充", "附录", "为什么", "如何", "怎么做",
    }
    if candidate_title in generic_titles:
        if preferred_section_label and preferred_section_label not in generic_titles and len(preferred_section_label) >= 3:
            return {
                "decision": "rename",
                "suggested_title": preferred_section_label,
                "reason": "agent_hook_promoted_non_generic_section_label",
                "confidence": 0.84,
            }
        if "bm25" in merged_text.lower():
            return {
                "decision": "rename",
                "suggested_title": "BM25",
                "reason": "agent_hook_detected_specific_technical_term",
                "confidence": 0.82,
            }
        if "llm-wiki" in merged_text.lower():
            return {
                "decision": "rename",
                "suggested_title": "LLM-Wiki",
                "reason": "agent_hook_detected_specific_technical_term",
                "confidence": 0.8,
            }
        return {
            "decision": "reject",
            "reason": "agent_hook_rejected_generic_structural_title",
            "confidence": 0.95,
        }

    if len(candidate_title) <= 1 and candidate_title not in {"AI"}:
        return {
            "decision": "reject",
            "reason": "agent_hook_rejected_too_short_title",
            "confidence": 0.98,
        }

    if text_is_question_like(merged_text):
        return {
            "decision": "reject",
            "reason": "agent_hook_rejected_question_like_candidate",
            "confidence": 0.9,
        }

    return {
        "decision": "accept",
        "suggested_title": candidate_title,
        "reason": "agent_hook_accepts_candidate_title",
        "confidence": 0.72,
    }


def handle_render_readable_concept_page(payload: dict) -> dict:
    default_summary = normalize_text(payload.get("default_summary", ""))
    default_key_points = payload.get("default_key_points", [])
    default_practical_notes = payload.get("default_practical_notes", [])

    key_points = []
    for item in default_key_points:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id", "")).strip()
        text = normalize_text(item.get("text", ""))
        if not claim_id or not text:
            continue
        key_points.append({"claim_id": claim_id, "text": text})

    practical_notes = []
    for item in default_practical_notes:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id", "")).strip()
        text = normalize_text(item.get("text", ""))
        if not claim_id or not text:
            continue
        practical_notes.append({"claim_id": claim_id, "text": text})

    return {
        "summary": default_summary,
        "key_points": key_points,
        "practical_notes": practical_notes,
    }


def handle_render_workspace_overview_page(payload: dict) -> dict:
    default_summary = normalize_text(payload.get("default_summary", ""))
    theme_rows = payload.get("theme_rows", [])
    reading_path_rows = payload.get("reading_path_rows", [])

    rendered_theme_rows = []
    for item in theme_rows:
        if not isinstance(item, dict):
            continue
        page_id = str(item.get("page_id", "")).strip()
        summary = normalize_text(item.get("summary", ""))
        if not page_id or not summary:
            continue
        rendered_theme_rows.append({"page_id": page_id, "text": summary})

    rendered_reading_path = []
    for item in reading_path_rows:
        if not isinstance(item, dict):
            continue
        page_id = str(item.get("page_id", "")).strip()
        summary = normalize_text(item.get("summary", ""))
        if not page_id or not summary:
            continue
        rendered_reading_path.append({
            "page_id": page_id,
            "text": summary,
        })

    return {
        "summary": default_summary,
        "theme_rows": rendered_theme_rows,
        "reading_path": rendered_reading_path,
    }


def handle_document_analysis_batch(payload: dict) -> dict:
    items = payload.get("items", []) or []
    decisions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", "")).strip()
        normalized_path = normalize_text(item.get("normalized_path", ""))
        title = normalize_text(item.get("title", ""))
        if not item_id:
            continue
        document_kind = "reference" if "faq" in normalized_path.lower() else "note"
        chunk_strategy_hint = "heading_first"
        if any(marker in title.lower() for marker in ("guide", "tutorial", "how")):
            document_kind = "tutorial"
        if "chat" in normalized_path.lower():
            chunk_strategy_hint = "chat_turn"
        elif "plain" in normalized_path.lower() or "note" in normalized_path.lower():
            chunk_strategy_hint = "paragraph_first"
        decisions.append(
            {
                "item_id": item_id,
                "decision": {
                    "document_kind": document_kind,
                    "structure_quality": "mostly_clean",
                    "chunk_strategy_hint": chunk_strategy_hint,
                },
                "confidence": 0.82,
                "reason_code": "agent_hook_document_analysis_batch_v1",
            }
        )
    return {"decisions": decisions}


def handle_claim_candidate_quality_batch(payload: dict) -> dict:
    items = payload.get("items", []) or []
    decisions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", "")).strip()
        text = normalize_text(item.get("text", ""))
        cleaned_text = normalize_text(item.get("cleaned_text", text))
        natural_char_count = int(item.get("natural_char_count", 0) or 0)
        if not item_id or not cleaned_text:
            continue

        quality_label = "standalone"
        review_required = False
        safe_auto_ready = True
        reason = "agent_hook_short_claim_kept_as_standalone"

        if text_is_question_like(cleaned_text):
            quality_label = "fragment"
            review_required = True
            safe_auto_ready = False
            reason = "agent_hook_short_claim_question_like_fragment"
        elif text_looks_fragmentary(cleaned_text):
            quality_label = "fragment"
            review_required = True
            safe_auto_ready = False
            reason = "agent_hook_short_claim_context_dependent_fragment"
        elif natural_char_count <= 4 and not any(marker in cleaned_text for marker in ("是", "需要", "应该", "可以", "会", "能", "用于", "保留", "支持", "记录")):
            quality_label = "title_shell"
            review_required = False
            safe_auto_ready = False
            reason = "agent_hook_short_claim_title_shell"
        elif any(marker in cleaned_text for marker in ("是", "需要", "应该", "可以", "会", "能", "用于", "保留", "支持", "记录")):
            quality_label = "standalone"
            review_required = False
            safe_auto_ready = True
            reason = "agent_hook_short_claim_predicate_complete"
        else:
            quality_label = "standalone"
            review_required = True
            safe_auto_ready = False
            reason = "agent_hook_short_claim_kept_but_not_safe_auto"

        decisions.append(
            {
                "item_id": item_id,
                "decision": {
                    "quality_label": quality_label,
                    "review_required": review_required,
                    "safe_auto_ready": safe_auto_ready,
                    "reason": reason,
                },
                "confidence": 0.86,
                "reason_code": "agent_hook_claim_candidate_quality_batch_v1",
            }
        )
    return {"decisions": decisions}


def handle_claim_role_batch(payload: dict) -> dict:
    items = payload.get("items", []) or []
    decisions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", "")).strip()
        text = normalize_text(item.get("text", ""))
        quality_label = normalize_text(item.get("quality_label", "")).lower()
        if not item_id or not text:
            continue
        role = "fact"
        page_intent_hints = ["topic"]
        concept_candidate_score = 0.45
        content_tags = semantic_content_tags(text)
        risk_flags = ambiguous_keyword_risk_flags(text)
        reason_code = "agent_hook_claim_role_conservative_fact"
        structure_role, structure_hints, structure_reason = claim_role_structure_hints(item)
        if text_is_question_like(text):
            role = "meta"
            page_intent_hints = ["reject"]
            concept_candidate_score = 0.05
            reason_code = "agent_hook_claim_role_question_like_reject"
        elif structure_role and structure_hints:
            role = structure_role
            page_intent_hints = structure_hints
            concept_candidate_score = 0.2
            reason_code = structure_reason or "agent_hook_claim_role_structure_evidence"
        elif strong_procedure_signal(text):
            role = "procedure"
            page_intent_hints = ["guide"]
            concept_candidate_score = 0.2
            reason_code = "agent_hook_claim_role_strong_procedure_pattern"
        elif strong_timeline_signal(text):
            role = "fact"
            page_intent_hints = ["timeline"]
            concept_candidate_score = 0.22
            reason_code = "agent_hook_claim_role_strong_timeline_pattern"
        elif strong_reference_signal(text):
            role = "fact"
            page_intent_hints = ["reference"]
            concept_candidate_score = 0.25
            reason_code = "agent_hook_claim_role_strong_reference_pattern"
        elif strong_example_signal(text):
            role = "example"
            page_intent_hints = ["example"]
            concept_candidate_score = 0.18
            reason_code = "agent_hook_claim_role_strong_example_pattern"
        elif strong_definition_signal(text, quality_label):
            role = "definition"
            page_intent_hints = ["concept", "topic"]
            concept_candidate_score = 0.88
            reason_code = "agent_hook_claim_role_definition_pattern"
        elif (
            quality_label not in {"fragment", "title_shell", "noise"}
            and not text_looks_fragmentary(text)
            and not text_is_question_like(text)
            and text_contains_any(text, CONCEPT_MARKERS)
        ):
            role = "fact"
            page_intent_hints = ["concept", "topic"]
            concept_candidate_score = 0.72
            reason_code = "agent_hook_claim_role_conceptual_fact_pattern"
        decisions.append(
            {
                "item_id": item_id,
                "decision": {
                    "knowledge_role": role,
                    "page_intent_hints": page_intent_hints,
                    "concept_candidate_score": concept_candidate_score,
                    "content_tags": content_tags,
                },
                "confidence": 0.84,
                "reason_code": reason_code,
                "risk_flags": risk_flags,
                "supporting_ids": [item_id],
            }
        )
    return {"decisions": decisions}


def handle_page_intent_batch(payload: dict) -> dict:
    items = payload.get("items", []) or []
    decisions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", "")).strip()
        claim_texts = [normalize_text(text) for text in item.get("claim_texts", []) if normalize_text(text)]
        claim_semantics = item.get("claim_semantics", []) or []
        merged = " ".join(claim_texts)
        if not item_id:
            continue
        page_intent = "topic"
        hint_counts: dict[str, int] = {}
        content_tags = semantic_content_tags(merged)
        risk_flags = ambiguous_keyword_risk_flags(merged)
        for semantic in claim_semantics:
            if not isinstance(semantic, dict):
                continue
            for hint in semantic.get("page_intent_hints", []) or []:
                normalized_hint = normalize_text(str(hint))
                if normalized_hint:
                    hint_counts[normalized_hint] = hint_counts.get(normalized_hint, 0) + 1
            for tag in semantic.get("content_tags", []) or []:
                tag_text = normalize_text(str(tag))
                if tag_text and tag_text not in content_tags:
                    content_tags.append(tag_text)
        reason_code = "agent_hook_page_intent_conservative_topic"
        if any(text_is_question_like(text) for text in claim_texts):
            page_intent = "reject"
            reason_code = "agent_hook_page_intent_question_like_reject"
        elif hint_counts.get("timeline", 0) >= 2 or strong_timeline_signal(merged):
            page_intent = "timeline"
            reason_code = "agent_hook_page_intent_strong_timeline_pattern"
        elif hint_counts.get("reference", 0) >= 2 or strong_reference_signal(merged):
            page_intent = "reference"
            reason_code = "agent_hook_page_intent_strong_reference_pattern"
        elif hint_counts.get("guide", 0) >= 2 or strong_procedure_signal(merged):
            page_intent = "guide"
            reason_code = "agent_hook_page_intent_strong_procedure_pattern"
        elif hint_counts.get("example", 0) >= 2 or strong_example_signal(merged):
            page_intent = "example"
            reason_code = "agent_hook_page_intent_strong_example_pattern"
        elif hint_counts.get("concept", 0) >= 1 or text_contains_any(merged, (*DEFINITION_MARKERS, "承担", "职责", "机制", "能力")):
            page_intent = "concept"
            reason_code = "agent_hook_page_intent_conceptual_pattern"
        decisions.append(
            {
                "item_id": item_id,
                "decision": {
                    "page_intent": page_intent,
                    "content_tags": content_tags,
                },
                "confidence": 0.81,
                "reason_code": reason_code,
                "risk_flags": risk_flags,
                "supporting_ids": [
                    str(semantic.get("claim_id", "")).strip()
                    for semantic in claim_semantics
                    if isinstance(semantic, dict) and str(semantic.get("claim_id", "")).strip()
                ],
            }
        )
    return {"decisions": decisions}


def handle_describe_image(payload: dict) -> dict:
    image_path = str(payload.get("image_path", "")).strip()
    image_name = str(payload.get("image_name", "")).strip() or Path(image_path).name or "image"
    image_context = payload.get("image_context", {})
    summary_parts = [f"图片文件: {image_name}"]
    if isinstance(image_context, dict):
        alt_text = normalize_text(str(image_context.get("image_alt", "")))
        if alt_text:
            summary_parts.append(f"alt: {alt_text}")
        target_value = normalize_text(str(image_context.get("image_target", "")))
        if target_value:
            summary_parts.append(f"source: {target_value}")
    return {
        "decision": "report_only",
        "confidence": 0.0,
        "reason": "agent_hook_image_description_not_implemented",
        "summary": "；".join(summary_parts),
        "extracted_text": "",
        "warnings": ["image_to_text_hook_returned_no_text"],
    }


def main() -> int:
    payload = json.load(sys.stdin)
    task = payload.get("task")
    if task == "review_auto_decision":
        result = handle_review_auto(payload)
    elif task == "claim_stable_promotion":
        result = handle_stable_promotion(payload)
    elif task == "review_concept_candidate":
        result = handle_review_concept_candidate(payload)
    elif task == "render_readable_concept_page":
        result = handle_render_readable_concept_page(payload)
    elif task == "render_workspace_overview_page":
        result = handle_render_workspace_overview_page(payload)
    elif task == "review_document_analysis_batch":
        result = handle_document_analysis_batch(payload)
    elif task == "review_claim_candidate_quality_batch":
        result = handle_claim_candidate_quality_batch(payload)
    elif task == "review_claim_role_batch":
        result = handle_claim_role_batch(payload)
    elif task == "review_page_intent_batch":
        result = handle_page_intent_batch(payload)
    elif task == "describe_image":
        result = handle_describe_image(payload)
    else:
        result = {"decision": "skip", "reason": "unsupported_task"}
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
