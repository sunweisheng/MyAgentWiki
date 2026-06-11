from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path | None = None) -> dict:
    command = [sys.executable, "-m", "myagentwiki.cli", *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def write_jsonl(path: Path, records: list[dict]) -> None:
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def inject_shared_alias_override(workspace_dir: Path, shared_alias: str) -> list[str]:
    live_pages = [
        record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if not record.get("removed")
        and record.get("lifecycle_status", "active") == "active"
        and record.get("type") == "concept"
    ]
    page_ids = [record["page_id"] for record in live_pages[:2]]
    assert len(page_ids) >= 2

    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = {"page_aliases": {}}
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    page_aliases = overrides.setdefault("page_aliases", {})
    live_page_map = {record["page_id"]: record for record in live_pages}

    for page_id in page_ids:
        page_record = live_page_map[page_id]
        page_override = page_aliases.setdefault(page_id, {})
        aliases = sorted(set(page_override.get("aliases", page_record.get("aliases", []))))
        if shared_alias not in aliases:
            aliases.append(shared_alias)
        page_override["aliases"] = sorted(set(aliases))

    overrides_path.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return page_ids


def append_text(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def create_workspace(tmp_path: Path, project_name: str, files: dict[str, str]) -> Path:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    for relative_path, text in files.items():
        file_path = source_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text, encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", project_name,
        "--target-dir", str(workspace_dir),
    )
    config_path = workspace_dir / "config" / "project.yml"
    config_text = config_path.read_text(encoding="utf-8")
    config_text = config_text.replace("  post_ingest:\n    review_auto: true\n", "  post_ingest:\n    review_auto: false\n")
    config_path.write_text(config_text, encoding="utf-8")
    run_cli("ingest", "--target-dir", str(workspace_dir))
    return workspace_dir


def test_review_auto_dry_run_reports_safe_merge_without_mutation(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoDryRun",
        {
            "topic.md": (
                "# 主题\n\n"
                "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
                "知识声明层用于承载可追踪、可合并、可审计的结论。\n"
            ),
        },
    )

    claims_path = workspace_dir / "state" / "claims.jsonl"
    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    claim_records = load_jsonl(claims_path)
    assert len(claim_records) >= 2
    first_claim_id = claim_records[0]["claim_id"]
    second_claim_id = claim_records[1]["claim_id"]

    claim_by_id = {record["claim_id"]: record for record in claim_records}
    for claim_id in (first_claim_id, second_claim_id):
        claim_by_id[claim_id]["status"] = "needs_review"
        claim_by_id[claim_id]["duplicate_candidates"] = [
            other_id for other_id in (first_claim_id, second_claim_id) if other_id != claim_id
        ]
        claim_by_id[claim_id]["review_reason"] = "possible_duplicate_claim"
    write_jsonl(claims_path, list(claim_by_id.values()))
    for claim_record in claim_by_id.values():
        write_json(workspace_dir / "claims" / f"{claim_record['claim_id']}.json", claim_record)

    review_record = {
        "review_id": "rev_auto_merge",
        "kind": "claim_duplicate",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [first_claim_id, second_claim_id],
        "candidate_page_ids": [],
        "reason": "safe duplicate",
        "recommended_action": "merge",
        "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-06-01T00:00:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_auto_merge.json",
    }
    write_jsonl(reviews_path, [review_record])
    write_json(workspace_dir / "reviews" / "rev_auto_merge.json", review_record)

    result = run_cli("review-auto", "--target-dir", str(workspace_dir), "--dry-run")

    assert result["dry_run"] is True
    assert result["summary"]["auto_apply_count"] == 1
    assert result["summary"]["applied_count"] == 0
    assert result["planned_actions"][0]["action"] == "merge"
    assert result["agent_brief"]["should_ask_user"] is False
    assert result["agent_brief"]["next_action"] == "continue_with_normal_workflow"

    refreshed_reviews = load_jsonl(reviews_path)
    assert refreshed_reviews[0]["status"] == "open"
    refreshed_claims = load_jsonl(claims_path)
    assert len(refreshed_claims) == len(claim_records)


def test_review_auto_prompt_format_returns_agent_handoff_prompt(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoPrompt",
        {
            "claim.md": "# Claim\n\nClaim 是位于 chunk 与 wiki 之间的独立知识声明层。\n",
            "chunk.md": "# Chunk\n\nChunk 是用于承载局部原文切片的证据单元。\n",
        },
    )

    inject_shared_alias_override(workspace_dir, "知识层")

    result = run_cli("review-auto", "--target-dir", str(workspace_dir), "--format", "prompt")

    assert result["contract_version"] == "review_auto_handoff/v1"
    assert "prompt_text" in result
    assert "## Review Auto Run" in result["prompt_text"]
    assert "## Escalations" in result["prompt_text"]
    assert "choice_options" in result["prompt_text"] or "suggested_user_prompt" in result["prompt_text"]


def test_review_auto_messages_and_chatml_formats_return_agent_ready_payloads(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoMessages",
        {
            "claim.md": "# Claim\n\nClaim 是位于 chunk 与 wiki 之间的独立知识声明层。\n",
            "chunk.md": "# Chunk\n\nChunk 是用于承载局部原文切片的证据单元。\n",
        },
    )

    inject_shared_alias_override(workspace_dir, "知识层")

    messages_result = run_cli("review-auto", "--target-dir", str(workspace_dir), "--format", "messages")
    assert messages_result["contract_version"] == "review_auto_handoff/v1"
    assert "messages" in messages_result
    assert len(messages_result["messages"]) == 2
    assert messages_result["messages"][0]["role"] == "system"
    assert "review-auto handoff" in messages_result["messages"][1]["content"]

    chatml_result = run_cli("review-auto", "--target-dir", str(workspace_dir), "--format", "chatml")
    assert chatml_result["contract_version"] == "review_auto_handoff/v1"
    assert "messages" in chatml_result
    assert "chatml_text" in chatml_result
    assert "<|im_start|>system" in chatml_result["chatml_text"]


def test_review_auto_applies_safe_merge_and_promotes_winner_to_stable(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoApply",
        {
            "a.md": "# Alpha\n\nAlpha 是一种适合长期维护的知识沉淀方式。\n",
            "b.md": "# Alpha补充\n\nAlpha 适合持续维护，并支持知识沉淀的长期积累。\n",
        },
    )

    claims_path = workspace_dir / "state" / "claims.jsonl"
    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    claim_records = load_jsonl(claims_path)
    assert len(claim_records) >= 2

    primary_claim_id = claim_records[0]["claim_id"]
    secondary_claim_id = claim_records[1]["claim_id"]

    claim_by_id = {record["claim_id"]: record for record in claim_records}
    for claim_id in (primary_claim_id, secondary_claim_id):
        claim_by_id[claim_id]["status"] = "needs_review"
        claim_by_id[claim_id]["duplicate_candidates"] = [
            other_id for other_id in (primary_claim_id, secondary_claim_id) if other_id != claim_id
        ]
        claim_by_id[claim_id]["review_reason"] = "possible_duplicate_claim"
    write_jsonl(claims_path, list(claim_by_id.values()))
    for claim_record in claim_by_id.values():
        write_json(workspace_dir / "claims" / f"{claim_record['claim_id']}.json", claim_record)

    review_record = {
        "review_id": "rev_auto_apply_merge",
        "kind": "claim_duplicate",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [primary_claim_id, secondary_claim_id],
        "candidate_page_ids": [],
        "reason": "safe duplicate",
        "recommended_action": "merge",
        "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-06-01T00:00:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_auto_apply_merge.json",
    }
    write_jsonl(reviews_path, [review_record])
    write_json(workspace_dir / "reviews" / "rev_auto_apply_merge.json", review_record)

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["dry_run"] is False
    assert result["summary"]["applied_count"] == 1
    assert result["applied_actions"][0]["action"] == "merge"
    assert result["summary"]["promoted_claim_count"] >= 1
    assert result["agent_brief"]["should_ask_user"] is False
    all_claim_records = load_jsonl(claims_path)
    active_claims = [record for record in all_claim_records if record.get("lifecycle_status") == "active"]
    historical_claims = [record for record in all_claim_records if record.get("lifecycle_status") != "active"]
    surviving_claim_ids = {record["claim_id"] for record in active_claims}
    assert len(active_claims) == len(claim_records) - 1
    assert historical_claims
    promoted_claim_ids = {item["claim_id"] for item in result["promoted_claims"]}
    surviving_promoted_ids = surviving_claim_ids & promoted_claim_ids
    assert surviving_promoted_ids


def test_review_auto_escalates_migration_followup_review(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoMigrationFollowup",
        {
            "topic.md": "# Topic\n\n知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        },
    )

    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    review_record = {
        "review_id": "rev_migrate_followup_chunk",
        "kind": "migration_followup",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [],
        "candidate_page_ids": [],
        "reason": "migration_followup:create_current_successor_required",
        "recommended_action": "edit_then_resume",
        "allowed_actions": ["keep_both", "edit_then_resume"],
        "resume_from": "migration_followup",
        "evidence": [
            {
                "canonical_id": "concept:chunk",
                "queue_action": "create_current_successor_required",
                "reason": "Need a current successor.",
                "confidence": 0.93,
            }
        ],
        "migration_followup": {
            "canonical_id": "concept:chunk",
            "queue_action": "create_current_successor_required",
            "status": "pending",
            "migration_class": "legacy_concept_summary_missing_current_successor",
        },
        "created_at": "2026-06-01T00:00:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_migrate_followup_chunk.json",
    }
    write_jsonl(reviews_path, [review_record])
    write_json(workspace_dir / "reviews" / "rev_migrate_followup_chunk.json", review_record)

    result = run_cli("review-auto", "--target-dir", str(workspace_dir), "--dry-run")

    assert result["summary"]["auto_apply_count"] == 0
    assert result["summary"]["escalated_count"] == 1
    assert result["agent_brief"]["should_ask_user"] is True
    escalation = result["escalation_handoff"][0]
    assert escalation["kind"] == "migration_followup"
    assert escalation["migration_followup"]["canonical_id"] == "concept:chunk"
    assert "迁移后续项" in escalation["issue_summary"]


def test_review_auto_agent_assisted_hook_can_resolve_claim_conflict(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoAgentHook",
        {
            "a.md": "# A\n\nChunking 不是最终知识成品。\n",
            "b.md": "# B\n\nChunking 是最终知识成品。\n",
        },
    )

    claims_path = workspace_dir / "state" / "claims.jsonl"
    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    claim_records = load_jsonl(claims_path)
    assert len(claim_records) >= 2
    first_claim_id = claim_records[0]["claim_id"]
    second_claim_id = claim_records[1]["claim_id"]

    review_record = {
        "review_id": "rev_agent_hook_conflict",
        "kind": "claim_conflict",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [first_claim_id, second_claim_id],
        "candidate_page_ids": [],
        "reason": "conflicting pair",
        "recommended_action": "archive_one",
        "allowed_actions": ["keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-06-01T00:00:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_agent_hook_conflict.json",
    }
    write_jsonl(reviews_path, [review_record])
    write_json(workspace_dir / "reviews" / "rev_agent_hook_conflict.json", review_record)

    hook_script = tmp_path / "review_hook.py"
    hook_script.write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "claim_ids = payload['review']['candidate_claim_ids']\n"
        "json.dump({\n"
        "  'decision': 'auto_apply',\n"
        "  'action': 'archive_one',\n"
        "  'primary_claim_id': claim_ids[1],\n"
        "  'confidence': 0.97,\n"
        "  'reason': 'agent_hook_archives_weaker_conflict_claim'\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )

    append_text(
        workspace_dir / "config" / "project.yml",
        "\n"
        + "automation:\n"
        + "  review_auto:\n"
        + '    strategy: "agent_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{hook_script}"\n'
        + "    timeout_seconds: 20\n"
        + "    min_confidence: 0.9\n",
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_count"] == 1
    assert result["applied_actions"][0]["action"] == "archive_one"
    assert result["applied_actions"][0]["reason"] == "agent_hook_archives_weaker_conflict_claim"
    assert result["automation"]["review_auto"]["strategy"] == "agent_assisted"
    refreshed_reviews = {record["review_id"]: record for record in load_jsonl(reviews_path)}
    assert refreshed_reviews["rev_agent_hook_conflict"]["status"] == "resolved"


def test_review_auto_agent_assisted_hook_archives_contained_conflict_claim(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoContainedConflict",
        {
            "topic.md": (
                "# Topic\n\n"
                "大多数人与 LLM 和文档的交互方式类似于 RAG：你上传一组文件，"
                "LLM 在查询时检索相关片段，然后生成答案。这能工作，但 LLM 在每个问题上都得从头重新发现知识。\n"
                "但 LLM 在每个问题上都得从头重新发现知识。\n"
            ),
        },
    )

    claims_path = workspace_dir / "state" / "claims.jsonl"
    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    claim_records = load_jsonl(claims_path)

    long_claim = next(record for record in claim_records if "上传一组文件" in record["text"])
    short_claim = next(record for record in claim_records if record["text"] == "但 LLM 在每个问题上都得从头重新发现知识")

    for record in claim_records:
        if record["claim_id"] == long_claim["claim_id"]:
            record["status"] = "stable"
        elif record["claim_id"] == short_claim["claim_id"]:
            record["status"] = "needs_review"
            record["conflict_group"] = "cfg_contained"
            record["review_reason"] = "conflicting_claims_detected"
    write_jsonl(claims_path, claim_records)
    for claim_record in claim_records:
        write_json(workspace_dir / "claims" / f"{claim_record['claim_id']}.json", claim_record)

    review_record = {
        "review_id": "rev_agent_hook_contained_conflict",
        "kind": "claim_conflict",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [long_claim["claim_id"], short_claim["claim_id"]],
        "candidate_page_ids": [],
        "reason": "conflicting pair",
        "recommended_action": "keep_both",
        "allowed_actions": ["keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-06-01T00:00:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_agent_hook_contained_conflict.json",
    }
    write_jsonl(reviews_path, [review_record])
    write_json(workspace_dir / "reviews" / "rev_agent_hook_contained_conflict.json", review_record)

    append_text(
        workspace_dir / "config" / "project.yml",
        "\n"
        + "automation:\n"
        + "  review_auto:\n"
        + '    strategy: "agent_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{REPO_ROOT / "scripts" / "agent_assisted_review_hook.py"}"\n'
        + "    timeout_seconds: 20\n"
        + "    min_confidence: 0.9\n",
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_count"] == 1
    assert result["applied_actions"][0]["action"] == "archive_one"
    assert result["applied_actions"][0]["reason"] == "agent_hook_archived_fragmentary_conflict_claim"
    refreshed_reviews = {record["review_id"]: record for record in load_jsonl(reviews_path)}
    assert refreshed_reviews["rev_agent_hook_contained_conflict"]["status"] == "resolved"


def test_review_auto_agent_assisted_hook_can_keep_both_distinct_question_claims(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoQuestionConflict",
        {
            "topic.md": "# Topic\n\n为什么 LLM-Wiki 不等于没有检索。\n为什么 LLM-Wiki 必须重视 Chunking。\n",
        },
    )

    claims_path = workspace_dir / "state" / "claims.jsonl"
    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    claim_records = load_jsonl(claims_path)
    assert len(claim_records) >= 2
    first_claim_id = claim_records[0]["claim_id"]
    second_claim_id = claim_records[1]["claim_id"]

    for record in claim_records:
        if record["claim_id"] in {first_claim_id, second_claim_id}:
            record["status"] = "needs_review"
            record["conflict_group"] = "cfg_question_conflict"
            record["review_reason"] = "conflicting_claims_detected"
    write_jsonl(claims_path, claim_records)
    for claim_record in claim_records:
        write_json(workspace_dir / "claims" / f"{claim_record['claim_id']}.json", claim_record)

    review_record = {
        "review_id": "rev_agent_hook_question_conflict",
        "kind": "claim_conflict",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [first_claim_id, second_claim_id],
        "candidate_page_ids": [],
        "reason": "question pair",
        "recommended_action": "keep_both",
        "allowed_actions": ["keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-06-01T00:00:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_agent_hook_question_conflict.json",
    }
    write_jsonl(reviews_path, [review_record])
    write_json(workspace_dir / "reviews" / "rev_agent_hook_question_conflict.json", review_record)

    append_text(
        workspace_dir / "config" / "project.yml",
        "\n"
        + "automation:\n"
        + "  review_auto:\n"
        + '    strategy: "agent_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{REPO_ROOT / "scripts" / "agent_assisted_review_hook.py"}"\n'
        + "    timeout_seconds: 20\n"
        + "    min_confidence: 0.9\n",
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_count"] == 1
    assert result["applied_actions"][0]["action"] == "keep_both"
    assert result["applied_actions"][0]["reason"] == "agent_hook_kept_distinct_question_claims"
    refreshed_reviews = {record["review_id"]: record for record in load_jsonl(reviews_path)}
    assert refreshed_reviews["rev_agent_hook_question_conflict"]["status"] == "resolved"


def test_review_auto_agent_assisted_hook_can_promote_claim_to_stable(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoStableHook",
        {
            "topic.md": "# Topic\n\n为什么知识声明层必须保留可追踪性？\n",
        },
    )

    promotion_script = tmp_path / "stable_hook.py"
    promotion_script.write_text(
        "import json, sys\n"
        "_payload = json.load(sys.stdin)\n"
        "json.dump({\n"
        "  'decision': 'promote',\n"
        "  'confidence': 0.96,\n"
        "  'reason': 'agent_hook_promoted_single_source_claim'\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )

    append_text(
        workspace_dir / "config" / "project.yml",
        "\n"
        + "automation:\n"
        + "  stable_promotion:\n"
        + '    strategy: "agent_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{promotion_script}"\n'
        + "    timeout_seconds: 20\n"
        + "    min_confidence: 0.9\n",
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["promoted_claim_count"] >= 1
    assert result["automation"]["stable_promotion"]["strategy"] == "agent_assisted"
    reasons = {item["reason"] for item in result["promoted_claims"]}
    assert "agent_hook_promoted_single_source_claim" in reasons
    refreshed_claims = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    assert any(record.get("status") == "stable" for record in refreshed_claims)


def test_review_auto_safe_auto_uses_semantic_quality_for_short_claim(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoSemanticShortClaim",
        {
            "topic.md": "# Topic\n\n保留回链。\n",
        },
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["promoted_claim_count"] >= 1
    reasons = {item["reason"] for item in result["promoted_claims"]}
    assert "semantic_quality_marked_short_claim_safe_auto_ready" in reasons
    refreshed_claims = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    assert any(
        record.get("text") == "保留回链"
        and record.get("status") == "stable"
        and record.get("quality_safe_auto_ready") is True
        for record in refreshed_claims
    )


def test_review_auto_recomputes_plan_after_each_merge(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoReplan",
        {
            "topic.md": "# Topic\n\nChunking 是知识切块流程。\n",
        },
    )

    claims_path = workspace_dir / "state" / "claims.jsonl"
    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    claim_records = load_jsonl(claims_path)
    claim_by_id = {record["claim_id"]: record for record in claim_records}
    base_record = claim_records[0]
    synthetic_records = []
    selected_ids = []
    for suffix, text in [
        ("a11111111111", "Chunking: concept_chunking"),
        ("b22222222222", "切块: concept_chunking"),
        ("c33333333333", "文档切片: concept_chunking"),
    ]:
        record = dict(base_record)
        record["claim_id"] = f"clm_chain_{suffix}"
        record["text"] = text
        record["normalized_text"] = text.lower()
        record["status"] = "needs_review"
        record["review_reason"] = "possible_duplicate_claim"
        record["duplicate_candidates"] = []
        record["page_ids"] = []
        record["claim_file_path"] = f"claims/{record['claim_id']}.json"
        synthetic_records.append(record)
        selected_ids.append(record["claim_id"])

    for record in synthetic_records:
        record["duplicate_candidates"] = [item for item in selected_ids if item != record["claim_id"]]
        claim_by_id[record["claim_id"]] = record

    for claim_id in selected_ids:
        claim_by_id[claim_id]["status"] = "needs_review"
        claim_by_id[claim_id]["review_reason"] = "possible_duplicate_claim"
        claim_by_id[claim_id]["duplicate_candidates"] = [item for item in selected_ids if item != claim_id]
    write_jsonl(claims_path, list(claim_by_id.values()))
    for claim_record in claim_by_id.values():
        write_json(workspace_dir / "claims" / f"{claim_record['claim_id']}.json", claim_record)

    review_records = [
        {
            "review_id": "rev_chain_first",
            "kind": "claim_duplicate",
            "status": "open",
            "lifecycle_status": "active",
            "candidate_claim_ids": [selected_ids[0], selected_ids[1]],
            "candidate_page_ids": [],
            "reason": "first duplicate pair",
            "recommended_action": "merge",
            "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
            "resume_from": "claim_review",
            "evidence": [],
            "created_at": "2026-06-01T00:00:00+00:00",
            "resolved_at": None,
            "archived_at": None,
            "review_file_path": "reviews/rev_chain_first.json",
        },
        {
            "review_id": "rev_chain_second",
            "kind": "claim_duplicate",
            "status": "open",
            "lifecycle_status": "active",
            "candidate_claim_ids": [selected_ids[1], selected_ids[2]],
            "candidate_page_ids": [],
            "reason": "second duplicate pair",
            "recommended_action": "merge",
            "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
            "resume_from": "claim_review",
            "evidence": [],
            "created_at": "2026-06-01T00:00:01+00:00",
            "resolved_at": None,
            "archived_at": None,
            "review_file_path": "reviews/rev_chain_second.json",
        },
    ]
    write_jsonl(reviews_path, review_records)
    for review_record in review_records:
        write_json(workspace_dir / "reviews" / f"{review_record['review_id']}.json", review_record)

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_count"] >= 2
    refreshed_reviews = {record["review_id"]: record for record in load_jsonl(reviews_path)}
    assert refreshed_reviews["rev_chain_first"]["status"] == "resolved"
    assert refreshed_reviews["rev_chain_second"]["status"] == "resolved"


def test_review_auto_escalates_ambiguous_alias_conflict(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoEscalate",
        {
            "claim.md": "# Claim\n\nClaim 是位于 chunk 与 wiki 之间的独立知识声明层。\n",
            "chunk.md": "# Chunk\n\nChunk 是用于承载局部原文切片的证据单元。\n",
        },
    )

    inject_shared_alias_override(workspace_dir, "知识层")

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["auto_apply_count"] == 0
    assert result["summary"]["escalated_count"] == 1
    assert result["escalated_reviews"][0]["kind"] == "alias_conflict"
    assert result["escalated_reviews"][0]["reason"] == "alias_conflict_needs_human_owner_choice"
    assert result["agent_brief"]["should_ask_user"] is True
    assert result["agent_brief"]["next_action"] == "ask_user_to_decide_escalated_reviews"
    assert result["escalation_handoff"][0]["kind"] == "alias_conflict"
    assert result["escalation_handoff"][0]["choice_options"]
    assert "issue_summary" in result["escalation_handoff"][0]

    refreshed_reviews = load_jsonl(workspace_dir / "state" / "reviews.jsonl")
    alias_reviews = [record for record in refreshed_reviews if record.get("kind") == "alias_conflict"]
    assert alias_reviews
    assert alias_reviews[0]["status"] == "open"


def test_review_auto_agent_assisted_hook_can_assign_noisy_alias_to_unique_title_owner(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoAliasOwner",
        {
            "alpha.md": "# Alpha\n\nAlpha 是概念一。\n",
            "beta.md": "# Beta\n\nBeta 是概念二。\n",
        },
    )

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_pages = [record for record in page_records if record.get("type") == "concept"][:2]
    assert len(concept_pages) == 2
    concept_pages[0]["title"] = "一句话总结"
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + ["一句话总结"]))
    write_jsonl(pages_path, page_records)

    run_cli("ingest", "--target-dir", str(workspace_dir))

    append_text(
        workspace_dir / "config" / "project.yml",
        "\n"
        + "automation:\n"
        + "  review_auto:\n"
        + '    strategy: "agent_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{REPO_ROOT / "scripts" / "agent_assisted_review_hook.py"}"\n'
        + "    timeout_seconds: 20\n"
        + "    min_confidence: 0.9\n",
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_count"] >= 1
    applied_reasons = {item["reason"] for item in result["applied_actions"]}
    assert "agent_hook_assigned_noisy_alias_to_title_owner" in applied_reasons
    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_review_auto_agent_assisted_hook_can_assign_non_noisy_alias_to_unique_title_owner(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoSpecificAliasOwner",
        {
            "alpha.md": "# Alpha\n\nAlpha 是规划信息的概念。\n",
            "beta.md": "# Beta\n\nBeta 是另一个概念。\n",
        },
    )

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_pages = [record for record in page_records if record.get("type") == "concept"][:2]
    assert len(concept_pages) == 2
    concept_pages[0]["title"] = "路线图"
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + ["路线图"]))
    write_jsonl(pages_path, page_records)

    run_cli("ingest", "--target-dir", str(workspace_dir))

    append_text(
        workspace_dir / "config" / "project.yml",
        "\n"
        + "automation:\n"
        + "  review_auto:\n"
        + '    strategy: "agent_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{REPO_ROOT / "scripts" / "agent_assisted_review_hook.py"}"\n'
        + "    timeout_seconds: 20\n"
        + "    min_confidence: 0.9\n",
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_count"] >= 1
    applied_reasons = {item["reason"] for item in result["applied_actions"]}
    assert "agent_hook_assigned_alias_to_unique_title_owner" in applied_reasons
    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_review_auto_agent_assisted_hook_can_keep_both_generated_image_aliases(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoImageAliasKeepBoth",
        {
            "alpha.md": "# Alpha\n\nAlpha 是概念一。\n",
            "beta.md": "# Beta\n\nBeta 是概念二。\n",
        },
    )

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_pages = [record for record in page_records if record.get("type") == "concept"][:2]
    assert len(concept_pages) == 2
    shared_alias = "image_x"
    for record in page_records:
        if record.get("page_id") in {concept_pages[0]["page_id"], concept_pages[1]["page_id"]}:
            record["aliases"] = sorted(set(record.get("aliases", []) + [shared_alias]))
    write_jsonl(pages_path, page_records)

    run_cli("ingest", "--target-dir", str(workspace_dir))

    append_text(
        workspace_dir / "config" / "project.yml",
        "\n"
        + "automation:\n"
        + "  review_auto:\n"
        + '    strategy: "agent_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{REPO_ROOT / "scripts" / "agent_assisted_review_hook.py"}"\n'
        + "    timeout_seconds: 20\n"
        + "    min_confidence: 0.9\n",
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_count"] >= 1
    applied_reasons = {item["reason"] for item in result["applied_actions"]}
    assert "agent_hook_kept_generated_image_aliases_distinct" in applied_reasons
    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_review_auto_downgrades_invalid_alias_auto_apply_to_escalation(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoAliasValidationFallback",
        {
            "topic.md": "# Topic\n\n知识声明层 是一个概念。\n",
            "guide.md": "# Guide\n\n证据切块层 是另一个概念。\n",
        },
    )

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    candidate_pages = [
        record for record in page_records
        if not record.get("removed")
        and record.get("lifecycle_status", "active") == "active"
        and record.get("type") != "source-summary"
    ]
    distinct_pages: list[dict] = []
    seen_canonical_ids: set[str] = set()
    for record in candidate_pages:
        canonical_id = record.get("canonical_id") or record.get("page_id")
        if canonical_id in seen_canonical_ids:
            continue
        seen_canonical_ids.add(canonical_id)
        distinct_pages.append(record)
        if len(distinct_pages) == 2:
            break
    assert len(distinct_pages) == 2
    shared_alias = "知识层"
    for record in page_records:
        if record.get("page_id") in {distinct_pages[0]["page_id"], distinct_pages[1]["page_id"]}:
            record["aliases"] = sorted(set(record.get("aliases", []) + [shared_alias]))
            record["title"] = shared_alias
    write_jsonl(pages_path, page_records)

    run_cli("ingest", "--target-dir", str(workspace_dir))

    hook_script = tmp_path / "alias_hook.py"
    hook_script.write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "review = payload.get('review', {})\n"
        "page_ids = review.get('candidate_page_ids', [])\n"
        "json.dump({\n"
        "  'decision': 'auto_apply',\n"
        "  'action': 'assign_alias',\n"
        "  'primary_page_id': page_ids[0] if page_ids else '',\n"
        "  'alias_value': payload.get('alias_conflict_context', {}).get('alias_value', ''),\n"
        "  'confidence': 0.99,\n"
        "  'reason': 'agent_hook_forced_invalid_alias_assignment'\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )

    append_text(
        workspace_dir / "config" / "project.yml",
        "\n"
        + "automation:\n"
        + "  review_auto:\n"
        + '    strategy: "agent_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{hook_script}"\n'
        + "    timeout_seconds: 20\n"
        + "    min_confidence: 0.9\n",
    )

    result = run_cli("review-auto", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_count"] == 0
    assert result["summary"]["auto_apply_failure_count"] == 1
    assert result["summary"]["escalated_count"] == 0
    assert result["auto_apply_failures"][0]["reason"] == "auto_apply_failed_validation"
    assert "validation_error" in result["auto_apply_failures"][0]
