from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path | None = None) -> dict:
    # 测试里统一走真实 CLI 入口，避免“函数级单测通过、命令行参数路径却有问题”。
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


def test_review_merge_rewrites_other_open_reviews(tmp_path: Path) -> None:
    # 这个回归场景覆盖最容易遗漏的一类问题：
    # 某个 claim 被 merge 掉后，其他仍然 open 的 review 不应继续引用它。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 主题\n\n"
        "第一条陈述说明 Alpha 方案能够稳定落地并长期维护。\n\n"
        "第二条陈述说明 Beta 方案支持团队在知识沉淀阶段逐步积累。\n\n"
        "第三条陈述说明 Gamma 方案强调来源回链与审核闭环。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReviewRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claims_path = workspace_dir / "state" / "claims.jsonl"
    reviews_path = workspace_dir / "state" / "reviews.jsonl"

    claim_records = load_jsonl(claims_path)
    assert len(claim_records) >= 3

    primary_claim_id = claim_records[0]["claim_id"]
    merged_away_claim_id = claim_records[1]["claim_id"]
    third_claim_id = claim_records[2]["claim_id"]

    # 给三条 claim 人工挂两张 open review，模拟一个 claim 同时参与多个待处理审核单。
    claim_by_id = {record["claim_id"]: record for record in claim_records}
    claim_by_id[primary_claim_id]["status"] = "needs_review"
    claim_by_id[primary_claim_id]["duplicate_candidates"] = [merged_away_claim_id]
    claim_by_id[primary_claim_id]["review_reason"] = "possible_duplicate_claim"

    claim_by_id[merged_away_claim_id]["status"] = "needs_review"
    claim_by_id[merged_away_claim_id]["duplicate_candidates"] = [primary_claim_id, third_claim_id]
    claim_by_id[merged_away_claim_id]["review_reason"] = "possible_duplicate_claim"

    claim_by_id[third_claim_id]["status"] = "needs_review"
    claim_by_id[third_claim_id]["duplicate_candidates"] = [merged_away_claim_id]
    claim_by_id[third_claim_id]["review_reason"] = "possible_duplicate_claim"

    write_jsonl(claims_path, list(claim_by_id.values()))
    for claim_record in claim_by_id.values():
        claim_file = workspace_dir / "claims" / f"{claim_record['claim_id']}.json"
        write_json(claim_file, claim_record)

    review_one = {
        "review_id": "rev_merge_pair",
        "kind": "claim_duplicate",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [primary_claim_id, merged_away_claim_id],
        "candidate_page_ids": [],
        "reason": "first duplicate pair",
        "recommended_action": "merge",
        "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-05-29T00:00:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_merge_pair.json",
    }
    review_two = {
        "review_id": "rev_followup_pair",
        "kind": "claim_duplicate",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [merged_away_claim_id, third_claim_id],
        "candidate_page_ids": [],
        "reason": "second duplicate pair",
        "recommended_action": "merge",
        "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-05-29T00:01:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_followup_pair.json",
    }

    write_jsonl(reviews_path, [review_one, review_two])
    for review_record in [review_one, review_two]:
        review_file = workspace_dir / "reviews" / f"{review_record['review_id']}.json"
        write_json(review_file, review_record)

    result = run_cli(
        "review-apply",
        "rev_merge_pair",
        "merge",
        "--primary-claim-id", primary_claim_id,
        "--secondary-claim-id", merged_away_claim_id,
        "--target-dir", str(workspace_dir),
    )
    assert result["action"] == "merge"

    refreshed_claim_records = load_jsonl(claims_path)
    refreshed_claims_by_id = {record["claim_id"]: record for record in refreshed_claim_records}

    assert primary_claim_id in refreshed_claims_by_id
    assert merged_away_claim_id not in refreshed_claims_by_id
    # 主 claim 仍然出现在另一张 open review 里，所以它应该继续保留 needs_review。
    assert refreshed_claims_by_id[primary_claim_id]["status"] == "needs_review"
    assert refreshed_claims_by_id[primary_claim_id]["review_reason"] == "possible_duplicate_claim"
    assert refreshed_claims_by_id[primary_claim_id]["duplicate_candidates"] == [third_claim_id]

    refreshed_review_records = load_jsonl(reviews_path)
    refreshed_reviews_by_id = {record["review_id"]: record for record in refreshed_review_records}

    assert refreshed_reviews_by_id["rev_merge_pair"]["status"] == "resolved"
    assert refreshed_reviews_by_id["rev_followup_pair"]["candidate_claim_ids"] == [primary_claim_id, third_claim_id]
    assert refreshed_reviews_by_id["rev_followup_pair"]["status"] == "open"

    stale_live_claim_file = workspace_dir / "claims" / f"{merged_away_claim_id}.json"
    assert not stale_live_claim_file.exists()


def test_review_edit_then_resume_reloads_manual_claim_edits(tmp_path: Path) -> None:
    # 这个场景验证“人先改 claim 文件，再让系统恢复后续步骤”。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 主题\n\n"
        "第一条陈述说明 Delta 方案需要先建立来源追踪。\n\n"
        "第二条陈述说明 Epsilon 方案需要补齐人工审核闭环。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "EditResumeRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

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
            other_id for other_id in (first_claim_id, second_claim_id)
            if other_id != claim_id
        ]
        claim_by_id[claim_id]["review_reason"] = "possible_duplicate_claim"

    write_jsonl(claims_path, list(claim_by_id.values()))
    for claim_record in claim_by_id.values():
        write_json(workspace_dir / "claims" / f"{claim_record['claim_id']}.json", claim_record)

    review_record = {
        "review_id": "rev_edit_resume",
        "kind": "claim_duplicate",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [first_claim_id, second_claim_id],
        "candidate_page_ids": [],
        "reason": "manual editing path",
        "recommended_action": "edit_then_resume",
        "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-05-29T00:10:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_edit_resume.json",
    }
    write_jsonl(reviews_path, [review_record])
    write_json(workspace_dir / "reviews" / "rev_edit_resume.json", review_record)

    # 模拟人工直接改 claim 文件，把其中一条文本改成更明确的版本并清掉重复标记。
    edited_claim = dict(claim_by_id[first_claim_id])
    edited_claim["text"] = "人工修订：Delta 方案应先建立来源追踪，再进入后续知识沉淀。"
    edited_claim["normalized_text"] = "人工修订 delta 方案应先建立来源追踪 再进入后续知识沉淀"
    edited_claim["status"] = "draft"
    edited_claim["duplicate_candidates"] = []
    edited_claim["review_reason"] = None
    write_json(workspace_dir / "claims" / f"{first_claim_id}.json", edited_claim)

    result = run_cli(
        "review-apply",
        "rev_edit_resume",
        "edit_then_resume",
        "--target-dir", str(workspace_dir),
    )
    assert result["action"] == "edit_then_resume"

    refreshed_claim_records = load_jsonl(claims_path)
    refreshed_claims_by_id = {record["claim_id"]: record for record in refreshed_claim_records}
    assert refreshed_claims_by_id[first_claim_id]["text"] == edited_claim["text"]
    assert refreshed_claims_by_id[first_claim_id]["status"] == "draft"
    assert refreshed_claims_by_id[first_claim_id]["review_reason"] is None

    refreshed_reviews_by_id = {record["review_id"]: record for record in load_jsonl(reviews_path)}
    assert refreshed_reviews_by_id["rev_edit_resume"]["status"] == "resolved"


def test_review_keep_both_clears_claim_review_flags_when_no_other_open_reviews(tmp_path: Path) -> None:
    # keep_both 的语义是“这张审核单处理完了，但两条 claim 都保留”。
    # 如果没有其他 open review，它们不该继续停在 needs_review。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 主题\n\n"
        "第一条陈述说明知识库需要保留多种视角。\n\n"
        "第二条陈述说明相似结论有时也应并存。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "KeepBothRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

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
            other_id for other_id in (first_claim_id, second_claim_id)
            if other_id != claim_id
        ]
        claim_by_id[claim_id]["review_reason"] = "possible_duplicate_claim"

    write_jsonl(claims_path, list(claim_by_id.values()))
    for claim_record in claim_by_id.values():
        write_json(workspace_dir / "claims" / f"{claim_record['claim_id']}.json", claim_record)

    review_record = {
        "review_id": "rev_keep_both",
        "kind": "claim_duplicate",
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": [first_claim_id, second_claim_id],
        "candidate_page_ids": [],
        "reason": "keep both path",
        "recommended_action": "keep_both",
        "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": [],
        "created_at": "2026-05-29T00:20:00+00:00",
        "resolved_at": None,
        "archived_at": None,
        "review_file_path": "reviews/rev_keep_both.json",
    }
    write_jsonl(reviews_path, [review_record])
    write_json(workspace_dir / "reviews" / "rev_keep_both.json", review_record)

    result = run_cli(
        "review-apply",
        "rev_keep_both",
        "keep_both",
        "--target-dir", str(workspace_dir),
    )
    assert result["action"] == "keep_both"

    refreshed_claims_by_id = {record["claim_id"]: record for record in load_jsonl(claims_path)}
    assert refreshed_claims_by_id[first_claim_id]["status"] == "draft"
    assert refreshed_claims_by_id[first_claim_id]["review_reason"] is None
    assert refreshed_claims_by_id[first_claim_id]["duplicate_candidates"] == []
    assert refreshed_claims_by_id[second_claim_id]["status"] == "draft"
