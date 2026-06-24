from __future__ import annotations

from pathlib import Path
from typing import Callable


def resolve_claim_record_for_action(
    claim_id: str,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    *,
    build_claim_lookup_by_any_id: Callable[[dict[str, dict], dict[str, dict]], dict[str, dict]],
) -> dict:
    claim_record = build_claim_lookup_by_any_id(live_claims_by_id, historical_claims_by_id).get(claim_id)
    if claim_record is None:
        raise KeyError(f"Unknown claim_id: {claim_id}")
    return claim_record


def archive_live_claim(
    claim_record: dict,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    *,
    utc_now_iso: Callable[[], str],
    append_unique: Callable[[list, object], None],
    convert_claim_record_to_historical: Callable[[dict], dict],
    archived_by_claim_id: str | None = None,
) -> dict:
    live_claims_by_id.pop(claim_record["claim_id"], None)
    claim_record = dict(claim_record)
    claim_record["lifecycle_status"] = "superseded"
    claim_record["archived_at"] = utc_now_iso()
    claim_record["updated_at"] = utc_now_iso()
    if archived_by_claim_id:
        append_unique(claim_record.setdefault("superseded_by", []), archived_by_claim_id)
    historical_claim_record = convert_claim_record_to_historical(claim_record)
    historical_claims_by_id[historical_claim_record["claim_id"]] = historical_claim_record
    return historical_claim_record


def normalize_claim_review_flags(
    claim_record: dict,
    *,
    utc_now_iso: Callable[[], str],
) -> None:
    duplicate_candidates = [
        item for item in claim_record.get("duplicate_candidates", [])
        if item != claim_record["claim_id"]
    ]
    claim_record["duplicate_candidates"] = sorted(set(duplicate_candidates))
    if claim_record.get("status") == "needs_review":
        has_duplicate_signal = bool(claim_record.get("duplicate_candidates"))
        has_conflict_signal = bool(claim_record.get("conflict_group"))
        if not has_duplicate_signal and not has_conflict_signal:
            claim_record["status"] = "draft"
            claim_record["review_reason"] = None
    claim_record["updated_at"] = utc_now_iso()


def sync_claim_review_state_from_open_reviews(
    claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
    *,
    is_actionable_review_record: Callable[[dict], bool],
    normalize_claim_review_flags: Callable[[dict], None],
) -> set[str]:
    dirty_claim_ids: set[str] = set()
    target_claim_ids = {claim_id for claim_id in claim_ids if claim_id in live_claims_by_id}

    for claim_id in sorted(target_claim_ids):
        claim_record = live_claims_by_id.get(claim_id)
        if claim_record is None:
            continue

        duplicate_candidates: set[str] = set()
        conflict_group = claim_record.get("conflict_group")
        review_reason = None

        for review_record in live_reviews_by_id.values():
            if not is_actionable_review_record(review_record):
                continue
            candidate_claim_ids = set(review_record.get("candidate_claim_ids", []))
            if claim_id not in candidate_claim_ids:
                continue

            if review_record.get("kind") == "claim_duplicate":
                duplicate_candidates.update(candidate_claim_ids - {claim_id})
                review_reason = "possible_duplicate_claim"
            elif review_record.get("kind") == "claim_conflict":
                if not conflict_group:
                    conflict_group = claim_record.get("conflict_group")
                review_reason = "conflicting_claims_detected"

        claim_record["duplicate_candidates"] = sorted(duplicate_candidates)
        claim_record["conflict_group"] = conflict_group if review_reason == "conflicting_claims_detected" else None
        if review_reason:
            claim_record["status"] = "needs_review"
            claim_record["review_reason"] = review_reason
        else:
            claim_record["review_reason"] = None
        normalize_claim_review_flags(claim_record)
        dirty_claim_ids.add(claim_id)

    return dirty_claim_ids


def rewrite_open_reviews_for_claim_change(
    changed_review_id: str,
    removed_claim_id: str,
    replacement_claim_id: str | None,
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
    *,
    utc_now_iso: Callable[[], str],
    review_lifecycle_status_for_record: Callable[[dict], str],
    sync_claim_review_state_from_open_reviews: Callable[[list[str], dict[str, dict], dict[str, dict]], set[str]],
) -> tuple[set[str], set[str]]:
    dirty_review_ids: set[str] = set()
    touched_live_claim_ids: set[str] = set()

    for review_id, candidate_review in live_reviews_by_id.items():
        if review_id == changed_review_id:
            continue
        if candidate_review.get("status") != "open":
            continue

        original_claim_ids = list(candidate_review.get("candidate_claim_ids", []))
        if removed_claim_id not in original_claim_ids:
            continue

        rewritten_claim_ids: list[str] = []
        for claim_id in original_claim_ids:
            if claim_id != removed_claim_id:
                if claim_id not in rewritten_claim_ids:
                    rewritten_claim_ids.append(claim_id)
                continue
            if replacement_claim_id and replacement_claim_id not in rewritten_claim_ids:
                rewritten_claim_ids.append(replacement_claim_id)

        if rewritten_claim_ids == original_claim_ids:
            continue

        candidate_review["candidate_claim_ids"] = rewritten_claim_ids
        candidate_review["candidate_page_ids"] = []

        if len(rewritten_claim_ids) < 2:
            candidate_review["status"] = "resolved"
            candidate_review["resolved_at"] = utc_now_iso()
        candidate_review["lifecycle_status"] = review_lifecycle_status_for_record(candidate_review)
        dirty_review_ids.add(review_id)

        touched_live_claim_ids.update(set(original_claim_ids) | set(rewritten_claim_ids))

    sync_claim_review_state_from_open_reviews(
        sorted(touched_live_claim_ids),
        live_claims_by_id,
        live_reviews_by_id,
    )

    return dirty_review_ids, touched_live_claim_ids


def cleanup_superseded_record_files(
    target: Path,
    historical_claims_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
    *,
    claim_file_path: Callable[[Path, str], Path],
    review_file_path: Callable[[Path, str], Path],
) -> None:
    for claim_record in historical_claims_by_id.values():
        original_claim_id = claim_record.get("original_claim_id")
        if not original_claim_id or original_claim_id == claim_record["claim_id"]:
            continue
        stale_claim_path = claim_file_path(target, original_claim_id)
        if stale_claim_path.exists():
            stale_claim_path.unlink()

    for review_record in historical_reviews_by_id.values():
        original_review_id = review_record.get("original_review_id")
        if not original_review_id or original_review_id == review_record["review_id"]:
            continue
        stale_review_path = review_file_path(target, original_review_id)
        if stale_review_path.exists():
            stale_review_path.unlink()


def reload_claims_from_disk_for_review(
    target: Path,
    claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
    *,
    claim_file_path: Callable[[Path, str], Path],
    ensure_claim_lifecycle_defaults: Callable[[dict], dict],
    load_json: Callable[[Path], dict],
) -> set[str]:
    reloaded_claim_ids: set[str] = set()

    for claim_id in claim_ids:
        claim_path = claim_file_path(target, claim_id)
        if not claim_path.exists():
            raise FileNotFoundError(
                f"Claim file does not exist for edit_then_resume: {claim_path}"
            )
        disk_record = ensure_claim_lifecycle_defaults(load_json(claim_path))
        disk_record["claim_id"] = claim_id
        disk_record["claim_file_path"] = str(Path("claims") / claim_path.name)
        disk_record.setdefault("page_ids", live_claims_by_id.get(claim_id, {}).get("page_ids", []))
        live_claims_by_id[claim_id] = disk_record
        reloaded_claim_ids.add(claim_id)

    return reloaded_claim_ids
