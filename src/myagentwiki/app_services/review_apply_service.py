from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .review_rebuild_service import ReviewRebuildRequest, ReviewRebuildServiceDeps, run_review_rebuild_service


@dataclass(frozen=True)
class ReviewApplyRequest:
    target: Path
    review_id: str
    action: str
    primary_claim_id: str | None
    secondary_claim_id: str | None
    primary_page_id: str | None
    alias_value: str | None


def run_review_apply_service(
    request: ReviewApplyRequest,
    *,
    load_claim_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]],
    load_review_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]],
    refresh_alias_conflict_reviews: Callable[..., tuple[dict, set[str], set[str]]],
    persist_ordered_review_state: Callable[..., list[dict]],
    persist_ordered_claim_state: Callable[..., list[dict]],
    cleanup_review_related_record_files: Callable[..., None],
    review_display_id: Callable[[dict], str],
    apply_review_action: Callable[..., dict],
    rebuild_review_affected_pages: Callable[[Path, dict[str, dict], dict[str, dict]], None],
    build_workspace_summary: Callable[[Path], dict],
) -> dict:
    target = request.target

    live_claims_by_id, historical_claims_by_id, _ = load_claim_state_maps(target)
    live_reviews_by_id, historical_reviews_by_id, _ = load_review_state_maps(target)
    _, _, archived_alias_review_ids = refresh_alias_conflict_reviews(
        target=target,
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )
    if archived_alias_review_ids:
        persist_ordered_review_state(
            target,
            live_reviews_by_id=live_reviews_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
        )
        cleanup_review_related_record_files(
            target,
            historical_claims_by_id=historical_claims_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
        )

    review_record = live_reviews_by_id.get(request.review_id) or historical_reviews_by_id.get(request.review_id)
    if review_record is None:
        matched_live_review = next(
            (
                record for record in live_reviews_by_id.values()
                if review_display_id(record) == request.review_id
            ),
            None,
        )
        if matched_live_review is not None:
            review_record = matched_live_review
    if review_record is None:
        raise KeyError(f"Unknown review_id: {request.review_id}")
    if review_record["review_id"] not in live_reviews_by_id:
        raise ValueError("review_apply currently only supports active review items.")

    result = apply_review_action(
        target=target,
        review_record=review_record,
        action=request.action,
        primary_claim_id=request.primary_claim_id,
        secondary_claim_id=request.secondary_claim_id,
        primary_page_id=request.primary_page_id,
        alias_value=request.alias_value,
        live_claims_by_id=live_claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )
    live_reviews_by_id[review_record["review_id"]] = review_record

    persist_ordered_claim_state(
        target,
        live_claims_by_id=live_claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
    )

    persist_ordered_review_state(
        target,
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )
    cleanup_review_related_record_files(
        target,
        historical_claims_by_id=historical_claims_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )

    run_review_rebuild_service(
        ReviewRebuildRequest(
            target=target,
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
        ),
        deps=ReviewRebuildServiceDeps(
            rebuild_review_affected_pages_impl=lambda target, live_claims_by_id, live_reviews_by_id: rebuild_review_affected_pages(
                target=target,
                live_claims_by_id=live_claims_by_id,
                live_reviews_by_id=live_reviews_by_id,
            )
        ),
    )
    _, _, archived_alias_review_ids = refresh_alias_conflict_reviews(
        target=target,
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )
    if archived_alias_review_ids:
        persist_ordered_review_state(
            target,
            live_reviews_by_id=live_reviews_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
        )
        cleanup_review_related_record_files(
            target,
            historical_claims_by_id=historical_claims_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
        )

    return {
        "workspace": str(target),
        "workspace_summary": build_workspace_summary(target),
        "review_id": review_record["review_id"],
        "display_id": review_display_id(review_record),
        **result,
    }
