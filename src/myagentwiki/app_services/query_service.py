from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class QueryRequest:
    target: Path
    text: str
    limit: int
    reading_depth: str
    claim_limit: int | None
    chunk_limit: int | None
    intent: str | None
    link_expansion: str
    answer_ready_format: str | None = None


@dataclass(frozen=True)
class QueryServiceDeps:
    reading_depth_limits: dict[str, dict[str, int]]
    link_expansion_choices: tuple[str, ...]
    build_query_payload: Callable[..., dict]
    build_answer_ready_payload: Callable[[dict], dict]
    render_answer_ready_prompt: Callable[[dict], str]
    build_answer_ready_messages: Callable[[dict], list[dict]]
    render_answer_ready_chatml: Callable[[dict], str]


def normalize_query_request(request: QueryRequest, deps: QueryServiceDeps) -> QueryRequest:
    reading_depth = str(request.reading_depth or "standard").strip().lower()
    if reading_depth not in deps.reading_depth_limits:
        reading_depth = "standard"

    link_expansion = str(request.link_expansion or "auto").strip().lower()
    if link_expansion not in deps.link_expansion_choices:
        link_expansion = "auto"

    depth_limits = deps.reading_depth_limits[reading_depth]
    claim_limit = request.claim_limit if request.claim_limit is not None else depth_limits["claim_limit"]
    chunk_limit = request.chunk_limit if request.chunk_limit is not None else depth_limits["chunk_limit"]
    answer_ready_format = None
    if request.answer_ready_format is not None:
        answer_ready_format = str(request.answer_ready_format or "summary").strip().lower()

    return QueryRequest(
        target=request.target,
        text=request.text,
        limit=request.limit,
        reading_depth=reading_depth,
        claim_limit=claim_limit,
        chunk_limit=chunk_limit,
        intent=request.intent,
        link_expansion=link_expansion,
        answer_ready_format=answer_ready_format,
    )


def run_query_service(request: QueryRequest, deps: QueryServiceDeps) -> dict:
    normalized_request = normalize_query_request(request, deps)
    return deps.build_query_payload(
        target=normalized_request.target,
        query_text=normalized_request.text,
        limit=normalized_request.limit,
        claim_limit=normalized_request.claim_limit,
        chunk_limit=normalized_request.chunk_limit,
        reading_depth=normalized_request.reading_depth,
        intent=normalized_request.intent,
        link_expansion=normalized_request.link_expansion,
    )


def run_answer_ready_query_service(request: QueryRequest, deps: QueryServiceDeps) -> tuple[dict, dict, str]:
    normalized_request = normalize_query_request(request, deps)
    query_payload = run_query_service(normalized_request, deps)
    answer_ready_payload = deps.build_answer_ready_payload(query_payload)
    answer_ready_format = normalized_request.answer_ready_format or "summary"
    if answer_ready_format == "prompt":
        answer_ready_payload["prompt_text"] = deps.render_answer_ready_prompt(answer_ready_payload)
    elif answer_ready_format == "messages":
        answer_ready_payload["messages"] = deps.build_answer_ready_messages(answer_ready_payload)
    elif answer_ready_format == "chatml":
        answer_ready_payload["messages"] = deps.build_answer_ready_messages(answer_ready_payload)
        answer_ready_payload["chatml_text"] = deps.render_answer_ready_chatml(answer_ready_payload)
    return query_payload, answer_ready_payload, answer_ready_format


def build_query_payload_via_runtime(
    *,
    target: Path,
    query_text: str,
    limit: int,
    claim_limit: int,
    chunk_limit: int,
    reading_depth: str,
    link_expansion: str,
    workspace_summary: dict,
    contract_version: str,
    query_field_weights: dict[str, float],
    query_intent_field_multipliers: dict[str, dict[str, float]],
    query_page_type_weights: dict[str, float],
    query_page_status_weights: dict[str, float],
    query_exact_match_max_boost: float,
    prepare_query_runtime_context: Callable[..., dict],
    compute_query_scoring_context: Callable[..., dict],
    build_scored_query_result: Callable[..., dict | None],
    bm25_score: Callable[..., float],
    query_intent_field_multiplier: Callable[[str, str], float],
    select_top_matches: Callable[[list[str], list[str], int], list[str]],
    query_page_type_weight: Callable[[dict], float],
    query_page_status_weight: Callable[[dict], float],
    alias_match_boost: Callable[[dict, str, list[dict]], tuple[float, list[str]]],
    query_intent_page_type_boost: Callable[[str, dict], tuple[float, str | None]],
    build_result_reading_pack: Callable[..., dict],
    compute_document_frequency: Callable[..., dict[str, int]],
) -> dict:
    runtime_context = prepare_query_runtime_context(
        target=target,
        query_text=query_text,
    )
    normalized_query_payload = runtime_context["normalized_query_payload"]
    normalized_query = runtime_context["normalized_query"]
    query_tokens = runtime_context["query_tokens"]
    query_intent = runtime_context["query_intent"]
    documents = runtime_context["documents"]
    document_source = runtime_context["document_source"]
    claim_records_by_id = runtime_context["claim_records_by_id"]
    chunk_records_by_id = runtime_context["chunk_records_by_id"]
    page_records_by_id = runtime_context["page_records_by_id"]
    page_links_index = runtime_context["page_links_index"]

    scoring_context = compute_query_scoring_context(
        documents,
        query_field_weights,
        compute_document_frequency=compute_document_frequency,
    )
    field_document_frequencies = scoring_context["field_document_frequencies"]
    field_average_lengths = scoring_context["field_average_lengths"]

    scored_results = []
    for document in documents:
        result_record = build_scored_query_result(
            document,
            query_tokens=query_tokens,
            normalized_query=normalized_query,
            normalized_query_payload=normalized_query_payload,
            query_intent=query_intent,
            reading_depth=reading_depth,
            claim_limit=claim_limit,
            chunk_limit=chunk_limit,
            link_expansion=link_expansion,
            documents=documents,
            claim_records_by_id=claim_records_by_id,
            chunk_records_by_id=chunk_records_by_id,
            page_records_by_id=page_records_by_id,
            page_links_index=page_links_index,
            query_field_weights=query_field_weights,
            bm25_score=bm25_score,
            query_intent_field_multiplier=query_intent_field_multiplier,
            select_top_matches=select_top_matches,
            query_page_type_weight=query_page_type_weight,
            query_page_status_weight=query_page_status_weight,
            alias_match_boost=alias_match_boost,
            query_intent_page_type_boost=query_intent_page_type_boost,
            build_result_reading_pack=build_result_reading_pack,
            query_text=query_text,
            field_document_frequencies=field_document_frequencies,
            field_average_lengths=field_average_lengths,
        )
        if result_record is not None:
            scored_results.append(result_record)

    scored_results.sort(key=lambda item: (item["score"], item["title"]), reverse=True)
    return {
        "workspace": str(target),
        "workspace_summary": workspace_summary,
        "contract_version": contract_version,
        "query": query_text,
        "normalized_query": normalized_query,
        "expanded_query": normalized_query_payload["expanded_query"],
        "query_tokens": query_tokens,
        "intent": query_intent,
        "reading_depth": reading_depth,
        "link_expansion": link_expansion,
        "alias_hits": normalized_query_payload["alias_hits"],
        "canonical_targets": normalized_query_payload["canonical_targets"],
        "weights": {
            "fields": query_field_weights,
            "intent_field_multipliers": query_intent_field_multipliers,
            "page_types": query_page_type_weights,
            "page_status": query_page_status_weights,
            "exact_match_max_boost": query_exact_match_max_boost,
        },
        "reading_depth_limits": {
            "claim_limit": claim_limit,
            "chunk_limit": chunk_limit,
        },
        "document_source": document_source,
        "results": scored_results[:limit],
        "summary": {
            "candidate_page_count": len(documents),
            "matched_page_count": len(scored_results),
            "returned_page_count": min(limit, len(scored_results)),
        },
    }
