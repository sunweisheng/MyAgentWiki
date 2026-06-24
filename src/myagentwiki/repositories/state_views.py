from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


def load_claim_state_maps(
    target: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_claim_lifecycle_defaults: Callable[[dict], dict],
    filter_live_claim_records: Callable[[list[dict]], list[dict]],
    is_live_claim_record: Callable[[dict], bool],
) -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    claim_records = [
        ensure_claim_lifecycle_defaults(record)
        for record in load_jsonl(target / "state" / "claims.jsonl")
    ]
    live_claims = {record["claim_id"]: record for record in filter_live_claim_records(claim_records)}
    historical_claims = {
        record["claim_id"]: record
        for record in claim_records
        if not is_live_claim_record(record)
    }
    return live_claims, historical_claims, claim_records


def build_claim_state_maps_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_claim_lifecycle_defaults: Callable[[dict], dict],
    filter_live_claim_records: Callable[[list[dict]], list[dict]],
    is_live_claim_record: Callable[[dict], bool],
) -> Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]]:
    return lambda target: load_claim_state_maps(
        target,
        load_jsonl=load_jsonl,
        ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
        filter_live_claim_records=filter_live_claim_records,
        is_live_claim_record=is_live_claim_record,
    )


def load_review_state_maps(
    target: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_review_lifecycle_defaults: Callable[[dict], dict],
    filter_live_review_records: Callable[[list[dict]], list[dict]],
    is_live_review_record: Callable[[dict], bool],
) -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    review_records = [
        ensure_review_lifecycle_defaults(record)
        for record in load_jsonl(target / "state" / "reviews.jsonl")
    ]
    live_reviews = {record["review_id"]: record for record in filter_live_review_records(review_records)}
    historical_reviews = {
        record["review_id"]: record
        for record in review_records
        if not is_live_review_record(record)
    }
    return live_reviews, historical_reviews, review_records


def build_review_state_maps_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_review_lifecycle_defaults: Callable[[dict], dict],
    filter_live_review_records: Callable[[list[dict]], list[dict]],
    is_live_review_record: Callable[[dict], bool],
) -> Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]]:
    return lambda target: load_review_state_maps(
        target,
        load_jsonl=load_jsonl,
        ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
        filter_live_review_records=filter_live_review_records,
        is_live_review_record=is_live_review_record,
    )


def load_page_state_records(
    target: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_page_lifecycle_defaults: Callable[[dict], dict],
) -> list[dict]:
    return [
        ensure_page_lifecycle_defaults(record)
        for record in load_jsonl(target / "state" / "pages.jsonl")
    ]


def build_page_state_records_loader(
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_page_lifecycle_defaults: Callable[[dict], dict],
) -> Callable[[Path], list[dict]]:
    return lambda target: load_page_state_records(
        target,
        load_jsonl=load_jsonl,
        ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
    )


def load_semantic_decisions(
    target: Path,
    *,
    semantic_decisions_path: Callable[[Path], Path],
    load_jsonl: Callable[[Path], list[dict]],
) -> list[dict]:
    return load_jsonl(semantic_decisions_path(target))


def load_search_pages_index(
    target: Path,
    *,
    search_pages_index_rel_path: Path,
    load_jsonl: Callable[[Path], list[dict]],
) -> list[dict]:
    index_path = target / search_pages_index_rel_path
    if not index_path.exists():
        return []
    return load_jsonl(index_path)


def load_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_alias_index(
    target: Path,
    *,
    alias_index_rel_path: Path,
    load_json: Callable[[Path], dict] = load_json_file,
    default_index_version: str,
) -> dict:
    path = target / alias_index_rel_path
    if not path.exists():
        return {
            "index_version": default_index_version,
            "updated_at": None,
            "canonical_map": {},
            "alias_map": {},
            "conflicts": [],
        }
    return load_json(path)


def load_page_links_index(
    target: Path,
    *,
    page_links_index_rel_path: Path,
    load_json: Callable[[Path], dict] = load_json_file,
    default_index_version: str,
) -> dict:
    path = target / page_links_index_rel_path
    if not path.exists():
        return {
            "index_version": default_index_version,
            "updated_at": None,
            "page_count": 0,
            "pages": {},
        }
    payload = load_json(path)
    payload.setdefault("pages", {})
    return payload
