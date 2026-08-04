from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from ..app_services.review_apply_service import ReviewApplyRequest, run_review_apply_service
from ..app_services.review_auto_service import ReviewAutoRequest, run_review_auto_service
from ..app_services.review_service import run_review_list_service
from .result import CommandResult


@dataclass(frozen=True)
class ReviewCliDeps:
    ensure_workspace_schema_supported: object
    load_claim_state_maps: object
    load_review_state_maps: object
    build_claim_lookup_by_any_id: object
    refresh_alias_conflict_reviews: object
    persist_ordered_review_state: object
    persist_ordered_claim_state: object
    cleanup_review_related_record_files: object
    review_display_id: object
    claim_display_id: object
    apply_review_action: object
    build_ordered_claim_state_records: object
    rebuild_review_affected_pages: object
    build_workspace_summary: object
    render_workspace_summary_message: object
    load_workspace_config: object
    load_automation_target_config: object
    propose_review_auto_action: object
    is_actionable_review_record: object
    claim_record_is_safe_auto_stable_candidate: object
    maybe_get_llm_assisted_stable_promotion: object
    utc_now_iso: object
    build_review_auto_escalation_entry: object
    build_review_auto_agent_handoff: object
    review_auto_handoff_contract_version: str
    render_review_auto_prompt: object
    build_review_auto_messages: object
    render_review_auto_chatml: object
    render_review_auto_message: object


def build_review_list_payload(deps: ReviewCliDeps, target: Path, status_filter: str | None = None) -> dict:
    return run_review_list_service(
        target=target,
        status_filter=status_filter,
        load_review_state_maps=deps.load_review_state_maps,
        load_claim_state_maps=deps.load_claim_state_maps,
        build_claim_lookup_by_any_id=deps.build_claim_lookup_by_any_id,
        refresh_alias_conflict_reviews=deps.refresh_alias_conflict_reviews,
        persist_ordered_review_state=deps.persist_ordered_review_state,
        cleanup_review_related_record_files=deps.cleanup_review_related_record_files,
        review_display_id=deps.review_display_id,
        claim_display_id=deps.claim_display_id,
        build_workspace_summary=lambda path: deps.build_workspace_summary(path),
    )


def command_review_list(deps: ReviewCliDeps, args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    deps.ensure_workspace_schema_supported(target)
    payload = build_review_list_payload(deps, target, status_filter=args.status)
    if args.json:
        return CommandResult(
            payload=payload,
            message=deps.render_workspace_summary_message(
                "Review list completed.",
                target_dir=target,
                extra_lines=[
                    f"Status filter: {args.status or 'all'}",
                    (
                        "Summary: "
                        f"reviews={payload['summary']['review_count']}, "
                        f"live={payload['summary']['live_review_count']}, "
                        f"historical={payload['summary']['historical_review_count']}"
                    ),
                ],
            ),
        )

    lines = [
        deps.render_workspace_summary_message(
            "Review list completed.",
            target_dir=target,
            extra_lines=[
                f"Status filter: {args.status or 'all'}",
                (
                    "Summary: "
                    f"reviews={payload['summary']['review_count']}, "
                    f"live={payload['summary']['live_review_count']}, "
                    f"historical={payload['summary']['historical_review_count']}"
                ),
                "",
                "Review Items:",
            ],
        )
    ]
    for index, item in enumerate(payload["items"], start=1):
        lines.append(
            f"{index}. {item['display_id']} [{item['kind']}, status={item['status']}, lifecycle={item['lifecycle_status']}]"
        )
        lines.append(f"   reason: {item['reason']}")
        lines.append(f"   recommended: {item['recommended_action']}")
        lines.append(f"   allowed: {', '.join(item['allowed_actions'])}")
        for claim in item["candidate_claims"][:4]:
            lines.append(
                f"   - {claim['display_id']} [{claim['lifecycle_status']}/{claim['status']}] {claim['text']}"
            )
    if len(lines) == 1:
        lines.append("No review items found.")
    return CommandResult(payload=payload, message="\n".join(lines))


def command_review_auto(deps: ReviewCliDeps, args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    deps.ensure_workspace_schema_supported(target)
    handoff_format = str(getattr(args, "format", "summary") or "summary").strip().lower()
    payload = run_review_auto_service(
        ReviewAutoRequest(
            target=target,
            dry_run=bool(args.dry_run),
            handoff_format=handoff_format,
        ),
        load_workspace_config=deps.load_workspace_config,
        load_automation_target_config=deps.load_automation_target_config,
        load_claim_state_maps=deps.load_claim_state_maps,
        load_review_state_maps=deps.load_review_state_maps,
        refresh_alias_conflict_reviews=deps.refresh_alias_conflict_reviews,
        persist_ordered_review_state=deps.persist_ordered_review_state,
        persist_ordered_claim_state=deps.persist_ordered_claim_state,
        cleanup_review_related_record_files=deps.cleanup_review_related_record_files,
        propose_review_auto_action=deps.propose_review_auto_action,
        review_display_id=deps.review_display_id,
        is_actionable_review_record=deps.is_actionable_review_record,
        apply_review_action=deps.apply_review_action,
        claim_record_is_safe_auto_stable_candidate=deps.claim_record_is_safe_auto_stable_candidate,
        maybe_get_llm_assisted_stable_promotion=deps.maybe_get_llm_assisted_stable_promotion,
        utc_now_iso=deps.utc_now_iso,
        rebuild_review_affected_pages=deps.rebuild_review_affected_pages,
        build_review_auto_escalation_entry=deps.build_review_auto_escalation_entry,
        build_review_auto_agent_handoff=deps.build_review_auto_agent_handoff,
        build_workspace_summary=lambda path: deps.build_workspace_summary(path),
        review_auto_handoff_contract_version=deps.review_auto_handoff_contract_version,
        render_review_auto_prompt=deps.render_review_auto_prompt,
        build_review_auto_messages=deps.build_review_auto_messages,
        render_review_auto_chatml=deps.render_review_auto_chatml,
    )

    if args.json:
        return CommandResult(
            payload=payload,
            message=deps.render_workspace_summary_message(
                "Review auto pass completed." if not args.dry_run else "Review auto dry-run completed.",
                target_dir=target,
                extra_lines=[
                    f"Dry run: {bool(args.dry_run)}",
                    f"Format: {handoff_format}",
                    (
                        "Summary: "
                        f"planned={payload['summary']['planned_review_count']}, "
                        f"auto_apply={payload['summary']['auto_apply_count']}, "
                        f"escalated={payload['summary']['escalated_count']}, "
                        f"applied={payload['summary']['applied_count']}, "
                        f"promoted_claims={payload['summary']['promoted_claim_count']}"
                    ),
                ],
            ),
        )
    if handoff_format == "prompt":
        return CommandResult(payload=payload, message=payload["prompt_text"])
    if handoff_format == "messages":
        return CommandResult(
            payload=payload,
            message=json.dumps(payload["messages"], ensure_ascii=False, indent=2),
        )
    if handoff_format == "chatml":
        return CommandResult(payload=payload, message=payload["chatml_text"])

    return CommandResult(
        payload=payload,
        message=deps.render_workspace_summary_message(
            "Review auto pass completed." if not args.dry_run else "Review auto dry-run completed.",
            target_dir=target,
            extra_lines=[
                f"Dry run: {bool(args.dry_run)}",
                (
                    "Summary: "
                    f"planned={payload['summary']['planned_review_count']}, "
                    f"auto_apply={payload['summary']['auto_apply_count']}, "
                    f"escalated={payload['summary']['escalated_count']}, "
                    f"applied={payload['summary']['applied_count']}, "
                    f"promoted_claims={payload['summary']['promoted_claim_count']}"
                ),
                "",
                deps.render_review_auto_message(payload),
            ],
        ),
    )


def run_post_ingest_review_auto(deps: ReviewCliDeps, target: Path) -> dict:
    return run_review_auto_service(
        ReviewAutoRequest(
            target=target,
            dry_run=False,
            handoff_format="summary",
        ),
        load_workspace_config=deps.load_workspace_config,
        load_automation_target_config=deps.load_automation_target_config,
        load_claim_state_maps=deps.load_claim_state_maps,
        load_review_state_maps=deps.load_review_state_maps,
        refresh_alias_conflict_reviews=deps.refresh_alias_conflict_reviews,
        persist_ordered_review_state=deps.persist_ordered_review_state,
        persist_ordered_claim_state=deps.persist_ordered_claim_state,
        cleanup_review_related_record_files=deps.cleanup_review_related_record_files,
        propose_review_auto_action=deps.propose_review_auto_action,
        review_display_id=deps.review_display_id,
        is_actionable_review_record=deps.is_actionable_review_record,
        apply_review_action=deps.apply_review_action,
        claim_record_is_safe_auto_stable_candidate=deps.claim_record_is_safe_auto_stable_candidate,
        maybe_get_llm_assisted_stable_promotion=deps.maybe_get_llm_assisted_stable_promotion,
        utc_now_iso=deps.utc_now_iso,
        rebuild_review_affected_pages=deps.rebuild_review_affected_pages,
        build_review_auto_escalation_entry=deps.build_review_auto_escalation_entry,
        build_review_auto_agent_handoff=deps.build_review_auto_agent_handoff,
        build_workspace_summary=lambda path: deps.build_workspace_summary(path),
        review_auto_handoff_contract_version=deps.review_auto_handoff_contract_version,
        render_review_auto_prompt=deps.render_review_auto_prompt,
        build_review_auto_messages=deps.build_review_auto_messages,
        render_review_auto_chatml=deps.render_review_auto_chatml,
    )


def command_review_apply(deps: ReviewCliDeps, args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    deps.ensure_workspace_schema_supported(target)
    payload = run_review_apply_service(
        ReviewApplyRequest(
            target=target,
            review_id=args.review_id,
            action=args.action,
            primary_claim_id=args.primary_claim_id,
            secondary_claim_id=args.secondary_claim_id,
            primary_page_id=args.primary_page_id,
            alias_value=args.alias_value,
        ),
        load_claim_state_maps=deps.load_claim_state_maps,
        load_review_state_maps=deps.load_review_state_maps,
        refresh_alias_conflict_reviews=deps.refresh_alias_conflict_reviews,
        persist_ordered_review_state=deps.persist_ordered_review_state,
        persist_ordered_claim_state=deps.persist_ordered_claim_state,
        cleanup_review_related_record_files=deps.cleanup_review_related_record_files,
        review_display_id=deps.review_display_id,
        apply_review_action=deps.apply_review_action,
        rebuild_review_affected_pages=deps.rebuild_review_affected_pages,
        build_workspace_summary=lambda path: deps.build_workspace_summary(path),
    )
    return CommandResult(
        payload=payload,
        message=deps.render_workspace_summary_message(
            "Review action applied.",
            target_dir=target,
            extra_lines=[
                f"Review: {payload['display_id']}",
                f"Action: {payload.get('action')}",
                f"Review id: {payload['review_id']}",
            ],
        ),
    )
