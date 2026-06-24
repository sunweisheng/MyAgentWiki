from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..app_services.ingest_service import (
    IngestContext,
    IngestContextDeps,
    IngestHelperDeps,
    IngestPageFinalizeDeps,
    IngestRegistrationDeps,
    IngestRequest,
    IngestServiceDeps,
    IngestStructureClaimDeps,
    build_ingest_context as build_ingest_context_service,
    build_ingest_payload,
    build_chunks_by_source_id as build_chunks_by_source_id_service,
    build_claims_by_source_id as build_claims_by_source_id_service,
    build_ingest_command_result as build_ingest_command_result_service,
    maybe_build_skipped_page_regeneration_result as maybe_build_skipped_page_regeneration_result_service,
    refresh_ingest_claim_similarity_state as refresh_ingest_claim_similarity_state_service,
    refresh_ingest_claim_state_from_records as refresh_ingest_claim_state_from_records_service,
    run_post_ingest_review_auto_if_enabled as run_post_ingest_review_auto_if_enabled_service,
    run_ingest_page_finalize_stage as run_ingest_page_finalize_service,
    run_ingest_registration_and_normalization_stage as run_ingest_registration_and_normalization_service,
    run_ingest_service,
    run_ingest_structure_chunk_claim_stage as run_ingest_structure_chunk_claim_service,
)
from ..repositories.ingest_persistence import (
    persist_claim_records as repo_persist_ingest_claim_records,
    persist_ordered_claim_state as repo_persist_ingest_ordered_claim_state,
    persist_ordered_review_state as repo_persist_ingest_ordered_review_state,
    persist_page_records as repo_persist_page_records,
    persist_review_records as repo_persist_ingest_review_records,
)
from ..repositories.ingest_state import (
    build_chunk_records_by_source_loader as repo_build_chunk_records_by_source_loader,
    build_chunk_records_loader as repo_build_chunk_records_loader,
    build_existing_chunked_by_source_loader as repo_build_existing_chunked_by_source_loader,
    build_existing_claim_state_loader as repo_build_existing_claim_state_loader,
    build_existing_pages_loader as repo_build_existing_pages_loader,
    build_existing_review_state_loader as repo_build_existing_review_state_loader,
    build_existing_sources_loader as repo_build_existing_sources_loader,
    load_active_knowledge_units_by_source as repo_load_active_knowledge_units_by_source,
    load_current_claim_records as repo_load_current_claim_records,
    load_existing_normalized_by_source as repo_load_existing_normalized_by_source,
    load_existing_structured_source_ids as repo_load_existing_structured_source_ids,
    load_normalized_records as repo_load_normalized_records,
    load_normalized_records_by_source as repo_load_normalized_records_by_source,
    load_source_records as repo_load_source_records,
)
from .result import CommandResult


@dataclass(frozen=True)
class IngestCliDeps:
    build_similarity_bucket: object
    rebuild_claim_similarity_index: object
    filter_live_claim_records: object
    is_live_claim_record: object
    run_post_ingest_review_auto: object
    build_workspace_summary: object
    render_workspace_summary_message: object
    render_post_ingest_review_auto_summary: object
    alias_index_rel_path: str
    workspace_can_skip_page_regeneration: object
    apply_page_alias_overrides_to_records: object
    filter_live_page_records: object
    load_jsonl: object
    load_existing_pages: object
    load_chunk_records: object
    collect_missing_source_page_source_ids: object
    collect_missing_concept_bucket_keys: object
    workspace_overview_page_missing: object
    persist_page_records: object
    write_alias_index: object
    load_search_pages_index: object
    search_pages_index_rel_path: str
    search_pages_index_version: str
    utc_now_iso: object
    append_wiki_log: object
    ensure_workspace_schema_supported: object
    load_workspace_config: object
    load_post_ingest_review_auto_config: object
    load_semantic_task_config: object
    load_readable_concept_render_config: object
    load_page_render_config: object
    resolve_workspace_raw_dir: object
    load_existing_sources: object
    load_existing_normalized_by_source: object
    load_existing_structured_source_ids: object
    load_existing_chunked_by_source: object
    load_existing_claim_state: object
    load_existing_review_state: object
    load_normalized_records_by_source: object
    load_source_records: object
    ensure_claim_lifecycle_defaults: object
    ensure_review_lifecycle_defaults: object
    filter_live_review_records: object
    is_live_review_record: object
    build_latest_source_record_by_path: object
    structure_blocks_rel_path: object
    evidence_blocks_rel_path: object
    knowledge_units_rel_path: object
    collect_files: object
    file_sha256: object
    infer_source_type: object
    build_source_version_group_from_source_path: object
    replace_source_scoped_jsonl_records: object
    purge_source_from_claims: object
    purge_deleted_claims_from_reviews: object
    replace_jsonl_record: object
    build_source_id: object
    build_source_version_group: object
    append_jsonl: object
    normalize_source_record: object
    load_normalized_records: object
    append_error_record: object
    run_semantic_batch_task: object
    apply_document_analysis_decisions_to_normalized_records: object
    compile_structure_knowledge_records: object
    chunk_normalized_record: object
    replace_jsonl_records_by_filter: object
    source_claim_stage_completed: object
    load_chunk_records_by_source: object
    load_active_knowledge_units_by_source: object
    load_current_claim_records: object
    choose_active_source_ids: object
    build_claim_candidates_for_source: object
    merge_claim_records: object
    write_claim_file: object
    collect_claim_review_candidate_ids: object
    has_negation: object
    claims_are_similar_for_review: object
    build_review_record: object
    index_claim_similarity_tokens: object
    persist_ordered_claim_state: object
    apply_claim_candidate_quality_decisions_to_claim_records: object
    apply_claim_role_decisions_to_claim_records: object
    persist_ordered_review_state: object
    write_review_file: object
    apply_page_alias_overrides: object
    upsert_wiki_page: object
    link_claims_to_page_in_memory: object
    build_ordered_claim_state_records: object
    build_ordered_review_state_records: object
    build_concept_group_key: object
    regroup_concept_claims_by_canonical_topic: object
    apply_page_intent_decisions_to_claim_groups: object
    page_route_for_bucket: object
    preferred_page_intent_for_claim_group: object
    should_generate_concept_page: object
    choose_group_topic_label: object
    choose_canonical_claim: object
    resolve_concept_title_candidate: object
    build_concept_page_id: object
    concept_summary_page_path: object
    build_concept_page: object
    apply_page_route_to_page_record: object
    link_reviews_to_page_in_memory: object
    page_intent_page_id: object
    page_intent_page_path: object
    build_intent_routed_page: object
    collect_workspace_overview_concept_pages: object
    should_generate_workspace_overview_page: object
    workspace_overview_page_path: object
    build_workspace_overview_page: object
    build_workspace_overview_page_id: object
    expected_source_summary_page_id: object
    prune_stale_auto_pages: object
    write_page_links_index: object
    write_search_pages_index: object
    build_alias_conflict_reviews: object
    rebuild_wiki_index: object
    source_summary_page_path: object
    build_source_summary_page: object


def build_ingest_cli_deps(provider: Any) -> IngestCliDeps:
    load_jsonl = provider.load_jsonl
    write_jsonl = provider.write_jsonl

    return IngestCliDeps(
        build_similarity_bucket=provider.build_similarity_bucket,
        rebuild_claim_similarity_index=provider.rebuild_claim_similarity_index,
        filter_live_claim_records=provider.filter_live_claim_records,
        is_live_claim_record=provider.is_live_claim_record,
        run_post_ingest_review_auto=provider.run_post_ingest_review_auto,
        build_workspace_summary=provider.build_workspace_summary,
        render_workspace_summary_message=provider.render_workspace_summary_message,
        render_post_ingest_review_auto_summary=provider.render_post_ingest_review_auto_summary,
        alias_index_rel_path=str(provider.ALIAS_INDEX_REL_PATH),
        workspace_can_skip_page_regeneration=provider.workspace_can_skip_page_regeneration,
        apply_page_alias_overrides_to_records=provider.apply_page_alias_overrides_to_records,
        filter_live_page_records=provider.filter_live_page_records,
        load_jsonl=load_jsonl,
        load_existing_pages=repo_build_existing_pages_loader(
            load_jsonl=load_jsonl,
            ensure_page_lifecycle_defaults=provider.ensure_page_lifecycle_defaults,
        ),
        load_chunk_records=repo_build_chunk_records_loader(
            load_jsonl=load_jsonl,
        ),
        collect_missing_source_page_source_ids=provider.collect_missing_source_page_source_ids,
        collect_missing_concept_bucket_keys=provider.collect_missing_concept_bucket_keys,
        workspace_overview_page_missing=provider.workspace_overview_page_missing,
        persist_page_records=lambda workspace_target, page_records: repo_persist_page_records(
            workspace_target,
            page_records=page_records,
            write_jsonl=write_jsonl,
        ),
        write_alias_index=provider.write_alias_index,
        load_search_pages_index=provider.load_search_pages_index,
        search_pages_index_rel_path=str(provider.SEARCH_PAGES_INDEX_REL_PATH),
        search_pages_index_version=provider.SEARCH_PAGES_INDEX_VERSION,
        utc_now_iso=provider.utc_now_iso,
        append_wiki_log=provider.append_wiki_log,
        ensure_workspace_schema_supported=provider.ensure_workspace_schema_supported,
        load_workspace_config=provider.load_workspace_config,
        load_post_ingest_review_auto_config=provider.load_post_ingest_review_auto_config,
        load_semantic_task_config=provider.load_semantic_task_config,
        load_readable_concept_render_config=provider.load_readable_concept_render_config,
        load_page_render_config=provider.load_page_render_config,
        resolve_workspace_raw_dir=provider.resolve_workspace_raw_dir,
        load_existing_sources=repo_build_existing_sources_loader(
            load_jsonl=load_jsonl,
        ),
        load_existing_normalized_by_source=lambda normalized_path: repo_load_existing_normalized_by_source(
            normalized_path,
            load_jsonl=load_jsonl,
        ),
        load_existing_structured_source_ids=lambda structure_blocks_path, evidence_blocks_path, knowledge_units_path: repo_load_existing_structured_source_ids(
            structure_blocks_path=structure_blocks_path,
            evidence_blocks_path=evidence_blocks_path,
            knowledge_units_path=knowledge_units_path,
            load_jsonl=load_jsonl,
        ),
        load_existing_chunked_by_source=repo_build_existing_chunked_by_source_loader(
            load_jsonl=load_jsonl,
        ),
        load_existing_claim_state=repo_build_existing_claim_state_loader(
            load_jsonl=load_jsonl,
            ensure_claim_lifecycle_defaults=provider.ensure_claim_lifecycle_defaults,
            filter_live_claim_records=provider.filter_live_claim_records,
            is_live_claim_record=provider.is_live_claim_record,
        ),
        load_existing_review_state=repo_build_existing_review_state_loader(
            load_jsonl=load_jsonl,
            ensure_review_lifecycle_defaults=provider.ensure_review_lifecycle_defaults,
            filter_live_review_records=provider.filter_live_review_records,
            is_live_review_record=provider.is_live_review_record,
        ),
        load_normalized_records_by_source=lambda normalized_path: repo_load_normalized_records_by_source(
            normalized_path,
            load_jsonl=load_jsonl,
        ),
        load_source_records=lambda sources_path: repo_load_source_records(
            sources_path,
            load_jsonl=load_jsonl,
        ),
        ensure_claim_lifecycle_defaults=provider.ensure_claim_lifecycle_defaults,
        ensure_review_lifecycle_defaults=provider.ensure_review_lifecycle_defaults,
        filter_live_review_records=provider.filter_live_review_records,
        is_live_review_record=provider.is_live_review_record,
        build_latest_source_record_by_path=provider.build_latest_source_record_by_path,
        structure_blocks_rel_path=provider.STRUCTURE_BLOCKS_REL_PATH,
        evidence_blocks_rel_path=provider.EVIDENCE_BLOCKS_REL_PATH,
        knowledge_units_rel_path=provider.KNOWLEDGE_UNITS_REL_PATH,
        collect_files=provider.collect_files,
        file_sha256=provider.file_sha256,
        infer_source_type=provider.infer_source_type,
        build_source_version_group_from_source_path=provider.build_source_version_group_from_source_path,
        replace_source_scoped_jsonl_records=provider.replace_source_scoped_jsonl_records,
        purge_source_from_claims=provider.purge_source_from_claims,
        purge_deleted_claims_from_reviews=provider.purge_deleted_claims_from_reviews,
        replace_jsonl_record=provider.replace_jsonl_record,
        build_source_id=provider.build_source_id,
        build_source_version_group=provider.build_source_version_group,
        append_jsonl=provider.append_jsonl,
        normalize_source_record=provider.normalize_source_record,
        load_normalized_records=lambda normalized_path: repo_load_normalized_records(
            normalized_path,
            load_jsonl=load_jsonl,
        ),
        append_error_record=provider.append_error_record,
        run_semantic_batch_task=provider.run_semantic_batch_task,
        apply_document_analysis_decisions_to_normalized_records=provider.apply_document_analysis_decisions_to_normalized_records,
        compile_structure_knowledge_records=provider.compile_structure_knowledge_records,
        chunk_normalized_record=provider.chunk_normalized_record,
        replace_jsonl_records_by_filter=provider.replace_jsonl_records_by_filter,
        source_claim_stage_completed=provider.source_claim_stage_completed,
        load_chunk_records_by_source=repo_build_chunk_records_by_source_loader(
            load_jsonl=load_jsonl,
        ),
        load_active_knowledge_units_by_source=lambda knowledge_units_path: repo_load_active_knowledge_units_by_source(
            knowledge_units_path,
            load_jsonl=load_jsonl,
        ),
        load_current_claim_records=lambda claims_path: repo_load_current_claim_records(
            claims_path,
            load_jsonl=load_jsonl,
            ensure_claim_lifecycle_defaults=provider.ensure_claim_lifecycle_defaults,
        ),
        choose_active_source_ids=provider.choose_active_source_ids,
        build_claim_candidates_for_source=provider.build_claim_candidates_for_source,
        merge_claim_records=provider.merge_claim_records,
        write_claim_file=provider.write_claim_file,
        collect_claim_review_candidate_ids=provider.collect_claim_review_candidate_ids,
        has_negation=provider.has_negation,
        claims_are_similar_for_review=provider.claims_are_similar_for_review,
        build_review_record=provider.build_review_record,
        index_claim_similarity_tokens=provider.index_claim_similarity_tokens,
        persist_ordered_claim_state=lambda workspace_target, live_claims_by_id, historical_claims_by_id: repo_persist_ingest_ordered_claim_state(
            workspace_target,
            live_claims_by_id=live_claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
            build_ordered_claim_state_records=provider.build_ordered_claim_state_records,
            persist_claim_records=lambda target_for_repo, claim_records: repo_persist_ingest_claim_records(
                target_for_repo,
                claim_records=claim_records,
                write_jsonl=write_jsonl,
                write_claim_file=provider.write_claim_file,
            ),
        ),
        apply_claim_candidate_quality_decisions_to_claim_records=provider.apply_claim_candidate_quality_decisions_to_claim_records,
        apply_claim_role_decisions_to_claim_records=provider.apply_claim_role_decisions_to_claim_records,
        persist_ordered_review_state=lambda workspace_target, live_reviews_by_id, historical_reviews_by_id: repo_persist_ingest_ordered_review_state(
            workspace_target,
            live_reviews_by_id=live_reviews_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
            build_ordered_review_state_records=provider.build_ordered_review_state_records,
            persist_review_records=lambda target_for_repo, review_records: repo_persist_ingest_review_records(
                target_for_repo,
                review_records=review_records,
                write_jsonl=write_jsonl,
                write_review_file=provider.write_review_file,
            ),
        ),
        write_review_file=provider.write_review_file,
        apply_page_alias_overrides=provider.apply_page_alias_overrides,
        upsert_wiki_page=provider.upsert_wiki_page,
        link_claims_to_page_in_memory=provider.link_claims_to_page_in_memory,
        build_ordered_claim_state_records=provider.build_ordered_claim_state_records,
        build_ordered_review_state_records=provider.build_ordered_review_state_records,
        build_concept_group_key=provider.build_concept_group_key,
        regroup_concept_claims_by_canonical_topic=provider.regroup_concept_claims_by_canonical_topic,
        apply_page_intent_decisions_to_claim_groups=provider.apply_page_intent_decisions_to_claim_groups,
        page_route_for_bucket=provider.page_route_for_bucket,
        preferred_page_intent_for_claim_group=provider.preferred_page_intent_for_claim_group,
        should_generate_concept_page=provider.should_generate_concept_page,
        choose_group_topic_label=provider.choose_group_topic_label,
        choose_canonical_claim=provider.choose_canonical_claim,
        resolve_concept_title_candidate=provider.resolve_concept_title_candidate,
        build_concept_page_id=provider.build_concept_page_id,
        concept_summary_page_path=provider.concept_summary_page_path,
        build_concept_page=provider.build_concept_page,
        apply_page_route_to_page_record=provider.apply_page_route_to_page_record,
        link_reviews_to_page_in_memory=provider.link_reviews_to_page_in_memory,
        page_intent_page_id=provider.page_intent_page_id,
        page_intent_page_path=provider.page_intent_page_path,
        build_intent_routed_page=provider.build_intent_routed_page,
        collect_workspace_overview_concept_pages=provider.collect_workspace_overview_concept_pages,
        should_generate_workspace_overview_page=provider.should_generate_workspace_overview_page,
        workspace_overview_page_path=provider.workspace_overview_page_path,
        build_workspace_overview_page=provider.build_workspace_overview_page,
        build_workspace_overview_page_id=provider.build_workspace_overview_page_id,
        expected_source_summary_page_id=provider.expected_source_summary_page_id,
        prune_stale_auto_pages=provider.prune_stale_auto_pages,
        write_page_links_index=provider.write_page_links_index,
        write_search_pages_index=provider.write_search_pages_index,
        build_alias_conflict_reviews=provider.build_alias_conflict_reviews,
        rebuild_wiki_index=provider.rebuild_wiki_index,
        source_summary_page_path=provider.source_summary_page_path,
        build_source_summary_page=provider.build_source_summary_page,
    )


def build_ingest_helper_deps(deps: IngestCliDeps) -> IngestHelperDeps:
    return IngestHelperDeps(
        build_similarity_bucket=deps.build_similarity_bucket,
        rebuild_claim_similarity_index=deps.rebuild_claim_similarity_index,
        filter_live_claim_records=deps.filter_live_claim_records,
        is_live_claim_record=deps.is_live_claim_record,
        run_post_ingest_review_auto=deps.run_post_ingest_review_auto,
        build_ingest_payload=build_ingest_payload,
        build_workspace_summary=deps.build_workspace_summary,
        render_workspace_summary_message=deps.render_workspace_summary_message,
        render_post_ingest_review_auto_summary=deps.render_post_ingest_review_auto_summary,
        alias_index_rel_path=deps.alias_index_rel_path,
        workspace_can_skip_page_regeneration=deps.workspace_can_skip_page_regeneration,
        apply_page_alias_overrides_to_records=deps.apply_page_alias_overrides_to_records,
        filter_live_page_records=deps.filter_live_page_records,
        load_existing_pages=deps.load_existing_pages,
        load_chunk_records=deps.load_chunk_records,
        collect_missing_source_page_source_ids=deps.collect_missing_source_page_source_ids,
        collect_missing_concept_bucket_keys=deps.collect_missing_concept_bucket_keys,
        workspace_overview_page_missing=deps.workspace_overview_page_missing,
        persist_page_records=deps.persist_page_records,
        write_alias_index=deps.write_alias_index,
        load_search_pages_index=deps.load_search_pages_index,
        search_pages_index_rel_path=deps.search_pages_index_rel_path,
        search_pages_index_version=deps.search_pages_index_version,
        utc_now_iso=deps.utc_now_iso,
        append_wiki_log=deps.append_wiki_log,
    )


def refresh_ingest_claim_similarity_state(deps: IngestCliDeps, context: IngestContext, live_claim_records: list[dict]) -> None:
    refresh_ingest_claim_similarity_state_service(
        context,
        live_claim_records,
        deps=build_ingest_helper_deps(deps),
    )


def refresh_ingest_claim_state_from_records(deps: IngestCliDeps, context: IngestContext, claim_records: list[dict]) -> None:
    refresh_ingest_claim_state_from_records_service(
        context,
        claim_records,
        deps=build_ingest_helper_deps(deps),
    )


def build_claims_by_source_id(claim_records: list[dict]) -> dict[str, list[dict]]:
    return build_claims_by_source_id_service(claim_records)


def build_chunks_by_source_id(chunk_records: list[dict]) -> dict[str, list[dict]]:
    return build_chunks_by_source_id_service(chunk_records)


def run_post_ingest_review_auto_if_enabled(deps: IngestCliDeps, context: IngestContext) -> dict | None:
    return run_post_ingest_review_auto_if_enabled_service(
        context,
        deps=build_ingest_helper_deps(deps),
    )


def build_ingest_command_result(
    deps: IngestCliDeps,
    context: IngestContext,
    *,
    search_index: dict,
    alias_index: dict,
    changed_page_count: int,
    message: str,
    existing_page_count: int | None = None,
    tracked_page_count: int | None = None,
) -> CommandResult:
    rendered_message, payload = build_ingest_command_result_service(
        context,
        search_index=search_index,
        alias_index=alias_index,
        changed_page_count=changed_page_count,
        message=message,
        existing_page_count=existing_page_count,
        tracked_page_count=tracked_page_count,
        deps=build_ingest_helper_deps(deps),
    )
    return CommandResult(payload=payload, message=rendered_message)


def maybe_build_skipped_page_regeneration_result(deps: IngestCliDeps, context: IngestContext) -> CommandResult | None:
    return maybe_build_skipped_page_regeneration_result_service(
        context,
        deps=build_ingest_helper_deps(deps),
        build_result=lambda *args, **kwargs: build_ingest_command_result(deps, *args, **kwargs),
    )


def build_ingest_context(deps: IngestCliDeps, request: IngestRequest) -> IngestContext:
    return build_ingest_context_service(
        request,
        deps=IngestContextDeps(
            ensure_workspace_schema_supported=deps.ensure_workspace_schema_supported,
            load_workspace_config=deps.load_workspace_config,
            load_post_ingest_review_auto_config=deps.load_post_ingest_review_auto_config,
            load_semantic_task_config=deps.load_semantic_task_config,
            load_readable_concept_render_config=deps.load_readable_concept_render_config,
            load_page_render_config=deps.load_page_render_config,
            resolve_workspace_raw_dir=deps.resolve_workspace_raw_dir,
            load_existing_sources=deps.load_existing_sources,
            load_existing_normalized_by_source=deps.load_existing_normalized_by_source,
            load_existing_structured_source_ids=deps.load_existing_structured_source_ids,
            load_existing_chunked_by_source=deps.load_existing_chunked_by_source,
            load_existing_claim_state=deps.load_existing_claim_state,
            load_existing_review_state=deps.load_existing_review_state,
            build_similarity_bucket=deps.build_similarity_bucket,
            rebuild_claim_similarity_index=deps.rebuild_claim_similarity_index,
            build_latest_source_record_by_path=deps.build_latest_source_record_by_path,
            structure_blocks_rel_path=deps.structure_blocks_rel_path,
            evidence_blocks_rel_path=deps.evidence_blocks_rel_path,
            knowledge_units_rel_path=deps.knowledge_units_rel_path,
            task_id_factory=lambda: f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        ),
    )


def build_ingest_registration_deps(deps: IngestCliDeps) -> IngestRegistrationDeps:
    return IngestRegistrationDeps(
        collect_files=deps.collect_files,
        file_sha256=deps.file_sha256,
        infer_source_type=deps.infer_source_type,
        build_source_version_group_from_source_path=deps.build_source_version_group_from_source_path,
        replace_source_scoped_jsonl_records=deps.replace_source_scoped_jsonl_records,
        purge_source_from_claims=deps.purge_source_from_claims,
        purge_deleted_claims_from_reviews=deps.purge_deleted_claims_from_reviews,
        refresh_claim_similarity_state=lambda context, live_claim_records: refresh_ingest_claim_similarity_state(deps, context, live_claim_records),
        utc_now_iso=deps.utc_now_iso,
        replace_jsonl_record=deps.replace_jsonl_record,
        build_source_id=deps.build_source_id,
        build_source_version_group=deps.build_source_version_group,
        append_jsonl=deps.append_jsonl,
        load_source_records=deps.load_source_records,
        load_normalized_records=deps.load_normalized_records,
        normalize_source_record=deps.normalize_source_record,
        append_error_record=deps.append_error_record,
        run_semantic_batch_task=deps.run_semantic_batch_task,
        apply_document_analysis_decisions_to_normalized_records=deps.apply_document_analysis_decisions_to_normalized_records,
    )


def build_ingest_structure_claim_deps(deps: IngestCliDeps) -> IngestStructureClaimDeps:
    return IngestStructureClaimDeps(
        compile_structure_knowledge_records=deps.compile_structure_knowledge_records,
        replace_source_scoped_jsonl_records=deps.replace_source_scoped_jsonl_records,
        chunk_normalized_record=deps.chunk_normalized_record,
        replace_jsonl_records_by_filter=deps.replace_jsonl_records_by_filter,
        utc_now_iso=deps.utc_now_iso,
        replace_jsonl_record=deps.replace_jsonl_record,
        load_normalized_records=deps.load_normalized_records,
        load_chunk_records_by_source=deps.load_chunk_records_by_source,
        load_active_knowledge_units_by_source=deps.load_active_knowledge_units_by_source,
        load_current_claim_records=deps.load_current_claim_records,
        source_claim_stage_completed=deps.source_claim_stage_completed,
        choose_active_source_ids=deps.choose_active_source_ids,
        build_claim_candidates_for_source=deps.build_claim_candidates_for_source,
        merge_claim_records=deps.merge_claim_records,
        write_claim_file=deps.write_claim_file,
        build_similarity_bucket=deps.build_similarity_bucket,
        collect_claim_review_candidate_ids=deps.collect_claim_review_candidate_ids,
        has_negation=deps.has_negation,
        claims_are_similar_for_review=deps.claims_are_similar_for_review,
        build_review_record=deps.build_review_record,
        append_jsonl=deps.append_jsonl,
        append_error_record=deps.append_error_record,
        index_claim_similarity_tokens=deps.index_claim_similarity_tokens,
        persist_ordered_claim_state=deps.persist_ordered_claim_state,
        ensure_claim_lifecycle_defaults=deps.ensure_claim_lifecycle_defaults,
        run_semantic_batch_task=deps.run_semantic_batch_task,
        apply_claim_candidate_quality_decisions_to_claim_records=deps.apply_claim_candidate_quality_decisions_to_claim_records,
        apply_claim_role_decisions_to_claim_records=deps.apply_claim_role_decisions_to_claim_records,
        refresh_claim_state_from_records=lambda context, claim_records: refresh_ingest_claim_state_from_records(deps, context, claim_records),
        persist_ordered_review_state=deps.persist_ordered_review_state,
        write_review_file=deps.write_review_file,
    )


def build_ingest_page_finalize_deps(deps: IngestCliDeps) -> IngestPageFinalizeDeps:
    return IngestPageFinalizeDeps(
        maybe_build_skipped_page_regeneration_result=lambda context: maybe_build_skipped_page_regeneration_result(deps, context),
        load_existing_pages=deps.load_existing_pages,
        load_chunk_records=deps.load_chunk_records,
        load_normalized_records_by_source=deps.load_normalized_records_by_source,
        load_source_records=deps.load_source_records,
        apply_page_alias_overrides_to_records=deps.apply_page_alias_overrides_to_records,
        build_ordered_claim_state_records=deps.build_ordered_claim_state_records,
        persist_ordered_claim_state=deps.persist_ordered_claim_state,
        persist_ordered_review_state=deps.persist_ordered_review_state,
        persist_page_records=deps.persist_page_records,
        utc_now_iso=deps.utc_now_iso,
        filter_live_claim_records=deps.filter_live_claim_records,
        build_claims_by_source_id=build_claims_by_source_id,
        build_chunks_by_source_id=build_chunks_by_source_id,
        collect_missing_source_page_source_ids=deps.collect_missing_source_page_source_ids,
        source_summary_page_path=deps.source_summary_page_path,
        build_source_summary_page=deps.build_source_summary_page,
        apply_page_alias_overrides=deps.apply_page_alias_overrides,
        upsert_wiki_page=deps.upsert_wiki_page,
        link_claims_to_page_in_memory=deps.link_claims_to_page_in_memory,
        replace_jsonl_record=deps.replace_jsonl_record,
        build_concept_group_key=deps.build_concept_group_key,
        regroup_concept_claims_by_canonical_topic=deps.regroup_concept_claims_by_canonical_topic,
        run_semantic_batch_task=deps.run_semantic_batch_task,
        apply_page_intent_decisions_to_claim_groups=deps.apply_page_intent_decisions_to_claim_groups,
        collect_missing_concept_bucket_keys=deps.collect_missing_concept_bucket_keys,
        page_route_for_bucket=deps.page_route_for_bucket,
        preferred_page_intent_for_claim_group=deps.preferred_page_intent_for_claim_group,
        should_generate_concept_page=deps.should_generate_concept_page,
        choose_group_topic_label=deps.choose_group_topic_label,
        choose_canonical_claim=deps.choose_canonical_claim,
        resolve_concept_title_candidate=deps.resolve_concept_title_candidate,
        build_concept_page_id=deps.build_concept_page_id,
        concept_summary_page_path=deps.concept_summary_page_path,
        build_concept_page=deps.build_concept_page,
        apply_page_route_to_page_record=deps.apply_page_route_to_page_record,
        link_reviews_to_page_in_memory=deps.link_reviews_to_page_in_memory,
        page_intent_page_id=deps.page_intent_page_id,
        page_intent_page_path=deps.page_intent_page_path,
        build_intent_routed_page=deps.build_intent_routed_page,
        collect_workspace_overview_concept_pages=deps.collect_workspace_overview_concept_pages,
        should_generate_workspace_overview_page=deps.should_generate_workspace_overview_page,
        workspace_overview_page_path=deps.workspace_overview_page_path,
        build_workspace_overview_page=deps.build_workspace_overview_page,
        build_workspace_overview_page_id=deps.build_workspace_overview_page_id,
        expected_source_summary_page_id=deps.expected_source_summary_page_id,
        prune_stale_auto_pages=deps.prune_stale_auto_pages,
        write_review_file=deps.write_review_file,
        write_page_links_index=deps.write_page_links_index,
        load_search_pages_index=deps.load_search_pages_index,
        write_search_pages_index=deps.write_search_pages_index,
        write_alias_index=deps.write_alias_index,
        build_alias_conflict_reviews=deps.build_alias_conflict_reviews,
        append_jsonl=deps.append_jsonl,
        rebuild_wiki_index=deps.rebuild_wiki_index,
        append_wiki_log=deps.append_wiki_log,
        build_ingest_command_result=lambda context, **kwargs: build_ingest_command_result(deps, context, **kwargs),
    )


def command_ingest(deps: IngestCliDeps, args: argparse.Namespace) -> CommandResult:
    return run_ingest_service(
        IngestRequest(
            target_dir=args.target_dir,
            disable_insecure_download_retry=bool(args.disable_insecure_download_retry),
        ),
        deps=IngestServiceDeps(
            build_context=lambda request: build_ingest_context(deps, request),
            run_registration_and_normalization_stage=lambda context, request: run_ingest_registration_and_normalization_service(
                context,
                request,
                deps=build_ingest_registration_deps(deps),
            ),
            run_structure_chunk_claim_stage=lambda context, request: run_ingest_structure_chunk_claim_service(
                context,
                request,
                deps=build_ingest_structure_claim_deps(deps),
            ),
            run_page_finalize_stage=lambda context, request: run_ingest_page_finalize_service(
                context,
                request,
                deps=build_ingest_page_finalize_deps(deps),
            ),
        ),
    )
