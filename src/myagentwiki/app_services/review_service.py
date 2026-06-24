from __future__ import annotations

from pathlib import Path
from typing import Callable


def run_review_list_service(
    *,
    target: Path,
    status_filter: str | None,
    load_review_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]],
    load_claim_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]],
    build_claim_lookup_by_any_id: Callable[[dict[str, dict], dict[str, dict]], dict[str, dict]],
    refresh_alias_conflict_reviews: Callable[..., tuple[dict, set[str], set[str]]],
    persist_ordered_review_state: Callable[..., list[dict]],
    cleanup_review_related_record_files: Callable[..., None],
    review_display_id: Callable[[dict], str],
    claim_display_id: Callable[[dict], str],
    build_workspace_summary: Callable[[Path], dict],
) -> dict:
    live_reviews_by_id, historical_reviews_by_id, _ = load_review_state_maps(target)
    live_claims_by_id, historical_claims_by_id, _ = load_claim_state_maps(target)
    claim_lookup = build_claim_lookup_by_any_id(live_claims_by_id, historical_claims_by_id)
    refresh_alias_conflict_reviews(
        target=target,
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )
    all_review_records = persist_ordered_review_state(
        target,
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )
    cleanup_review_related_record_files(
        target,
        historical_claims_by_id=historical_claims_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )

    review_records = all_review_records
    if status_filter:
        review_records = [
            record for record in review_records
            if record.get("status") == status_filter
        ]
    else:
        review_records = [
            record for record in review_records
            if record.get("lifecycle_status") == "active" and record.get("status") == "open"
        ]

    items = []
    for review_record in sorted(
        review_records,
        key=lambda item: (
            1 if item.get("lifecycle_status") == "active" else 0,
            1 if item.get("status") == "open" else 0,
            item.get("created_at", ""),
            review_display_id(item),
        ),
        reverse=True,
    ):
        candidate_claims = []
        for claim_id in review_record.get("candidate_claim_ids", []):
            claim_record = claim_lookup.get(claim_id)
            if claim_record is None:
                continue
            candidate_claims.append({
                "claim_id": claim_id,
                "display_id": claim_display_id(claim_record),
                "lifecycle_status": claim_record.get("lifecycle_status"),
                "status": claim_record.get("status"),
                "text": claim_record.get("text", ""),
                "source_count": len(claim_record.get("source_ids", [])),
                "page_count": len(claim_record.get("page_ids", [])),
            })

        items.append({
            "review_id": review_display_id(review_record),
            "state_review_id": review_record["review_id"],
            "display_id": review_display_id(review_record),
            "kind": review_record.get("kind"),
            "status": review_record.get("status"),
            "lifecycle_status": review_record.get("lifecycle_status"),
            "reason": review_record.get("reason"),
            "recommended_action": review_record.get("recommended_action"),
            "allowed_actions": review_record.get("allowed_actions", []),
            "candidate_page_ids": review_record.get("candidate_page_ids", []),
            "candidate_claims": candidate_claims,
            "created_at": review_record.get("created_at"),
            "resolved_at": review_record.get("resolved_at"),
            "archived_at": review_record.get("archived_at"),
        })

    return {
        "workspace": str(target),
        "workspace_summary": build_workspace_summary(target),
        "items": items,
        "summary": {
            "review_count": len(items),
            "live_review_count": len(live_reviews_by_id),
            "historical_review_count": len(historical_reviews_by_id),
        },
    }
