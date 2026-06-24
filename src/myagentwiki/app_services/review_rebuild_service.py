from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ReviewRebuildRequest:
    target: Path
    live_claims_by_id: dict[str, dict]
    live_reviews_by_id: dict[str, dict]


@dataclass(frozen=True)
class ReviewRebuildServiceDeps:
    rebuild_review_affected_pages_impl: Callable[[Path, dict[str, dict], dict[str, dict]], None]


def run_review_rebuild_service(
    request: ReviewRebuildRequest,
    *,
    deps: ReviewRebuildServiceDeps,
) -> None:
    deps.rebuild_review_affected_pages_impl(
        request.target,
        request.live_claims_by_id,
        request.live_reviews_by_id,
    )


AUTO_REBUILD_PAGE_INTENTS = ("guide", "duty", "example", "topic", "reference", "timeline")
AUTO_REBUILD_PAGE_TYPES = {
    "source-summary",
    "concept",
    "overview",
    *AUTO_REBUILD_PAGE_INTENTS,
}


@dataclass(frozen=True)
class ReviewRebuildPageContext:
    target: Path
    config: dict[str, Any]
    readable_concept_render_config: dict[str, Any]
    overview_render_config: dict[str, Any]
    page_intent_config: Any
    sources_by_id: dict[str, dict]
    normalized_records_by_source: dict[str, dict]
    chunks_by_source_id: dict[str, list[dict]]
    page_records_by_id: dict[str, dict]
    active_source_ids: set[str]
    live_claims_by_id: dict[str, dict]
    live_reviews_by_id: dict[str, dict]


@dataclass(frozen=True)
class ReviewRebuildPageDeps:
    is_actionable_review_record: Callable[[dict], bool]
    utc_now_iso: Callable[[], str]
    source_summary_page_path: Callable[[str, str], Path]
    build_source_summary_page: Callable[..., tuple[str, dict]]
    apply_page_alias_overrides: Callable[[Path, dict], dict]
    upsert_wiki_page: Callable[..., tuple[dict, bool]]
    link_claims_to_page_in_memory: Callable[..., set[str]]
    build_concept_group_key: Callable[[dict], str]
    regroup_concept_claims_by_canonical_topic: Callable[[dict[str, list[dict]]], dict[str, list[dict]]]
    apply_page_intent_decisions_to_claim_groups: Callable[..., dict]
    page_route_for_bucket: Callable[[dict, str], dict]
    preferred_page_intent_for_claim_group: Callable[[list[dict], str], str]
    should_generate_concept_page: Callable[[list[dict]], bool]
    choose_group_topic_label: Callable[[list[dict]], str | None]
    choose_canonical_claim: Callable[..., dict]
    resolve_concept_title_candidate: Callable[..., tuple[str, dict]]
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


@dataclass(frozen=True)
class ReviewRebuildPersistContext:
    target: Path
    page_records_by_id: dict[str, dict]
    live_claims_by_id: dict[str, dict]
    live_reviews_by_id: dict[str, dict]


@dataclass(frozen=True)
class ReviewRebuildPersistDeps:
    load_claim_state_records: Callable[[Path], list[dict]]
    ensure_claim_lifecycle_defaults: Callable[[dict], dict]
    build_ordered_claim_state_records: Callable[[dict[str, dict], dict[str, dict]], list[dict]]
    write_jsonl: Callable[[Path, list[dict]], None]
    write_claim_file: Callable[[Path, dict], None]
    load_review_state_records: Callable[[Path], list[dict]]
    ensure_review_lifecycle_defaults: Callable[[dict], dict]
    is_live_review_record: Callable[[dict], bool]
    build_ordered_review_state_records: Callable[[dict[str, dict], dict[str, dict]], list[dict]]
    write_review_file: Callable[[Path, dict], None]
    write_page_links_index: Callable[[Path, list[dict]], dict]
    rebuild_wiki_index: Callable[[Path, list[dict]], None]
    write_alias_index: Callable[[Path, list[dict]], dict]
    refresh_alias_conflict_reviews: Callable[..., tuple[dict, set[str], set[str]]]
    cleanup_superseded_record_files: Callable[[Path, dict[str, dict], dict[str, dict]], None]
    load_search_pages_index: Callable[[Path], list[dict]]
    write_search_pages_index: Callable[..., dict]


def run_review_rebuild_persistence(
    context: ReviewRebuildPersistContext,
    *,
    deps: ReviewRebuildPersistDeps,
) -> None:
    claims_path = context.target / "state" / "claims.jsonl"
    reviews_path = context.target / "state" / "reviews.jsonl"
    pages_path = context.target / "state" / "pages.jsonl"

    existing_historical_claims_by_id = {
        record["claim_id"]: deps.ensure_claim_lifecycle_defaults(record)
        for record in deps.load_claim_state_records(context.target)
        if deps.ensure_claim_lifecycle_defaults(record).get("lifecycle_status") != "active"
    }
    claim_state_records = deps.build_ordered_claim_state_records(
        context.live_claims_by_id,
        existing_historical_claims_by_id,
    )
    deps.write_jsonl(claims_path, claim_state_records)
    for claim_record in claim_state_records:
        deps.write_claim_file(context.target, claim_record)

    existing_historical_reviews_by_id = {
        record["review_id"]: deps.ensure_review_lifecycle_defaults(record)
        for record in deps.load_review_state_records(context.target)
        if not deps.is_live_review_record(deps.ensure_review_lifecycle_defaults(record))
    }
    review_state_records = deps.build_ordered_review_state_records(
        context.live_reviews_by_id,
        existing_historical_reviews_by_id,
    )
    deps.write_jsonl(reviews_path, review_state_records)
    for review_record in review_state_records:
        deps.write_review_file(context.target, review_record)

    page_records = list(context.page_records_by_id.values())
    deps.write_jsonl(pages_path, page_records)
    page_links_index = deps.write_page_links_index(context.target, page_records)
    for page_id, link_entry in page_links_index.get("pages", {}).items():
        page_record = context.page_records_by_id.get(page_id)
        if page_record is None:
            continue
        page_record["outgoing_page_ids"] = link_entry.get("outgoing_page_ids", [])
        page_record["incoming_page_ids"] = link_entry.get("incoming_page_ids", [])
        page_record["related_page_ids"] = link_entry.get("related_page_ids", [])
    page_records = list(context.page_records_by_id.values())
    deps.write_jsonl(pages_path, page_records)
    deps.rebuild_wiki_index(context.target, page_records)
    deps.write_alias_index(context.target, page_records)
    deps.refresh_alias_conflict_reviews(
        target=context.target,
        live_reviews_by_id=context.live_reviews_by_id,
        historical_reviews_by_id=existing_historical_reviews_by_id,
        page_records=page_records,
    )
    updated_review_state_records = deps.build_ordered_review_state_records(
        context.live_reviews_by_id,
        existing_historical_reviews_by_id,
    )
    deps.write_jsonl(reviews_path, updated_review_state_records)
    for review_record in updated_review_state_records:
        deps.write_review_file(context.target, review_record)
    deps.cleanup_superseded_record_files(
        context.target,
        existing_historical_claims_by_id,
        existing_historical_reviews_by_id,
    )
    previous_search_index_records = deps.load_search_pages_index(context.target)
    deps.write_search_pages_index(
        target=context.target,
        page_records=page_records,
        claim_records_by_id=context.live_claims_by_id,
        previous_records=previous_search_index_records,
    )


def _reset_existing_auto_page_links(
    *,
    page_records_by_id: dict[str, dict],
    live_claim_records: list[dict],
    live_review_records: list[dict],
    utc_now_iso: Callable[[], str],
) -> None:
    for page_record in list(page_records_by_id.values()):
        if page_record.get("type") not in AUTO_REBUILD_PAGE_TYPES:
            continue
        page_id = page_record["page_id"]
        for claim_record in live_claim_records:
            if page_id in claim_record.get("page_ids", []):
                claim_record["page_ids"] = [item for item in claim_record["page_ids"] if item != page_id]
                claim_record["updated_at"] = utc_now_iso()
        for review_record in live_review_records:
            if page_id in review_record.get("candidate_page_ids", []):
                review_record["candidate_page_ids"] = [
                    item for item in review_record["candidate_page_ids"] if item != page_id
                ]


def _build_claims_by_source_id(
    *,
    live_claim_records: list[dict],
    active_source_ids: set[str],
) -> dict[str, list[dict]]:
    claims_by_source_id: dict[str, list[dict]] = {}
    for claim_record in live_claim_records:
        for source_id in claim_record.get("source_ids", []):
            if source_id in active_source_ids:
                claims_by_source_id.setdefault(source_id, []).append(claim_record)
    return claims_by_source_id


def run_review_rebuild_page_regeneration(
    context: ReviewRebuildPageContext,
    *,
    deps: ReviewRebuildPageDeps,
) -> None:
    live_claim_records = list(context.live_claims_by_id.values())
    live_review_records = [
        record for record in context.live_reviews_by_id.values()
        if deps.is_actionable_review_record(record)
    ]
    _reset_existing_auto_page_links(
        page_records_by_id=context.page_records_by_id,
        live_claim_records=live_claim_records,
        live_review_records=live_review_records,
        utc_now_iso=deps.utc_now_iso,
    )

    claims_by_source_id = _build_claims_by_source_id(
        live_claim_records=live_claim_records,
        active_source_ids=context.active_source_ids,
    )

    for source_id in sorted(context.active_source_ids):
        source_record = context.sources_by_id.get(source_id)
        if source_record is None or source_record.get("status") == "failed":
            continue
        source_claims = claims_by_source_id.get(source_id, [])
        source_chunks = context.chunks_by_source_id.get(source_id, [])
        if not source_claims and not source_chunks:
            continue
        source_record_for_page = dict(source_record)
        source_record_for_page["status"] = "generated"
        normalized_record = context.normalized_records_by_source.get(source_id)
        page_rel_path = deps.source_summary_page_path(
            source_id,
            normalized_record["title"] if normalized_record else Path(source_record["source_path"]).stem,
        )
        page_text, page_record = deps.build_source_summary_page(
            target=context.target,
            source_record=source_record_for_page,
            page_rel_path=page_rel_path,
            normalized_record=normalized_record,
            claim_records=source_claims,
            chunk_records=source_chunks,
        )
        page_record = deps.apply_page_alias_overrides(context.target, page_record)
        page_record["page_path"] = str(page_rel_path)
        stored_page_record, _ = deps.upsert_wiki_page(
            target=context.target,
            page_records_by_id=context.page_records_by_id,
            page_record=page_record,
            page_text=page_text,
        )
        deps.link_claims_to_page_in_memory(
            source_claims,
            stored_page_record["page_id"],
            context.live_claims_by_id,
        )

    concept_claim_groups: dict[str, list[dict]] = {}
    for claim_record in live_claim_records:
        active_claim_source_ids = [
            source_id for source_id in claim_record.get("source_ids", [])
            if source_id in context.active_source_ids
        ]
        if not active_claim_source_ids:
            continue
        bucket_key = deps.build_concept_group_key(claim_record)
        concept_claim_groups.setdefault(bucket_key, []).append(claim_record)
    concept_claim_groups = deps.regroup_concept_claims_by_canonical_topic(concept_claim_groups)
    page_routes_by_bucket = deps.apply_page_intent_decisions_to_claim_groups(
        target=context.target,
        concept_claim_groups=concept_claim_groups,
        task_config=context.page_intent_config,
    )

    for bucket_key, grouped_claims in sorted(concept_claim_groups.items()):
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
            concept_title, concept_title_quality = deps.resolve_concept_title_candidate(
                target=context.target,
                config=context.config,
                canonical_claim=canonical_claim,
                claim_records=grouped_claims,
                preferred_section_label=group_topic_label,
            )
            if concept_title_quality["classification"] == "reject":
                continue
            page_rel_path = deps.concept_summary_page_path(
                concept_page_id,
                concept_title,
            )
            page_text, page_record = deps.build_concept_page(
                target=context.target,
                bucket_key=bucket_key,
                page_rel_path=page_rel_path,
                claim_records=grouped_claims,
                page_records_by_id=context.page_records_by_id,
                review_records=live_review_records,
                render_config=context.readable_concept_render_config,
            )
            page_record = deps.apply_page_route_to_page_record(page_record, page_route)
            page_record = deps.apply_page_alias_overrides(context.target, page_record)
            page_record["page_path"] = str(page_rel_path)
            stored_page_record, _ = deps.upsert_wiki_page(
                target=context.target,
                page_records_by_id=context.page_records_by_id,
                page_record=page_record,
                page_text=page_text,
            )
            deps.link_claims_to_page_in_memory(
                grouped_claims,
                stored_page_record["page_id"],
                context.live_claims_by_id,
            )
            deps.link_reviews_to_page_in_memory(
                review_records=live_review_records,
                page_id=stored_page_record["page_id"],
                claim_ids=stored_page_record["claim_ids"],
                reviews_by_id=context.live_reviews_by_id,
            )
        elif page_intent in AUTO_REBUILD_PAGE_INTENTS:
            page_id = deps.page_intent_page_id(bucket_key, page_intent)
            page_title_source = deps.choose_group_topic_label(grouped_claims) or deps.choose_canonical_claim(grouped_claims).get("text", "")
            page_rel_path = deps.page_intent_page_path(page_intent, page_id, page_title_source)
            page_text, page_record = deps.build_intent_routed_page(
                target=context.target,
                config=context.config,
                bucket_key=bucket_key,
                page_intent=page_intent,
                page_rel_path=page_rel_path,
                claim_records=grouped_claims,
                page_records_by_id=context.page_records_by_id,
                review_records=live_review_records,
            )
            page_record = deps.apply_page_route_to_page_record(page_record, page_route)
            page_record = deps.apply_page_alias_overrides(context.target, page_record)
            page_record["page_path"] = str(page_rel_path)
            stored_page_record, _ = deps.upsert_wiki_page(
                target=context.target,
                page_records_by_id=context.page_records_by_id,
                page_record=page_record,
                page_text=page_text,
            )
            deps.link_claims_to_page_in_memory(
                grouped_claims,
                stored_page_record["page_id"],
                context.live_claims_by_id,
            )
            deps.link_reviews_to_page_in_memory(
                review_records=live_review_records,
                page_id=stored_page_record["page_id"],
                claim_ids=stored_page_record["claim_ids"],
                reviews_by_id=context.live_reviews_by_id,
            )

    overview_concept_pages = deps.collect_workspace_overview_concept_pages(
        claims_by_similarity_bucket=concept_claim_groups,
        page_records_by_id=context.page_records_by_id,
    )
    if deps.should_generate_workspace_overview_page(overview_concept_pages):
        overview_page_rel_path = deps.workspace_overview_page_path()
        overview_page_text, overview_page_record = deps.build_workspace_overview_page(
            target=context.target,
            page_rel_path=overview_page_rel_path,
            concept_pages=overview_concept_pages,
            page_records_by_id=context.page_records_by_id,
            claim_records_by_id=context.live_claims_by_id,
            render_config=context.overview_render_config,
        )
        overview_page_record = deps.apply_page_alias_overrides(context.target, overview_page_record)
        overview_page_record["page_path"] = str(overview_page_rel_path)
        stored_overview_page, _ = deps.upsert_wiki_page(
            target=context.target,
            page_records_by_id=context.page_records_by_id,
            page_record=overview_page_record,
            page_text=overview_page_text,
        )
        deps.link_claims_to_page_in_memory(
            [
                context.live_claims_by_id[claim_id]
                for claim_id in stored_overview_page["claim_ids"]
                if claim_id in context.live_claims_by_id
            ],
            stored_overview_page["page_id"],
            context.live_claims_by_id,
        )
        deps.link_reviews_to_page_in_memory(
            review_records=live_review_records,
            page_id=stored_overview_page["page_id"],
            claim_ids=stored_overview_page["claim_ids"],
            reviews_by_id=context.live_reviews_by_id,
        )

    desired_auto_page_ids = {
        deps.expected_source_summary_page_id(source_id)
        for source_id in context.active_source_ids
        if claims_by_source_id.get(source_id) or context.chunks_by_source_id.get(source_id)
    }
    forced_stale_page_ids: set[str] = set()
    for bucket_key, grouped_claims in concept_claim_groups.items():
        page_route = deps.page_route_for_bucket(page_routes_by_bucket, bucket_key)
        page_intent = deps.preferred_page_intent_for_claim_group(
            grouped_claims,
            page_route.get("page_intent", "topic"),
        )
        forced_stale_page_ids.update(
            {
                deps.build_concept_page_id(bucket_key),
                *{
                    deps.page_intent_page_id(bucket_key, stale_intent)
                    for stale_intent in AUTO_REBUILD_PAGE_INTENTS
                    if stale_intent != page_intent
                },
            }
        )
        if page_intent == "concept" and deps.should_generate_concept_page(grouped_claims):
            desired_auto_page_ids.add(deps.build_concept_page_id(bucket_key))
        elif page_intent in AUTO_REBUILD_PAGE_INTENTS:
            desired_auto_page_ids.add(deps.page_intent_page_id(bucket_key, page_intent))
    if deps.should_generate_workspace_overview_page(overview_concept_pages):
        desired_auto_page_ids.add(deps.build_workspace_overview_page_id())

    deps.prune_stale_auto_pages(
        target=context.target,
        page_records_by_id=context.page_records_by_id,
        desired_auto_page_ids=desired_auto_page_ids,
        claims_by_id=context.live_claims_by_id,
        reviews_by_id=context.live_reviews_by_id,
        forced_stale_page_ids=forced_stale_page_ids - desired_auto_page_ids,
    )
