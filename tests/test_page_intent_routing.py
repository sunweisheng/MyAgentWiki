from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from myagentwiki.cli import build_page_intent_item_payload, choose_bucket_page_intent, claim_role_blocks_concept_path


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


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def assert_routed_page_has_page_route_decision(workspace_dir: Path, page_record: dict) -> None:
    page_route = page_record.get("page_route", {})
    semantic_decision_id = page_route.get("semantic_decision_id")
    assert semantic_decision_id
    assert semantic_decision_id in page_record.get("semantic_decision_ids", [])
    assert page_route.get("route_target") == page_record.get("type")

    semantic_records = load_jsonl(workspace_dir / "state" / "semantic_decisions.jsonl")
    route_decision = next(
        record for record in semantic_records
        if record.get("decision_id") == semantic_decision_id
    )
    assert route_decision["task_type"] == "page_route"
    assert route_decision["decision"]["route_target"] == page_record.get("type")


def test_claim_semantic_readers_prefer_projection() -> None:
    claim_record = {
        "claim_id": "clm_projection_only",
        "text": "示例步骤用于验证 projection 读取。",
        "knowledge_role": None,
        "page_intent_hints": [],
        "concept_candidate_score": 0.0,
        "semantic_projection": {
            "knowledge_role": "procedure",
            "page_intent_hints": ["guide"],
            "concept_candidate_score": 0.82,
        },
    }

    assert choose_bucket_page_intent([claim_record]) == "guide"
    assert claim_role_blocks_concept_path(claim_record) is True

    payload = build_page_intent_item_payload("projection_bucket", [claim_record])
    assert payload["claim_semantics"] == [
        {
            "claim_id": "clm_projection_only",
            "knowledge_role": "procedure",
            "page_intent_hints": ["guide"],
            "concept_candidate_score": 0.82,
        }
    ]
    assert payload["group_context"]["knowledge_role_counts"] == {"procedure": 1}
    assert payload["group_context"]["page_intent_hint_counts"] == {"guide": 1}


def test_page_intent_heuristic_downgrades_single_specialized_hint() -> None:
    claim_record = {
        "claim_id": "clm_single_reference_hint",
        "text": "产品规则在这次迭代中需要继续完善。",
        "knowledge_role": "fact",
        "page_intent_hints": ["reference"],
        "concept_candidate_score": 0.2,
        "semantic_projection": {
            "knowledge_role": "fact",
            "page_intent_hints": ["reference"],
            "concept_candidate_score": 0.2,
        },
    }

    assert choose_bucket_page_intent([claim_record]) == "topic"


def test_page_intent_heuristic_accepts_group_level_reference_evidence() -> None:
    claim_records = [
        {
            "claim_id": "clm_reference_table",
            "text": "参数列表用于说明系统的关键配置项。",
            "knowledge_role": "fact",
            "page_intent_hints": ["reference"],
            "concept_candidate_score": 0.2,
            "structure_context": {
                "evidence_block_kind_counts": {"table_row": 1},
                "content_tag_counts": {"rules": 1},
            },
        },
        {
            "claim_id": "clm_reference_rules",
            "text": "规则清单用于列出处理约束。",
            "knowledge_role": "fact",
            "page_intent_hints": ["reference"],
            "concept_candidate_score": 0.2,
            "structure_context": {
                "content_tag_counts": {"rules": 1},
            },
        },
    ]

    assert choose_bucket_page_intent(claim_records) == "reference"


def test_page_intent_does_not_route_chinese_workflow_words_to_guide_page(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text(
        "# Guide\n\n"
        "首先扫描 raw 目录。\n\n"
        "然后生成 normalized 文档。\n\n"
        "最后写入 chunk 与 claim。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "GuideIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl") if not record.get("removed")]
    assert not any(record.get("type") == "guide" for record in pages)


def test_page_intent_does_not_route_chinese_example_words_to_example_page(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "example.md").write_text(
        "# Example\n\n"
        "例如，Claim 可以承载定义句。\n\n"
        "比如，一个概念页可以引用多个 Claim。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "ExampleIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl") if not record.get("removed")]
    assert not any(record.get("type") == "example" for record in pages)


def test_page_intent_routes_reference_content_to_reference_page(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "reference.md").write_text(
        "# FAQ Reference\n\n"
        "| field | value |\n"
        "| --- | --- |\n"
        "| timeout_seconds | 45 |\n"
        "| batch_size | 10 |\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "ReferenceIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl") if not record.get("removed")]
    assert any(record.get("type") == "reference" for record in pages)


def test_page_intent_does_not_route_chinese_timeline_words_to_timeline_page(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "timeline.md").write_text(
        "# Timeline\n\n"
        "起初系统只支持 source-summary。\n\n"
        "随后加入 claim 层。\n\n"
        "后来引入 semantic batch。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "TimelineIntent", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl") if not record.get("removed")]
    assert not any(record.get("type") == "timeline" for record in pages)


def test_chinese_ambiguous_keywords_do_not_single_vote_page_intent(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "work_note.md").write_text(
        "# 项目复盘\n\n"
        "团队整理历史数据用于分析转化趋势。\n\n"
        "我们沉淀案例库，方便新人学习常见问题。\n\n"
        "产品规则在这次迭代中需要继续完善。\n\n"
        "这个说明用于帮助团队理解背景。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli("init", "--source-dir", str(source_dir), "--project-name", "AmbiguousKeywords", "--target-dir", str(workspace_dir))
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages = [
        record
        for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if not record.get("removed") and record.get("type") in {"guide", "example", "reference", "timeline"}
    ]
    assert pages == []


def test_structure_code_example_hint_routes_to_example() -> None:
    claim_records = [
        {
            "claim_id": "clm_code_example",
            "text": "print('hello wiki')",
            "knowledge_role": "example",
            "page_intent_hints": ["example"],
            "concept_candidate_score": 0.2,
            "structure_context": {
                "evidence_block_kind_counts": {"code_example": 1},
            },
        },
    ]

    assert choose_bucket_page_intent(claim_records) == "example"


def test_mixed_chinese_document_types_route_by_structure_not_keywords(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text(
        "# 导入流程指南\n\n"
        "首先确认 raw 目录只包含本次要导入的资料。\n\n"
        "然后执行 ingest 生成 normalized、chunks 和 claims。\n\n"
        "最后运行 lint 检查页面与索引一致性。\n",
        encoding="utf-8",
    )
    (source_dir / "case.md").write_text(
        "# 客诉案例复盘\n\n"
        "案例：某城市出现车辆离线后，团队先定位网络异常，再回滚配置，最终恢复服务。\n\n"
        "该场景的输入是告警记录，过程是排查和回滚，结果是恢复运营。\n",
        encoding="utf-8",
    )
    (source_dir / "reference.md").write_text(
        "# 配置参数参考\n\n"
        "| 字段 | 含义 |\n"
        "| --- | --- |\n"
        "| timeout_seconds | CLI hook 的超时时间 |\n"
        "| batch_size | 每次语义批处理的条目数 |\n\n"
        "规则清单用于列出处理约束。\n",
        encoding="utf-8",
    )
    (source_dir / "timeline.md").write_text(
        "# 系统演进时间线\n\n"
        "起初系统只生成 source summary。\n\n"
        "随后加入 claim 层保存可追溯结论。\n\n"
        "后来引入 semantic batch 支持结构优先判断。\n",
        encoding="utf-8",
    )
    (source_dir / "study.md").write_text(
        "# BM25 学习笔记\n\n"
        "BM25 是一种用于关键词检索的相关性排序算法。\n\n"
        "倒排索引用于把词项映射到包含该词项的文档。\n",
        encoding="utf-8",
    )
    (source_dir / "ambiguous_work.md").write_text(
        "# 项目复盘\n\n"
        "团队整理历史数据用于分析转化趋势。\n\n"
        "我们沉淀案例库，方便新人学习常见问题。\n\n"
        "产品规则在这次迭代中需要继续完善。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "MixedChineseDocs",
        "--target-dir",
        str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    live_pages = [
        record
        for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if not record.get("removed")
    ]
    page_types_by_title = {
        record.get("title"): record.get("type")
        for record in live_pages
        if record.get("type") != "source-summary"
    }
    assert page_types_by_title["导入流程指南"] == "concept"
    assert page_types_by_title["客诉案例复盘"] == "concept"
    assert page_types_by_title["配置参数参考"] == "reference"
    assert page_types_by_title["系统演进时间线"] == "concept"
    assert page_types_by_title["BM25 学习笔记"] == "concept"
    assert page_types_by_title["项目复盘"] == "concept"

    claims_by_text = {
        record.get("text"): record
        for record in load_jsonl(workspace_dir / "state" / "claims.jsonl")
        if record.get("lifecycle_status", "active") == "active"
    }
    assert claims_by_text["案例：某城市出现车辆离线后，团队先定位网络异常，再回滚配置，最终恢复服务"].get("knowledge_role") == "fact"
    assert claims_by_text["案例：某城市出现车辆离线后，团队先定位网络异常，再回滚配置，最终恢复服务"].get("page_intent_hints") == ["topic"]
    assert claims_by_text["团队整理历史数据用于分析转化趋势"].get("page_intent_hints") == ["topic"]
    assert claims_by_text["我们沉淀案例库，方便新人学习常见问题"].get("page_intent_hints") == ["topic"]
    assert claims_by_text["产品规则在这次迭代中需要继续完善"].get("page_intent_hints") == ["topic"]

    semantic_records = load_jsonl(workspace_dir / "state" / "semantic_decisions.jsonl")
    role_risk_flags = [
        flag
        for record in semantic_records
        if record.get("task_type") == "claim_role"
        for flag in record.get("risk_flags", [])
    ]
    assert "ambiguous_case_keyword" not in role_risk_flags
    assert "ambiguous_reference_keyword" not in role_risk_flags

    lint_result = run_cli("lint", "--target-dir", str(workspace_dir))
    assert lint_result["summary"]["ok"] is True
    failed_checks = {check["name"]: check for check in lint_result["checks"] if not check["ok"]}
    assert "page_semantic_consistency" not in failed_checks


def test_page_intent_reject_blocks_question_hint_groups() -> None:
    claim_records = [
        {
            "claim_id": "clm_question_1",
            "text": "为什么要做知识库?",
            "knowledge_role": "reject",
            "page_intent_hints": ["reject"],
        },
        {
            "claim_id": "clm_question_2",
            "text": "如何才能整理页面?",
            "knowledge_role": "reject",
            "page_intent_hints": ["reject"],
        },
    ]

    assert choose_bucket_page_intent(claim_records) == "reject"
