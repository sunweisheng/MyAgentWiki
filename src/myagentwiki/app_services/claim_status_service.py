from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .review_rebuild_service import ReviewRebuildRequest, ReviewRebuildServiceDeps, run_review_rebuild_service


@dataclass(frozen=True)
class ClaimSetStatusRequest:
    target: Path
    claim_id: str
    status: str


@dataclass(frozen=True)
class ClaimStatusServiceDeps:
    ensure_workspace_schema_supported: Callable[[Path], None]
    load_claim_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]]
    load_review_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]]
    is_actionable_review_record: Callable[[dict], bool]
    utc_now_iso: Callable[[], str]
    rebuild_review_affected_pages: Callable[..., None]


@dataclass(frozen=True)
class ClaimStatusServiceResult:
    payload: dict
    message: str


def run_claim_set_status_service(
    request: ClaimSetStatusRequest,
    *,
    deps: ClaimStatusServiceDeps,
) -> ClaimStatusServiceResult:
    target = request.target
    deps.ensure_workspace_schema_supported(target)
    live_claims_by_id, historical_claims_by_id, _ = deps.load_claim_state_maps(target)
    live_reviews_by_id, _, _ = deps.load_review_state_maps(target)

    claim_record = live_claims_by_id.get(request.claim_id) or historical_claims_by_id.get(request.claim_id)
    if claim_record is None:
        raise KeyError(f"Unknown claim_id: {request.claim_id}")
    if claim_record["claim_id"] not in live_claims_by_id:
        raise ValueError("claim_set_status currently only supports active claims.")

    active_review_ids = sorted(
        review_record["review_id"]
        for review_record in live_reviews_by_id.values()
        if deps.is_actionable_review_record(review_record)
        and request.claim_id in review_record.get("candidate_claim_ids", [])
    )

    updated_claim = dict(claim_record)
    updated_claim["status"] = request.status
    if request.status != "needs_review":
        updated_claim["review_reason"] = None
    updated_claim["updated_at"] = deps.utc_now_iso()
    live_claims_by_id[request.claim_id] = updated_claim

    run_review_rebuild_service(
        ReviewRebuildRequest(
            target=target,
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
        ),
        deps=ReviewRebuildServiceDeps(
            rebuild_review_affected_pages_impl=lambda target, live_claims_by_id, live_reviews_by_id: deps.rebuild_review_affected_pages(
                target=target,
                live_claims_by_id=live_claims_by_id,
                live_reviews_by_id=live_reviews_by_id,
            )
        ),
    )

    return ClaimStatusServiceResult(
        payload={
            "workspace": str(target),
            "claim_id": request.claim_id,
            "status": request.status,
            "active_review_ids": active_review_ids,
        },
        message="Claim status updated.",
    )
