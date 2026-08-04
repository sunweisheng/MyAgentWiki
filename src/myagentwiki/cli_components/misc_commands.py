from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ..debug_trace import current_debug_tracer, entity_reference, trace_lineage, trace_step
from ..app_services.claim_status_service import (
    ClaimSetStatusRequest,
    ClaimStatusServiceDeps,
    run_claim_set_status_service,
)
from ..app_services.lint_service import LintRequest, LintServiceDeps, run_lint_service
from ..app_services.render_service import RenderPageRequest, RenderPageServiceDeps, run_render_page_service
from ..app_services.semantic_batch_service import (
    SemanticBatchRequest,
    SemanticBatchServiceDeps,
    run_semantic_batch_service,
)
from .result import CommandResult


@dataclass(frozen=True)
class MiscCliDeps:
    find_project_root: object
    workspace_schema_guard_payload: object
    load_simple_yaml: object
    resolve_workspace_path: object
    load_jsonl: object
    load_semantic_decisions: object
    ensure_claim_lifecycle_defaults: object
    filter_live_claim_records: object
    is_live_claim_record: object
    ensure_review_lifecycle_defaults: object
    filter_live_review_records: object
    is_live_review_record: object
    load_page_state_records: object
    ensure_page_lifecycle_defaults: object
    filter_live_page_records: object
    is_live_page_record: object
    claim_semantic_risk_issues: object
    rendered_page_grounding_issues: object
    concept_page_quality_issues: object
    page_semantic_consistency_issues: object
    page_intent_brake_issues: object
    load_alias_index: object
    alias_index_path: object
    unresolved_alias_conflicts: object
    load_search_pages_index: object
    atomic_write_text: object
    build_workspace_summary: object
    render_workspace_summary_message: object
    alias_index_rel_path: str
    search_pages_index_rel_path: str
    structure_blocks_rel_path: str
    evidence_blocks_rel_path: str
    knowledge_units_rel_path: str
    semantic_decisions_rel_path: str
    ensure_workspace_schema_supported: object
    page_render_targets: object
    load_claim_state_maps: object
    load_review_state_maps: object
    rebuild_review_affected_pages: object
    live_pages_for_render_target: object
    page_record_render_target: object
    run_semantic_batch_task: object
    is_actionable_review_record: object
    utc_now_iso: object


def build_misc_cli_deps(
    *,
    find_project_root: object,
    workspace_schema_guard_payload: object,
    load_simple_yaml: object,
    resolve_workspace_path: object,
    load_jsonl: object,
    load_semantic_decisions: object,
    ensure_claim_lifecycle_defaults: object,
    filter_live_claim_records: object,
    is_live_claim_record: object,
    ensure_review_lifecycle_defaults: object,
    filter_live_review_records: object,
    is_live_review_record: object,
    load_page_state_records: object,
    ensure_page_lifecycle_defaults: object,
    filter_live_page_records: object,
    is_live_page_record: object,
    claim_semantic_risk_issues: object,
    rendered_page_grounding_issues: object,
    concept_page_quality_issues: object,
    page_semantic_consistency_issues: object,
    page_intent_brake_issues: object,
    load_alias_index: object,
    alias_index_path: object,
    unresolved_alias_conflicts: object,
    load_search_pages_index: object,
    atomic_write_text: object,
    build_workspace_summary: object,
    render_workspace_summary_message: object,
    alias_index_rel_path: str,
    search_pages_index_rel_path: str,
    structure_blocks_rel_path: str,
    evidence_blocks_rel_path: str,
    knowledge_units_rel_path: str,
    semantic_decisions_rel_path: str,
    ensure_workspace_schema_supported: object,
    page_render_targets: object,
    load_claim_state_maps: object,
    load_review_state_maps: object,
    rebuild_review_affected_pages: object,
    live_pages_for_render_target: object,
    page_record_render_target: object,
    run_semantic_batch_task: object,
    is_actionable_review_record: object,
    utc_now_iso: object,
) -> MiscCliDeps:
    return MiscCliDeps(
        find_project_root=find_project_root,
        workspace_schema_guard_payload=workspace_schema_guard_payload,
        load_simple_yaml=load_simple_yaml,
        resolve_workspace_path=resolve_workspace_path,
        load_jsonl=load_jsonl,
        load_semantic_decisions=load_semantic_decisions,
        ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
        filter_live_claim_records=filter_live_claim_records,
        is_live_claim_record=is_live_claim_record,
        ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
        filter_live_review_records=filter_live_review_records,
        is_live_review_record=is_live_review_record,
        load_page_state_records=load_page_state_records,
        ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
        filter_live_page_records=filter_live_page_records,
        is_live_page_record=is_live_page_record,
        claim_semantic_risk_issues=claim_semantic_risk_issues,
        rendered_page_grounding_issues=rendered_page_grounding_issues,
        concept_page_quality_issues=concept_page_quality_issues,
        page_semantic_consistency_issues=page_semantic_consistency_issues,
        page_intent_brake_issues=page_intent_brake_issues,
        load_alias_index=load_alias_index,
        alias_index_path=alias_index_path,
        unresolved_alias_conflicts=unresolved_alias_conflicts,
        load_search_pages_index=load_search_pages_index,
        atomic_write_text=atomic_write_text,
        build_workspace_summary=build_workspace_summary,
        render_workspace_summary_message=render_workspace_summary_message,
        alias_index_rel_path=alias_index_rel_path,
        search_pages_index_rel_path=search_pages_index_rel_path,
        structure_blocks_rel_path=structure_blocks_rel_path,
        evidence_blocks_rel_path=evidence_blocks_rel_path,
        knowledge_units_rel_path=knowledge_units_rel_path,
        semantic_decisions_rel_path=semantic_decisions_rel_path,
        ensure_workspace_schema_supported=ensure_workspace_schema_supported,
        page_render_targets=page_render_targets,
        load_claim_state_maps=load_claim_state_maps,
        load_review_state_maps=load_review_state_maps,
        rebuild_review_affected_pages=rebuild_review_affected_pages,
        live_pages_for_render_target=live_pages_for_render_target,
        page_record_render_target=page_record_render_target,
        run_semantic_batch_task=run_semantic_batch_task,
        is_actionable_review_record=is_actionable_review_record,
        utc_now_iso=utc_now_iso,
    )


def command_lint(deps: MiscCliDeps, args: argparse.Namespace) -> CommandResult:
    request = LintRequest(target_dir=args.target_dir)
    with trace_step("lint.evaluate_workspace", kind="lint_stage", input_data=request) as lint_step:
        result = run_lint_service(
            request,
            deps=LintServiceDeps(
                find_project_root=deps.find_project_root,
                workspace_schema_guard_payload=deps.workspace_schema_guard_payload,
                load_simple_yaml=deps.load_simple_yaml,
                resolve_workspace_path=deps.resolve_workspace_path,
                load_jsonl=deps.load_jsonl,
                load_semantic_decisions=deps.load_semantic_decisions,
                ensure_claim_lifecycle_defaults=deps.ensure_claim_lifecycle_defaults,
                filter_live_claim_records=deps.filter_live_claim_records,
                is_live_claim_record=deps.is_live_claim_record,
                ensure_review_lifecycle_defaults=deps.ensure_review_lifecycle_defaults,
                filter_live_review_records=deps.filter_live_review_records,
                is_live_review_record=deps.is_live_review_record,
                load_page_state_records=deps.load_page_state_records,
                ensure_page_lifecycle_defaults=deps.ensure_page_lifecycle_defaults,
                filter_live_page_records=deps.filter_live_page_records,
                is_live_page_record=deps.is_live_page_record,
                claim_semantic_risk_issues=deps.claim_semantic_risk_issues,
                rendered_page_grounding_issues=deps.rendered_page_grounding_issues,
                concept_page_quality_issues=deps.concept_page_quality_issues,
                page_semantic_consistency_issues=deps.page_semantic_consistency_issues,
                page_intent_brake_issues=deps.page_intent_brake_issues,
                load_alias_index=deps.load_alias_index,
                alias_index_path=deps.alias_index_path,
                unresolved_alias_conflicts=deps.unresolved_alias_conflicts,
                load_search_pages_index=deps.load_search_pages_index,
                atomic_write_text=deps.atomic_write_text,
                build_workspace_summary=deps.build_workspace_summary,
                render_workspace_summary_message=deps.render_workspace_summary_message,
                alias_index_rel_path=deps.alias_index_rel_path,
                search_pages_index_rel_path=deps.search_pages_index_rel_path,
                structure_blocks_rel_path=deps.structure_blocks_rel_path,
                evidence_blocks_rel_path=deps.evidence_blocks_rel_path,
                knowledge_units_rel_path=deps.knowledge_units_rel_path,
                semantic_decisions_rel_path=deps.semantic_decisions_rel_path,
            ),
        )
        lint_step.set_output(result.payload)
    return CommandResult(
        exit_code=result.exit_code,
        payload=result.payload,
        message=result.message,
    )


def command_render_page(deps: MiscCliDeps, args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    request = RenderPageRequest(
        target=target,
        render_target=args.render_target,
        page_id=args.page_id,
        canonical_id=args.canonical_id,
        claim_id=args.claim_id,
    )
    with trace_step("page.render", kind="page_stage", input_data=request) as render_step:
        result = run_render_page_service(
            request,
            deps=RenderPageServiceDeps(
                ensure_workspace_schema_supported=deps.ensure_workspace_schema_supported,
                page_render_targets=deps.page_render_targets,
                load_claim_state_maps=deps.load_claim_state_maps,
                load_review_state_maps=deps.load_review_state_maps,
                rebuild_review_affected_pages=deps.rebuild_review_affected_pages,
                load_page_state_records=deps.load_page_state_records,
                live_pages_for_render_target=deps.live_pages_for_render_target,
                page_record_render_target=deps.page_record_render_target,
            ),
        )
        render_step.set_output(result.payload)
        trace_lineage(
            operation="generated",
            reason="explicit_page_render_command",
            inputs=lambda: [entity_reference("render_request", args.render_target, value=request)],
            outputs=lambda: [entity_reference("render_result", args.render_target, value=result.payload)],
            snapshot_name=f"render_{args.render_target}_result",
        )
    return CommandResult(payload=result.payload, message=result.message)


def command_semantic_batch(deps: MiscCliDeps, args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    request = SemanticBatchRequest(
        target=target,
        task=args.task,
        dry_run=bool(args.dry_run),
    )
    with trace_step("semantic.run_task", kind="semantic_stage", input_data=request) as semantic_step:
        result = run_semantic_batch_service(
            request,
            deps=SemanticBatchServiceDeps(
                ensure_workspace_schema_supported=deps.ensure_workspace_schema_supported,
                run_semantic_batch_task=deps.run_semantic_batch_task,
                render_workspace_summary_message=deps.render_workspace_summary_message,
            ),
        )
        semantic_step.set_output(result.payload)
    return CommandResult(payload=result.payload, message=result.message)


def command_claim_set_status(deps: MiscCliDeps, args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    before_claim = None
    if current_debug_tracer() is not None:
        before_live_claims, before_historical_claims, _ = deps.load_claim_state_maps(target)
        before_claim = before_live_claims.get(args.claim_id) or before_historical_claims.get(
            args.claim_id
        )
    request = ClaimSetStatusRequest(
        target=target,
        claim_id=args.claim_id,
        status=args.status,
    )
    with trace_step("claim.set_status", kind="claim_stage", input_data=request) as claim_step:
        result = run_claim_set_status_service(
            request,
            deps=ClaimStatusServiceDeps(
                ensure_workspace_schema_supported=deps.ensure_workspace_schema_supported,
                load_claim_state_maps=deps.load_claim_state_maps,
                load_review_state_maps=deps.load_review_state_maps,
                is_actionable_review_record=deps.is_actionable_review_record,
                utc_now_iso=deps.utc_now_iso,
                rebuild_review_affected_pages=deps.rebuild_review_affected_pages,
            ),
        )
        claim_step.set_output(result.payload)
        after_claim = None
        if current_debug_tracer() is not None:
            after_live_claims, after_historical_claims, _ = deps.load_claim_state_maps(target)
            after_claim = after_live_claims.get(args.claim_id) or after_historical_claims.get(
                args.claim_id
            )
        trace_lineage(
            operation="replaced",
            reason="explicit_claim_status_update",
            inputs=lambda: [entity_reference(
                "claim",
                args.claim_id,
                value={"record": before_claim, "requested_status": args.status},
            )],
            outputs=lambda: [entity_reference(
                "claim_status_result",
                args.claim_id,
                value={"record": after_claim, "result": result.payload},
            )],
            snapshot_name=f"claim_{args.claim_id}_status_update",
        )
    return CommandResult(payload=result.payload, message=result.message)
