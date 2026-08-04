from __future__ import annotations

import json

import pytest

from myagentwiki.llm.contracts import (
    build_task_context,
    cli_result_schema,
    get_function_spec,
    registered_task_names,
)
from myagentwiki.llm.errors import LLMResponseError
from myagentwiki.llm.repair import RawFunctionCall, repair_and_validate
from myagentwiki.llm.repair import validate_function_schema


def test_all_current_llm_tasks_have_strict_function_contracts() -> None:
    assert set(registered_task_names()) == {
        "document_analysis",
        "claim_candidate_quality",
        "claim_role",
        "page_intent",
        "review_auto_decision",
        "claim_stable_promotion",
        "review_concept_candidate",
        "render_readable_concept_page",
        "render_workspace_overview_page",
        "describe_image",
    }
    for task_name in registered_task_names():
        spec = get_function_spec(task_name)
        validate_function_schema(spec)
        assert callable(spec.context_builder)
        assert spec.parameters_schema["additionalProperties"] is False
        assert cli_result_schema(spec)["properties"]["function_name"]["const"] == spec.function_name


def test_document_context_includes_and_truncates_real_content() -> None:
    spec = get_function_spec("document_analysis")
    context = build_task_context(
        spec,
        {
            "task": "review_document_analysis_batch",
            "task_name": "document_analysis",
            "items": [{"item_id": "doc-1", "content": "a" * 20}],
        },
        document_max_chars=10,
    )
    item = context["items"][0]
    assert item["content_truncated"] is True
    assert len(item["content"]) == 10
    assert item["content"].startswith("aaaaa")
    assert item["content"].endswith("aaaaa")
    assert "task" not in context
    assert "task_name" not in context


def test_semantic_contract_rejects_supporting_id_outside_item_context() -> None:
    spec = get_function_spec("claim_role")
    payload = {
        "task": "review_claim_role_batch",
        "task_name": "claim_role",
        "items": [{"item_id": "claim-1", "claim_id": "claim-1", "source_ids": ["source-1"]}],
    }
    arguments = {
        "decisions": [{
            "item_id": "claim-1",
            "decision": {
                "knowledge_role": "fact",
                "page_intent_hints": ["topic"],
                "concept_candidate_score": 0.8,
                "risk_flags": [],
                "content_tags": [],
            },
            "decision_status": "accepted",
            "confidence": 0.9,
            "reason_code": "test",
            "risk_flags": [],
            "supporting_ids": ["invented-evidence"],
            "abstain_reason": "",
        }],
    }
    with pytest.raises(LLMResponseError, match="supporting_id outside"):
        repair_and_validate(
            spec=spec,
            raw_call=RawFunctionCall(spec.function_name, json.dumps(arguments)),
            payload=payload,
            backend="online",
        )
