from __future__ import annotations

import json
import re
import sys
from pathlib import Path


DETERMINISTIC_RULES = json.loads(
    Path(__file__).with_name("deterministic_rules.json").read_text(encoding="utf-8")
)
TEXT_RULES = DETERMINISTIC_RULES["text"]
ALIAS_RULES = DETERMINISTIC_RULES["aliases"]
CONCEPT_TITLE_RULES = DETERMINISTIC_RULES["concept_titles"]
DOCUMENT_ANALYSIS_RULES = DETERMINISTIC_RULES["document_analysis"]
COMPACT_TEXT_RE = re.compile(r"[\s，。；：！？、,.!?:;\"'“”‘’（）()\[\]【】`]+")
IMAGE_SLOT_ALIAS_RE = re.compile(ALIAS_RULES["image_slot_pattern"], re.IGNORECASE)
NOISY_ALIAS_VALUES = frozenset(ALIAS_RULES["noisy_values"])


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def sentence_score(text: str) -> tuple[int, int, int]:
    cleaned = normalize_text(text)
    punctuation_bonus = sum(cleaned.count(marker) for marker in TEXT_RULES["sentence_punctuation"])
    return (
        len(cleaned),
        punctuation_bonus,
        0,
    )


def text_looks_fragmentary(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    if cleaned.endswith(tuple(TEXT_RULES["fragment_endings"])):
        return True
    return False


def compact_text(text: str) -> str:
    return COMPACT_TEXT_RE.sub("", normalize_text(text))


def text_is_question_like(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    return cleaned.endswith(tuple(TEXT_RULES["question_endings"]))


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


def claim_role_structure_hints(item: dict) -> tuple[str | None, list[str], str | None]:
    block_kinds = evidence_block_kinds(item)
    knowledge_kinds = unit_kinds(item)
    tags = structure_content_tags(item)
    if counter_has_any(block_kinds, ("table_row",)) or counter_has_any(knowledge_kinds, ("table_fact",)):
        return "fact", ["reference"], "deterministic_processor_claim_role_structure_reference_evidence"
    if counter_has_any(block_kinds, ("code_example",)) or counter_has_any(knowledge_kinds, ("code_example",)):
        return "example", ["example"], "deterministic_processor_claim_role_structure_example_evidence"
    if tags.get("cases", 0) >= 2:
        return "example", ["example"], "deterministic_processor_claim_role_structure_case_cluster"
    if tags.get("rules", 0) >= 2:
        return "fact", ["reference"], "deterministic_processor_claim_role_structure_rule_cluster"
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
            return "deterministic_processor_kept_distinct_question_claims"

    if not any(text_is_question_like(text) for text in texts):
        left_compact, right_compact = [compact_text(text) for text in texts]
        if left_compact and right_compact and left_compact != right_compact:
            shared_tokens = set(re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", texts[0])) & set(
                re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", texts[1])
            )
            if shared_tokens and not (left_compact in right_compact or right_compact in left_compact):
                return "deterministic_processor_kept_complementary_conflict_claims"

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
        return weaker, "deterministic_processor_archived_fragmentary_conflict_claim"

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
        return shorter, "deterministic_processor_archived_contained_conflict_claim"

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
                    "deterministic_processor_assigned_noisy_alias_to_title_owner"
                    if alias_value in NOISY_ALIAS_VALUES
                    else "deterministic_processor_assigned_alias_to_unique_title_owner"
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
                "reason": "deterministic_processor_kept_generated_image_aliases_distinct",
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
                    "reason": "deterministic_processor_archived_fragmentary_duplicate_claim",
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
                            "reason": "deterministic_processor_merged_best_supported_duplicate_pair",
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
            "reason": "deterministic_processor_promoted_multi_source_claim",
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

    generic_titles = set(CONCEPT_TITLE_RULES["generic_values"])
    if candidate_title in generic_titles:
        if preferred_section_label and preferred_section_label not in generic_titles and len(preferred_section_label) >= 3:
            return {
                "decision": "rename",
                "suggested_title": preferred_section_label,
                "reason": "deterministic_processor_promoted_non_generic_section_label",
                "confidence": 0.84,
            }
        lowered_text = merged_text.lower()
        for marker, suggested_title in CONCEPT_TITLE_RULES["technical_terms"].items():
            if marker in lowered_text:
                return {
                    "decision": "rename",
                    "suggested_title": suggested_title,
                    "reason": "deterministic_processor_detected_specific_technical_term",
                    "confidence": 0.82,
                }
        return {
            "decision": "reject",
            "reason": "deterministic_processor_rejected_generic_structural_title",
            "confidence": 0.95,
        }

    if len(candidate_title) <= 1 and candidate_title not in set(CONCEPT_TITLE_RULES["short_allowed_values"]):
        return {
            "decision": "reject",
            "reason": "deterministic_processor_rejected_too_short_title",
            "confidence": 0.98,
        }

    if text_is_question_like(merged_text):
        return {
            "decision": "reject",
            "reason": "deterministic_processor_rejected_question_like_candidate",
            "confidence": 0.9,
        }

    return {
        "decision": "accept",
        "suggested_title": candidate_title,
        "reason": "deterministic_processor_accepts_candidate_title",
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
        normalized_path_lower = normalized_path.lower()
        title_lower = title.lower()
        document_kind = (
            "reference"
            if any(marker in normalized_path_lower for marker in DOCUMENT_ANALYSIS_RULES["reference_path_markers"])
            else "note"
        )
        chunk_strategy_hint = "heading_first"
        if any(marker in title_lower for marker in DOCUMENT_ANALYSIS_RULES["tutorial_title_markers"]):
            document_kind = "tutorial"
        if any(marker in normalized_path_lower for marker in DOCUMENT_ANALYSIS_RULES["chat_path_markers"]):
            chunk_strategy_hint = "chat_turn"
        elif any(marker in normalized_path_lower for marker in DOCUMENT_ANALYSIS_RULES["paragraph_path_markers"]):
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
                "reason_code": "deterministic_processor_document_analysis_batch_v1",
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
        reason = "deterministic_processor_short_claim_kept_as_standalone"

        if text_is_question_like(cleaned_text):
            quality_label = "fragment"
            review_required = True
            safe_auto_ready = False
            reason = "deterministic_processor_short_claim_question_like_fragment"
        elif text_looks_fragmentary(cleaned_text):
            quality_label = "fragment"
            review_required = True
            safe_auto_ready = False
            reason = "deterministic_processor_short_claim_context_dependent_fragment"
        elif natural_char_count <= 4:
            quality_label = "title_shell"
            review_required = False
            safe_auto_ready = False
            reason = "deterministic_processor_short_claim_title_shell"
        else:
            quality_label = "standalone"
            review_required = True
            safe_auto_ready = False
            reason = "deterministic_processor_short_claim_kept_but_not_safe_auto"

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
                "reason_code": "deterministic_processor_claim_candidate_quality_batch_v1",
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
        content_tags: list[str] = []
        risk_flags: list[str] = []
        reason_code = "deterministic_processor_claim_role_conservative_fact"
        structure_role, structure_hints, structure_reason = claim_role_structure_hints(item)
        if text_is_question_like(text):
            role = "meta"
            page_intent_hints = ["reject"]
            concept_candidate_score = 0.05
            reason_code = "deterministic_processor_claim_role_question_like_reject"
        elif structure_role and structure_hints:
            role = structure_role
            page_intent_hints = structure_hints
            concept_candidate_score = 0.2
            reason_code = structure_reason or "deterministic_processor_claim_role_structure_evidence"
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
        content_tags: list[str] = []
        risk_flags: list[str] = []
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
        reason_code = "deterministic_processor_page_intent_conservative_topic"
        if any(text_is_question_like(text) for text in claim_texts):
            page_intent = "reject"
            reason_code = "deterministic_processor_page_intent_question_like_reject"
        elif hint_counts.get("timeline", 0) >= 2:
            page_intent = "timeline"
            reason_code = "deterministic_processor_page_intent_group_timeline_hints"
        elif hint_counts.get("reference", 0) >= 2:
            page_intent = "reference"
            reason_code = "deterministic_processor_page_intent_group_reference_hints"
        elif hint_counts.get("guide", 0) >= 2:
            page_intent = "guide"
            reason_code = "deterministic_processor_page_intent_group_guide_hints"
        elif hint_counts.get("example", 0) >= 2:
            page_intent = "example"
            reason_code = "deterministic_processor_page_intent_group_example_hints"
        elif hint_counts.get("concept", 0) >= 1:
            page_intent = "concept"
            reason_code = "deterministic_processor_page_intent_group_concept_hints"
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
        "reason": "deterministic_processor_image_description_not_implemented",
        "summary": "；".join(summary_parts),
        "extracted_text": "",
        "warnings": ["image_to_text_deterministic_processor_returned_no_text"],
    }


def process(payload: dict) -> dict:
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
    return result


def main() -> int:
    payload = json.load(sys.stdin)
    result = process(payload if isinstance(payload, dict) else {})
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
