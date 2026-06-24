from __future__ import annotations

from pathlib import Path
from typing import Callable


def persist_claim_records(
    target: Path,
    *,
    claim_records: list[dict],
    write_jsonl: Callable[[Path, list[dict]], None],
    write_claim_file: Callable[[Path, dict], None],
) -> None:
    claims_path = target / "state" / "claims.jsonl"
    write_jsonl(claims_path, claim_records)
    for claim_record in claim_records:
        write_claim_file(target, claim_record)


def persist_review_records(
    target: Path,
    *,
    review_records: list[dict],
    write_jsonl: Callable[[Path, list[dict]], None],
    write_review_file: Callable[[Path, dict], None],
) -> None:
    reviews_path = target / "state" / "reviews.jsonl"
    write_jsonl(reviews_path, review_records)
    for review_record in review_records:
        write_review_file(target, review_record)


def persist_page_records(
    target: Path,
    *,
    page_records: list[dict],
    write_jsonl: Callable[[Path, list[dict]], None],
) -> None:
    pages_path = target / "state" / "pages.jsonl"
    write_jsonl(pages_path, page_records)


def persist_ordered_claim_state(
    target: Path,
    *,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    build_ordered_claim_state_records: Callable[[dict[str, dict], dict[str, dict]], list[dict]],
    persist_claim_records: Callable[..., None],
) -> list[dict]:
    claim_records = build_ordered_claim_state_records(
        live_claims_by_id=live_claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
    )
    persist_claim_records(
        target,
        claim_records=claim_records,
    )
    return claim_records


def persist_ordered_review_state(
    target: Path,
    *,
    live_reviews_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
    build_ordered_review_state_records: Callable[[dict[str, dict], dict[str, dict]], list[dict]],
    persist_review_records: Callable[..., None],
) -> list[dict]:
    review_records = build_ordered_review_state_records(
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )
    persist_review_records(
        target,
        review_records=review_records,
    )
    return review_records
