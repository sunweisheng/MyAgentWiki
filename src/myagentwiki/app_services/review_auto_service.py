from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .review_rebuild_service import ReviewRebuildRequest, ReviewRebuildServiceDeps, run_review_rebuild_service


@dataclass(frozen=True)
class ReviewAutoRequest:
    target: Path
    dry_run: bool
    handoff_format: str


def run_review_auto_service(
    request: ReviewAutoRequest,
    *,
    load_workspace_config: Callable[[Path], dict],
    load_automation_target_config: Callable[[dict, str], dict],
    load_claim_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]],
    load_review_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]],
    refresh_alias_conflict_reviews: Callable[..., tuple[dict, set[str], set[str]]],
    persist_ordered_review_state: Callable[..., list[dict]],
    persist_ordered_claim_state: Callable[..., list[dict]],
    cleanup_review_related_record_files: Callable[..., None],
    propose_review_auto_action: Callable[..., dict],
    review_display_id: Callable[[dict], str],
    is_actionable_review_record: Callable[[dict], bool],
    apply_review_action: Callable[..., dict],
    claim_record_is_safe_auto_stable_candidate: Callable[[dict, dict[str, dict]], tuple[bool, str | None]],
    maybe_get_agent_assisted_stable_promotion: Callable[..., tuple[bool, str | None]],
    utc_now_iso: Callable[[], str],
    rebuild_review_affected_pages: Callable[[Path, dict[str, dict], dict[str, dict]], None],
    build_review_auto_escalation_entry: Callable[[dict, dict, dict[str, dict]], dict],
    build_review_auto_agent_handoff: Callable[..., tuple[dict, str]],
    build_workspace_summary: Callable[[Path], dict],
    review_auto_handoff_contract_version: str,
    render_review_auto_prompt: Callable[[dict], str],
    build_review_auto_messages: Callable[[dict], list[dict]],
    render_review_auto_chatml: Callable[[dict], str],
) -> dict:
    target = request.target
    config = load_workspace_config(target)
    review_automation_config = load_automation_target_config(config, "review_auto")
    stable_automation_config = load_automation_target_config(config, "stable_promotion")

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

    planned_actions = [
        propose_review_auto_action(
            target=target,
            review_record=review_record,
            live_claims_by_id=live_claims_by_id,
            automation_config=review_automation_config,
        )
        for review_record in sorted(
            live_reviews_by_id.values(),
            key=lambda item: (item.get("created_at", ""), review_display_id(item)),
        )
        if is_actionable_review_record(review_record)
    ]

    auto_apply_plans = [item for item in planned_actions if item["decision"] == "auto_apply"]
    escalated_plans = [item for item in planned_actions if item["decision"] != "auto_apply"]
    applied_actions: list[dict] = []
    promoted_claims: list[dict] = []
    auto_apply_failures: list[dict] = []

    if not request.dry_run:
        for plan in auto_apply_plans:
            review_record = live_reviews_by_id.get(plan["review_id"])
            if review_record is None:
                continue
            current_plan = propose_review_auto_action(
                target=target,
                review_record=review_record,
                live_claims_by_id=live_claims_by_id,
                automation_config=review_automation_config,
            )
            if current_plan.get("decision") != "auto_apply":
                continue
            try:
                result = apply_review_action(
                    target=target,
                    review_record=review_record,
                    action=current_plan["action"],
                    primary_claim_id=current_plan["primary_claim_id"],
                    secondary_claim_id=current_plan["secondary_claim_id"],
                    primary_page_id=current_plan["primary_page_id"],
                    alias_value=current_plan["alias_value"],
                    live_claims_by_id=live_claims_by_id,
                    historical_claims_by_id=historical_claims_by_id,
                    live_reviews_by_id=live_reviews_by_id,
                    historical_reviews_by_id=historical_reviews_by_id,
                )
            except ValueError as exc:
                auto_apply_failures.append({
                    "review_id": current_plan["review_id"],
                    "display_id": current_plan["display_id"],
                    "kind": current_plan["kind"],
                    "reason": "auto_apply_failed_validation",
                    "validation_error": str(exc),
                })
                continue
            live_reviews_by_id[review_record["review_id"]] = review_record
            applied_actions.append({
                "review_id": current_plan["review_id"],
                "display_id": current_plan["display_id"],
                "kind": current_plan["kind"],
                "reason": current_plan["reason"],
                "action": result.get("action"),
                "changed_claim_ids": result.get("changed_claim_ids", []),
                "changed_page_ids": result.get("changed_page_ids", []),
            })

        for claim_record in sorted(live_claims_by_id.values(), key=lambda item: item["claim_id"]):
            is_safe, reason = claim_record_is_safe_auto_stable_candidate(claim_record, live_reviews_by_id)
            if not is_safe:
                promoted_by_hook, hook_reason = maybe_get_agent_assisted_stable_promotion(
                    target=target,
                    claim_record=claim_record,
                    automation_config=stable_automation_config,
                )
                if not promoted_by_hook:
                    continue
                reason = hook_reason
            claim_record["status"] = "stable"
            claim_record["review_reason"] = None
            claim_record["updated_at"] = utc_now_iso()
            promoted_claims.append({
                "claim_id": claim_record["claim_id"],
                "reason": reason or "safe_auto_promoted_to_stable",
            })

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

    failure_plan_by_review_id = {
        item["review_id"]: item
        for item in auto_apply_failures
    }
    final_escalated_plans = list(escalated_plans) + [
        {
            "review_id": item["review_id"],
            "display_id": item["display_id"],
            "kind": item["kind"],
            "recommended_action": None,
            "decision": "escalate",
            "reason": item["reason"],
            "action": None,
            "primary_claim_id": None,
            "secondary_claim_id": None,
            "primary_page_id": None,
            "alias_value": None,
            "confidence": None,
        }
        for item in auto_apply_failures
        if item["review_id"] in live_reviews_by_id
    ]

    escalated_entries = [
        build_review_auto_escalation_entry(
            review_record=live_reviews_by_id[plan["review_id"]],
            plan=plan,
            live_claims_by_id=live_claims_by_id,
        )
        for plan in final_escalated_plans
        if plan["review_id"] in live_reviews_by_id
    ]
    for entry in escalated_entries:
        failure_meta = failure_plan_by_review_id.get(entry["review_id"])
        if failure_meta is not None:
            entry["why_human_needed"] = (
                "自动裁决在最终收敛校验时失败，需要人工确认别名归属或改为保留多义并存。"
            )
            entry["validation_error"] = failure_meta["validation_error"]
    agent_brief, agent_summary = build_review_auto_agent_handoff(
        auto_apply_plans=auto_apply_plans,
        escalated_entries=escalated_entries,
        promoted_claims=promoted_claims,
        review_automation_config=review_automation_config,
        stable_automation_config=stable_automation_config,
    )

    payload = {
        "contract_version": review_auto_handoff_contract_version,
        "workspace": str(target),
        "workspace_summary": build_workspace_summary(target),
        "dry_run": bool(request.dry_run),
        "planned_actions": planned_actions,
        "applied_actions": applied_actions,
        "escalated_reviews": final_escalated_plans,
        "escalation_handoff": escalated_entries,
        "auto_apply_failures": auto_apply_failures,
        "promoted_claims": promoted_claims,
        "agent_brief": agent_brief,
        "agent_summary": agent_summary,
        "summary": {
            "planned_review_count": len(planned_actions),
            "auto_apply_count": len(auto_apply_plans),
            "escalated_count": len(final_escalated_plans),
            "applied_count": len(applied_actions),
            "auto_apply_failure_count": len(auto_apply_failures),
            "promoted_claim_count": len(promoted_claims),
        },
        "automation": {
            "review_auto": {
                "strategy": review_automation_config.get("strategy"),
                "enabled": review_automation_config.get("enabled"),
                "min_confidence": review_automation_config.get("min_confidence"),
            },
            "stable_promotion": {
                "strategy": stable_automation_config.get("strategy"),
                "enabled": stable_automation_config.get("enabled"),
                "min_confidence": stable_automation_config.get("min_confidence"),
            },
        },
    }
    handoff_format = request.handoff_format
    if handoff_format == "prompt":
        payload["prompt_text"] = render_review_auto_prompt(payload)
    elif handoff_format == "messages":
        payload["messages"] = build_review_auto_messages(payload)
    elif handoff_format == "chatml":
        payload["messages"] = build_review_auto_messages(payload)
        payload["chatml_text"] = render_review_auto_chatml(payload)
    return payload
