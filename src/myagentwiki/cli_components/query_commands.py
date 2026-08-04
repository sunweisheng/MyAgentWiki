from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..debug_trace import entity_reference, trace_lineage, trace_step
from ..app_services.query_service import (
    QueryRequest,
    QueryServiceDeps,
    build_query_payload_via_runtime,
    run_answer_ready_query_service,
    run_query_service,
)
from .result import CommandResult


@dataclass(frozen=True)
class QueryCliDeps:
    provider: object
    ensure_workspace_schema_supported: object
    render_workspace_summary_message: object
    render_answer_ready_message: object
    format_claim_type_label: object
    reading_depth_limits: dict[str, dict[str, int]]
    link_expansion_choices: tuple[str, ...]
    build_query_payload: object
    build_answer_ready_payload: object
    render_answer_ready_prompt: object
    build_answer_ready_messages: object
    render_answer_ready_chatml: object


def build_query_payload(deps: QueryCliDeps, **kwargs) -> dict:
    target = kwargs["target"]
    query_text = kwargs["query_text"]
    limit = kwargs["limit"]
    claim_limit = kwargs["claim_limit"]
    chunk_limit = kwargs["chunk_limit"]
    reading_depth = kwargs.get("reading_depth", "standard")
    intent = kwargs.get("intent")
    link_expansion = kwargs.get("link_expansion", "auto")

    provider: Any = deps.provider
    return build_query_payload_via_runtime(
        target=target,
        query_text=query_text,
        limit=limit,
        claim_limit=claim_limit,
        chunk_limit=chunk_limit,
        reading_depth=reading_depth,
        link_expansion=link_expansion,
        workspace_summary=provider.build_workspace_summary(target),
        contract_version=provider.QUERY_ANSWER_HANDOFF_CONTRACT_VERSION,
        query_field_weights=provider.QUERY_FIELD_WEIGHTS,
        query_intent_field_multipliers=provider.QUERY_INTENT_FIELD_MULTIPLIERS,
        query_page_type_weights=provider.QUERY_PAGE_TYPE_WEIGHTS,
        query_page_status_weights=provider.QUERY_PAGE_STATUS_WEIGHTS,
        query_exact_match_max_boost=provider.QUERY_EXACT_MATCH_MAX_BOOST,
        prepare_query_runtime_context=lambda **inner_kwargs: provider.prepare_query_runtime_context_helper(
            inner_kwargs["target"],
            inner_kwargs["query_text"],
            intent,
            load_query_page_records=lambda workspace_target: provider.repo_load_query_page_records(
                workspace_target,
                load_jsonl=provider.load_jsonl,
                ensure_page_lifecycle_defaults=provider.ensure_page_lifecycle_defaults,
            ),
            load_query_live_claim_records=lambda workspace_target: provider.repo_load_query_live_claim_records(
                workspace_target,
                load_jsonl=provider.load_jsonl,
                ensure_claim_lifecycle_defaults=provider.ensure_claim_lifecycle_defaults,
                filter_live_claim_records=provider.filter_live_claim_records,
            ),
            load_chunk_records_by_id=lambda workspace_target: provider.repo_load_chunk_records_by_id(
                workspace_target,
                load_jsonl=provider.load_jsonl,
            ),
            load_alias_index=provider.load_alias_index,
            load_page_links_index=provider.load_page_links_index,
            expand_query_with_alias_registry=provider.expand_query_with_alias_registry,
            ensure_query_documents=provider.ensure_query_documents,
            query_intent_choices=provider.QUERY_INTENT_CHOICES,
        ),
        compute_query_scoring_context=provider.compute_query_scoring_context_helper,
        build_scored_query_result=provider.build_scored_query_result_helper,
        bm25_score=provider.bm25_score,
        query_intent_field_multiplier=provider.query_intent_field_multiplier,
        select_top_matches=provider.select_top_matches,
        query_page_type_weight=provider.query_page_type_weight,
        query_page_status_weight=provider.query_page_status_weight,
        alias_match_boost=provider.alias_match_boost,
        query_intent_page_type_boost=provider.query_intent_page_type_boost,
        build_result_reading_pack=provider.build_result_reading_pack,
        compute_document_frequency=provider.compute_document_frequency,
    )


def build_query_service_deps(deps: QueryCliDeps) -> QueryServiceDeps:
    return QueryServiceDeps(
        reading_depth_limits=deps.reading_depth_limits,
        link_expansion_choices=deps.link_expansion_choices,
        build_query_payload=deps.build_query_payload,
        build_answer_ready_payload=deps.build_answer_ready_payload,
        render_answer_ready_prompt=deps.render_answer_ready_prompt,
        build_answer_ready_messages=deps.build_answer_ready_messages,
        render_answer_ready_chatml=deps.render_answer_ready_chatml,
    )


def build_query_request(args: argparse.Namespace, target: Path) -> QueryRequest:
    return QueryRequest(
        target=target,
        text=args.text,
        limit=args.limit,
        reading_depth=getattr(args, "reading_depth", "standard"),
        claim_limit=getattr(args, "claim_limit", None),
        chunk_limit=getattr(args, "chunk_limit", None),
        intent=getattr(args, "intent", None),
        link_expansion=getattr(args, "link_expansion", "auto"),
        answer_ready_format=getattr(args, "format", "summary"),
    )


def render_query_summary_line(payload: dict) -> str:
    return (
        "Summary: "
        f"candidates={payload['summary']['candidate_page_count']}, "
        f"matched={payload['summary']['matched_page_count']}, "
        f"returned={payload['summary']['returned_page_count']}"
    )


def render_answer_ready_result(
    deps: QueryCliDeps,
    *,
    target: Path,
    query_payload: dict,
    answer_ready_payload: dict,
    answer_ready_format: str,
    as_json_summary: bool,
) -> CommandResult:
    if as_json_summary:
        return CommandResult(
            payload=answer_ready_payload,
            message=deps.render_workspace_summary_message(
                "Answer-ready query completed.",
                target_dir=target,
                extra_lines=[
                    f"Query: {query_payload['query']}",
                    f"Intent: {query_payload['intent']}",
                    render_query_summary_line(query_payload),
                ],
            ),
        )
    if answer_ready_format == "prompt":
        return CommandResult(payload=answer_ready_payload, message=answer_ready_payload["prompt_text"])
    if answer_ready_format == "messages":
        return CommandResult(
            payload=answer_ready_payload,
            message=json.dumps(answer_ready_payload["messages"], ensure_ascii=False, indent=2),
        )
    if answer_ready_format == "chatml":
        return CommandResult(payload=answer_ready_payload, message=answer_ready_payload["chatml_text"])
    return CommandResult(
        payload=answer_ready_payload,
        message=deps.render_workspace_summary_message(
            "Answer-ready query completed.",
            target_dir=target,
            extra_lines=[
                f"Query: {query_payload['query']}",
                f"Intent: {query_payload['intent']}",
                "",
                deps.render_answer_ready_message(answer_ready_payload),
            ],
        ),
    )


def command_query(deps: QueryCliDeps, args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    deps.ensure_workspace_schema_supported(target)
    service_deps = build_query_service_deps(deps)
    request = build_query_request(args, target)
    with trace_step("query.search", kind="query_stage", input_data=request) as query_step:
        payload = run_query_service(request, service_deps)
        query_step.set_output(payload)
        trace_lineage(
            operation="generated",
            reason="query_ranked_workspace_pages",
            inputs=lambda: [entity_reference("query", payload["normalized_query"], value={
                "query": payload["query"],
                "normalized_query": payload["normalized_query"],
                "expanded_query": payload["expanded_query"],
                "intent": payload["intent"],
            })],
            outputs=lambda: [
                entity_reference(
                    "query_result_page",
                    str(result.get("page_id")),
                    value=result,
                    path=str(result.get("page_path", "")),
                )
                for result in payload["results"]
            ],
            details=payload.get("summary", {}),
            snapshot_name="query_ranked_results",
        )

    if getattr(args, "answer_ready", False):
        _, answer_ready_payload, answer_ready_format = run_answer_ready_query_service(request, service_deps)
        return render_answer_ready_result(
            deps,
            target=target,
            query_payload=payload,
            answer_ready_payload=answer_ready_payload,
            answer_ready_format=answer_ready_format,
            as_json_summary=bool(args.json),
        )

    if args.json:
        return CommandResult(
            payload=payload,
            message=deps.render_workspace_summary_message(
                "Query completed.",
                target_dir=target,
                extra_lines=[
                    f"Query: {payload['query']}",
                    f"Intent: {payload['intent']}",
                    render_query_summary_line(payload),
                ],
            ),
        )

    if not payload["results"]:
        return CommandResult(
            payload=payload,
            message=deps.render_workspace_summary_message(
                f"No wiki results matched query: {args.text}",
                target_dir=target,
                extra_lines=[
                    f"Intent: {payload['intent']}",
                    render_query_summary_line(payload),
                ],
            ),
        )

    lines = [
        deps.render_workspace_summary_message(
            "Query completed.",
            target_dir=target,
            extra_lines=[
                f'Query: {payload["query"]}',
                f'Normalized: {payload["normalized_query"]}',
                f'Expanded: {payload["expanded_query"]}',
                f'Intent: {payload["intent"]}',
                render_query_summary_line(payload),
                "",
                "Top Results:",
            ],
        )
    ]
    for index, result in enumerate(payload["results"], start=1):
        lines.append(
            f"{index}. {result['title']} [{result['type']}, status={result['status']}, score={result['score']:.4f}]"
        )
        lines.append(f"   path: {result['page_path']}")
        lines.append(f"   summary: {result['summary']}")
        if result["field_scores"]:
            explanation = ", ".join(
                f"{field}={score:.3f}"
                for field, score in sorted(result["field_scores"].items(), key=lambda item: item[1], reverse=True)
            )
            lines.append(f"   field_scores: {explanation}")
        if result.get("exact_match_reasons"):
            lines.append(
                f"   exact_match_boost: {result['exact_match_boost']:.3f} ({'/'.join(result['exact_match_reasons'])})"
            )
        if result.get("intent_boost_reason"):
            lines.append(
                f"   intent_boost: {result['intent_boost']:.3f} ({result['intent_boost_reason']})"
            )
        if result["field_hits"]:
            hit_explanation = ", ".join(
                f"{field}:{'/'.join(tokens)}"
                for field, tokens in result["field_hits"].items()
                if tokens
            )
            if hit_explanation:
                lines.append(f"   hits: {hit_explanation}")
        reading_pack = result.get("reading_pack", {})
        retrieval_context = reading_pack.get("retrieval_context", {})
        hierarchy_hits = retrieval_context.get("hierarchy_hits", [])
        hierarchy_paths = retrieval_context.get("hierarchy_paths", [])
        hierarchy_anchor_reason = retrieval_context.get("hierarchy_anchor_reason")
        hierarchy_anchor_reason_text = retrieval_context.get("hierarchy_anchor_reason_text")
        if hierarchy_hits or hierarchy_paths:
            hierarchy_explanation_parts = []
            if hierarchy_hits:
                hierarchy_explanation_parts.append(f"hits={'/'.join(hierarchy_hits)}")
            if hierarchy_paths:
                hierarchy_explanation_parts.append(f"paths={' | '.join(hierarchy_paths)}")
            if hierarchy_anchor_reason_text:
                hierarchy_explanation_parts.append(f"reason={hierarchy_anchor_reason_text}")
            elif hierarchy_anchor_reason:
                hierarchy_explanation_parts.append(f"reason={hierarchy_anchor_reason}")
            lines.append(f"   hierarchy: {'; '.join(hierarchy_explanation_parts)}")
        matched_claims = reading_pack.get("matched_claims", [])
        matched_chunks = reading_pack.get("matched_chunks", [])
        if matched_claims:
            lines.append("   matched_claims:")
            for claim in matched_claims:
                lines.append(
                    f"     - {claim['claim_id']} {deps.format_claim_type_label(claim.get('claim_type'))} "
                    f"{claim['text']} (hits={'/'.join(claim.get('matched_tokens', []))})"
                )
        if matched_chunks:
            lines.append("   matched_chunks:")
            for chunk in matched_chunks:
                lines.append(
                    f"     - {chunk['chunk_id']} {chunk['section_path']} "
                    f"(lines {chunk['start_line']}-{chunk['end_line']}, hits={'/'.join(chunk.get('matched_tokens', []))})"
                )
                lines.append(f"       prev={chunk.get('previous_chunk')} next={chunk.get('next_chunk')}")
        source_trail = reading_pack.get("source_trail", [])
        if source_trail:
            lines.append("   source_trail:")
            for source in source_trail:
                lines.append(
                    f"     - {source['source_id']} "
                    f"(claims={len(source.get('claim_ids', []))}, chunks={len(source.get('chunk_ids', []))}) "
                    f"{source.get('source_path')}"
                )
    return CommandResult(payload=payload, message="\n".join(lines))


def command_answer_query(deps: QueryCliDeps, args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    deps.ensure_workspace_schema_supported(target)
    service_deps = build_query_service_deps(deps)
    request = build_query_request(args, target)
    with trace_step("query.answer_ready", kind="query_stage", input_data=request) as query_step:
        query_payload, answer_ready_payload, answer_ready_format = run_answer_ready_query_service(request, service_deps)
        query_step.set_output({
            "query_payload": query_payload,
            "answer_ready_payload": answer_ready_payload,
            "answer_ready_format": answer_ready_format,
        })
        trace_lineage(
            operation="generated",
            reason="query_reading_pack_prepared_for_answer",
            inputs=lambda: [
                entity_reference(
                    "query_result_page",
                    str(result.get("page_id")),
                    value=result,
                    path=str(result.get("page_path", "")),
                )
                for result in query_payload["results"]
            ],
            outputs=lambda: [entity_reference("answer_ready_payload", query_payload["normalized_query"], value=answer_ready_payload)],
            snapshot_name="query_answer_ready_payload",
        )
    return render_answer_ready_result(
        deps,
        target=target,
        query_payload=query_payload,
        answer_ready_payload=answer_ready_payload,
        answer_ready_format=answer_ready_format,
        as_json_summary=bool(args.json),
    )
