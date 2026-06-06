from __future__ import annotations

import json
import re
import sys


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
)

COMPACT_TEXT_RE = re.compile(r"[\s，。；：！？、,.!?:;\"'“”‘’（）()\[\]【】`]+")
QUESTION_PREFIXES = ("问题", "为什么", "如何", "怎么", "是否")


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
    if len(cleaned) <= 12:
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
    return any(cleaned.startswith(prefix) for prefix in QUESTION_PREFIXES)


def candidate_pages_by_canonical(candidate_pages: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for page in candidate_pages:
        canonical_id = page.get("canonical_id") or page.get("page_id")
        if not canonical_id:
            continue
        grouped.setdefault(canonical_id, []).append(page)
    return grouped


def choose_alias_conflict_owner(review: dict, candidate_pages: list[dict], alias_value: str) -> str | None:
    normalized_alias = normalize_text(alias_value)
    if normalized_alias not in NOISY_ALIAS_VALUES:
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
    concept_like_pages = [
        page for page in target_pages
        if page.get("type") == "concept"
    ]
    preferred_pages = concept_like_pages or target_pages
    if not preferred_pages:
        return None

    page_ids = review.get("candidate_page_ids", [])
    ranked_pages = sorted(
        preferred_pages,
        key=lambda page: (
            1 if page.get("type") == "concept" else 0,
            1 if page.get("status") == "stable" else 0,
            page_ids.index(page.get("page_id")) if page.get("page_id") in page_ids else 10**6,
        ),
        reverse=True,
    )
    return ranked_pages[0].get("page_id")


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
                "reason": "agent_hook_assigned_noisy_alias_to_title_owner",
            }
        if alias_value in NOISY_ALIAS_VALUES and "remove_alias" in review.get("allowed_actions", []):
            normalized_titles = {normalize_text(page.get("title", "")) for page in candidate_pages}
            if alias_value in normalized_titles:
                return {"decision": "escalate", "reason": "alias_matches_page_title"}
            page_ids = review.get("candidate_page_ids", [])
            if page_ids:
                return {
                    "decision": "auto_apply",
                    "action": "remove_alias",
                    "primary_page_id": page_ids[0],
                    "alias_value": alias_value,
                    "confidence": 0.99,
                    "reason": "agent_hook_removed_noisy_alias",
                }
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
    else:
        result = {"decision": "skip", "reason": "unsupported_task"}
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
