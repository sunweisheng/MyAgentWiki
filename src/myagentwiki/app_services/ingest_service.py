from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import os
from pathlib import Path
from typing import Any, Callable

from ..debug_trace import (
    current_debug_tracer,
    entity_reference,
    file_snapshot,
    trace_lineage,
    trace_step,
)


@dataclass(frozen=True)
class IngestRequest:
    target_dir: str | None
    disable_insecure_download_retry: bool


@dataclass(frozen=True)
class IngestServiceDeps:
    build_context: Callable[[IngestRequest], "IngestContext"]
    run_registration_and_normalization_stage: Callable[["IngestContext", IngestRequest], None]
    run_structure_chunk_claim_stage: Callable[["IngestContext", IngestRequest], None]
    run_page_finalize_stage: Callable[["IngestContext", IngestRequest], object]


@dataclass(frozen=True)
class IngestContextDeps:
    ensure_workspace_schema_supported: Callable[[Path], None]
    load_workspace_config: Callable[[Path], dict[str, Any]]
    load_post_ingest_review_auto_config: Callable[[dict[str, Any]], dict[str, Any]]
    load_semantic_task_config: Callable[[dict[str, Any], str], Any]
    load_readable_concept_render_config: Callable[[dict[str, Any]], dict[str, Any]]
    load_page_render_config: Callable[[dict[str, Any], str], dict[str, Any]]
    resolve_workspace_raw_dir: Callable[[Path], Path]
    load_existing_sources: Callable[[Path], list[dict]]
    load_existing_normalized_by_source: Callable[[Path], dict[str, dict]]
    load_existing_structured_source_ids: Callable[..., set[str]]
    load_existing_chunked_by_source: Callable[[Path], dict[str, dict]]
    load_existing_claim_state: Callable[[Path], tuple[list[dict], list[dict], dict[str, dict], dict[str, dict], dict[str, dict]]]
    load_existing_review_state: Callable[[Path], tuple[list[dict], list[dict], dict[str, dict], dict[str, dict]]]
    build_similarity_bucket: Callable[[str], str]
    rebuild_claim_similarity_index: Callable[[list[dict]], Any]
    build_latest_source_record_by_path: Callable[[list[dict]], dict[str, dict]]
    structure_blocks_rel_path: Path
    evidence_blocks_rel_path: Path
    knowledge_units_rel_path: Path
    task_id_factory: Callable[[], str]


@dataclass
class IngestContext:
    target: Path
    config: dict[str, Any]
    post_ingest_config: dict[str, Any]
    document_analysis_config: Any
    claim_candidate_quality_config: Any
    claim_role_config: Any
    page_intent_config: Any
    readable_concept_render_config: dict[str, Any]
    overview_render_config: dict[str, Any]
    raw_dir: Path
    sources_path: Path
    ingest_state_path: Path
    normalized_path: Path
    structure_blocks_path: Path
    evidence_blocks_path: Path
    knowledge_units_path: Path
    chunks_path: Path
    claims_path: Path
    reviews_path: Path
    error_log_path: Path
    pages_path: Path
    existing_sources: list[dict]
    existing_by_hash: dict[str, dict]
    sources_by_id: dict[str, dict]
    latest_source_by_path: dict[str, dict]
    existing_normalized: dict[str, dict]
    existing_structured_source_ids: set[str]
    existing_chunked: dict[str, dict]
    claims_by_id: dict[str, dict]
    historical_claims_by_id: dict[str, dict]
    claims_by_normalized_text: dict[str, dict]
    claims_by_similarity_bucket: dict[str, list[dict]]
    claim_similarity_index: Any
    existing_reviews: dict[str, dict]
    historical_reviews_by_id: dict[str, dict]
    task_id: str
    created_sources: list[dict] = field(default_factory=list)
    skipped_sources: list[dict] = field(default_factory=list)
    normalized_sources: list[dict] = field(default_factory=list)
    structured_sources: list[dict] = field(default_factory=list)
    chunked_sources: list[dict] = field(default_factory=list)
    claimed_sources: list[dict] = field(default_factory=list)
    review_items: list[dict] = field(default_factory=list)
    error_items: list[dict] = field(default_factory=list)
    generated_pages: list[dict] = field(default_factory=list)
    reingested_source_ids: set[str] = field(default_factory=set)
    purged_claim_ids: set[str] = field(default_factory=set)
    purged_review_ids: set[str] = field(default_factory=set)
    active_source_ids: set[str] = field(default_factory=set)
    claims_created_by_source: dict[str, int] = field(default_factory=dict)
    semantic_claim_updates_applied: bool = False
    normalized_records: list[dict] | None = None


@dataclass(frozen=True)
class IngestRegistrationDeps:
    collect_files: Callable[[Path], list[Path]]
    file_sha256: Callable[[Path], str]
    infer_source_type: Callable[[Path], str]
    build_source_version_group_from_source_path: Callable[[str], str]
    replace_source_scoped_jsonl_records: Callable[[Path, str, list[dict]], None]
    purge_source_from_claims: Callable[..., tuple[set[str], set[str]]]
    purge_deleted_claims_from_reviews: Callable[..., tuple[set[str], set[str]]]
    refresh_claim_similarity_state: Callable[[IngestContext, list[dict]], None]
    utc_now_iso: Callable[[], str]
    replace_jsonl_record: Callable[[Path, str, str, dict], None]
    build_source_id: Callable[[Path, Path, str], str]
    build_source_version_group: Callable[[Path, Path], str]
    append_jsonl: Callable[[Path, dict], None]
    load_jsonl: Callable[[Path], list[dict]]
    load_source_records: Callable[[Path], list[dict]]
    load_normalized_records: Callable[[Path], list[dict]]
    normalize_source_record: Callable[..., dict | None]
    normalized_record_is_current: Callable[[dict], bool]
    append_error_record: Callable[..., dict]
    run_semantic_batch_task: Callable[..., None]
    apply_document_analysis_decisions_to_normalized_records: Callable[..., list[dict]]


@dataclass(frozen=True)
class IngestStructureClaimDeps:
    compile_structure_knowledge_records: Callable[[dict, str], dict]
    replace_source_scoped_jsonl_records: Callable[[Path, str, list[dict]], None]
    chunk_normalized_record: Callable[[Path, dict], dict | None]
    replace_jsonl_records_by_filter: Callable[..., None]
    utc_now_iso: Callable[[], str]
    replace_jsonl_record: Callable[[Path, str, str, dict], None]
    load_normalized_records: Callable[[Path], list[dict]]
    load_chunk_records_by_source: Callable[[Path], dict[str, list[dict]]]
    load_active_knowledge_units_by_source: Callable[[Path], dict[str, list[dict]]]
    load_current_claim_records: Callable[[Path], list[dict]]
    source_claim_stage_completed: Callable[[dict], bool]
    choose_active_source_ids: Callable[[dict[str, dict]], set[str]]
    build_claim_candidates_for_source: Callable[..., list[dict]]
    merge_claim_records: Callable[[dict, dict], dict]
    write_claim_file: Callable[[Path, dict], str]
    build_similarity_bucket: Callable[[str], str]
    collect_claim_review_candidate_ids: Callable[..., list[str] | set[str]]
    has_negation: Callable[[str], bool]
    claims_are_similar_for_review: Callable[[str, str], bool]
    build_review_record: Callable[..., dict]
    append_jsonl: Callable[[Path, dict], None]
    append_error_record: Callable[..., dict]
    index_claim_similarity_tokens: Callable[[Any, dict], None]
    persist_ordered_claim_state: Callable[..., list[dict]]
    ensure_claim_lifecycle_defaults: Callable[[dict], dict]
    run_semantic_batch_task: Callable[..., None]
    apply_claim_candidate_quality_decisions_to_claim_records: Callable[..., tuple[list[dict], set[str], Any]]
    apply_claim_role_decisions_to_claim_records: Callable[..., list[dict]]
    refresh_claim_state_from_records: Callable[[IngestContext, list[dict]], None]
    persist_ordered_review_state: Callable[..., list[dict]]
    write_review_file: Callable[[Path, dict], str]


@dataclass(frozen=True)
class IngestPageFinalizeDeps:
    maybe_build_skipped_page_regeneration_result: Callable[[IngestContext], object | None]
    load_existing_pages: Callable[[Path], list[dict]]
    load_chunk_records: Callable[[Path], list[dict]]
    load_normalized_records_by_source: Callable[[Path], dict[str, dict]]
    load_source_records: Callable[[Path], list[dict]]
    apply_page_alias_overrides_to_records: Callable[[Path, list[dict]], list[dict]]
    build_ordered_claim_state_records: Callable[..., list[dict]]
    persist_ordered_claim_state: Callable[..., list[dict]]
    persist_ordered_review_state: Callable[..., list[dict]]
    persist_page_records: Callable[..., None]
    utc_now_iso: Callable[[], str]
    filter_live_claim_records: Callable[[list[dict]], list[dict]]
    build_claims_by_source_id: Callable[[list[dict]], dict[str, list[dict]]]
    build_chunks_by_source_id: Callable[[list[dict]], dict[str, list[dict]]]
    collect_missing_source_page_source_ids: Callable[..., set[str]]
    source_summary_page_path: Callable[[str, str], Path]
    build_source_summary_page: Callable[..., tuple[str, dict]]
    apply_page_alias_overrides: Callable[[Path, dict], dict]
    upsert_wiki_page: Callable[..., tuple[dict, bool]]
    link_claims_to_page_in_memory: Callable[..., set[str]]
    replace_jsonl_record: Callable[[Path, str, str, dict], None]
    build_concept_group_key: Callable[[dict], str]
    regroup_concept_claims_by_canonical_topic: Callable[[dict[str, list[dict]]], dict[str, list[dict]]]
    run_semantic_batch_task: Callable[..., None]
    apply_page_intent_decisions_to_claim_groups: Callable[..., dict]
    collect_missing_concept_bucket_keys: Callable[..., set[str]]
    page_route_for_bucket: Callable[[dict, str], dict]
    preferred_page_intent_for_claim_group: Callable[[list[dict], str], str]
    should_generate_concept_page: Callable[[list[dict]], bool]
    choose_group_topic_label: Callable[[list[dict]], str | None]
    choose_canonical_claim: Callable[..., dict]
    resolve_concept_title_candidate: Callable[..., tuple[str, str]]
    build_concept_page_id: Callable[[str], str]
    concept_summary_page_path: Callable[[str, str], Path]
    build_concept_page: Callable[..., tuple[str, dict]]
    apply_page_route_to_page_record: Callable[[dict, dict], dict]
    link_reviews_to_page_in_memory: Callable[..., set[str]]
    page_intent_page_id: Callable[[str, str], str]
    page_intent_page_path: Callable[[str, str, str], Path]
    build_intent_routed_page: Callable[..., tuple[str, dict]]
    collect_workspace_overview_concept_pages: Callable[..., list[dict]]
    should_generate_workspace_overview_page: Callable[[list[dict]], bool]
    workspace_overview_page_path: Callable[[], Path]
    build_workspace_overview_page: Callable[..., tuple[str, dict]]
    build_workspace_overview_page_id: Callable[[], str]
    expected_source_summary_page_id: Callable[[str], str]
    prune_stale_auto_pages: Callable[..., tuple[list[dict], set[str], set[str]]]
    write_review_file: Callable[[Path, dict], str]
    write_page_links_index: Callable[[Path, list[dict]], dict]
    load_search_pages_index: Callable[[Path], list[dict]]
    write_search_pages_index: Callable[..., dict]
    write_alias_index: Callable[[Path, list[dict]], dict]
    build_alias_conflict_reviews: Callable[[dict, dict[str, dict]], tuple[list[dict], Any]]
    append_jsonl: Callable[[Path, dict], None]
    rebuild_wiki_index: Callable[[Path, list[dict]], None]
    append_wiki_log: Callable[[Path, str, list[dict]], None]
    build_ingest_command_result: Callable[..., object]


@dataclass(frozen=True)
class IngestHelperDeps:
    build_similarity_bucket: Callable[[str], str]
    rebuild_claim_similarity_index: Callable[[list[dict]], Any]
    filter_live_claim_records: Callable[[list[dict]], list[dict]]
    is_live_claim_record: Callable[[dict], bool]
    run_post_ingest_review_auto: Callable[[Path], dict]
    build_ingest_payload: Callable[..., dict[str, Any]]
    build_workspace_summary: Callable[[Path, Path | None], dict[str, Any]]
    render_workspace_summary_message: Callable[..., str]
    render_post_ingest_review_auto_summary: Callable[[dict], str]
    alias_index_rel_path: str
    workspace_can_skip_page_regeneration: Callable[..., bool]
    apply_page_alias_overrides_to_records: Callable[[Path, list[dict]], list[dict]]
    filter_live_page_records: Callable[[list[dict]], list[dict]]
    load_existing_pages: Callable[[Path], list[dict]]
    load_chunk_records: Callable[[Path], list[dict]]
    collect_missing_source_page_source_ids: Callable[..., set[str]]
    collect_missing_concept_bucket_keys: Callable[..., set[str]]
    workspace_overview_page_missing: Callable[..., bool]
    persist_page_records: Callable[..., None]
    write_alias_index: Callable[[Path, list[dict]], dict]
    load_search_pages_index: Callable[[Path], list[dict]]
    search_pages_index_rel_path: str
    search_pages_index_version: str
    utc_now_iso: Callable[[], str]
    append_wiki_log: Callable[[Path, str, list[dict]], None]


def normalized_trace_value(target: Path, record: dict[str, Any]) -> dict[str, Any]:
    normalized_path = record.get("normalized_path")
    return {
        "record": record,
        "document": file_snapshot(target / normalized_path) if normalized_path else None,
    }


def replace_source_record_and_ingest_state(
    *,
    source_id: str,
    source_record: dict,
    source_status: str,
    normalized_path: str | None,
    sources_path: Path,
    ingest_state_path: Path,
    sources_by_id: dict[str, dict],
    task_id: str,
    stage_state: str,
    last_successful_stage: str | None,
    failed_stage: str | None,
    utc_now_iso: Callable[[], str],
    replace_jsonl_record: Callable[[Path, str, str, dict], None],
) -> dict:
    updated_source = dict(source_record)
    updated_source["status"] = source_status
    if normalized_path is not None:
        updated_source["normalized_path"] = normalized_path
    replace_jsonl_record(sources_path, "source_id", source_id, updated_source)
    sources_by_id[source_id] = updated_source
    replace_jsonl_record(
        ingest_state_path,
        "source_id",
        source_id,
        {
            "task_id": task_id,
            "source_id": source_id,
            "state": stage_state,
            "last_successful_stage": last_successful_stage,
            "failed_stage": failed_stage,
            "retry_count": 0,
            "updated_at": utc_now_iso(),
        },
    )
    return updated_source


def append_new_source_and_ingest_state(
    *,
    source_record: dict,
    sources_path: Path,
    ingest_state_path: Path,
    task_id: str,
    utc_now_iso: Callable[[], str],
    append_jsonl: Callable[[Path, dict], None],
) -> None:
    append_jsonl(sources_path, source_record)
    append_jsonl(
        ingest_state_path,
        {
            "task_id": task_id,
            "source_id": source_record["source_id"],
            "state": "new",
            "last_successful_stage": None,
            "failed_stage": None,
            "retry_count": 0,
            "updated_at": utc_now_iso(),
        },
    )


def build_ingest_payload(
    *,
    context: IngestContext,
    workspace_summary: dict[str, Any],
    search_index: dict[str, Any],
    alias_index: dict[str, Any],
    changed_page_count: int,
    tracked_page_count: int | None = None,
    existing_page_count: int | None = None,
) -> dict[str, Any]:
    payload = {
        "task_id": context.task_id,
        "workspace": str(context.target),
        "raw_dir": str(context.raw_dir),
        "workspace_summary": workspace_summary,
        "created_sources": context.created_sources,
        "skipped_sources": context.skipped_sources,
        "normalized_sources": context.normalized_sources,
        "structured_sources": context.structured_sources,
        "chunked_sources": context.chunked_sources,
        "claimed_sources": context.claimed_sources,
        "generated_pages": context.generated_pages,
        "search_index": search_index,
        "alias_index": {
            "index_path": alias_index.get("index_path"),
            "canonical_count": len(alias_index.get("canonical_map", {})),
            "alias_key_count": len(alias_index.get("alias_map", {})),
            "conflict_count": len(alias_index.get("conflicts", [])),
            "index_version": alias_index.get("index_version"),
        },
        "review_items": context.review_items,
        "error_items": context.error_items,
        "summary": {
            "created_count": len(context.created_sources),
            "skipped_count": len(context.skipped_sources),
            "normalized_count": len(context.normalized_sources),
            "structured_count": len(context.structured_sources),
            "chunked_count": len(context.chunked_sources),
            "claimed_count": len(context.claimed_sources),
            "changed_page_count": changed_page_count,
            "review_count": len(context.review_items),
            "error_count": len([item for item in context.error_items if item["level"] == "error"]),
            "warning_count": len([item for item in context.error_items if item["level"] == "warning"]),
        },
    }
    if tracked_page_count is not None:
        payload["summary"]["tracked_page_count"] = tracked_page_count
    if existing_page_count is not None:
        payload["summary"]["existing_page_count"] = existing_page_count
    return payload


def run_ingest_service(
    request: IngestRequest,
    *,
    deps: IngestServiceDeps,
) -> object:
    with trace_step("ingest.build_context", kind="ingest_stage", input_data=request) as context_step:
        context = deps.build_context(request)
        context_step.set_output({
            "target": context.target,
            "raw_dir": context.raw_dir,
            "task_id": context.task_id,
            "existing_source_count": len(context.existing_sources),
            "existing_claim_count": len(context.claims_by_id),
            "existing_review_count": len(context.existing_reviews),
        })
    with trace_step(
        "ingest.registration_and_normalization",
        kind="ingest_stage",
        input_data=lambda: {
            "task_id": context.task_id,
            "raw_dir": context.raw_dir,
            "existing_sources": context.existing_sources,
        },
    ) as registration_step:
        deps.run_registration_and_normalization_stage(context, request)
        registration_step.set_output(lambda: {
            "created_sources": context.created_sources,
            "skipped_sources": context.skipped_sources,
            "normalized_sources": context.normalized_sources,
            "normalized_records": context.normalized_records,
        })
    with trace_step(
        "ingest.structure_chunk_claim",
        kind="ingest_stage",
        input_data=lambda: {"normalized_records": context.normalized_records},
    ) as structure_step:
        deps.run_structure_chunk_claim_stage(context, request)
        structure_step.set_output(lambda: {
            "structured_sources": context.structured_sources,
            "chunked_sources": context.chunked_sources,
            "claimed_sources": context.claimed_sources,
            "claims": list(context.claims_by_id.values()),
            "reviews": list(context.existing_reviews.values()),
        })
    with trace_step(
        "ingest.page_finalize",
        kind="ingest_stage",
        input_data=lambda: {
            "sources": list(context.sources_by_id.values()),
            "claims": list(context.claims_by_id.values()),
            "reviews": list(context.existing_reviews.values()),
        },
    ) as page_step:
        result = deps.run_page_finalize_stage(context, request)
        page_step.set_output(lambda: {
            "result": result,
            "generated_pages": context.generated_pages,
        })
        return result


def build_ingest_context(
    request: IngestRequest,
    *,
    deps: IngestContextDeps,
) -> IngestContext:
    target = Path(request.target_dir).expanduser().resolve() if request.target_dir else Path.cwd()
    deps.ensure_workspace_schema_supported(target)
    config = deps.load_workspace_config(target)
    post_ingest_config = deps.load_post_ingest_review_auto_config(config)
    document_analysis_config = deps.load_semantic_task_config(config, "document_analysis")
    claim_candidate_quality_config = deps.load_semantic_task_config(config, "claim_candidate_quality")
    claim_role_config = deps.load_semantic_task_config(config, "claim_role")
    page_intent_config = deps.load_semantic_task_config(config, "page_intent")
    readable_concept_render_config = deps.load_readable_concept_render_config(config)
    overview_render_config = deps.load_page_render_config(config, "overview")
    raw_dir = deps.resolve_workspace_raw_dir(target)
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw directory does not exist: {raw_dir}")

    sources_path = target / "state" / "sources.jsonl"
    ingest_state_path = target / "state" / "ingest_state.jsonl"
    normalized_path = target / "state" / "normalized.jsonl"
    structure_blocks_path = target / deps.structure_blocks_rel_path
    evidence_blocks_path = target / deps.evidence_blocks_rel_path
    knowledge_units_path = target / deps.knowledge_units_rel_path
    chunks_path = target / "state" / "chunks.jsonl"
    claims_path = target / "state" / "claims.jsonl"
    reviews_path = target / "state" / "reviews.jsonl"
    error_log_path = target / "state" / "error_log.jsonl"
    pages_path = target / "state" / "pages.jsonl"

    existing_sources = deps.load_existing_sources(target)
    existing_by_hash = {record["source_hash"]: record for record in existing_sources}
    sources_by_id = {record["source_id"]: record for record in existing_sources}
    latest_source_by_path = deps.build_latest_source_record_by_path(existing_sources)
    existing_normalized = deps.load_existing_normalized_by_source(normalized_path)
    existing_structured_source_ids = deps.load_existing_structured_source_ids(
        structure_blocks_path=structure_blocks_path,
        evidence_blocks_path=evidence_blocks_path,
        knowledge_units_path=knowledge_units_path,
    )
    existing_chunked = deps.load_existing_chunked_by_source(chunks_path)
    (
        live_existing_claims,
        historical_existing_claims,
        claims_by_id,
        historical_claims_by_id,
        claims_by_normalized_text,
    ) = deps.load_existing_claim_state(claims_path)
    claims_by_similarity_bucket: dict[str, list[dict]] = {}
    for record in live_existing_claims:
        claims_by_similarity_bucket.setdefault(
            deps.build_similarity_bucket(record["text"]),
            [],
        ).append(record)
    claim_similarity_index = deps.rebuild_claim_similarity_index(live_existing_claims)
    (
        live_existing_reviews,
        historical_existing_reviews,
        existing_reviews,
        historical_reviews_by_id,
    ) = deps.load_existing_review_state(reviews_path)

    return IngestContext(
        target=target,
        config=config,
        post_ingest_config=post_ingest_config,
        document_analysis_config=document_analysis_config,
        claim_candidate_quality_config=claim_candidate_quality_config,
        claim_role_config=claim_role_config,
        page_intent_config=page_intent_config,
        readable_concept_render_config=readable_concept_render_config,
        overview_render_config=overview_render_config,
        raw_dir=raw_dir,
        sources_path=sources_path,
        ingest_state_path=ingest_state_path,
        normalized_path=normalized_path,
        structure_blocks_path=structure_blocks_path,
        evidence_blocks_path=evidence_blocks_path,
        knowledge_units_path=knowledge_units_path,
        chunks_path=chunks_path,
        claims_path=claims_path,
        reviews_path=reviews_path,
        error_log_path=error_log_path,
        pages_path=pages_path,
        existing_sources=existing_sources,
        existing_by_hash=existing_by_hash,
        sources_by_id=sources_by_id,
        latest_source_by_path=latest_source_by_path,
        existing_normalized=existing_normalized,
        existing_structured_source_ids=existing_structured_source_ids,
        existing_chunked=existing_chunked,
        claims_by_id=claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
        claims_by_normalized_text=claims_by_normalized_text,
        claims_by_similarity_bucket=claims_by_similarity_bucket,
        claim_similarity_index=claim_similarity_index,
        existing_reviews=existing_reviews,
        historical_reviews_by_id=historical_reviews_by_id,
        created_sources=[],
        skipped_sources=[],
        normalized_sources=[],
        structured_sources=[],
        chunked_sources=[],
        claimed_sources=[],
        review_items=[],
        error_items=[],
        generated_pages=[],
        task_id=deps.task_id_factory(),
        reingested_source_ids=set(),
        purged_claim_ids=set(),
        purged_review_ids=set(),
        active_source_ids=set(),
        claims_created_by_source={},
        semantic_claim_updates_applied=False,
    )


def run_ingest_registration_and_normalization_stage(
    context: IngestContext,
    request: IngestRequest,
    *,
    deps: IngestRegistrationDeps,
) -> None:
    target = context.target
    raw_dir = context.raw_dir
    sources_path = context.sources_path
    ingest_state_path = context.ingest_state_path
    normalized_path = context.normalized_path
    structure_blocks_path = context.structure_blocks_path
    evidence_blocks_path = context.evidence_blocks_path
    knowledge_units_path = context.knowledge_units_path
    task_id = context.task_id
    existing_by_hash = context.existing_by_hash
    latest_source_by_path = context.latest_source_by_path
    existing_normalized = context.existing_normalized
    existing_structured_source_ids = context.existing_structured_source_ids
    existing_chunked = context.existing_chunked
    claims_by_id = context.claims_by_id
    historical_claims_by_id = context.historical_claims_by_id
    claims_by_normalized_text = context.claims_by_normalized_text
    existing_reviews = context.existing_reviews
    historical_reviews_by_id = context.historical_reviews_by_id
    created_sources = context.created_sources
    skipped_sources = context.skipped_sources
    normalized_sources = context.normalized_sources
    error_items = context.error_items
    sources_by_id = context.sources_by_id
    reingested_source_ids = context.reingested_source_ids
    purged_claim_ids = context.purged_claim_ids
    purged_review_ids = context.purged_review_ids
    existing_sources = context.existing_sources
    debug_enabled = current_debug_tracer() is not None

    for file_path in deps.collect_files(raw_dir):
        source_hash = deps.file_sha256(file_path)
        relative_path = os.path.relpath(file_path, start=target).replace(os.sep, "/")
        previous_path_record = latest_source_by_path.get(relative_path)
        previous_normalized_record = (
            existing_normalized.get(previous_path_record["source_id"])
            if previous_path_record is not None
            else None
        )
        needs_normalizer_refresh = (
            previous_normalized_record is not None
            and not deps.normalized_record_is_current(previous_normalized_record)
        )
        if source_hash in existing_by_hash and not needs_normalizer_refresh:
            existing_source = existing_by_hash[source_hash]
            skipped_record = {
                "path": str(file_path),
                "source_hash": source_hash,
                "reason": "duplicate_hash",
                "source_id": existing_source["source_id"],
            }
            skipped_sources.append(skipped_record)
            trace_lineage(
                operation="skipped",
                reason="duplicate_hash",
                inputs=lambda: [entity_reference(
                    "source_file",
                    source_hash,
                    value=file_snapshot(file_path),
                    path=file_path,
                    source_id=str(existing_source["source_id"]),
                )],
                outputs=lambda: [entity_reference(
                    "source",
                    str(existing_source["source_id"]),
                    value=existing_source,
                    path=str(existing_source.get("source_path", "")),
                    source_id=str(existing_source["source_id"]),
                )],
                details=skipped_record,
                snapshot_name=f"source_{existing_source['source_id']}_reused",
            )
            continue

        if previous_path_record is not None:
            source_id = previous_path_record["source_id"]
            version_group = (
                previous_path_record.get("version_group")
                or deps.build_source_version_group_from_source_path(relative_path)
            )
            previous_normalized_path = previous_path_record.get("normalized_path")
            chunk_file_path = target / "chunks" / f"{source_id}.jsonl"
            previous_structure_records = []
            previous_evidence_records = []
            previous_knowledge_records = []
            previous_chunk_records = []
            previous_claim_records = []
            previous_normalized_snapshot_value = previous_normalized_record
            if debug_enabled:
                previous_structure_records = [
                    record for record in deps.load_jsonl(structure_blocks_path)
                    if record.get("source_id") == source_id
                ]
                previous_evidence_records = [
                    record for record in deps.load_jsonl(evidence_blocks_path)
                    if record.get("source_id") == source_id
                ]
                previous_knowledge_records = [
                    record for record in deps.load_jsonl(knowledge_units_path)
                    if record.get("source_id") == source_id
                ]
                previous_chunk_records = deps.load_jsonl(chunk_file_path)
                previous_claim_records = [
                    dict(record)
                    for record in claims_by_id.values()
                    if source_id in record.get("source_ids", [])
                ]
                if previous_normalized_record is not None:
                    previous_normalized_snapshot_value = normalized_trace_value(
                        target,
                        previous_normalized_record,
                    )
                previous_claim_ids = {
                    str(record.get("claim_id")) for record in previous_claim_records
                }
                previous_review_records = [
                    dict(record)
                    for record in existing_reviews.values()
                    if previous_claim_ids.intersection(record.get("candidate_claim_ids", []))
                ]
            else:
                previous_review_records = []

            existing_normalized.pop(source_id, None)
            existing_structured_source_ids.discard(source_id)
            existing_chunked.pop(source_id, None)

            if previous_normalized_path:
                normalized_file_path = target / previous_normalized_path
                if normalized_file_path.exists():
                    normalized_file_path.unlink()

            if chunk_file_path.exists():
                chunk_file_path.unlink()

            deps.replace_source_scoped_jsonl_records(structure_blocks_path, source_id, [])
            deps.replace_source_scoped_jsonl_records(evidence_blocks_path, source_id, [])
            deps.replace_source_scoped_jsonl_records(knowledge_units_path, source_id, [])

            dirty_claim_ids, deleted_claim_ids = deps.purge_source_from_claims(
                target=target,
                claims_by_id=claims_by_id,
                historical_claims_by_id=historical_claims_by_id,
                source_id=source_id,
            )
            purged_claim_ids.update(deleted_claim_ids)

            dirty_review_ids, deleted_review_ids = deps.purge_deleted_claims_from_reviews(
                reviews_by_id=existing_reviews,
                historical_reviews_by_id=historical_reviews_by_id,
                deleted_claim_ids=deleted_claim_ids,
            )
            purged_review_ids.update(deleted_review_ids)

            removed_artifacts = [
                *(
                    [entity_reference(
                        "normalized",
                        str(previous_normalized_record.get("normalized_id") or source_id),
                        value=previous_normalized_snapshot_value,
                        path=str(previous_normalized_record.get("normalized_path", "")),
                        source_id=source_id,
                    )]
                    if previous_normalized_record is not None
                    else []
                ),
                *[
                    entity_reference(
                        "structure_block",
                        str(record.get("structure_block_id")),
                        value=record,
                        source_id=source_id,
                    )
                    for record in previous_structure_records
                ],
                *[
                    entity_reference(
                        "evidence_block",
                        str(record.get("evidence_block_id")),
                        value=record,
                        source_id=source_id,
                    )
                    for record in previous_evidence_records
                ],
                *[
                    entity_reference(
                        "knowledge_unit",
                        str(record.get("knowledge_unit_id")),
                        value=record,
                        source_id=source_id,
                    )
                    for record in previous_knowledge_records
                ],
                *[
                    entity_reference(
                        "chunk",
                        str(record.get("chunk_id")),
                        value=record,
                        path=chunk_file_path,
                        source_id=source_id,
                    )
                    for record in previous_chunk_records
                ],
            ] if debug_enabled else []
            if removed_artifacts:
                trace_lineage(
                    operation="removed",
                    reason="source_changed_old_derived_artifacts_removed_before_rebuild",
                    inputs=removed_artifacts,
                    outputs=lambda: [],
                    details={"source_id": source_id},
                    snapshot_name=f"source_{source_id}_old_derived_artifacts",
                )

            if dirty_claim_ids:
                trace_lineage(
                    operation="replaced",
                    reason="changed_source_removed_from_multi_source_claim",
                    inputs=lambda: [
                        entity_reference("claim", str(record.get("claim_id")), value=record)
                        for record in previous_claim_records
                        if record.get("claim_id") in dirty_claim_ids
                    ],
                    outputs=lambda: [
                        entity_reference("claim", claim_id, value=claims_by_id[claim_id])
                        for claim_id in sorted(dirty_claim_ids)
                        if claim_id in claims_by_id
                    ],
                    snapshot_name=f"source_{source_id}_claims_updated",
                )
            if deleted_claim_ids:
                trace_lineage(
                    operation="archived",
                    reason="changed_source_was_last_active_source_for_claim",
                    inputs=lambda: [
                        entity_reference("claim", str(record.get("claim_id")), value=record)
                        for record in previous_claim_records
                        if record.get("claim_id") in deleted_claim_ids
                    ],
                    outputs=lambda: [
                        entity_reference("historical_claim", str(record.get("claim_id")), value=record)
                        for record in historical_claims_by_id.values()
                        if record.get("original_claim_id") in deleted_claim_ids
                    ],
                    snapshot_name=f"source_{source_id}_claims_archived",
                )
            if dirty_review_ids or deleted_review_ids:
                changed_review_ids = dirty_review_ids | deleted_review_ids
                trace_lineage(
                    operation="archived" if deleted_review_ids and not dirty_review_ids else "replaced",
                    reason="claim_rebuild_updated_dependent_reviews",
                    inputs=lambda: [
                        entity_reference("review", str(record.get("review_id")), value=record)
                        for record in previous_review_records
                        if record.get("review_id") in changed_review_ids
                    ],
                    outputs=lambda: [
                        *[
                            entity_reference("review", review_id, value=existing_reviews[review_id])
                            for review_id in sorted(dirty_review_ids)
                            if review_id in existing_reviews
                        ],
                        *[
                            entity_reference("historical_review", str(record.get("review_id")), value=record)
                            for record in historical_reviews_by_id.values()
                            if record.get("original_review_id") in deleted_review_ids
                        ],
                    ],
                    snapshot_name=f"source_{source_id}_reviews_updated",
                )

            claims_by_normalized_text.clear()
            claims_by_normalized_text.update({
                record["normalized_text"]: record for record in claims_by_id.values()
            })
            deps.refresh_claim_similarity_state(context, list(claims_by_id.values()))

            updated_record = dict(previous_path_record)
            updated_record.update({
                "source_path": relative_path,
                "source_type": deps.infer_source_type(file_path),
                "source_hash": source_hash,
                "dedupe_key": source_hash,
                "version_group": version_group,
                "imported_at": deps.utc_now_iso(),
                "status": "new",
                "normalized_path": None,
                "warnings": [],
            })
            replace_source_record_and_ingest_state(
                source_id=source_id,
                source_record=updated_record,
                source_status="new",
                normalized_path=None,
                sources_path=sources_path,
                ingest_state_path=ingest_state_path,
                sources_by_id=sources_by_id,
                task_id=task_id,
                stage_state="new",
                last_successful_stage=None,
                failed_stage=None,
                utc_now_iso=deps.utc_now_iso,
                replace_jsonl_record=deps.replace_jsonl_record,
            )
            latest_source_by_path[relative_path] = updated_record
            existing_by_hash[source_hash] = updated_record
            created_sources.append(updated_record)
            reingested_source_ids.add(source_id)
            trace_lineage(
                operation="replaced",
                reason="source_content_or_normalizer_changed",
                inputs=lambda: [entity_reference(
                    "source",
                    source_id,
                    value=previous_path_record,
                    path=relative_path,
                    source_id=source_id,
                )],
                outputs=lambda: [entity_reference(
                    "source",
                    source_id,
                    value=updated_record,
                    path=relative_path,
                    source_id=source_id,
                )],
                details={
                    "previous_source_hash": previous_path_record.get("source_hash"),
                    "new_source_hash": source_hash,
                    "normalizer_refresh": needs_normalizer_refresh,
                    "removed_claim_ids": sorted(deleted_claim_ids),
                    "removed_review_ids": sorted(deleted_review_ids),
                },
                snapshot_name=f"source_{source_id}_replacement",
            )
            continue

        source_id = deps.build_source_id(raw_dir, file_path, source_hash)
        version_group = deps.build_source_version_group(raw_dir, file_path)
        record = {
            "source_id": source_id,
            "source_path": relative_path,
            "source_type": deps.infer_source_type(file_path),
            "source_uri": None,
            "source_hash": source_hash,
            "dedupe_key": source_hash,
            "version_group": version_group,
            "imported_at": deps.utc_now_iso(),
            "status": "new",
            "normalized_path": None,
            "warnings": [],
        }
        append_new_source_and_ingest_state(
            source_record=record,
            sources_path=sources_path,
            ingest_state_path=ingest_state_path,
            task_id=task_id,
            utc_now_iso=deps.utc_now_iso,
            append_jsonl=deps.append_jsonl,
        )
        created_sources.append(record)
        existing_sources.append(record)
        sources_by_id[source_id] = record
        latest_source_by_path[relative_path] = record
        trace_lineage(
            operation="created",
            reason="new_source_path_and_hash",
            inputs=lambda: [entity_reference(
                "source_file",
                source_hash,
                value=file_snapshot(file_path),
                path=file_path,
                source_id=source_id,
            )],
            outputs=lambda: [entity_reference(
                "source",
                source_id,
                value=record,
                path=relative_path,
                source_id=source_id,
            )],
            snapshot_name=f"source_{source_id}_created",
        )

    for source_record in deps.load_source_records(sources_path):
        if source_record["source_id"] in existing_normalized:
            existing_record = existing_normalized[source_record["source_id"]]
            trace_lineage(
                operation="reused",
                reason="normalized_record_is_current",
                inputs=lambda: [entity_reference(
                    "source",
                    str(source_record["source_id"]),
                    value=source_record,
                    source_id=str(source_record["source_id"]),
                )],
                outputs=lambda: [entity_reference(
                    "normalized",
                    str(existing_record.get("normalized_id") or source_record["source_id"]),
                    value=normalized_trace_value(target, existing_record),
                    path=str(existing_record.get("normalized_path", "")),
                    source_id=str(source_record["source_id"]),
                )],
                snapshot_name=f"source_{source_record['source_id']}_normalized_reused",
            )
            continue
        normalized_record = deps.normalize_source_record(
            target,
            source_record,
            allow_insecure_downloads=not request.disable_insecure_download_retry,
        )
        if normalized_record is None:
            continue

        deps.replace_source_scoped_jsonl_records(
            normalized_path,
            source_record["source_id"],
            [normalized_record],
        )
        normalized_sources.append(normalized_record)
        trace_lineage(
            operation="generated",
            reason="source_requires_normalization",
            inputs=lambda: [entity_reference(
                "source",
                str(source_record["source_id"]),
                value=source_record,
                path=str(source_record.get("source_path", "")),
                source_id=str(source_record["source_id"]),
            )],
            outputs=lambda: [entity_reference(
                "normalized",
                str(normalized_record.get("normalized_id") or normalized_record["source_id"]),
                value=normalized_trace_value(target, normalized_record),
                path=str(normalized_record.get("normalized_path", "")),
                source_id=str(normalized_record["source_id"]),
            )],
            details={"extraction_quality": normalized_record.get("extraction_quality")},
            snapshot_name=f"source_{source_record['source_id']}_normalized",
        )

        if normalized_record["extraction_quality"] in {"failed", "poor", "partial"}:
            level = "error" if normalized_record["extraction_quality"] == "failed" else "warning"
            error_items.append(
                deps.append_error_record(
                    error_log_path=context.error_log_path,
                    task_id=task_id,
                    source_id=normalized_record["source_id"],
                    stage="normalized",
                    level=level,
                    message=f"Normalization finished with quality={normalized_record['extraction_quality']}",
                    details={
                        "warnings": normalized_record.get("warnings", []),
                        "normalized_path": normalized_record["normalized_path"],
                        "source_type": normalized_record["source_type"],
                    },
                )
            )

        stage_state = (
            "failed"
            if normalized_record["extraction_quality"] == "failed"
            else "review_required"
            if normalized_record["extraction_quality"] == "poor"
            else "normalized"
        )
        replace_source_record_and_ingest_state(
            source_id=source_record["source_id"],
            source_record=source_record,
            source_status=stage_state,
            normalized_path=normalized_record["normalized_path"],
            sources_path=sources_path,
            ingest_state_path=ingest_state_path,
            sources_by_id=sources_by_id,
            task_id=task_id,
            stage_state=stage_state,
            last_successful_stage=None if normalized_record["extraction_quality"] == "failed" else "normalized",
            failed_stage="normalized" if normalized_record["extraction_quality"] == "failed" else None,
            utc_now_iso=deps.utc_now_iso,
            replace_jsonl_record=deps.replace_jsonl_record,
        )

    context.normalized_records = deps.load_normalized_records(normalized_path)
    if context.normalized_records and context.document_analysis_config.enabled:
        deps.run_semantic_batch_task(
            target=target,
            task_name="document_analysis",
            dry_run=False,
        )
        context.normalized_records = deps.apply_document_analysis_decisions_to_normalized_records(
            target=target,
            normalized_records=context.normalized_records,
            task_config=context.document_analysis_config,
        )
        context.existing_normalized = {
            record["source_id"]: record for record in context.normalized_records
        }


def run_ingest_structure_chunk_claim_stage(
    context: IngestContext,
    request: IngestRequest,
    *,
    deps: IngestStructureClaimDeps,
) -> None:
    target = context.target
    sources_path = context.sources_path
    ingest_state_path = context.ingest_state_path
    chunks_path = context.chunks_path
    claims_path = context.claims_path
    reviews_path = context.reviews_path
    knowledge_units_path = context.knowledge_units_path
    normalized_path = context.normalized_path
    error_log_path = context.error_log_path
    task_id = context.task_id
    normalized_records = context.normalized_records or deps.load_normalized_records(normalized_path)
    existing_structured_source_ids = context.existing_structured_source_ids
    existing_chunked = context.existing_chunked
    structured_sources = context.structured_sources
    chunked_sources = context.chunked_sources
    claims_by_id = context.claims_by_id
    historical_claims_by_id = context.historical_claims_by_id
    claims_by_normalized_text = context.claims_by_normalized_text
    claims_by_similarity_bucket = context.claims_by_similarity_bucket
    existing_reviews = context.existing_reviews
    historical_reviews_by_id = context.historical_reviews_by_id
    claimed_sources = context.claimed_sources
    review_items = context.review_items
    error_items = context.error_items
    sources_by_id = context.sources_by_id
    reingested_source_ids = context.reingested_source_ids
    purged_claim_ids = context.purged_claim_ids
    purged_review_ids = context.purged_review_ids
    debug_enabled = current_debug_tracer() is not None

    for normalized_record in normalized_records:
        source_id = normalized_record["source_id"]
        if source_id in existing_structured_source_ids:
            trace_lineage(
                operation="reused",
                reason="structured_records_already_current",
                inputs=lambda: [entity_reference(
                    "normalized",
                    str(normalized_record.get("normalized_id") or source_id),
                    value=normalized_trace_value(target, normalized_record),
                    source_id=source_id,
                )],
                outputs=lambda: [
                    entity_reference("structure_block_set", source_id, path=context.structure_blocks_path, source_id=source_id),
                    entity_reference("evidence_block_set", source_id, path=context.evidence_blocks_path, source_id=source_id),
                    entity_reference("knowledge_unit_set", source_id, path=context.knowledge_units_path, source_id=source_id),
                ],
                snapshot_name=f"source_{source_id}_structured_reused",
            )
            continue
        if normalized_record["extraction_quality"] not in {"good", "partial"}:
            continue

        normalized_file_path = target / normalized_record["normalized_path"]
        if not normalized_file_path.exists():
            continue
        normalized_text = normalized_file_path.read_text(encoding="utf-8")
        compiled_records = deps.compile_structure_knowledge_records(normalized_record, normalized_text)
        deps.replace_source_scoped_jsonl_records(
            context.structure_blocks_path,
            source_id,
            compiled_records["structure_blocks"],
        )
        deps.replace_source_scoped_jsonl_records(
            context.evidence_blocks_path,
            source_id,
            compiled_records["evidence_blocks"],
        )
        deps.replace_source_scoped_jsonl_records(
            context.knowledge_units_path,
            source_id,
            compiled_records["knowledge_units"],
        )
        structured_sources.append({
            "source_id": source_id,
            "structure_block_count": len(compiled_records["structure_blocks"]),
            "evidence_block_count": len(compiled_records["evidence_blocks"]),
            "knowledge_unit_count": len(compiled_records["knowledge_units"]),
            "updated_at": compiled_records["updated_at"],
        })
        existing_structured_source_ids.add(source_id)
        structured_outputs = lambda: [
            *[
                entity_reference(
                    "structure_block",
                    str(record.get("structure_block_id")),
                    value=record,
                    source_id=source_id,
                )
                for record in compiled_records["structure_blocks"]
            ],
            *[
                entity_reference(
                    "evidence_block",
                    str(record.get("evidence_block_id")),
                    value=record,
                    source_id=source_id,
                )
                for record in compiled_records["evidence_blocks"]
            ],
            *[
                entity_reference(
                    "knowledge_unit",
                    str(record.get("knowledge_unit_id")),
                    value=record,
                    source_id=source_id,
                )
                for record in compiled_records["knowledge_units"]
            ],
        ]
        trace_lineage(
            operation="generated",
            reason="normalized_source_requires_structure_compilation",
            inputs=lambda: [entity_reference(
                "normalized",
                str(normalized_record.get("normalized_id") or source_id),
                value={"record": normalized_record, "text": normalized_text},
                path=normalized_record.get("normalized_path"),
                source_id=source_id,
            )],
            outputs=structured_outputs,
            details={
                "structure_block_count": len(compiled_records["structure_blocks"]),
                "evidence_block_count": len(compiled_records["evidence_blocks"]),
                "knowledge_unit_count": len(compiled_records["knowledge_units"]),
            },
            snapshot_name=f"source_{source_id}_structured",
        )

    for normalized_record in normalized_records:
        if normalized_record["source_id"] in existing_chunked:
            existing_chunk_record = existing_chunked[normalized_record["source_id"]]
            trace_lineage(
                operation="reused",
                reason="chunk_records_already_current",
                inputs=lambda: [entity_reference(
                    "normalized",
                    str(normalized_record.get("normalized_id") or normalized_record["source_id"]),
                    value=normalized_trace_value(target, normalized_record),
                    source_id=str(normalized_record["source_id"]),
                )],
                outputs=lambda: [entity_reference(
                    "chunk_set",
                    str(normalized_record["source_id"]),
                    value=existing_chunk_record,
                    path=f"chunks/{normalized_record['source_id']}.jsonl",
                    source_id=str(normalized_record["source_id"]),
                )],
                snapshot_name=f"source_{normalized_record['source_id']}_chunks_reused",
            )
            continue

        chunk_result = deps.chunk_normalized_record(target, normalized_record)
        if chunk_result is None:
            continue

        deps.replace_jsonl_records_by_filter(
            chunks_path,
            keep_predicate=lambda record, source_id=chunk_result["source_id"]: record.get("source_id") != source_id,
            replacement_records=chunk_result["chunks"],
        )
        chunked_sources.append({
            "source_id": chunk_result["source_id"],
            "chunk_file_path": chunk_result["chunk_file_path"],
            "chunk_count": chunk_result["chunk_count"],
            "updated_at": chunk_result["updated_at"],
        })
        existing_chunked[chunk_result["source_id"]] = {
            "source_id": chunk_result["source_id"],
            "chunk_count": chunk_result["chunk_count"],
        }
        trace_lineage(
            operation="generated",
            reason="normalized_source_requires_chunking",
            inputs=lambda: [entity_reference(
                "normalized",
                str(normalized_record.get("normalized_id") or normalized_record["source_id"]),
                value=normalized_trace_value(target, normalized_record),
                source_id=str(normalized_record["source_id"]),
            )],
            outputs=lambda: [
                entity_reference(
                    "chunk",
                    str(record.get("chunk_id")),
                    value=record,
                    path=chunk_result["chunk_file_path"],
                    source_id=str(chunk_result["source_id"]),
                )
                for record in chunk_result["chunks"]
            ],
            details={"chunk_count": chunk_result["chunk_count"]},
            snapshot_name=f"source_{chunk_result['source_id']}_chunks",
        )

        source_record = sources_by_id.get(normalized_record["source_id"])
        if source_record is not None:
            replace_source_record_and_ingest_state(
                source_id=source_record["source_id"],
                source_record=source_record,
                source_status="chunked",
                normalized_path=source_record.get("normalized_path"),
                sources_path=sources_path,
                ingest_state_path=ingest_state_path,
                sources_by_id=sources_by_id,
                task_id=task_id,
                stage_state="chunked",
                last_successful_stage="chunked",
                failed_stage=None,
                utc_now_iso=deps.utc_now_iso,
                replace_jsonl_record=deps.replace_jsonl_record,
            )

    chunks_by_source_id_for_claims = deps.load_chunk_records_by_source(chunks_path)
    knowledge_units_by_source_id = deps.load_active_knowledge_units_by_source(
        knowledge_units_path
    )
    claims_created_by_source: dict[str, int] = {}
    completed_claim_source_ids = {
        source_id
        for source_id, source_record in sources_by_id.items()
        if deps.source_claim_stage_completed(source_record)
    }
    active_source_ids = deps.choose_active_source_ids(sources_by_id)

    claim_candidate_source_ids = sorted(set(chunks_by_source_id_for_claims) | set(knowledge_units_by_source_id))
    for source_id in claim_candidate_source_ids:
        if source_id in completed_claim_source_ids:
            trace_lineage(
                operation="reused",
                reason="source_claim_stage_already_completed",
                inputs=lambda: [
                    *[
                        entity_reference("knowledge_unit", str(record.get("knowledge_unit_id")), value=record, source_id=source_id)
                        for record in knowledge_units_by_source_id.get(source_id, [])
                    ],
                    *[
                        entity_reference("chunk", str(record.get("chunk_id")), value=record, source_id=source_id)
                        for record in chunks_by_source_id_for_claims.get(source_id, [])
                    ],
                ],
                outputs=lambda: [
                    entity_reference("claim", str(record.get("claim_id")), value=record, source_id=source_id)
                    for record in claims_by_id.values()
                    if source_id in record.get("source_ids", [])
                ],
                snapshot_name=f"source_{source_id}_claims_reused",
            )
            continue
        source_claim_candidates = deps.build_claim_candidates_for_source(
            source_id=source_id,
            knowledge_units_by_source_id=knowledge_units_by_source_id,
            chunks_by_source_id=chunks_by_source_id_for_claims,
        )
        trace_lineage(
            operation="generated",
            reason="claim_candidates_built_from_knowledge_units_and_chunks",
            inputs=lambda: [
                *[
                    entity_reference("knowledge_unit", str(record.get("knowledge_unit_id")), value=record, source_id=source_id)
                    for record in knowledge_units_by_source_id.get(source_id, [])
                ],
                *[
                    entity_reference("chunk", str(record.get("chunk_id")), value=record, source_id=source_id)
                    for record in chunks_by_source_id_for_claims.get(source_id, [])
                ],
            ],
            outputs=lambda: [
                entity_reference("claim_candidate", str(record.get("claim_id")), value=record, source_id=source_id)
                for record in source_claim_candidates
            ],
            details={"candidate_count": len(source_claim_candidates)},
            snapshot_name=f"source_{source_id}_claim_candidates",
        )
        for claim_record in source_claim_candidates:
            existing_claim = claims_by_normalized_text.get(claim_record["normalized_text"])
            if existing_claim is not None:
                existing_claim_before = dict(existing_claim) if debug_enabled else existing_claim
                merged_claim = deps.merge_claim_records(existing_claim, claim_record)
                deps.write_claim_file(target, merged_claim)
                deps.replace_jsonl_record(claims_path, "claim_id", merged_claim["claim_id"], merged_claim)
                claims_by_id[merged_claim["claim_id"]] = merged_claim
                claims_by_normalized_text[merged_claim["normalized_text"]] = merged_claim
                trace_lineage(
                    operation="replaced",
                    reason="claim_candidate_matches_existing_normalized_text",
                    inputs=lambda: [
                        entity_reference("claim", str(existing_claim_before["claim_id"]), value=existing_claim_before, source_id=source_id),
                        entity_reference("claim_candidate", str(claim_record["claim_id"]), value=claim_record, source_id=source_id),
                    ],
                    outputs=lambda: [entity_reference(
                        "claim",
                        str(merged_claim["claim_id"]),
                        value=merged_claim,
                        source_id=source_id,
                    )],
                    snapshot_name=f"claim_{merged_claim['claim_id']}_merged",
                )
                continue

            similarity_bucket = deps.build_similarity_bucket(claim_record["text"])
            candidate_claim_ids = deps.collect_claim_review_candidate_ids(
                claim_record=claim_record,
                claims_by_similarity_bucket=claims_by_similarity_bucket,
                claim_similarity_index=context.claim_similarity_index,
            )
            conflicting_candidates = []
            duplicate_candidates = []
            incoming_has_negation = deps.has_negation(claim_record["text"])

            for candidate_claim_id in sorted(candidate_claim_ids):
                similar_claim = claims_by_id.get(candidate_claim_id)
                if similar_claim is None:
                    continue
                if not deps.claims_are_similar_for_review(claim_record["text"], similar_claim["text"]):
                    continue
                if deps.has_negation(similar_claim["text"]) != incoming_has_negation:
                    conflicting_candidates.append(similar_claim)
                else:
                    duplicate_candidates.append(similar_claim)

            if duplicate_candidates:
                claim_record["duplicate_candidates"] = [item["claim_id"] for item in duplicate_candidates]
                claim_record["review_reason"] = "possible_duplicate_claim"
                claim_record["status"] = "needs_review"

                review_record = deps.build_review_record(
                    kind="claim_duplicate",
                    candidate_claim_ids=sorted([claim_record["claim_id"], *[item["claim_id"] for item in duplicate_candidates]]),
                    reason="Detected highly similar claims that may need merge or archive decisions.",
                    evidence=[
                        {
                            "claim_id": claim_record["claim_id"],
                            "text": claim_record["text"],
                            "source_refs": claim_record["source_refs"],
                        },
                        *[
                            {
                                "claim_id": item["claim_id"],
                                "text": item["text"],
                                "source_refs": item.get("source_refs", []),
                            }
                            for item in duplicate_candidates
                        ],
                    ],
                    recommended_action="merge",
                    signature_parts=[
                        claim_record["normalized_text"],
                        *sorted(item["claim_id"] for item in duplicate_candidates),
                    ],
                )
                if review_record["review_id"] not in existing_reviews:
                    review_file_path = deps.write_review_file(target, review_record)
                    review_record["review_file_path"] = review_file_path
                    deps.append_jsonl(reviews_path, review_record)
                    existing_reviews[review_record["review_id"]] = review_record
                    review_items.append(review_record)

                error_items.append(
                    deps.append_error_record(
                        error_log_path=error_log_path,
                        task_id=task_id,
                        source_id=claim_record["source_ids"][0],
                        stage="claim",
                        level="warning",
                        message="Possible duplicate claims detected",
                        details={
                            "claim_id": claim_record["claim_id"],
                            "duplicate_candidates": claim_record["duplicate_candidates"],
                        },
                    )
                )

            if conflicting_candidates:
                conflict_claim_ids = sorted([claim_record["claim_id"], *[item["claim_id"] for item in conflicting_candidates]])
                conflict_group = hashlib.sha256("|".join(conflict_claim_ids).encode("utf-8")).hexdigest()[:12]
                claim_record["conflict_group"] = f"cfg_{conflict_group}"
                claim_record["review_reason"] = "conflicting_claims_detected"
                claim_record["status"] = "needs_review"

                evidence = [
                    {
                        "claim_id": claim_record["claim_id"],
                        "text": claim_record["text"],
                        "source_refs": claim_record["source_refs"],
                    }
                ]
                evidence.extend({
                    "claim_id": item["claim_id"],
                    "text": item["text"],
                    "source_refs": item.get("source_refs", []),
                } for item in conflicting_candidates)

                review_record = deps.build_review_record(
                    kind="claim_conflict",
                    candidate_claim_ids=conflict_claim_ids,
                    reason="Detected claims with opposite negation pattern but very similar normalized content.",
                    evidence=evidence,
                    recommended_action="keep_both",
                )
                if review_record["review_id"] not in existing_reviews:
                    review_file_path = deps.write_review_file(target, review_record)
                    review_record["review_file_path"] = review_file_path
                    deps.append_jsonl(reviews_path, review_record)
                    existing_reviews[review_record["review_id"]] = review_record
                    review_items.append(review_record)

                error_items.append(
                    deps.append_error_record(
                        error_log_path=error_log_path,
                        task_id=task_id,
                        source_id=claim_record["source_ids"][0],
                        stage="claim",
                        level="warning",
                        message="Conflicting claims detected",
                        details={
                            "claim_id": claim_record["claim_id"],
                            "conflict_group": claim_record["conflict_group"],
                            "candidate_claim_ids": conflict_claim_ids,
                        },
                    )
                )

            claim_file_rel_path = deps.write_claim_file(target, claim_record)
            claim_record["claim_file_path"] = claim_file_rel_path
            deps.append_jsonl(claims_path, claim_record)
            claims_by_id[claim_record["claim_id"]] = claim_record
            claims_by_normalized_text[claim_record["normalized_text"]] = claim_record
            claims_by_similarity_bucket.setdefault(similarity_bucket, []).append(claim_record)
            deps.index_claim_similarity_tokens(context.claim_similarity_index, claim_record)
            source_id = claim_record["source_ids"][0]
            claims_created_by_source[source_id] = claims_created_by_source.get(source_id, 0) + 1
            trace_lineage(
                operation="created",
                reason="new_claim_candidate",
                inputs=lambda: [entity_reference(
                    "claim_candidate",
                    str(claim_record["claim_id"]),
                    value=claim_record,
                    source_id=source_id,
                )],
                outputs=lambda: [entity_reference(
                    "claim",
                    str(claim_record["claim_id"]),
                    value=claim_record,
                    path=claim_file_rel_path,
                    source_id=source_id,
                )],
                details={"status": claim_record.get("status"), "review_reason": claim_record.get("review_reason")},
                snapshot_name=f"claim_{claim_record['claim_id']}_created",
            )

    for source_id, claim_count in sorted(claims_created_by_source.items()):
        source_claims = [
            record for record in claims_by_id.values()
            if source_id in record.get("source_ids", [])
        ]
        has_review_claim = any(record.get("status") == "needs_review" for record in source_claims)

        claimed_sources.append({
            "source_id": source_id,
            "claim_count": claim_count,
            "needs_review": has_review_claim,
        })

        source_record = sources_by_id.get(source_id)
        if source_record is not None:
            stage_state = "review_required" if has_review_claim else "claimed"
            replace_source_record_and_ingest_state(
                source_id=source_id,
                source_record=source_record,
                source_status=stage_state,
                normalized_path=source_record.get("normalized_path"),
                sources_path=sources_path,
                ingest_state_path=ingest_state_path,
                sources_by_id=sources_by_id,
                task_id=task_id,
                stage_state=stage_state,
                last_successful_stage="claimed",
                failed_stage=None,
                utc_now_iso=deps.utc_now_iso,
                replace_jsonl_record=deps.replace_jsonl_record,
            )

    if reingested_source_ids or purged_claim_ids:
        deps.persist_ordered_claim_state(
            target,
            live_claims_by_id=claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
        )

    current_claim_records = deps.load_current_claim_records(claims_path)
    quality_archived_claim_ids: set[str] = set()
    if current_claim_records and context.claim_candidate_quality_config.enabled:
        deps.run_semantic_batch_task(
            target=target,
            task_name="claim_candidate_quality",
            dry_run=False,
        )
        current_claim_records, quality_archived_claim_ids, _ = deps.apply_claim_candidate_quality_decisions_to_claim_records(
            target=target,
            claim_records=current_claim_records,
            task_config=context.claim_candidate_quality_config,
        )
        if quality_archived_claim_ids:
            claims_created_by_source = {
                source_id: count
                for source_id, count in claims_created_by_source.items()
                if count > 0
            }

    semantic_claim_updates_applied = False
    if current_claim_records and context.claim_role_config.enabled:
        claim_records_before_semantic = [dict(record) for record in current_claim_records]
        deps.run_semantic_batch_task(
            target=target,
            task_name="claim_role",
            dry_run=False,
        )
        current_claim_records = deps.apply_claim_role_decisions_to_claim_records(
            target=target,
            claim_records=current_claim_records,
            task_config=context.claim_role_config,
        )
        semantic_claim_updates_applied = current_claim_records != claim_records_before_semantic
        deps.refresh_claim_state_from_records(context, current_claim_records)

    if reingested_source_ids or purged_review_ids:
        deps.persist_ordered_review_state(
            target,
            live_reviews_by_id=existing_reviews,
            historical_reviews_by_id=historical_reviews_by_id,
        )

    context.normalized_records = normalized_records
    context.active_source_ids = active_source_ids
    context.claims_created_by_source = claims_created_by_source
    context.semantic_claim_updates_applied = semantic_claim_updates_applied


def run_ingest_page_finalize_stage(
    context: IngestContext,
    request: IngestRequest,
    *,
    deps: IngestPageFinalizeDeps,
) -> object:
    skipped_result = deps.maybe_build_skipped_page_regeneration_result(context)
    if skipped_result is not None:
        return skipped_result

    target = context.target
    pages_path = context.pages_path
    claims_path = context.claims_path
    reviews_path = context.reviews_path
    sources_path = context.sources_path
    ingest_state_path = context.ingest_state_path
    normalized_path = context.normalized_path
    chunks_path = context.chunks_path
    task_id = context.task_id
    generated_pages = context.generated_pages
    sources_by_id = context.sources_by_id
    claims_by_id = context.claims_by_id
    historical_claims_by_id = context.historical_claims_by_id
    existing_reviews = context.existing_reviews
    historical_reviews_by_id = context.historical_reviews_by_id
    active_source_ids = context.active_source_ids
    claims_created_by_source = context.claims_created_by_source
    semantic_claim_updates_applied = context.semantic_claim_updates_applied
    review_items = context.review_items

    page_records = deps.load_existing_pages(pages_path)
    page_records = deps.apply_page_alias_overrides_to_records(target, page_records)
    page_records_by_id = {record["page_id"]: record for record in page_records}
    all_claim_records = deps.build_ordered_claim_state_records(
        live_claims_by_id=claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
    )
    all_chunk_records = deps.load_chunk_records(chunks_path)
    dirty_claim_ids: set[str] = set()
    dirty_review_ids: set[str] = set()
    existing_overview_page = page_records_by_id.get(deps.build_workspace_overview_page_id())
    if existing_overview_page is not None and existing_overview_page.get("type") == "overview":
        overview_page_id = existing_overview_page["page_id"]
        for claim_record in claims_by_id.values():
            if overview_page_id in claim_record.get("page_ids", []):
                claim_record["page_ids"] = [item for item in claim_record["page_ids"] if item != overview_page_id]
                claim_record["updated_at"] = deps.utc_now_iso()
                dirty_claim_ids.add(claim_record["claim_id"])
        for review_record in existing_reviews.values():
            if overview_page_id in review_record.get("candidate_page_ids", []):
                review_record["candidate_page_ids"] = [
                    item for item in review_record["candidate_page_ids"] if item != overview_page_id
                ]
                dirty_review_ids.add(review_record["review_id"])
    changed_source_ids = {record["source_id"] for record in context.created_sources}
    changed_source_ids.update(record["source_id"] for record in context.normalized_sources)
    changed_source_ids.update(record["source_id"] for record in context.chunked_sources)
    changed_source_ids.update(claims_created_by_source.keys())
    normalized_records_by_source = deps.load_normalized_records_by_source(normalized_path)
    claims_by_source_id = deps.build_claims_by_source_id(
        deps.filter_live_claim_records(all_claim_records)
    )
    chunks_by_source_id = deps.build_chunks_by_source_id(all_chunk_records)

    changed_source_ids.update(
        deps.collect_missing_source_page_source_ids(
            active_source_ids=active_source_ids,
            sources_by_id=sources_by_id,
            page_records_by_id=page_records_by_id,
            claims_by_source_id=claims_by_source_id,
            chunks_by_source_id=chunks_by_source_id,
        )
    )

    for source_record in deps.load_source_records(sources_path):
        source_id = source_record["source_id"]
        if source_id not in changed_source_ids:
            continue
        if source_id not in active_source_ids:
            continue
        source_claims = claims_by_source_id.get(source_id, [])
        source_chunks = chunks_by_source_id.get(source_id, [])
        if not source_claims and not source_chunks:
            continue

        source_record_for_page = dict(sources_by_id.get(source_id, source_record))
        source_record_for_page["status"] = "generated"

        normalized_record = normalized_records_by_source.get(source_id)
        page_rel_path = deps.source_summary_page_path(
            source_id,
            normalized_record["title"] if normalized_record else Path(source_record["source_path"]).stem,
        )
        page_text, page_record = deps.build_source_summary_page(
            target=target,
            source_record=source_record_for_page,
            page_rel_path=page_rel_path,
            normalized_record=normalized_record,
            claim_records=source_claims,
            chunk_records=source_chunks,
        )
        page_record = deps.apply_page_alias_overrides(target, page_record)
        page_record["page_path"] = str(page_rel_path)
        stored_page_record, page_changed = deps.upsert_wiki_page(
            target=target,
            page_records_by_id=page_records_by_id,
            page_record=page_record,
            page_text=page_text,
        )
        trace_lineage(
            operation="generated" if page_changed else "reused",
            reason="source_summary_inputs_changed" if page_changed else "source_summary_content_unchanged",
            inputs=lambda: [
                entity_reference("source", source_id, value=source_record_for_page, source_id=source_id),
                *[
                    entity_reference("claim", str(record.get("claim_id")), value=record, source_id=source_id)
                    for record in source_claims
                ],
                *[
                    entity_reference("chunk", str(record.get("chunk_id")), value=record, source_id=source_id)
                    for record in source_chunks
                ],
            ],
            outputs=lambda: [entity_reference(
                "page",
                str(stored_page_record["page_id"]),
                value={"record": stored_page_record, "text": page_text},
                path=page_rel_path,
                source_id=source_id,
            )],
            details={"page_type": stored_page_record.get("type")},
            snapshot_name=f"page_{stored_page_record['page_id']}_source_summary",
        )
        if page_changed:
            generated_pages.append(stored_page_record)
            dirty_claim_ids.update(
                deps.link_claims_to_page_in_memory(
                    source_claims,
                    stored_page_record["page_id"],
                    claims_by_id,
                )
            )

        replace_source_record_and_ingest_state(
            source_id=source_id,
            source_record=source_record_for_page,
            source_status="generated",
            normalized_path=source_record_for_page.get("normalized_path"),
            sources_path=sources_path,
            ingest_state_path=ingest_state_path,
            sources_by_id=sources_by_id,
            task_id=task_id,
            stage_state="generated",
            last_successful_stage="generated",
            failed_stage=None,
            utc_now_iso=deps.utc_now_iso,
            replace_jsonl_record=deps.replace_jsonl_record,
        )

    all_claim_records = list(claims_by_id.values())
    review_records = list(existing_reviews.values())
    concept_claim_groups: dict[str, list[dict]] = {}
    for claim_record in all_claim_records:
        active_claim_source_ids = [
            source_id for source_id in claim_record.get("source_ids", [])
            if source_id in active_source_ids
        ]
        if not active_claim_source_ids:
            continue
        bucket_key = deps.build_concept_group_key(claim_record)
        concept_claim_groups.setdefault(bucket_key, []).append(claim_record)
    concept_claim_groups = deps.regroup_concept_claims_by_canonical_topic(concept_claim_groups)
    if concept_claim_groups and context.page_intent_config.enabled:
        deps.run_semantic_batch_task(
            target=target,
            task_name="page_intent",
            dry_run=False,
        )
    page_routes_by_bucket = deps.apply_page_intent_decisions_to_claim_groups(
        target=target,
        concept_claim_groups=concept_claim_groups,
        task_config=context.page_intent_config,
    )

    changed_bucket_keys = set()
    for claim_record in all_claim_records:
        if any(source_id in changed_source_ids for source_id in claim_record.get("source_ids", [])):
            original_bucket_key = deps.build_concept_group_key(claim_record)
            matching_bucket_key = next(
                (
                    bucket_key
                    for bucket_key, grouped_claims in concept_claim_groups.items()
                    if any(item["claim_id"] == claim_record["claim_id"] for item in grouped_claims)
                ),
                original_bucket_key,
            )
            changed_bucket_keys.add(matching_bucket_key)
    changed_bucket_keys.update(
        deps.collect_missing_concept_bucket_keys(
            claims_by_similarity_bucket=concept_claim_groups,
            page_records_by_id=page_records_by_id,
        )
    )
    if semantic_claim_updates_applied:
        changed_bucket_keys.update(concept_claim_groups.keys())
    for bucket_key, grouped_claims in sorted(concept_claim_groups.items()):
        if bucket_key not in changed_bucket_keys:
            continue
        page_route = deps.page_route_for_bucket(page_routes_by_bucket, bucket_key)
        page_intent = deps.preferred_page_intent_for_claim_group(
            grouped_claims,
            page_route.get("page_intent", "topic"),
        )
        page_route["page_intent"] = page_intent
        page_route["route_target"] = page_intent
        if page_intent == "reject":
            continue
        if page_intent == "concept" and deps.should_generate_concept_page(grouped_claims):
            group_topic_label = deps.choose_group_topic_label(grouped_claims)
            canonical_claim = deps.choose_canonical_claim(grouped_claims, group_topic_label)
            concept_page_id = deps.build_concept_page_id(bucket_key)
            concept_title, _ = deps.resolve_concept_title_candidate(
                target=target,
                config=context.config,
                canonical_claim=canonical_claim,
                claim_records=grouped_claims,
                preferred_section_label=group_topic_label,
            )
            page_rel_path = deps.concept_summary_page_path(
                concept_page_id,
                concept_title,
            )
            page_text, page_record = deps.build_concept_page(
                target=target,
                bucket_key=bucket_key,
                page_rel_path=page_rel_path,
                claim_records=grouped_claims,
                page_records_by_id=page_records_by_id,
                review_records=review_records,
                render_config=context.readable_concept_render_config,
            )
            page_record = deps.apply_page_route_to_page_record(page_record, page_route)
            page_record = deps.apply_page_alias_overrides(target, page_record)
            page_record["page_path"] = str(page_rel_path)
            stored_page_record, page_changed = deps.upsert_wiki_page(
                target=target,
                page_records_by_id=page_records_by_id,
                page_record=page_record,
                page_text=page_text,
            )
            trace_lineage(
                operation="generated" if page_changed else "reused",
                reason="concept_page_inputs_changed" if page_changed else "concept_page_content_unchanged",
                inputs=lambda: [
                    entity_reference("claim", str(record.get("claim_id")), value=record)
                    for record in grouped_claims
                ],
                outputs=lambda: [entity_reference(
                    "page",
                    str(stored_page_record["page_id"]),
                    value={"record": stored_page_record, "text": page_text, "route": page_route},
                    path=page_rel_path,
                )],
                details={"bucket_key": bucket_key, "page_intent": page_intent},
                snapshot_name=f"page_{stored_page_record['page_id']}_concept",
            )
            if page_changed:
                generated_pages.append(stored_page_record)
                dirty_claim_ids.update(
                    deps.link_claims_to_page_in_memory(
                        grouped_claims,
                        stored_page_record["page_id"],
                        claims_by_id,
                    )
                )
                dirty_review_ids.update(
                    deps.link_reviews_to_page_in_memory(
                        review_records=review_records,
                        page_id=stored_page_record["page_id"],
                        claim_ids=stored_page_record["claim_ids"],
                        reviews_by_id=existing_reviews,
                    )
                )

        elif page_intent in {"guide", "duty", "example", "topic", "reference", "timeline"}:
            page_id = deps.page_intent_page_id(bucket_key, page_intent)
            page_title_source = deps.choose_group_topic_label(grouped_claims) or deps.choose_canonical_claim(grouped_claims).get("text", "")
            page_rel_path = deps.page_intent_page_path(page_intent, page_id, page_title_source)
            page_text, page_record = deps.build_intent_routed_page(
                target=target,
                config=context.config,
                bucket_key=bucket_key,
                page_intent=page_intent,
                page_rel_path=page_rel_path,
                claim_records=grouped_claims,
                page_records_by_id=page_records_by_id,
                review_records=review_records,
            )
            page_record = deps.apply_page_route_to_page_record(page_record, page_route)
            page_record = deps.apply_page_alias_overrides(target, page_record)
            page_record["page_path"] = str(page_rel_path)
            stored_page_record, page_changed = deps.upsert_wiki_page(
                target=target,
                page_records_by_id=page_records_by_id,
                page_record=page_record,
                page_text=page_text,
            )
            trace_lineage(
                operation="generated" if page_changed else "reused",
                reason="intent_page_inputs_changed" if page_changed else "intent_page_content_unchanged",
                inputs=lambda: [
                    entity_reference("claim", str(record.get("claim_id")), value=record)
                    for record in grouped_claims
                ],
                outputs=lambda: [entity_reference(
                    "page",
                    str(stored_page_record["page_id"]),
                    value={"record": stored_page_record, "text": page_text, "route": page_route},
                    path=page_rel_path,
                )],
                details={"bucket_key": bucket_key, "page_intent": page_intent},
                snapshot_name=f"page_{stored_page_record['page_id']}_{page_intent}",
            )
            if page_changed:
                generated_pages.append(stored_page_record)
                dirty_claim_ids.update(
                    deps.link_claims_to_page_in_memory(
                        grouped_claims,
                        stored_page_record["page_id"],
                        claims_by_id,
                    )
                )
                dirty_review_ids.update(
                    deps.link_reviews_to_page_in_memory(
                        review_records=review_records,
                        page_id=stored_page_record["page_id"],
                        claim_ids=stored_page_record["claim_ids"],
                        reviews_by_id=existing_reviews,
                    )
                )

    overview_concept_pages = deps.collect_workspace_overview_concept_pages(
        claims_by_similarity_bucket=concept_claim_groups,
        page_records_by_id=page_records_by_id,
    )
    if deps.should_generate_workspace_overview_page(overview_concept_pages):
        overview_page_rel_path = deps.workspace_overview_page_path()
        overview_page_text, overview_page_record = deps.build_workspace_overview_page(
            target=target,
            page_rel_path=overview_page_rel_path,
            concept_pages=overview_concept_pages,
            page_records_by_id=page_records_by_id,
            claim_records_by_id=claims_by_id,
            render_config=context.overview_render_config,
        )
        overview_page_record = deps.apply_page_alias_overrides(target, overview_page_record)
        overview_page_record["page_path"] = str(overview_page_rel_path)
        stored_overview_page, overview_page_changed = deps.upsert_wiki_page(
            target=target,
            page_records_by_id=page_records_by_id,
            page_record=overview_page_record,
            page_text=overview_page_text,
        )
        trace_lineage(
            operation="generated" if overview_page_changed else "reused",
            reason="overview_inputs_changed" if overview_page_changed else "overview_content_unchanged",
            inputs=lambda: [
                entity_reference("page", str(record.get("page_id")), value=record)
                for record in overview_concept_pages
            ],
            outputs=lambda: [entity_reference(
                "page",
                str(stored_overview_page["page_id"]),
                value={"record": stored_overview_page, "text": overview_page_text},
                path=overview_page_rel_path,
            )],
            details={"page_type": "overview"},
            snapshot_name=f"page_{stored_overview_page['page_id']}_overview",
        )
        dirty_claim_ids.update(
            deps.link_claims_to_page_in_memory(
                [
                    claims_by_id[claim_id]
                    for claim_id in stored_overview_page["claim_ids"]
                    if claim_id in claims_by_id
                ],
                stored_overview_page["page_id"],
                claims_by_id,
            )
        )
        dirty_review_ids.update(
            deps.link_reviews_to_page_in_memory(
                review_records=review_records,
                page_id=stored_overview_page["page_id"],
                claim_ids=stored_overview_page["claim_ids"],
                reviews_by_id=existing_reviews,
            )
        )
        if overview_page_changed:
            generated_pages.append(stored_overview_page)

    desired_auto_page_ids = {
        deps.expected_source_summary_page_id(source_id)
        for source_id in active_source_ids
        if claims_by_source_id.get(source_id) or chunks_by_source_id.get(source_id)
    }
    forced_stale_page_ids: set[str] = set()
    for bucket_key, grouped_claims in concept_claim_groups.items():
        page_route = deps.page_route_for_bucket(page_routes_by_bucket, bucket_key)
        page_intent = page_route.get("page_intent", "topic")
        forced_stale_page_ids.update(
            {
                deps.build_concept_page_id(bucket_key),
                *{
                    deps.page_intent_page_id(bucket_key, stale_intent)
                    for stale_intent in {"guide", "duty", "example", "topic", "reference", "timeline"}
                    if stale_intent != page_intent
                },
            }
        )
        if page_intent == "concept" and deps.should_generate_concept_page(grouped_claims):
            desired_auto_page_ids.add(deps.build_concept_page_id(bucket_key))
        elif page_intent in {"guide", "duty", "example", "topic", "reference", "timeline"}:
            desired_auto_page_ids.add(deps.page_intent_page_id(bucket_key, page_intent))
    if deps.should_generate_workspace_overview_page(overview_concept_pages):
        desired_auto_page_ids.add(deps.build_workspace_overview_page_id())

    removed_pages, pruned_claim_ids, pruned_review_ids = deps.prune_stale_auto_pages(
        target=target,
        page_records_by_id=page_records_by_id,
        desired_auto_page_ids=desired_auto_page_ids,
        claims_by_id=claims_by_id,
        reviews_by_id=existing_reviews,
        forced_stale_page_ids=forced_stale_page_ids - desired_auto_page_ids,
    )
    if removed_pages:
        generated_pages.extend(removed_pages)
        for removed_page in removed_pages:
            trace_lineage(
                operation="removed",
                reason="page_no_longer_matches_current_route_or_source_state",
                inputs=lambda: [entity_reference(
                    "page",
                    str(removed_page.get("page_id")),
                    value=removed_page,
                    path=str(removed_page.get("page_path", "")),
                )],
                outputs=lambda: [],
                snapshot_name=f"page_{removed_page.get('page_id')}_removed",
            )
    dirty_claim_ids.update(pruned_claim_ids)
    dirty_review_ids.update(pruned_review_ids)

    if dirty_claim_ids:
        claim_state_records = deps.persist_ordered_claim_state(
            target,
            live_claims_by_id=claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
        )
        dirty_claim_ids.intersection_update(
            {record["claim_id"] for record in claim_state_records}
        )

    if dirty_review_ids:
        review_state_records = deps.persist_ordered_review_state(
            target,
            live_reviews_by_id=existing_reviews,
            historical_reviews_by_id=historical_reviews_by_id,
        )
        dirty_review_ids.intersection_update(
            {record["review_id"] for record in review_state_records}
        )

    deps.persist_page_records(
        target,
        page_records=list(page_records_by_id.values()),
    )
    page_links_index = deps.write_page_links_index(target, list(page_records_by_id.values()))
    for page_id, link_entry in page_links_index.get("pages", {}).items():
        page_record = page_records_by_id.get(page_id)
        if page_record is None:
            continue
        page_record["outgoing_page_ids"] = link_entry.get("outgoing_page_ids", [])
        page_record["incoming_page_ids"] = link_entry.get("incoming_page_ids", [])
        page_record["related_page_ids"] = link_entry.get("related_page_ids", [])
    deps.persist_page_records(
        target,
        page_records=list(page_records_by_id.values()),
    )

    all_claim_records = list(claims_by_id.values())
    page_records_for_index = list(page_records_by_id.values())
    claim_records_by_id = {record["claim_id"]: record for record in all_claim_records}
    previous_search_index_records = deps.load_search_pages_index(target)
    search_index = deps.write_search_pages_index(
        target=target,
        page_records=page_records_for_index,
        claim_records_by_id=claim_records_by_id,
        previous_records=previous_search_index_records,
    )
    trace_lineage(
        operation="generated" if search_index.get("rebuilt_count", 0) else "reused",
        reason="page_search_documents_refreshed",
        inputs=lambda: [
            entity_reference("page", str(record.get("page_id")), value=record)
            for record in page_records_for_index
        ],
        outputs=lambda: [entity_reference(
            "search_index",
            str(search_index.get("index_version", "current")),
            value=search_index,
            path=str(search_index.get("index_path", "indexes/search_pages.jsonl")),
        )],
        snapshot_name="search_index_refresh",
    )

    alias_index = deps.write_alias_index(target, page_records_for_index)
    alias_conflict_reviews, _ = deps.build_alias_conflict_reviews(alias_index, existing_reviews)
    for review_record in alias_conflict_reviews:
        review_file_path = deps.write_review_file(target, review_record)
        review_record["review_file_path"] = review_file_path
        deps.append_jsonl(reviews_path, review_record)
        existing_reviews[review_record["review_id"]] = review_record
        review_items.append(review_record)
    deps.rebuild_wiki_index(target, list(page_records_by_id.values()))
    deps.append_wiki_log(target, task_id, generated_pages)

    return deps.build_ingest_command_result(
        context,
        search_index=search_index,
        alias_index={
            **alias_index,
            "index_path": "indexes/aliases.json",
        },
        changed_page_count=len(generated_pages),
        message="Ingest registration, normalization, chunking, claim drafting, and wiki generation completed.",
    )


def refresh_ingest_claim_similarity_state(
    context: IngestContext,
    live_claim_records: list[dict],
    *,
    deps: IngestHelperDeps,
) -> None:
    context.claims_by_normalized_text = {
        record["normalized_text"]: record for record in live_claim_records
    }
    context.claims_by_similarity_bucket = {}
    for record in live_claim_records:
        context.claims_by_similarity_bucket.setdefault(
            deps.build_similarity_bucket(record["text"]),
            [],
        ).append(record)
    context.claim_similarity_index = deps.rebuild_claim_similarity_index(live_claim_records)


def refresh_ingest_claim_state_from_records(
    context: IngestContext,
    claim_records: list[dict],
    *,
    deps: IngestHelperDeps,
) -> None:
    live_claim_records = deps.filter_live_claim_records(claim_records)
    historical_claim_records = [
        record for record in claim_records
        if not deps.is_live_claim_record(record)
    ]
    context.claims_by_id = {record["claim_id"]: record for record in live_claim_records}
    context.historical_claims_by_id = {
        record["claim_id"]: record for record in historical_claim_records
    }
    refresh_ingest_claim_similarity_state(
        context,
        live_claim_records,
        deps=deps,
    )


def build_claims_by_source_id(claim_records: list[dict]) -> dict[str, list[dict]]:
    claims_by_source_id: dict[str, list[dict]] = {}
    for claim_record in claim_records:
        for source_id in claim_record.get("source_ids", []):
            claims_by_source_id.setdefault(source_id, []).append(claim_record)
    return claims_by_source_id


def build_chunks_by_source_id(chunk_records: list[dict]) -> dict[str, list[dict]]:
    chunks_by_source_id: dict[str, list[dict]] = {}
    for chunk_record in chunk_records:
        chunks_by_source_id.setdefault(chunk_record["source_id"], []).append(chunk_record)
    return chunks_by_source_id


def run_post_ingest_review_auto_if_enabled(
    context: IngestContext,
    *,
    deps: IngestHelperDeps,
) -> dict | None:
    if not context.post_ingest_config.get("review_auto"):
        return None
    with trace_step(
        "ingest.post_review_auto",
        kind="review_stage",
        input_data={
            "claims": list(context.claims_by_id.values()),
            "reviews": list(context.existing_reviews.values()),
        },
    ) as step:
        result = deps.run_post_ingest_review_auto(context.target)
        step.set_output(result)
        return result


def build_ingest_command_result(
    context: IngestContext,
    *,
    search_index: dict,
    alias_index: dict,
    changed_page_count: int,
    message: str,
    deps: IngestHelperDeps,
    existing_page_count: int | None = None,
    tracked_page_count: int | None = None,
) -> object:
    post_ingest_review_auto_payload = run_post_ingest_review_auto_if_enabled(
        context,
        deps=deps,
    )
    payload = deps.build_ingest_payload(
        context=context,
        workspace_summary=deps.build_workspace_summary(context.target, context.raw_dir),
        search_index=search_index,
        alias_index={
            **alias_index,
            "index_path": deps.alias_index_rel_path,
        },
        changed_page_count=changed_page_count,
        existing_page_count=existing_page_count,
        tracked_page_count=tracked_page_count,
    )
    if post_ingest_review_auto_payload is not None:
        payload["post_ingest_review_auto"] = post_ingest_review_auto_payload
    return deps.render_workspace_summary_message(
        message,
        target_dir=context.target,
        raw_dir=context.raw_dir,
        extra_lines=[
            f"Task id: {context.task_id}",
            (
                "Ingest: "
                f"normalized={payload['summary']['normalized_count']}, "
                f"structured={payload['summary']['structured_count']}, "
                f"chunks={payload['summary']['chunked_count']}, "
                f"claims={payload['summary']['claimed_count']}, "
                f"changed_pages={payload['summary']['changed_page_count']}, "
                f"reviews_detected={payload['summary']['review_count']}, "
                f"warnings={payload['summary']['warning_count']}, "
                f"errors={payload['summary']['error_count']}"
            ),
            (
                deps.render_post_ingest_review_auto_summary(post_ingest_review_auto_payload)
            )
            if post_ingest_review_auto_payload is not None
            else None,
        ],
    ), payload


def maybe_build_skipped_page_regeneration_result(
    context: IngestContext,
    *,
    deps: IngestHelperDeps,
    build_result: Callable[..., object],
) -> object | None:
    can_skip_page_regeneration = deps.workspace_can_skip_page_regeneration(
        sources_by_id=context.sources_by_id,
        created_sources=context.created_sources,
        normalized_sources=context.normalized_sources,
        chunked_sources=context.chunked_sources,
        claims_created_by_source=context.claims_created_by_source,
        review_items=context.review_items,
        semantic_claim_updates_applied=context.semantic_claim_updates_applied,
    )
    if not can_skip_page_regeneration:
        return None

    existing_pages = deps.load_existing_pages(context.pages_path)
    existing_pages = deps.apply_page_alias_overrides_to_records(context.target, existing_pages)
    live_existing_pages = deps.filter_live_page_records(existing_pages)
    page_records_by_id = {record["page_id"]: record for record in existing_pages}
    all_chunk_records = deps.load_chunk_records(context.chunks_path)
    claims_by_source_id = build_claims_by_source_id(list(context.claims_by_id.values()))
    chunks_by_source_id = build_chunks_by_source_id(all_chunk_records)
    missing_source_page_source_ids = deps.collect_missing_source_page_source_ids(
        active_source_ids=context.active_source_ids,
        sources_by_id=context.sources_by_id,
        page_records_by_id=page_records_by_id,
        claims_by_source_id=claims_by_source_id,
        chunks_by_source_id=chunks_by_source_id,
    )
    missing_concept_bucket_keys = deps.collect_missing_concept_bucket_keys(
        claims_by_similarity_bucket=context.claims_by_similarity_bucket,
        page_records_by_id=page_records_by_id,
    )
    missing_workspace_overview = deps.workspace_overview_page_missing(
        claims_by_similarity_bucket=context.claims_by_similarity_bucket,
        page_records_by_id=page_records_by_id,
    )
    if (
        missing_source_page_source_ids
        or missing_concept_bucket_keys
        or missing_workspace_overview
    ):
        return None

    deps.persist_page_records(
        context.target,
        page_records=existing_pages,
    )
    alias_index = deps.write_alias_index(context.target, existing_pages)
    previous_search_index_records = deps.load_search_pages_index(context.target)
    search_index = {
        "index_path": deps.search_pages_index_rel_path,
        "record_count": len(previous_search_index_records),
        "rebuilt_count": 0,
        "reused_count": len(previous_search_index_records),
        "index_version": deps.search_pages_index_version,
        "updated_at": deps.utc_now_iso(),
    }
    trace_lineage(
        operation="skipped",
        reason="no_upstream_changes_and_no_missing_pages",
        inputs=lambda: [
            *[
                entity_reference("source", str(record.get("source_id")), value=record, source_id=str(record.get("source_id")))
                for record in context.sources_by_id.values()
            ],
            *[
                entity_reference("claim", str(record.get("claim_id")), value=record)
                for record in context.claims_by_id.values()
            ],
        ],
        outputs=lambda: [
            entity_reference("page", str(record.get("page_id")), value=record, path=str(record.get("page_path", "")))
            for record in existing_pages
        ],
        details={
            "existing_page_count": len(live_existing_pages),
            "search_index_reused_count": len(previous_search_index_records),
        },
        snapshot_name="page_regeneration_skipped",
    )
    deps.append_wiki_log(context.target, context.task_id, context.generated_pages)
    return build_result(
        context,
        search_index=search_index,
        alias_index=alias_index,
        changed_page_count=0,
        existing_page_count=len(live_existing_pages),
        tracked_page_count=len(existing_pages),
        message="Ingest completed with no upstream changes; wiki regeneration was skipped.",
    )
