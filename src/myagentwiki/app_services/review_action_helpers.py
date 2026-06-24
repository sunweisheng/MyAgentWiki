from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ReviewActionDeps:
    review_display_id: Callable[[dict], str]
    utc_now_iso: Callable[[], str]
    load_live_page_aliases_by_id: Callable[[Path], dict]
    load_page_state_records: Callable[[Path], list[dict]]
    apply_alias_override_action: Callable[..., dict]
    apply_page_alias_overrides_payload: Callable[[dict, dict], dict]
    build_alias_index: Callable[[list[dict]], dict]
    alias_index_matches_for_value: Callable[[dict, str], list[dict]]
    clear_accepted_alias_conflict: Callable[[dict, str, list[str]], dict]
    update_page_alias_overrides_with_lock: Callable[[Path, Callable[[dict], dict]], None]
    persist_accepted_alias_conflict: Callable[..., dict]
    sync_claim_review_state_from_open_reviews: Callable[[list[str], dict[str, dict], dict[str, dict]], set[str]]
    reload_claims_from_disk_for_review: Callable[[Path, list[str], dict[str, dict]], set[str]]
    resolve_claim_record_for_action: Callable[[str, dict[str, dict], dict[str, dict]], dict]
    archive_live_claim: Callable[..., dict]
    rewrite_open_reviews_for_claim_change: Callable[..., tuple[set[str], set[str]]]
    merge_claim_records: Callable[[dict, dict], dict]
    normalize_claim_review_flags: Callable[[dict], None]


def _resolve_alias_conflict_action(
    *,
    target: Path,
    review_record: dict,
    action: str,
    primary_page_id: str | None,
    alias_value: str | None,
    candidate_page_ids: list[str],
    deps: ReviewActionDeps,
) -> dict:
    if not primary_page_id:
        raise ValueError(f"{action} requires --primary-page-id.")
    if primary_page_id not in candidate_page_ids:
        raise ValueError("primary page must belong to candidate_page_ids.")

    evidence = review_record.get("evidence", [])
    alias_from_review = evidence[0].get("alias") if evidence else None
    alias_to_assign = alias_value or alias_from_review
    if not alias_to_assign:
        raise ValueError(f"{action} requires alias value from review evidence or --alias-value.")

    live_aliases_by_page_id = deps.load_live_page_aliases_by_id(target)
    page_state_records = deps.load_page_state_records(target)

    def update_and_validate(overrides: dict) -> dict:
        updated_overrides = deps.apply_alias_override_action(
            overrides=overrides,
            live_aliases_by_page_id=live_aliases_by_page_id,
            candidate_page_ids=candidate_page_ids,
            primary_page_id=primary_page_id,
            alias_value=alias_to_assign,
            action=action,
        )
        page_records = [
            deps.apply_page_alias_overrides_payload(record, updated_overrides)
            for record in page_state_records
        ]
        projected_alias_index = deps.build_alias_index(page_records)
        projected_matches = deps.alias_index_matches_for_value(projected_alias_index, alias_to_assign)
        projected_page_ids = sorted({match.get("page_id") for match in projected_matches if match.get("page_id")})
        projected_canonical_ids = sorted({
            match.get("canonical_id") or match.get("page_id")
            for match in projected_matches
            if match.get("canonical_id") or match.get("page_id")
        })
        primary_canonical_id = next(
            (
                record.get("canonical_id") or record.get("page_id")
                for record in page_state_records
                if record.get("page_id") == primary_page_id
            ),
            primary_page_id,
        )

        if action == "assign_alias":
            if projected_canonical_ids != [primary_canonical_id]:
                raise ValueError(
                    "assign_alias did not converge alias ownership. "
                    f"Alias `{alias_to_assign}` would remain on canonical_ids={projected_canonical_ids} "
                    f"(page_ids={projected_page_ids})."
                )
        elif projected_page_ids:
            raise ValueError(
                "remove_alias did not fully clear alias ownership. "
                f"Alias `{alias_to_assign}` would remain on page_ids={projected_page_ids}."
            )

        return deps.clear_accepted_alias_conflict(
            updated_overrides,
            alias_to_assign,
            projected_canonical_ids,
        )

    deps.update_page_alias_overrides_with_lock(target, update_and_validate)

    review_record["status"] = "resolved"
    review_record["resolved_at"] = deps.utc_now_iso()
    review_record["lifecycle_status"] = "active"
    return {
        "action": action,
        "changed_page_ids": candidate_page_ids,
        "resolved_review_id": review_record["review_id"],
        "alias_value": alias_to_assign,
        "primary_page_id": primary_page_id,
    }


def _resolve_keep_both_action(
    *,
    target: Path,
    review_record: dict,
    candidate_claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
    deps: ReviewActionDeps,
) -> dict:
    if review_record.get("kind") == "alias_conflict":
        evidence = review_record.get("evidence", [])
        alias_from_review = str(evidence[0].get("alias", "")).strip() if evidence else ""
        canonical_ids = [
            str(value).strip()
            for value in (evidence[0].get("canonical_ids", []) if evidence else [])
            if str(value).strip()
        ]
        if alias_from_review and canonical_ids:
            def accept_alias_conflict(overrides: dict) -> dict:
                return deps.persist_accepted_alias_conflict(
                    overrides=overrides,
                    alias_value=alias_from_review,
                    canonical_ids=canonical_ids,
                )

            deps.update_page_alias_overrides_with_lock(target, accept_alias_conflict)
    review_record["status"] = "resolved"
    review_record["resolved_at"] = deps.utc_now_iso()
    review_record["lifecycle_status"] = "active"
    deps.sync_claim_review_state_from_open_reviews(
        candidate_claim_ids,
        live_claims_by_id,
        live_reviews_by_id,
    )
    return {
        "action": "keep_both",
        "changed_claim_ids": candidate_claim_ids,
        "resolved_review_id": review_record["review_id"],
    }


def _resolve_edit_then_resume_action(
    *,
    target: Path,
    review_record: dict,
    candidate_claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
    deps: ReviewActionDeps,
) -> dict:
    reloaded_claim_ids = deps.reload_claims_from_disk_for_review(
        target,
        candidate_claim_ids,
        live_claims_by_id,
    )
    review_record["status"] = "resolved"
    review_record["resolved_at"] = deps.utc_now_iso()
    review_record["lifecycle_status"] = "active"
    deps.sync_claim_review_state_from_open_reviews(
        sorted(reloaded_claim_ids),
        live_claims_by_id,
        live_reviews_by_id,
    )
    return {
        "action": "edit_then_resume",
        "changed_claim_ids": sorted(reloaded_claim_ids),
        "resolved_review_id": review_record["review_id"],
    }


def _resolve_archive_one_action(
    *,
    review_record: dict,
    primary_claim_id: str | None,
    candidate_claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
    deps: ReviewActionDeps,
) -> dict:
    if not primary_claim_id:
        raise ValueError("archive_one requires --primary-claim-id.")
    if primary_claim_id not in candidate_claim_ids:
        raise ValueError("primary claim must belong to candidate_claim_ids.")
    claim_record = deps.resolve_claim_record_for_action(
        primary_claim_id,
        live_claims_by_id,
        historical_claims_by_id,
    )
    if claim_record["claim_id"] not in live_claims_by_id:
        raise ValueError("archive_one currently only supports active claims.")
    historical_claim_record = deps.archive_live_claim(
        claim_record=claim_record,
        live_claims_by_id=live_claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
    )
    review_record["status"] = "resolved"
    review_record["resolved_at"] = deps.utc_now_iso()
    review_record["lifecycle_status"] = "active"
    deps.rewrite_open_reviews_for_claim_change(
        changed_review_id=review_record["review_id"],
        removed_claim_id=primary_claim_id,
        replacement_claim_id=None,
        live_claims_by_id=live_claims_by_id,
        live_reviews_by_id=live_reviews_by_id,
    )
    return {
        "action": "archive_one",
        "changed_claim_ids": [historical_claim_record["claim_id"]],
        "resolved_review_id": review_record["review_id"],
    }


def _resolve_merge_action(
    *,
    review_record: dict,
    primary_claim_id: str | None,
    secondary_claim_id: str | None,
    candidate_claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
    deps: ReviewActionDeps,
) -> dict:
    if not primary_claim_id or not secondary_claim_id:
        raise ValueError("merge requires --primary-claim-id and --secondary-claim-id.")
    if primary_claim_id == secondary_claim_id:
        raise ValueError("primary and secondary claim ids must be different.")
    if primary_claim_id not in candidate_claim_ids or secondary_claim_id not in candidate_claim_ids:
        raise ValueError("Both primary and secondary claims must belong to candidate_claim_ids.")

    primary_record = deps.resolve_claim_record_for_action(
        primary_claim_id,
        live_claims_by_id,
        historical_claims_by_id,
    )
    secondary_record = deps.resolve_claim_record_for_action(
        secondary_claim_id,
        live_claims_by_id,
        historical_claims_by_id,
    )
    if primary_record["claim_id"] not in live_claims_by_id or secondary_record["claim_id"] not in live_claims_by_id:
        raise ValueError("merge currently only supports active claims.")

    merged_record = deps.merge_claim_records(primary_record, secondary_record)
    merged_record["duplicate_candidates"] = [
        item for item in merged_record.get("duplicate_candidates", [])
        if item not in {merged_record["claim_id"], secondary_record["claim_id"]}
    ]
    merged_record["conflict_group"] = None
    merged_record["review_reason"] = None
    merged_record["status"] = "draft"
    merged_record["updated_at"] = deps.utc_now_iso()
    live_claims_by_id[merged_record["claim_id"]] = merged_record

    historical_secondary = deps.archive_live_claim(
        claim_record=secondary_record,
        live_claims_by_id=live_claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
        archived_by_claim_id=merged_record["claim_id"],
    )
    review_record["status"] = "resolved"
    review_record["resolved_at"] = deps.utc_now_iso()
    review_record["lifecycle_status"] = "active"
    deps.rewrite_open_reviews_for_claim_change(
        changed_review_id=review_record["review_id"],
        removed_claim_id=secondary_claim_id,
        replacement_claim_id=merged_record["claim_id"],
        live_claims_by_id=live_claims_by_id,
        live_reviews_by_id=live_reviews_by_id,
    )
    deps.normalize_claim_review_flags(merged_record)
    return {
        "action": "merge",
        "changed_claim_ids": [merged_record["claim_id"], historical_secondary["claim_id"]],
        "resolved_review_id": review_record["review_id"],
    }


def apply_review_action_via_helpers(
    *,
    target: Path,
    review_record: dict,
    action: str,
    primary_claim_id: str | None,
    secondary_claim_id: str | None,
    primary_page_id: str | None,
    alias_value: str | None,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
    deps: ReviewActionDeps,
) -> dict:
    del historical_reviews_by_id

    allowed_actions = set(review_record.get("allowed_actions", []))
    if action not in allowed_actions:
        raise ValueError(f"Action `{action}` is not allowed for review `{deps.review_display_id(review_record)}`.")

    candidate_claim_ids = list(review_record.get("candidate_claim_ids", []))
    candidate_page_ids = list(review_record.get("candidate_page_ids", []))

    if review_record.get("kind") == "alias_conflict" and action in {"assign_alias", "remove_alias"}:
        return _resolve_alias_conflict_action(
            target=target,
            review_record=review_record,
            action=action,
            primary_page_id=primary_page_id,
            alias_value=alias_value,
            candidate_page_ids=candidate_page_ids,
            deps=deps,
        )

    if action == "keep_both":
        return _resolve_keep_both_action(
            target=target,
            review_record=review_record,
            candidate_claim_ids=candidate_claim_ids,
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
            deps=deps,
        )

    if action == "edit_then_resume":
        return _resolve_edit_then_resume_action(
            target=target,
            review_record=review_record,
            candidate_claim_ids=candidate_claim_ids,
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
            deps=deps,
        )

    if action == "archive_one":
        return _resolve_archive_one_action(
            review_record=review_record,
            primary_claim_id=primary_claim_id,
            candidate_claim_ids=candidate_claim_ids,
            live_claims_by_id=live_claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
            deps=deps,
        )

    if action == "merge":
        return _resolve_merge_action(
            review_record=review_record,
            primary_claim_id=primary_claim_id,
            secondary_claim_id=secondary_claim_id,
            candidate_claim_ids=candidate_claim_ids,
            live_claims_by_id=live_claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
            deps=deps,
        )

    raise NotImplementedError(f"Action `{action}` is not implemented yet.")
