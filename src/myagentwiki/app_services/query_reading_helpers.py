from __future__ import annotations

from pathlib import Path
from collections import Counter


def normalize_query_text(text: str, *, normalize_claim_text: object) -> str:
    return normalize_claim_text(text)


def detect_query_intent(
    query_text: str,
    normalized_query: str,
    *,
    query_intent_markers: dict[str, list[str]],
) -> str:
    combined_text = f"{query_text.lower()} {normalized_query}"
    if any(marker in combined_text for marker in query_intent_markers["how_to"]):
        return "how_to"
    if any(marker in combined_text for marker in query_intent_markers["evidence"]):
        return "evidence"
    if any(marker in combined_text for marker in query_intent_markers["reference"]):
        return "reference"
    if any(marker in combined_text for marker in query_intent_markers["overview"]):
        return "overview"
    for intent, markers in query_intent_markers.items():
        if intent in {"how_to", "evidence", "reference", "overview"}:
            continue
        if any(marker in combined_text for marker in markers):
            return intent
    return "lookup"


def alias_match_boost(
    page_record: dict,
    normalized_query: str,
    alias_hits: list[dict],
    *,
    normalize_query_text: object,
    query_exact_match_max_boost: float,
) -> tuple[float, list[str]]:
    boost_reasons: list[str] = []
    title_norm = normalize_query_text(page_record.get("title", ""))
    aliases_norm = [normalize_query_text(alias) for alias in page_record.get("aliases", [])]
    canonical_norm = normalize_query_text(page_record.get("canonical_id", "") or "")

    boost = 1.0
    if normalized_query and title_norm == normalized_query:
        boost = max(boost, query_exact_match_max_boost)
        boost_reasons.append("title_exact")
    if normalized_query and canonical_norm == normalized_query:
        boost = max(boost, 1.30)
        boost_reasons.append("canonical_exact")
    if normalized_query and normalized_query in aliases_norm:
        boost = max(boost, 1.25)
        boost_reasons.append("alias_exact")

    alias_hit_page_ids = {item.get("page_id") for item in alias_hits}
    if page_record.get("page_id") in alias_hit_page_ids:
        boost = max(boost, 1.20)
        boost_reasons.append("alias_registry_hit")

    return boost, boost_reasons


def query_intent_page_type_boost(intent: str, page_record: dict) -> tuple[float, str | None]:
    page_type = page_record.get("type", "")
    page_status = page_record.get("status", "")

    if intent == "overview" and page_type == "overview":
        return 1.85, "intent_overview_prefers_overview_page"
    if intent == "overview" and page_type == "concept":
        return 1.05, "intent_overview_falls_back_to_readable_concept"
    if intent == "overview" and page_type == "duty":
        return 1.08, "intent_overview_can_use_duty_page"
    if intent == "overview" and page_type == "source-summary":
        return 0.70, "intent_overview_deprioritizes_source_summary"
    if intent == "definition" and page_type == "concept":
        return 1.7, "intent_definition_prefers_concept"
    if intent == "definition" and page_type == "duty":
        return 1.35, "intent_definition_can_use_duty_page"
    if intent == "compare" and page_type == "concept":
        return 1.12, "intent_compare_prefers_concept"
    if intent == "compare" and page_type == "duty":
        return 1.10, "intent_compare_can_use_duty_page"
    if intent == "reference" and page_type == "reference":
        return 2.40, "intent_reference_prefers_reference_page"
    if intent == "reference" and page_type == "duty":
        return 1.20, "intent_reference_can_use_duty_page"
    if intent == "reference" and page_type == "source-summary":
        return 1.45, "intent_reference_prefers_source"
    if intent == "reference" and page_type == "concept":
        return 0.35, "intent_reference_deprioritizes_concept_views"
    if intent == "how_to" and page_type == "source-summary":
        return 1.05, "intent_how_to_prefers_source"
    if intent == "evidence" and page_type == "source-summary":
        return 2.6, "intent_evidence_prefers_source"
    if intent == "evidence" and page_type == "topic":
        return 0.55, "intent_evidence_deprioritizes_topic_page"
    if intent == "evidence" and page_type == "guide":
        return 0.50, "intent_evidence_deprioritizes_guide_page"
    if intent == "evidence" and page_type == "duty":
        return 0.70, "intent_evidence_deprioritizes_duty_page"
    if intent == "evidence" and page_type == "example":
        return 0.50, "intent_evidence_deprioritizes_example_page"
    if intent == "evidence" and page_type == "concept":
        return 0.40, "intent_evidence_deprioritizes_concept"
    if intent == "timeline" and page_status == "stable":
        return 1.05, "intent_timeline_prefers_stable"
    return 1.0, None


def query_intent_field_multiplier(
    intent: str,
    field_name: str,
    *,
    query_intent_field_multipliers: dict[str, dict[str, float]],
) -> float:
    return query_intent_field_multipliers.get(intent, {}).get(field_name, 1.0)


def expand_query_with_alias_registry(
    query_text: str,
    alias_index: dict,
    *,
    normalize_query_text: object,
    tokenize_for_search: object,
    detect_query_intent: object,
) -> dict:
    normalized_query = normalize_query_text(query_text)
    alias_map = alias_index.get("alias_map", {})
    canonical_map = alias_index.get("canonical_map", {})
    matched_alias_entries = alias_map.get(normalized_query, [])

    alias_expansions: list[str] = []
    canonical_targets: list[dict] = []
    for entry in matched_alias_entries:
        canonical_id = entry.get("canonical_id")
        canonical_record = canonical_map.get(canonical_id, {})
        for candidate in [
            entry.get("title", ""),
            canonical_id or "",
            *canonical_record.get("aliases", []),
        ]:
            normalized_candidate = normalize_query_text(candidate)
            if normalized_candidate and normalized_candidate not in alias_expansions:
                alias_expansions.append(normalized_candidate)
        if canonical_record and canonical_record not in canonical_targets:
            canonical_targets.append(canonical_record)

    expanded_parts = [normalized_query, *alias_expansions]
    expanded_query = " ".join(part for part in expanded_parts if part).strip()
    expanded_tokens = tokenize_for_search(expanded_query)
    detected_intent = detect_query_intent(query_text, normalized_query)

    return {
        "raw_query": query_text,
        "normalized_query": normalized_query,
        "expanded_query": expanded_query or normalized_query,
        "query_tokens": expanded_tokens,
        "alias_hits": matched_alias_entries,
        "canonical_targets": canonical_targets,
        "intent": detected_intent,
    }


def query_reading_focus(query_intent: str, page_type: str = "") -> str:
    if query_intent == "overview":
        return "workspace_overview"
    if query_intent == "compare":
        return "compare_claims"
    if query_intent == "timeline":
        return "timeline_evidence"
    if query_intent == "how_to":
        return "guide_steps" if page_type == "guide" else "procedural_chunks"
    if query_intent == "evidence":
        return "source_evidence"
    if page_type == "example":
        return "worked_examples"
    if page_type == "topic":
        return "topic_orientation"
    return "general_lookup"


def build_answer_guardrails(
    query_intent: str,
    page_status: str,
    page_type: str,
    review_ids: list[str],
    matched_claims: list[dict],
    matched_chunks: list[dict],
    timeline_sources: list[dict],
    source_trail: list[dict],
) -> dict:
    risk_flags: list[str] = []
    if review_ids:
        risk_flags.append("has_open_reviews")
    if page_status == "needs_review":
        risk_flags.append("page_needs_review")
    elif page_status == "disputed":
        risk_flags.append("page_disputed")
    elif page_status == "outdated":
        risk_flags.append("page_outdated")
    elif page_status == "draft":
        risk_flags.append("page_draft")
    if not matched_claims:
        risk_flags.append("no_matched_claims")
    if query_intent in {"how_to", "timeline", "evidence"} and not matched_chunks:
        risk_flags.append("no_matched_chunks")
    if query_intent == "timeline" and not timeline_sources:
        risk_flags.append("no_timeline_sources")
    if query_intent == "evidence" and not source_trail and not any(
        claim.get("source_refs") for claim in matched_claims
    ):
        risk_flags.append("weak_source_trace")

    can_answer_from_summary_only = (
        query_intent in {"lookup", "definition", "overview"}
        and page_type not in {"guide", "example"}
        and page_status not in {"needs_review", "disputed", "outdated"}
        and not review_ids
    )

    return {
        "can_answer_from_summary_only": can_answer_from_summary_only,
        "must_read_claims": query_intent in {"compare", "timeline", "evidence"},
        "must_read_chunks": query_intent in {"how_to", "timeline", "evidence"},
        "must_read_sources": query_intent in {"timeline", "evidence"},
        "cite_expectation": (
            "strong" if query_intent in {"timeline", "evidence"}
            else "light" if query_intent in {"compare", "how_to"}
            else "none"
        ),
        "risk_flags": risk_flags,
    }


def build_answer_handoff(query_intent: str, answer_guardrails: dict, page_type: str) -> dict:
    if query_intent in {"timeline", "evidence"}:
        answer_mode = "sources_first"
        recommended_read_order = [
            "retrieval_context.focus",
            "evidence_context.matched_claims",
            "evidence_context.matched_chunks",
            "evidence_context.timeline_sources" if query_intent == "timeline" else "evidence_context.source_trail",
            "page_context.summary",
        ]
    elif page_type == "guide":
        answer_mode = "chunks_first"
        recommended_read_order = [
            "retrieval_context.focus",
            "page_context.summary",
            "evidence_context.matched_chunks",
            "evidence_context.matched_claims",
        ]
    elif page_type == "example":
        answer_mode = "claims_first"
        recommended_read_order = [
            "retrieval_context.focus",
            "page_context.summary",
            "evidence_context.matched_claims",
            "evidence_context.matched_chunks",
        ]
    elif page_type == "topic" and query_intent in {"lookup", "definition", "overview"}:
        answer_mode = "summary_first"
        recommended_read_order = [
            "retrieval_context.focus",
            "page_context.summary",
            "evidence_context.matched_claims",
            "evidence_context.matched_chunks",
        ]
    elif query_intent == "how_to":
        answer_mode = "chunks_first"
        recommended_read_order = [
            "retrieval_context.focus",
            "evidence_context.matched_chunks",
            "evidence_context.matched_claims",
            "page_context.summary",
        ]
    elif query_intent == "compare":
        answer_mode = "claims_first"
        recommended_read_order = [
            "retrieval_context.focus",
            "evidence_context.matched_claims",
            "evidence_context.matched_chunks",
            "page_context.summary",
        ]
    else:
        answer_mode = "summary_first"
        recommended_read_order = [
            "page_context.summary",
            "evidence_context.matched_claims",
            "retrieval_context.focus",
        ]

    required_evidence_paths = []
    if answer_guardrails.get("must_read_claims"):
        required_evidence_paths.append("evidence_context.matched_claims")
    if answer_guardrails.get("must_read_chunks"):
        required_evidence_paths.append("evidence_context.matched_chunks")
    if answer_guardrails.get("must_read_sources"):
        required_evidence_paths.append(
            "evidence_context.timeline_sources" if query_intent == "timeline" else "evidence_context.source_trail"
        )

    risk_flags = answer_guardrails.get("risk_flags", [])
    if risk_flags:
        fallback_action = "answer_with_uncertainty"
    elif answer_guardrails.get("can_answer_from_summary_only"):
        fallback_action = "answer_from_summary_and_claims"
    else:
        fallback_action = "read_required_evidence_before_answering"

    return {
        "answer_mode": answer_mode,
        "recommended_read_order": recommended_read_order,
        "required_evidence_paths": required_evidence_paths,
        "should_cite_sources": answer_guardrails.get("cite_expectation") in {"light", "strong"},
        "should_surface_uncertainty": bool(risk_flags),
        "fallback_action": fallback_action,
    }


def select_top_matches(query_tokens: list[str], field_tokens: list[str], limit: int = 5) -> list[str]:
    if not query_tokens or not field_tokens:
        return []
    field_counter = Counter(field_tokens)
    matches = []
    for token in query_tokens:
        if field_counter.get(token, 0) > 0 and token not in matches:
            matches.append(token)
    return matches[:limit]


def score_claim_for_query(
    query_tokens: list[str],
    claim_record: dict,
    *,
    tokenize_for_search: object,
    select_top_matches: object,
) -> tuple[float, list[str]]:
    claim_tokens = tokenize_for_search(claim_record.get("text", ""))
    matched_tokens = select_top_matches(query_tokens, claim_tokens, limit=8)
    if not matched_tokens:
        return 0.0, []
    score = float(len(matched_tokens))
    return score, matched_tokens


def score_chunk_for_query(
    query_tokens: list[str],
    chunk_record: dict,
    *,
    tokenize_for_search: object,
    select_top_matches: object,
) -> tuple[float, list[str]]:
    chunk_text = "\n".join([chunk_record.get("summary", ""), chunk_record.get("text", "")])
    chunk_tokens = tokenize_for_search(chunk_text)
    matched_tokens = select_top_matches(query_tokens, chunk_tokens, limit=8)
    section_tokens = tokenize_for_search(
        "\n".join(
            [
                chunk_record.get("section_title", ""),
                chunk_record.get("parent_section_path", ""),
                chunk_record.get("section_path", ""),
                "\n".join(chunk_record.get("section_path_parts", []) if isinstance(chunk_record.get("section_path_parts", []), list) else []),
            ]
        )
    )
    section_matches = select_top_matches(query_tokens, section_tokens, limit=8)
    if not matched_tokens and not section_matches:
        return 0.0, []
    score = float(len(matched_tokens))
    score += float(len(section_matches)) * 0.45
    if chunk_record.get("section_title") and section_matches:
        score += 0.2
    score += 0.25 if chunk_record.get("char_count", 0) <= 600 else 0.0
    combined_matches = []
    for token in [*matched_tokens, *section_matches]:
        if token not in combined_matches:
            combined_matches.append(token)
    return score, combined_matches[:8]


def build_source_brief(source_ref: dict) -> dict:
    return {
        "source_id": source_ref.get("source_id"),
        "source_path": source_ref.get("source_path"),
        "normalized_path": source_ref.get("normalized_path"),
        "start_line": source_ref.get("start_line"),
        "end_line": source_ref.get("end_line"),
        "section_path": source_ref.get("section_path"),
        "chunk_id": source_ref.get("chunk_id"),
    }


def build_chunk_reading_brief(chunk_record: dict) -> dict:
    return {
        "chunk_id": chunk_record.get("chunk_id"),
        "section_path": chunk_record.get("section_path"),
        "start_line": chunk_record.get("start_line"),
        "end_line": chunk_record.get("end_line"),
        "summary": chunk_record.get("summary"),
        "text": chunk_record.get("text"),
        "previous_chunk": chunk_record.get("previous_chunk"),
        "next_chunk": chunk_record.get("next_chunk"),
        "source_id": chunk_record.get("source_id"),
        "source_path": chunk_record.get("source_path"),
        "normalized_path": chunk_record.get("normalized_path"),
    }


def build_timeline_sources(chunk_matches: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for chunk in chunk_matches:
        source_id = chunk.get("source_id")
        if not source_id:
            continue
        if source_id not in grouped:
            grouped[source_id] = {
                "source_id": source_id,
                "source_path": chunk.get("source_path"),
                "normalized_path": chunk.get("normalized_path"),
                "chunk_ids": [],
                "section_paths": [],
            }
        if chunk.get("chunk_id") and chunk["chunk_id"] not in grouped[source_id]["chunk_ids"]:
            grouped[source_id]["chunk_ids"].append(chunk["chunk_id"])
        if chunk.get("section_path") and chunk["section_path"] not in grouped[source_id]["section_paths"]:
            grouped[source_id]["section_paths"].append(chunk["section_path"])
    return sorted(grouped.values(), key=lambda item: item["source_id"])


def build_source_trail(claim_matches: list[dict], chunk_matches: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for claim in claim_matches:
        for source_ref in claim.get("source_refs", []):
            source_id = source_ref.get("source_id")
            if not source_id:
                continue
            if source_id not in grouped:
                grouped[source_id] = {
                    "source_id": source_id,
                    "source_path": source_ref.get("source_path"),
                    "normalized_path": source_ref.get("normalized_path"),
                    "claim_ids": [],
                    "chunk_ids": [],
                    "section_paths": [],
                }
            if claim.get("claim_id") and claim["claim_id"] not in grouped[source_id]["claim_ids"]:
                grouped[source_id]["claim_ids"].append(claim["claim_id"])
            chunk_id = source_ref.get("chunk_id")
            if chunk_id and chunk_id not in grouped[source_id]["chunk_ids"]:
                grouped[source_id]["chunk_ids"].append(chunk_id)
            section_path = source_ref.get("section_path")
            if section_path and section_path not in grouped[source_id]["section_paths"]:
                grouped[source_id]["section_paths"].append(section_path)

    for chunk in chunk_matches:
        source_id = chunk.get("source_id")
        if not source_id:
            continue
        if source_id not in grouped:
            grouped[source_id] = {
                "source_id": source_id,
                "source_path": chunk.get("source_path"),
                "normalized_path": chunk.get("normalized_path"),
                "claim_ids": [],
                "chunk_ids": [],
                "section_paths": [],
            }
        if chunk.get("chunk_id") and chunk["chunk_id"] not in grouped[source_id]["chunk_ids"]:
            grouped[source_id]["chunk_ids"].append(chunk["chunk_id"])
        if chunk.get("section_path") and chunk["section_path"] not in grouped[source_id]["section_paths"]:
            grouped[source_id]["section_paths"].append(chunk["section_path"])

    return sorted(
        grouped.values(),
        key=lambda item: (len(item["claim_ids"]), len(item["chunk_ids"]), item["source_id"]),
        reverse=True,
    )


def build_hierarchy_match_explanation(
    result: dict,
    matched_chunks: list[dict],
    *,
    parse_section_path: object,
    tokenize_for_search: object,
) -> dict:
    hierarchy_tokens = result.get("field_hits", {}).get("hierarchy", []) or []
    hierarchy_paths: list[str] = []
    matched_parent = False
    matched_leaf = False

    for chunk in matched_chunks:
        section_path = chunk.get("section_path")
        if section_path and section_path not in hierarchy_paths:
            hierarchy_paths.append(section_path)

    for source_ref in result.get("source_refs", []) or []:
        section_path = source_ref.get("section_path")
        if section_path and section_path not in hierarchy_paths:
            hierarchy_paths.append(section_path)
        for chunk_ref in source_ref.get("chunks", []) or []:
            chunk_section_path = chunk_ref.get("section_path")
            if chunk_section_path and chunk_section_path not in hierarchy_paths:
                hierarchy_paths.append(chunk_section_path)

    for section_path in hierarchy_paths:
        parsed = parse_section_path(section_path)
        section_parts = parsed.get("section_path_parts", [])
        if not section_parts:
            continue
        leaf_tokens = set(tokenize_for_search(section_parts[-1]))
        parent_tokens = set(tokenize_for_search(" ".join(section_parts[:-1])))
        if leaf_tokens.intersection(hierarchy_tokens):
            matched_leaf = True
        if parent_tokens.intersection(hierarchy_tokens):
            matched_parent = True

    if matched_parent and matched_leaf:
        anchor_reason = "matched_parent_and_leaf"
    elif matched_parent:
        anchor_reason = "matched_parent_only"
    elif matched_leaf:
        anchor_reason = "matched_leaf_only"
    else:
        anchor_reason = "matched_hierarchy_context"

    anchor_reason_text = {
        "matched_parent_and_leaf": "同时命中了父级路径和叶子标题，因此更偏向这个层级分支。",
        "matched_parent_only": "主要命中了父级路径，因此结果更偏向这个上层分类。",
        "matched_leaf_only": "主要命中了叶子标题，因此结果更偏向这个具体节点。",
        "matched_hierarchy_context": "命中了层级相关上下文，因此结果参考了章节路径信息。",
    }.get(anchor_reason, "命中了层级路径信息。")

    return {
        "matched_tokens": hierarchy_tokens,
        "matched_paths": hierarchy_paths[:5],
        "anchor_reason": anchor_reason,
        "anchor_reason_text": anchor_reason_text,
    }


def summarize_linked_page(page_record: dict, reason: str) -> dict:
    return {
        "page_id": page_record.get("page_id"),
        "title": page_record.get("title", ""),
        "page_path": page_record.get("page_path", ""),
        "type": page_record.get("type", ""),
        "status": page_record.get("status", ""),
        "canonical_id": page_record.get("canonical_id"),
        "summary": page_record.get("summary", ""),
        "reason": reason,
    }


def expand_related_pages_for_query_result(
    result: dict,
    page_records_by_id: dict[str, dict],
    page_links_index: dict,
    link_expansion: str,
    *,
    is_live_page_record: object,
) -> tuple[list[dict], dict]:
    if link_expansion == "off":
        return [], {
            "link_expansion_used": False,
            "link_expansion_reason": None,
            "linked_page_paths": [],
        }

    page_links = page_links_index.get("pages", {})
    entry = page_links.get(result.get("page_id"), {})
    if not entry:
        return [], {
            "link_expansion_used": False,
            "link_expansion_reason": None,
            "linked_page_paths": [],
        }

    limit = 3 if link_expansion == "auto" else 5
    linked_pages: list[dict] = []
    linked_page_paths: list[str] = []
    added_page_ids: set[str] = set()

    same_family_ids = []
    canonical_family = entry.get("canonical_family_id")
    if canonical_family:
        for candidate_page_id, candidate_entry in page_links.items():
            if candidate_page_id == result.get("page_id"):
                continue
            if candidate_entry.get("canonical_family_id") == canonical_family:
                same_family_ids.append(candidate_page_id)

    candidate_groups = [
        ("same_canonical_family", same_family_ids),
        ("outgoing_link", entry.get("outgoing_page_ids", [])),
        ("incoming_link", entry.get("incoming_page_ids", [])),
        ("related_page", entry.get("related_page_ids", [])),
    ]

    first_reason = None
    for reason, candidate_page_ids in candidate_groups:
        for candidate_page_id in candidate_page_ids:
            if candidate_page_id in added_page_ids:
                continue
            candidate_page = page_records_by_id.get(candidate_page_id)
            if candidate_page is None or not is_live_page_record(candidate_page):
                continue
            linked_pages.append(summarize_linked_page(candidate_page, reason))
            linked_page_paths.append(candidate_page.get("page_path", ""))
            added_page_ids.add(candidate_page_id)
            if first_reason is None:
                first_reason = reason
            if len(linked_pages) >= limit:
                return linked_pages, {
                    "link_expansion_used": True,
                    "link_expansion_reason": first_reason,
                    "linked_page_paths": linked_page_paths,
                }

    return linked_pages, {
        "link_expansion_used": bool(linked_pages),
        "link_expansion_reason": first_reason,
        "linked_page_paths": linked_page_paths,
    }


def build_result_reading_pack(
    result: dict,
    query_text: str,
    normalized_query: str,
    query_tokens: list[str],
    claim_records_by_id: dict[str, dict],
    chunk_records_by_id: dict[str, dict],
    page_records_by_id: dict[str, dict],
    page_links_index: dict,
    claim_limit: int,
    chunk_limit: int,
    query_intent: str,
    link_expansion: str,
    *,
    score_claim_for_query: object,
    build_source_brief: object,
    score_chunk_for_query: object,
    build_chunk_reading_brief: object,
    build_source_trail: object,
    build_timeline_sources: object,
    query_reading_focus: object,
    build_hierarchy_match_explanation: object,
    expand_related_pages_for_query_result: object,
    build_answer_guardrails: object,
    build_answer_handoff: object,
    query_answer_handoff_contract_version: str,
    page_type_profile: object,
) -> dict:
    claim_matches: list[dict] = []
    chunk_matches: list[dict] = []
    seen_chunk_ids: set[str] = set()

    for claim_id in result.get("claim_ids", []):
        claim_record = claim_records_by_id.get(claim_id)
        if claim_record is None:
            continue
        claim_score, claim_hits = score_claim_for_query(query_tokens, claim_record)
        if claim_score <= 0:
            continue

        claim_matches.append({
            "claim_id": claim_record["claim_id"],
            "text": claim_record.get("text", ""),
            "claim_type": claim_record.get("claim_type"),
            "status": claim_record.get("status"),
            "matched_tokens": claim_hits,
            "source_refs": [build_source_brief(item) for item in claim_record.get("source_refs", [])],
            "_score": (
                claim_score + (len(claim_record.get("source_refs", [])) * 0.25)
                if query_intent == "evidence"
                else claim_score + 0.4
                if query_intent == "compare" and claim_record.get("claim_type") in {"comparison", "evaluation", "causal"}
                else claim_score + 0.2
                if query_intent == "timeline" and claim_record.get("source_refs")
                else claim_score
            ),
        })

        for chunk_id in claim_record.get("chunk_ids", []):
            if chunk_id in seen_chunk_ids:
                continue
            chunk_record = chunk_records_by_id.get(chunk_id)
            if chunk_record is None:
                continue
            chunk_score, chunk_hits = score_chunk_for_query(query_tokens, chunk_record)
            if chunk_score <= 0:
                continue
            seen_chunk_ids.add(chunk_id)
            chunk_matches.append({
                "matched_tokens": chunk_hits,
                "_score": (
                    chunk_score + 0.5
                    if query_intent == "evidence" and chunk_record.get("source_id")
                    else chunk_score + 0.25
                    if query_intent == "timeline" and chunk_record.get("source_id")
                    else chunk_score
                ),
                **build_chunk_reading_brief(chunk_record),
            })

    claim_matches.sort(key=lambda item: item["_score"], reverse=True)
    chunk_matches.sort(key=lambda item: item["_score"], reverse=True)

    trimmed_claims = []
    for item in claim_matches[:claim_limit]:
        cleaned = dict(item)
        cleaned.pop("_score", None)
        trimmed_claims.append(cleaned)

    trimmed_chunks = []
    for item in chunk_matches[:chunk_limit]:
        cleaned = dict(item)
        cleaned.pop("_score", None)
        trimmed_chunks.append(cleaned)

    reading_depth = result.get("reading_depth", "standard")
    source_trail = build_source_trail(trimmed_claims, trimmed_chunks) if reading_depth == "deep" else []
    timeline_sources = build_timeline_sources(trimmed_chunks) if query_intent == "timeline" else []
    page_type = result.get("type", "")
    focus = query_reading_focus(query_intent, page_type=page_type)
    hierarchy_explanation = build_hierarchy_match_explanation(result, trimmed_chunks)
    linked_pages, link_expansion_context = expand_related_pages_for_query_result(
        result=result,
        page_records_by_id=page_records_by_id,
        page_links_index=page_links_index,
        link_expansion=link_expansion,
    )
    ranking_reasons = []
    if result.get("exact_match_reasons"):
        ranking_reasons.extend(result["exact_match_reasons"])
    if result.get("intent_boost_reason"):
        ranking_reasons.append(result["intent_boost_reason"])
    if hierarchy_explanation["matched_tokens"] or hierarchy_explanation["matched_paths"]:
        ranking_reasons.append(f"hierarchy_{hierarchy_explanation['anchor_reason']}")
    ranking_reasons.extend(sorted(result.get("field_scores", {}).keys()))
    answer_guardrails = build_answer_guardrails(
        query_intent=query_intent,
        page_status=result.get("status", ""),
        page_type=page_type,
        review_ids=result.get("review_ids", []),
        matched_claims=trimmed_claims,
        matched_chunks=trimmed_chunks,
        timeline_sources=timeline_sources,
        source_trail=source_trail,
    )
    risk_flags = answer_guardrails.get("risk_flags", [])
    if linked_pages and link_expansion_context.get("link_expansion_reason") in {"incoming_link"}:
        if "weak_link_expansion" not in risk_flags:
            risk_flags.append("weak_link_expansion")
    answer_handoff = build_answer_handoff(
        query_intent=query_intent,
        answer_guardrails=answer_guardrails,
        page_type=page_type,
    )
    return {
        "contract_version": query_answer_handoff_contract_version,
        "handoff_kind": "reading_pack",
        "page_summary": result.get("summary", ""),
        "query_intent": query_intent,
        "reading_depth": reading_depth,
        "matched_claims": trimmed_claims,
        "matched_chunks": trimmed_chunks,
        "source_trail": source_trail,
        "timeline_sources": timeline_sources,
        "linked_pages": linked_pages,
        "review_ids": result.get("review_ids", []),
        "focus": focus,
        "query": {
            "text": query_text,
            "normalized_text": normalized_query,
            "intent": query_intent,
            "reading_depth": reading_depth,
        },
        "page_context": {
            "page_id": result.get("page_id"),
            "title": result.get("title", ""),
            "page_path": result.get("page_path", ""),
            "type": result.get("type", ""),
            "page_type_profile": page_type_profile(result.get("type", "")),
            "status": result.get("status", ""),
            "summary": result.get("summary", ""),
            "canonical_id": result.get("canonical_id"),
            "aliases": result.get("aliases", []),
        },
        "retrieval_context": {
            "focus": focus,
            "matched_fields": sorted(result.get("field_hits", {}).keys()),
            "ranking_reasons": ranking_reasons,
            "review_ids": result.get("review_ids", []),
            "hierarchy_hits": hierarchy_explanation["matched_tokens"],
            "hierarchy_paths": hierarchy_explanation["matched_paths"],
            "hierarchy_anchor_reason": hierarchy_explanation["anchor_reason"],
            "hierarchy_anchor_reason_text": hierarchy_explanation["anchor_reason_text"],
            "link_expansion_used": link_expansion_context.get("link_expansion_used", False),
            "link_expansion_reason": link_expansion_context.get("link_expansion_reason"),
            "linked_page_paths": link_expansion_context.get("linked_page_paths", []),
        },
        "evidence_context": {
            "matched_claims": trimmed_claims,
            "matched_chunks": trimmed_chunks,
            "timeline_sources": timeline_sources,
            "source_trail": source_trail,
            "linked_pages": linked_pages,
        },
        "answer_guardrails": answer_guardrails,
        "answer_handoff": answer_handoff,
    }


def prepare_query_runtime_context(
    target: Path,
    query_text: str,
    intent: str | None,
    *,
    load_query_page_records: object,
    load_query_live_claim_records: object,
    load_chunk_records_by_id: object,
    load_alias_index: object,
    load_page_links_index: object,
    expand_query_with_alias_registry: object,
    ensure_query_documents: object,
    query_intent_choices: object,
) -> dict:
    page_records = load_query_page_records(target)
    live_claim_records = load_query_live_claim_records(target)
    claim_records_by_id = {record["claim_id"]: record for record in live_claim_records}
    page_records_by_id = {
        record["page_id"]: record
        for record in page_records
        if record.get("page_id")
    }
    chunk_records_by_id = load_chunk_records_by_id(target)
    alias_index = load_alias_index(target)
    page_links_index = load_page_links_index(target)
    normalized_query_payload = expand_query_with_alias_registry(query_text, alias_index)

    normalized_query = normalized_query_payload["normalized_query"]
    query_tokens = normalized_query_payload["query_tokens"]
    explicit_intent = str(intent or "").strip().lower()
    query_intent = explicit_intent if explicit_intent in query_intent_choices else normalized_query_payload["intent"]
    documents, document_source = ensure_query_documents(target, page_records, claim_records_by_id)

    return {
        "page_records": page_records,
        "page_records_by_id": page_records_by_id,
        "claim_records_by_id": claim_records_by_id,
        "chunk_records_by_id": chunk_records_by_id,
        "page_links_index": page_links_index,
        "normalized_query_payload": normalized_query_payload,
        "normalized_query": normalized_query,
        "query_tokens": query_tokens,
        "query_intent": query_intent,
        "documents": documents,
        "document_source": document_source,
    }


def compute_query_scoring_context(
    documents: list[dict],
    query_field_weights: dict[str, float],
    *,
    compute_document_frequency: object,
) -> dict:
    field_document_frequencies = {
        field_name: compute_document_frequency(
            [document["field_tokens"] for document in documents],
            field_name,
        )
        for field_name in query_field_weights
    }
    field_average_lengths = {
        field_name: (
            sum(len(document["field_tokens"].get(field_name, [])) for document in documents) / len(documents)
            if documents else 0.0
        )
        for field_name in query_field_weights
    }
    return {
        "field_document_frequencies": field_document_frequencies,
        "field_average_lengths": field_average_lengths,
    }


def build_scored_query_result(
    document: dict,
    *,
    query_tokens: list[str],
    normalized_query: str,
    normalized_query_payload: dict,
    query_intent: str,
    reading_depth: str,
    claim_limit: int,
    chunk_limit: int,
    link_expansion: str,
    documents: list[dict],
    claim_records_by_id: dict[str, dict],
    chunk_records_by_id: dict[str, dict],
    page_records_by_id: dict[str, dict],
    page_links_index: dict,
    query_field_weights: dict[str, float],
    bm25_score: object,
    query_intent_field_multiplier: object,
    select_top_matches: object,
    query_page_type_weight: object,
    query_page_status_weight: object,
    alias_match_boost: object,
    query_intent_page_type_boost: object,
    build_result_reading_pack: object,
    query_text: str,
    field_document_frequencies: dict[str, dict[str, int]],
    field_average_lengths: dict[str, float],
) -> dict | None:
    page_record = document["page_record"]
    field_scores: dict[str, float] = {}
    weighted_field_sum = 0.0
    field_hits: dict[str, list[str]] = {}

    for field_name, field_weight in query_field_weights.items():
        document_tokens = document["field_tokens"].get(field_name, [])
        raw_score = bm25_score(
            query_tokens=query_tokens,
            document_tokens=document_tokens,
            document_frequency=field_document_frequencies[field_name],
            total_documents=len(documents),
            average_length=field_average_lengths[field_name],
        )
        if raw_score <= 0:
            continue
        intent_field_multiplier = query_intent_field_multiplier(query_intent, field_name)
        weighted_score = raw_score * field_weight * intent_field_multiplier
        field_scores[field_name] = round(weighted_score, 6)
        weighted_field_sum += weighted_score
        field_hits[field_name] = select_top_matches(query_tokens, document_tokens)

    if weighted_field_sum <= 0:
        return None

    page_type_weight = query_page_type_weight(page_record)
    page_status_weight = query_page_status_weight(page_record)
    exact_match_boost, exact_match_reasons = alias_match_boost(
        page_record=page_record,
        normalized_query=normalized_query,
        alias_hits=normalized_query_payload["alias_hits"],
    )
    intent_boost, intent_boost_reason = query_intent_page_type_boost(query_intent, page_record)
    final_score = weighted_field_sum * page_type_weight * page_status_weight * exact_match_boost * intent_boost
    result_record = {
        "page_id": page_record["page_id"],
        "title": page_record.get("title", ""),
        "page_path": page_record.get("page_path", ""),
        "type": page_record.get("type", ""),
        "canonical_id": page_record.get("canonical_id"),
        "status": page_record.get("status", ""),
        "summary": page_record.get("summary", ""),
        "aliases": page_record.get("aliases", []),
        "claim_ids": page_record.get("claim_ids", []),
        "review_ids": page_record.get("review_ids", []),
        "score": round(final_score, 6),
        "field_scores": field_scores,
        "field_hits": field_hits,
        "page_type_weight": page_type_weight,
        "page_status_weight": page_status_weight,
        "exact_match_boost": round(exact_match_boost, 4),
        "exact_match_reasons": exact_match_reasons,
        "intent": query_intent,
        "intent_boost": round(intent_boost, 4),
        "intent_boost_reason": intent_boost_reason,
        "reading_depth": reading_depth,
    }
    result_record["reading_pack"] = build_result_reading_pack(
        result=result_record,
        query_text=query_text,
        normalized_query=normalized_query,
        query_tokens=query_tokens,
        claim_records_by_id=claim_records_by_id,
        chunk_records_by_id=chunk_records_by_id,
        page_records_by_id=page_records_by_id,
        page_links_index=page_links_index,
        claim_limit=claim_limit,
        chunk_limit=chunk_limit,
        query_intent=query_intent,
        link_expansion=link_expansion,
    )
    return result_record
