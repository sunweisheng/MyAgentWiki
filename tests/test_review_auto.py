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

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_page_ids = [record["page_id"] for record in page_records if record.get("type") == "concept-summary"][:2]
    for record in page_records:
        if record.get("page_id") in concept_page_ids:
            record["aliases"] = sorted(set(record.get("aliases", []) + ["知识层"]))
    write_jsonl(pages_path, page_records)

    result = run_cli("review-auto", "--target-dir", str(workspace_dir), "--format", "prompt")

    assert result["contract_version"] == "review_auto_handoff/v1"
    assert "prompt_text" in result
    assert "## Review Auto Run" in result["prompt_text"]
    assert "## Escalations" in result["prompt_text"]
    assert "suggested_user_prompt" in result["prompt_text"]


def test_review_auto_messages_and_chatml_formats_return_agent_ready_payloads(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoMessages",
        {
            "claim.md": "# Claim\n\nClaim 是位于 chunk 与 wiki 之间的独立知识声明层。\n",
            "chunk.md": "# Chunk\n\nChunk 是用于承载局部原文切片的证据单元。\n",
        },
    )

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_page_ids = [record["page_id"] for record in page_records if record.get("type") == "concept-summary"][:2]
    for record in page_records:
        if record.get("page_id") in concept_page_ids:
            record["aliases"] = sorted(set(record.get("aliases", []) + ["知识层"]))
    write_jsonl(pages_path, page_records)

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

    refreshed_claims = {record["claim_id"]: record for record in active_claims}
    assert refreshed_claims[next(iter(surviving_promoted_ids))]["status"] == "stable"
    assert ({primary_claim_id, secondary_claim_id} - set(refreshed_claims)).__len__() == 1

    refreshed_reviews = {record["review_id"]: record for record in load_jsonl(reviews_path)}
    assert refreshed_reviews["rev_auto_apply_merge"]["status"] == "resolved"


def test_review_auto_escalates_ambiguous_alias_conflict(tmp_path: Path) -> None:
    workspace_dir = create_workspace(
        tmp_path,
        "ReviewAutoEscalate",
        {
            "claim.md": "# Claim\n\nClaim 是位于 chunk 与 wiki 之间的独立知识声明层。\n",
            "chunk.md": "# Chunk\n\nChunk 是用于承载局部原文切片的证据单元。\n",
        },
    )

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_page_ids = [record["page_id"] for record in page_records if record.get("type") == "concept-summary"][:2]
    assert len(concept_page_ids) == 2
    shared_alias = "知识层"
    for record in page_records:
        if record.get("page_id") in concept_page_ids:
            record["aliases"] = sorted(set(record.get("aliases", []) + [shared_alias]))
    write_jsonl(pages_path, page_records)

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
