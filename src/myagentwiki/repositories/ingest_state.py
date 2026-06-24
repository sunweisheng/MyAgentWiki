from __future__ import annotations

from pathlib import Path
from typing import Callable


def load_existing_sources(target: Path, *, load_jsonl: Callable[[Path], list[dict]]) -> list[dict]:
    return load_jsonl(target / "state" / "sources.jsonl")


def build_existing_sources_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> Callable[[Path], list[dict]]:
    return lambda target: load_existing_sources(target, load_jsonl=load_jsonl)


def load_existing_normalized_by_source(
    normalized_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> dict[str, dict]:
    return {
        record["source_id"]: record
        for record in load_jsonl(normalized_path)
    }


def load_existing_structured_source_ids(
    *,
    structure_blocks_path: Path,
    evidence_blocks_path: Path,
    knowledge_units_path: Path,
    load_jsonl: Callable[[Path], list[dict]],
) -> set[str]:
    existing_structure_source_ids = {
        record["source_id"] for record in load_jsonl(structure_blocks_path)
    }
    existing_evidence_source_ids = {
        record["source_id"] for record in load_jsonl(evidence_blocks_path)
    }
    existing_knowledge_source_ids = {
        record["source_id"] for record in load_jsonl(knowledge_units_path)
    }
    return (
        existing_structure_source_ids
        & existing_evidence_source_ids
        & existing_knowledge_source_ids
    )


def load_existing_chunked_by_source(
    chunks_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> dict[str, dict]:
    return {
        record["source_id"]: record
        for record in load_jsonl(chunks_path)
    }


def build_existing_chunked_by_source_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> Callable[[Path], dict[str, dict]]:
    return lambda chunks_path: load_existing_chunked_by_source(
        chunks_path,
        load_jsonl=load_jsonl,
    )


def load_existing_claim_state(
    claims_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_claim_lifecycle_defaults: Callable[[dict], dict],
    filter_live_claim_records: Callable[[list[dict]], list[dict]],
    is_live_claim_record: Callable[[dict], bool],
) -> tuple[list[dict], list[dict], dict[str, dict], dict[str, dict], dict[str, dict]]:
    existing_claim_records = [
        ensure_claim_lifecycle_defaults(record)
        for record in load_jsonl(claims_path)
    ]
    live_existing_claims = filter_live_claim_records(existing_claim_records)
    historical_existing_claims = [
        record for record in existing_claim_records
        if not is_live_claim_record(record)
    ]
    claims_by_id = {record["claim_id"]: record for record in live_existing_claims}
    historical_claims_by_id = {
        record["claim_id"]: record for record in historical_existing_claims
    }
    claims_by_normalized_text = {
        record["normalized_text"]: record for record in live_existing_claims
    }
    return (
        live_existing_claims,
        historical_existing_claims,
        claims_by_id,
        historical_claims_by_id,
        claims_by_normalized_text,
    )


def build_existing_claim_state_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_claim_lifecycle_defaults: Callable[[dict], dict],
    filter_live_claim_records: Callable[[list[dict]], list[dict]],
    is_live_claim_record: Callable[[dict], bool],
) -> Callable[[Path], tuple[list[dict], list[dict], dict[str, dict], dict[str, dict], dict[str, dict]]]:
    return lambda claims_path: load_existing_claim_state(
        claims_path,
        load_jsonl=load_jsonl,
        ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
        filter_live_claim_records=filter_live_claim_records,
        is_live_claim_record=is_live_claim_record,
    )


def load_existing_review_state(
    reviews_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_review_lifecycle_defaults: Callable[[dict], dict],
    filter_live_review_records: Callable[[list[dict]], list[dict]],
    is_live_review_record: Callable[[dict], bool],
) -> tuple[list[dict], list[dict], dict[str, dict], dict[str, dict]]:
    existing_review_records = [
        ensure_review_lifecycle_defaults(record)
        for record in (load_jsonl(reviews_path) if reviews_path.exists() else [])
    ]
    live_existing_reviews = filter_live_review_records(existing_review_records)
    historical_existing_reviews = [
        record for record in existing_review_records
        if not is_live_review_record(record)
    ]
    existing_reviews = {
        record["review_id"]: record for record in live_existing_reviews
    }
    historical_reviews_by_id = {
        record["review_id"]: ensure_review_lifecycle_defaults(record)
        for record in historical_existing_reviews
    }
    return (
        live_existing_reviews,
        historical_existing_reviews,
        existing_reviews,
        historical_reviews_by_id,
    )


def build_existing_review_state_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_review_lifecycle_defaults: Callable[[dict], dict],
    filter_live_review_records: Callable[[list[dict]], list[dict]],
    is_live_review_record: Callable[[dict], bool],
) -> Callable[[Path], tuple[list[dict], list[dict], dict[str, dict], dict[str, dict]]]:
    return lambda reviews_path: load_existing_review_state(
        reviews_path,
        load_jsonl=load_jsonl,
        ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
        filter_live_review_records=filter_live_review_records,
        is_live_review_record=is_live_review_record,
    )


def load_existing_pages(
    pages_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_page_lifecycle_defaults: Callable[[dict], dict],
) -> list[dict]:
    if not pages_path.exists():
        return []
    return [
        ensure_page_lifecycle_defaults(record)
        for record in load_jsonl(pages_path)
    ]


def build_existing_pages_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_page_lifecycle_defaults: Callable[[dict], dict],
) -> Callable[[Path], list[dict]]:
    return lambda pages_path: load_existing_pages(
        pages_path,
        load_jsonl=load_jsonl,
        ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
    )


def load_chunk_records(
    chunks_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> list[dict]:
    return load_jsonl(chunks_path)


def build_chunk_records_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> Callable[[Path], list[dict]]:
    return lambda chunks_path: load_chunk_records(
        chunks_path,
        load_jsonl=load_jsonl,
    )


def load_chunk_records_by_source(
    chunks_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> dict[str, list[dict]]:
    chunk_records_by_source: dict[str, list[dict]] = {}
    for chunk_record in load_jsonl(chunks_path):
        chunk_records_by_source.setdefault(chunk_record["source_id"], []).append(chunk_record)
    return chunk_records_by_source


def build_chunk_records_by_source_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> Callable[[Path], dict[str, list[dict]]]:
    return lambda chunks_path: load_chunk_records_by_source(
        chunks_path,
        load_jsonl=load_jsonl,
    )


def load_normalized_records(
    normalized_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> list[dict]:
    return load_jsonl(normalized_path)


def load_normalized_records_by_source(
    normalized_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> dict[str, dict]:
    return {
        record["source_id"]: record
        for record in load_jsonl(normalized_path)
    }


def load_source_records(
    sources_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> list[dict]:
    return load_jsonl(sources_path)


def load_active_knowledge_units_by_source(
    knowledge_units_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> dict[str, list[dict]]:
    knowledge_units_by_source: dict[str, list[dict]] = {}
    for knowledge_unit_record in load_jsonl(knowledge_units_path):
        if knowledge_unit_record.get("lifecycle_status", "active") != "active":
            continue
        knowledge_units_by_source.setdefault(
            knowledge_unit_record["source_id"],
            [],
        ).append(knowledge_unit_record)
    return knowledge_units_by_source


def load_current_claim_records(
    claims_path: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_claim_lifecycle_defaults: Callable[[dict], dict],
) -> list[dict]:
    return [
        ensure_claim_lifecycle_defaults(record)
        for record in load_jsonl(claims_path)
    ]
