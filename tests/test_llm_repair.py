from __future__ import annotations

import json

import pytest

from myagentwiki.llm.contracts import get_function_spec
from myagentwiki.llm.errors import LLMResponseError
from myagentwiki.llm.repair import RawFunctionCall, repair_and_validate


def promotion_payload() -> dict:
    return {"task": "claim_stable_promotion", "claim": {"claim_id": "c1"}}


def test_repair_keeps_valid_arguments_unchanged() -> None:
    arguments = {"decision": "skip", "confidence": 0.8, "reason": "证据不足"}
    result = repair_and_validate(
        spec=get_function_spec("claim_stable_promotion"),
        raw_call=RawFunctionCall(
            "submit_claim_promotion_decision",
            json.dumps(arguments, ensure_ascii=False),
        ),
        payload=promotion_payload(),
        backend="online",
    )
    assert result.arguments == arguments
    assert result.repaired is False


def test_repair_fixes_common_json_syntax_before_validation() -> None:
    result = repair_and_validate(
        spec=get_function_spec("claim_stable_promotion"),
        raw_call=RawFunctionCall(
            "submit_claim_promotion_decision",
            "{'decision':'skip','confidence':0.8,'reason':'证据不足',}",
        ),
        payload=promotion_payload(),
        backend="online",
    )
    assert result.arguments["reason"] == "证据不足"
    assert result.repaired is True


def test_schema_and_function_name_errors_do_not_reach_business_processing() -> None:
    spec = get_function_spec("claim_stable_promotion")
    with pytest.raises(LLMResponseError, match="Expected function"):
        repair_and_validate(
            spec=spec,
            raw_call=RawFunctionCall("wrong", "{}"),
            payload=promotion_payload(),
            backend="online",
        )
    with pytest.raises(LLMResponseError, match="schema validation"):
        repair_and_validate(
            spec=spec,
            raw_call=RawFunctionCall(spec.function_name, '{"decision":"skip"}'),
            payload=promotion_payload(),
            backend="online",
        )
