from __future__ import annotations

from pathlib import Path


def review_action_plain_label(action: str) -> str:
    labels = {
        "merge": "合并成一条更清楚的结论",
        "keep_both": "两条都保留",
        "archive_one": "保留一条并归档另一条",
        "edit_then_resume": "先手工修改再继续",
        "assign_alias": "把别名指定给某个页面",
        "remove_alias": "移除这个别名",
    }
    return labels.get(action, action)


def build_review_auto_decision_payload(
    review_record: dict,
    live_claims_by_id: dict[str, dict],
    target: Path,
    *,
    ensure_page_lifecycle_defaults: object,
    load_jsonl: object,
    load_alias_index: object,
    alias_index_matches_for_value: object,
) -> dict:
    candidate_claims = []
    for claim_id in review_record.get("candidate_claim_ids", []):
        claim_record = live_claims_by_id.get(claim_id)
        if claim_record is None:
            continue
        candidate_claims.append({
            "claim_id": claim_id,
            "text": claim_record.get("text", ""),
            "status": claim_record.get("status"),
            "claim_type": claim_record.get("claim_type"),
            "source_count": len(set(claim_record.get("source_ids", []))),
            "source_ref_count": len(claim_record.get("source_refs", [])),
            "duplicate_candidates": claim_record.get("duplicate_candidates", []),
            "conflict_group": claim_record.get("conflict_group"),
        })
    payload = {
        "task": "review_auto_decision",
        "review": {
            "review_id": review_record.get("review_id"),
            "kind": review_record.get("kind"),
            "reason": review_record.get("reason"),
            "recommended_action": review_record.get("recommended_action"),
            "allowed_actions": review_record.get("allowed_actions", []),
            "candidate_claim_ids": review_record.get("candidate_claim_ids", []),
            "candidate_page_ids": review_record.get("candidate_page_ids", []),
            "evidence": review_record.get("evidence", []),
        },
        "candidate_claims": candidate_claims,
        "candidate_pages": [],
    }
    candidate_page_ids = review_record.get("candidate_page_ids", [])
    if candidate_page_ids:
        pages_path = target / "state" / "pages.jsonl"
        if pages_path.exists():
            page_records = [
                ensure_page_lifecycle_defaults(record)
                for record in load_jsonl(pages_path)
            ]
            page_lookup = {record.get("page_id"): record for record in page_records}
            for page_id in candidate_page_ids:
                page_record = page_lookup.get(page_id)
                if page_record is None:
                    continue
                payload["candidate_pages"].append({
                    "page_id": page_id,
                    "canonical_id": page_record.get("canonical_id") or page_id,
                    "title": page_record.get("title", ""),
                    "aliases": page_record.get("aliases", []),
                    "type": page_record.get("type"),
                    "status": page_record.get("status"),
                })
    if review_record.get("kind") == "alias_conflict":
        evidence = review_record.get("evidence", [])
        alias_value = str(evidence[0].get("alias", "")).strip() if evidence else ""
        alias_index = load_alias_index(target)
        alias_matches = alias_index_matches_for_value(alias_index, alias_value) if alias_value else []
        payload["alias_conflict_context"] = {
            "alias_value": alias_value,
            "canonical_ids": evidence[0].get("canonical_ids", []) if evidence else [],
            "matched_pages": alias_matches,
        }
    return payload


def normalize_review_auto_llm_plan(
    model_result: dict,
    review_record: dict,
    base_plan: dict,
    live_claims_by_id: dict[str, dict],
    min_confidence: float,
    *,
    coerce_float: object,
    choose_auto_merge_primary_claim_id: object,
) -> dict | None:
    decision = str(model_result.get("decision", "")).strip().lower()
    if decision != "auto_apply":
        return None

    confidence = coerce_float(model_result.get("confidence", 0.0), 0.0)
    if confidence < min_confidence:
        return None

    action = str(model_result.get("action", "")).strip()
    allowed_actions = set(review_record.get("allowed_actions", []))
    if action not in allowed_actions:
        return None

    candidate_claim_ids = list(review_record.get("candidate_claim_ids", []))
    candidate_page_ids = list(review_record.get("candidate_page_ids", []))
    plan = dict(base_plan)
    plan.update({
        "decision": "auto_apply",
        "action": action,
        "reason": str(model_result.get("reason", "llm_auto_apply")).strip() or "llm_auto_apply",
        "confidence": confidence,
    })

    if action in {"merge", "archive_one"}:
        primary_claim_id = str(model_result.get("primary_claim_id", "")).strip()
        if primary_claim_id not in candidate_claim_ids:
            return None
        plan["primary_claim_id"] = primary_claim_id
        if action == "merge":
            secondary_claim_id = str(model_result.get("secondary_claim_id", "")).strip()
            if secondary_claim_id not in candidate_claim_ids or secondary_claim_id == primary_claim_id:
                ranked_primary = choose_auto_merge_primary_claim_id(candidate_claim_ids, live_claims_by_id)
                if ranked_primary is None:
                    return None
                primary_claim_id = ranked_primary
                secondary_claim_id = next(
                    claim_id for claim_id in candidate_claim_ids
                    if claim_id != primary_claim_id
                )
                plan["primary_claim_id"] = primary_claim_id
            plan["secondary_claim_id"] = secondary_claim_id
    elif action in {"assign_alias", "remove_alias"}:
        primary_page_id = str(model_result.get("primary_page_id", "")).strip()
        if primary_page_id not in candidate_page_ids:
            return None
        alias_value = str(model_result.get("alias_value", "")).strip()
        if not alias_value:
            evidence = review_record.get("evidence", [])
            alias_value = str(evidence[0].get("alias", "")).strip() if evidence else ""
        if not alias_value:
            return None
        plan["primary_page_id"] = primary_page_id
        plan["alias_value"] = alias_value
    return plan


def maybe_get_llm_assisted_review_plan(
    target: Path,
    review_record: dict,
    live_claims_by_id: dict[str, dict],
    automation_config: dict,
    base_plan: dict,
    *,
    build_review_auto_decision_payload: object,
    request_llm: object,
    run_deterministic_processor: object,
    normalize_review_auto_llm_plan: object,
) -> dict | None:
    if not automation_config.get("enabled"):
        return None

    payload = build_review_auto_decision_payload(
        review_record=review_record,
        live_claims_by_id=live_claims_by_id,
        target=target,
    )
    if automation_config.get("strategy") == "deterministic":
        model_result = run_deterministic_processor(payload)
    else:
        model_result = request_llm(
            workspace=target,
            task_name="review_auto_decision",
            payload=payload,
            timeout_seconds=automation_config.get("timeout_seconds"),
        )
    return normalize_review_auto_llm_plan(
        model_result=model_result,
        review_record=review_record,
        base_plan=base_plan,
        live_claims_by_id=live_claims_by_id,
        min_confidence=automation_config.get("min_confidence", 0.8),
    )


def claim_record_is_safe_auto_stable_candidate(
    claim_record: dict,
    live_reviews_by_id: dict[str, dict],
    *,
    is_actionable_review_record: object,
    clean_claim_candidate_text: object,
    claim_candidate_is_noise: object,
    claim_starts_with_dependent_prefix: object,
    text_is_question_like: object,
    claim_candidate_has_short_gray_zone: object,
    claim_can_stand_alone: object,
) -> tuple[bool, str | None]:
    if claim_record.get("lifecycle_status") != "active":
        return False, "claim_not_active"
    if claim_record.get("status") != "draft":
        return False, f"claim_status_is_{claim_record.get('status')}"
    if not claim_record.get("source_ids") or not claim_record.get("source_refs"):
        return False, "claim_missing_source_traceability"
    active_review_ids = [
        review_record["review_id"]
        for review_record in live_reviews_by_id.values()
        if is_actionable_review_record(review_record)
        and claim_record["claim_id"] in review_record.get("candidate_claim_ids", [])
    ]
    if active_review_ids:
        return False, "claim_still_attached_to_open_review"
    if claim_record.get("duplicate_candidates"):
        return False, "claim_still_has_duplicate_candidates"
    if claim_record.get("conflict_group"):
        return False, "claim_still_has_conflict_group"
    cleaned_text = clean_claim_candidate_text(claim_record.get("text", ""))
    if claim_candidate_is_noise(cleaned_text):
        return False, "claim_text_is_noise"
    if claim_starts_with_dependent_prefix(cleaned_text):
        return False, "claim_text_is_dependent_fragment"
    if text_is_question_like(cleaned_text):
        return False, "claim_text_is_question_like"
    quality_label = str(claim_record.get("quality_label") or "").strip().lower()
    if quality_label in {"noise", "fragment", "title_shell"}:
        return False, f"claim_quality_label_is_{quality_label}"
    if claim_candidate_has_short_gray_zone(cleaned_text):
        if claim_record.get("quality_safe_auto_ready") is True:
            return True, "semantic_quality_marked_short_claim_safe_auto_ready"
        return False, "short_claim_requires_semantic_quality_clearance"
    if not claim_can_stand_alone(cleaned_text) and claim_record.get("claim_type") != "definition":
        return False, "claim_text_not_standalone_enough"
    return True, None


def build_stable_promotion_payload(claim_record: dict) -> dict:
    return {
        "task": "claim_stable_promotion",
        "claim": {
            "claim_id": claim_record.get("claim_id"),
            "text": claim_record.get("text", ""),
            "status": claim_record.get("status"),
            "claim_type": claim_record.get("claim_type"),
            "source_ids": claim_record.get("source_ids", []),
            "source_refs": claim_record.get("source_refs", []),
            "duplicate_candidates": claim_record.get("duplicate_candidates", []),
            "conflict_group": claim_record.get("conflict_group"),
            "page_ids": claim_record.get("page_ids", []),
        },
    }


def maybe_get_llm_assisted_stable_promotion(
    target: Path,
    claim_record: dict,
    automation_config: dict,
    *,
    request_llm: object,
    run_deterministic_processor: object,
    build_stable_promotion_payload: object,
    coerce_float: object,
) -> tuple[bool, str | None]:
    if not automation_config.get("enabled"):
        return False, None

    payload = build_stable_promotion_payload(claim_record)
    if automation_config.get("strategy") == "deterministic":
        model_result = run_deterministic_processor(payload)
    else:
        model_result = request_llm(
            workspace=target,
            task_name="claim_stable_promotion",
            payload=payload,
            timeout_seconds=automation_config.get("timeout_seconds"),
        )
    decision = str(model_result.get("decision", "")).strip().lower()
    confidence = coerce_float(model_result.get("confidence", 0.0), 0.0)
    if decision != "promote" or confidence < automation_config.get("min_confidence", 0.8):
        return False, None
    reason = str(model_result.get("reason", "llm_promoted_to_stable")).strip() or "llm_promoted_to_stable"
    return True, reason


def propose_review_auto_action(
    target: Path,
    review_record: dict,
    live_claims_by_id: dict[str, dict],
    automation_config: dict,
    *,
    review_display_id: object,
    is_actionable_review_record: object,
    maybe_get_llm_assisted_review_plan: object,
    choose_auto_merge_primary_claim_id: object,
) -> dict:
    review_id = review_record["review_id"]
    kind = review_record.get("kind")
    recommended_action = review_record.get("recommended_action")
    allowed_actions = set(review_record.get("allowed_actions", []))

    plan = {
        "review_id": review_id,
        "display_id": review_display_id(review_record),
        "kind": kind,
        "recommended_action": recommended_action,
        "decision": "escalate",
        "reason": "review_requires_human_judgment",
        "action": None,
        "primary_claim_id": None,
        "secondary_claim_id": None,
        "primary_page_id": None,
        "alias_value": None,
        "confidence": None,
    }

    if not is_actionable_review_record(review_record):
        plan["reason"] = "review_not_actionable"
        return plan

    if kind == "alias_conflict":
        evidence = review_record.get("evidence", [])
        alias_value = evidence[0].get("alias") if evidence else None
        candidate_page_ids = list(review_record.get("candidate_page_ids", []))
        if (
            recommended_action == "remove_alias"
            and "remove_alias" in allowed_actions
            and alias_value
            and len(candidate_page_ids) >= 1
        ):
            plan.update({
                "decision": "auto_apply",
                "reason": "alias_conflict_can_safely_remove_shared_alias",
                "action": "remove_alias",
                "primary_page_id": candidate_page_ids[0],
                "alias_value": alias_value,
            })
            return plan
        if (
            recommended_action == "assign_alias"
            and "assign_alias" in allowed_actions
            and alias_value
            and len(candidate_page_ids) == 1
        ):
            plan.update({
                "decision": "auto_apply",
                "reason": "alias_conflict_has_single_candidate_owner",
                "action": "assign_alias",
                "primary_page_id": candidate_page_ids[0],
                "alias_value": alias_value,
            })
            return plan
        plan["reason"] = "alias_conflict_needs_human_owner_choice"
        agent_plan = maybe_get_llm_assisted_review_plan(
            target=target,
            review_record=review_record,
            live_claims_by_id=live_claims_by_id,
            automation_config=automation_config,
            base_plan=plan,
        )
        return agent_plan or plan

    if kind == "claim_duplicate" and recommended_action == "merge" and "merge" in allowed_actions:
        candidate_claim_ids = list(review_record.get("candidate_claim_ids", []))
        primary_claim_id = choose_auto_merge_primary_claim_id(candidate_claim_ids, live_claims_by_id)
        if primary_claim_id is None:
            plan["reason"] = "duplicate_review_needs_human_merge_choice"
            agent_plan = maybe_get_llm_assisted_review_plan(
                target=target,
                review_record=review_record,
                live_claims_by_id=live_claims_by_id,
                automation_config=automation_config,
                base_plan=plan,
            )
            return agent_plan or plan
        secondary_claim_id = next(
            claim_id for claim_id in candidate_claim_ids
            if claim_id != primary_claim_id
        )
        plan.update({
            "decision": "auto_apply",
            "reason": "duplicate_review_has_safe_two_claim_merge",
            "action": "merge",
            "primary_claim_id": primary_claim_id,
            "secondary_claim_id": secondary_claim_id,
        })
        return plan

    if kind == "claim_conflict":
        agent_plan = maybe_get_llm_assisted_review_plan(
            target=target,
            review_record=review_record,
            live_claims_by_id=live_claims_by_id,
            automation_config=automation_config,
            base_plan=plan,
        )
        return agent_plan or plan

    agent_plan = maybe_get_llm_assisted_review_plan(
        target=target,
        review_record=review_record,
        live_claims_by_id=live_claims_by_id,
        automation_config=automation_config,
        base_plan=plan,
    )
    if agent_plan is not None:
        return agent_plan
    plan["reason"] = "review_kind_or_action_not_in_safe_auto_rules"
    return plan


def build_review_auto_escalation_entry(
    review_record: dict,
    plan: dict,
    live_claims_by_id: dict[str, dict],
    *,
    review_display_id: object,
) -> dict:
    candidate_claims = []
    for claim_id in review_record.get("candidate_claim_ids", [])[:3]:
        claim_record = live_claims_by_id.get(claim_id)
        if claim_record is None:
            continue
        candidate_claims.append({
            "claim_id": claim_id,
            "text": claim_record.get("text", ""),
            "status": claim_record.get("status"),
            "source_count": len(claim_record.get("source_ids", [])),
        })

    choice_options = [
        {
            "action": action,
            "label": review_action_plain_label(action),
            "is_recommended": action == review_record.get("recommended_action"),
        }
        for action in review_record.get("allowed_actions", [])
    ]

    if review_record.get("kind") == "alias_conflict":
        evidence = review_record.get("evidence", [])
        alias_value = evidence[0].get("alias") if evidence else None
        issue_summary = (
            f"别名 `{alias_value}` 同时指向多个页面，当前还不能安全地自动决定归属。"
            if alias_value
            else "有一个别名同时指向多个页面，当前还不能安全地自动决定归属。"
        )
    elif review_record.get("kind") == "claim_duplicate":
        issue_summary = "这组 claim 可能在说同一件事，但当前仍需要人确认是否真的该合并。"
    else:
        issue_summary = "这条 review 超出了当前保守自动规则，需要人进一步判断。"

    if plan.get("reason") == "alias_conflict_needs_human_owner_choice":
        why_human_needed = "多个页面都可能拥有这个 alias，自动分配存在误伤风险。"
    elif plan.get("reason") == "duplicate_review_needs_human_merge_choice":
        why_human_needed = "候选 claim 不止两条，或主次关系不够明确，自动合并风险偏高。"
    else:
        why_human_needed = "当前证据还不足以支持保守自动裁决。"

    return {
        "review_id": review_record["review_id"],
        "display_id": review_display_id(review_record),
        "kind": review_record.get("kind"),
        "issue_summary": issue_summary,
        "why_human_needed": why_human_needed,
        "recommended_action": review_record.get("recommended_action"),
        "choice_options": choice_options,
        "candidate_claims": candidate_claims,
        "candidate_page_ids": review_record.get("candidate_page_ids", []),
        "suggested_user_prompt": (
            f"请帮我判断审核单 {review_display_id(review_record)}。"
            "如果你已经知道怎么处理，可以直接告诉我保留、合并、归档，或先手工修改再继续。"
        ),
    }


def build_review_auto_agent_handoff(
    auto_apply_plans: list[dict],
    escalated_entries: list[dict],
    promoted_claims: list[dict],
    review_automation_config: dict,
    stable_automation_config: dict,
) -> tuple[dict, str]:
    should_ask_user = bool(escalated_entries)
    next_action = (
        "ask_user_to_decide_escalated_reviews"
        if should_ask_user
        else "continue_with_normal_workflow"
    )
    agent_brief = {
        "mode": "needs_user_decision" if should_ask_user else "auto_resolved_all_safe_reviews",
        "should_ask_user": should_ask_user,
        "next_action": next_action,
        "auto_apply_review_count": len(auto_apply_plans),
        "escalated_review_count": len(escalated_entries),
        "promoted_claim_count": len(promoted_claims),
        "review_auto_strategy": review_automation_config.get("strategy"),
        "stable_promotion_strategy": stable_automation_config.get("strategy"),
    }
    if should_ask_user:
        first_item = escalated_entries[0]
        agent_summary = (
            f"已自动处理 {len(auto_apply_plans)} 条高把握 review"
            f"（review_auto={review_automation_config.get('strategy')}），"
            f"但还有 {len(escalated_entries)} 条需要用户判断。"
            f"优先向用户解释 `{first_item['display_id']}`：{first_item['issue_summary']}"
        )
    else:
        agent_summary = (
            f"本轮高把握 review 已全部自动收口，共处理 {len(auto_apply_plans)} 条，"
            f"并额外提升了 {len(promoted_claims)} 条 claim 为 stable"
            f"（stable_promotion={stable_automation_config.get('strategy')}）。"
        )
    return agent_brief, agent_summary


def render_review_auto_message(review_auto_payload: dict) -> str:
    lines = [
        "Review Auto Summary:",
        f"  dry_run: {review_auto_payload.get('dry_run')}",
        (
            "  counts: "
            f"planned={review_auto_payload['summary']['planned_review_count']}, "
            f"auto_apply={review_auto_payload['summary']['auto_apply_count']}, "
            f"escalated={review_auto_payload['summary']['escalated_count']}, "
            f"applied={review_auto_payload['summary']['applied_count']}, "
            f"promoted_claims={review_auto_payload['summary']['promoted_claim_count']}"
        ),
        f"  next_action: {review_auto_payload.get('agent_brief', {}).get('next_action')}",
        f"  agent_summary: {review_auto_payload.get('agent_summary', '')}",
    ]
    applied_actions = review_auto_payload.get("applied_actions", [])
    if applied_actions:
        lines.append("  applied_actions:")
        for item in applied_actions[:5]:
            lines.append(
                f"    - {item.get('display_id')} [{item.get('kind')}] action={item.get('action')} reason={item.get('reason')}"
            )
    escalations = review_auto_payload.get("escalation_handoff", [])
    if escalations:
        lines.append("  escalations:")
        for item in escalations[:5]:
            lines.append(
                f"    - {item.get('display_id')} [{item.get('kind')}] {item.get('issue_summary')}"
            )
            lines.append(f"      why_human_needed: {item.get('why_human_needed')}")
    return "\n".join(lines)


def render_review_auto_prompt(review_auto_payload: dict) -> str:
    agent_brief = review_auto_payload.get("agent_brief", {})
    lines = [
        "You are the workflow layer for a MyAgentWiki review-auto handoff.",
        "Use the handoff below to decide whether to continue automatically or ask the user for a focused review decision.",
        "Do not invent review outcomes that are not supported by the handoff.",
        "",
        "## Review Auto Run",
        f"- contract_version: {review_auto_payload.get('contract_version', '')}",
        f"- dry_run: {review_auto_payload.get('dry_run')}",
        f"- workspace: {review_auto_payload.get('workspace', '')}",
        f"- planned_review_count: {review_auto_payload.get('summary', {}).get('planned_review_count')}",
        f"- auto_apply_count: {review_auto_payload.get('summary', {}).get('auto_apply_count')}",
        f"- escalated_count: {review_auto_payload.get('summary', {}).get('escalated_count')}",
        f"- applied_count: {review_auto_payload.get('summary', {}).get('applied_count')}",
        f"- promoted_claim_count: {review_auto_payload.get('summary', {}).get('promoted_claim_count')}",
        "",
        "## Agent Brief",
        f"- mode: {agent_brief.get('mode')}",
        f"- should_ask_user: {agent_brief.get('should_ask_user')}",
        f"- next_action: {agent_brief.get('next_action')}",
        f"- agent_summary: {review_auto_payload.get('agent_summary', '')}",
        "",
        "## Applied Actions",
    ]
    applied_actions = review_auto_payload.get("applied_actions", [])
    if applied_actions:
        for item in applied_actions:
            lines.append(
                f"- {item.get('display_id')}: kind={item.get('kind')} action={item.get('action')} "
                f"reason={item.get('reason')} changed_claim_ids={','.join(item.get('changed_claim_ids', [])) or 'none'} "
                f"changed_page_ids={','.join(item.get('changed_page_ids', [])) or 'none'}"
            )
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Escalations",
    ])
    escalations = review_auto_payload.get("escalation_handoff", [])
    if escalations:
        for item in escalations:
            lines.append(
                f"- {item.get('display_id')}: kind={item.get('kind')} issue={item.get('issue_summary')} "
                f"why_human_needed={item.get('why_human_needed')} recommended_action={item.get('recommended_action')}"
            )
            if item.get("candidate_claims"):
                for claim in item["candidate_claims"]:
                    lines.append(
                        f"  candidate_claim: {claim.get('claim_id')} status={claim.get('status')} "
                        f"sources={claim.get('source_count')} text={claim.get('text')}"
                    )
            if item.get("candidate_page_ids"):
                lines.append(f"  candidate_page_ids: {', '.join(item['candidate_page_ids'])}")
            if item.get("choice_options"):
                for option in item["choice_options"]:
                    lines.append(
                        f"  option: action={option.get('action')} label={option.get('label')} "
                        f"recommended={option.get('is_recommended')}"
                    )
            lines.append(f"  suggested_user_prompt: {item.get('suggested_user_prompt')}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Instruction",
        "If `should_ask_user` is false, continue the broader workflow without asking the user to re-judge already resolved reviews.",
        "If `should_ask_user` is true, ask only about the escalated reviews and explain the options in plain language.",
        "Prefer the recommended action when presenting options, but make uncertainty explicit when the handoff says human judgment is needed.",
    ])
    return "\n".join(lines)


def build_review_auto_messages(review_auto_payload: dict) -> list[dict]:
    prompt_text = render_review_auto_prompt(review_auto_payload)
    return [
        {
            "role": "system",
            "content": (
                "You are the workflow layer for a MyAgentWiki review-auto handoff. "
                "Continue automatically when the handoff says it is safe, and ask the user only for escalated decisions."
            ),
        },
        {
            "role": "user",
            "content": prompt_text,
        },
    ]


def render_review_auto_chatml(review_auto_payload: dict) -> str:
    messages = build_review_auto_messages(review_auto_payload)
    blocks = []
    for message in messages:
        blocks.append(f"<|im_start|>{message['role']}\n{message['content']}\n<|im_end|>")
    return "\n".join(blocks)
