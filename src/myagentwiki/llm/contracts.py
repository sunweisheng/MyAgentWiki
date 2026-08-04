from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable


BusinessValidator = Callable[[dict[str, Any], dict[str, Any]], None]
ContextBuilder = Callable[[dict[str, Any], int], dict[str, Any]]


def _default_context_builder(payload: dict[str, Any], document_max_chars: int) -> dict[str, Any]:
    del document_max_chars
    return {
        key: copy.deepcopy(value)
        for key, value in payload.items()
        if key not in {"task", "task_name", "instructions", "command"}
    }


def _document_context_builder(payload: dict[str, Any], document_max_chars: int) -> dict[str, Any]:
    context = _default_context_builder(payload, document_max_chars)
    for item in context.get("items", []):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", ""))
        if len(content) <= document_max_chars:
            item["content_truncated"] = False
            continue
        leading_chars = max(document_max_chars // 2, 1)
        trailing_chars = max(document_max_chars - leading_chars, 1)
        item["content"] = content[:leading_chars] + content[-trailing_chars:]
        item["content_truncated"] = True
    return context


@dataclass(frozen=True)
class LLMFunctionSpec:
    task_name: str
    function_name: str
    description: str
    instructions: str
    parameters_schema: dict[str, Any]
    schema_version: str
    prompt_version: str
    supports_images: bool
    validate_business: BusinessValidator
    context_builder: ContextBuilder = _default_context_builder


def _string(*, nullable: bool = False, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": ["string", "null"] if nullable else "string"}
    if enum is not None:
        schema["enum"] = [*enum, None] if nullable else enum
    return schema


def _number(*, nullable: bool = False) -> dict[str, Any]:
    return {
        "type": ["number", "null"] if nullable else "number",
        "minimum": 0,
        "maximum": 1,
    }


def _boolean(*, nullable: bool = False) -> dict[str, Any]:
    return {"type": ["boolean", "null"] if nullable else "boolean"}


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array(item_schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item_schema}


def _semantic_parameters(decision_properties: dict[str, Any]) -> dict[str, Any]:
    decision_schema = _object(decision_properties)
    item_schema = _object({
        "item_id": _string(),
        "decision": decision_schema,
        "decision_status": _string(enum=["accepted", "abstained", "rejected"]),
        "confidence": _number(),
        "reason_code": _string(),
        "risk_flags": _string_array(),
        "supporting_ids": _string_array(),
        "abstain_reason": _string(),
    })
    return _object({"decisions": _array(item_schema)})


SEMANTIC_DECISION_FIELDS: dict[str, tuple[str, ...]] = {
    "document_analysis": ("document_kind", "structure_quality", "chunk_strategy_hint"),
    "claim_candidate_quality": ("quality_label", "review_required", "safe_auto_ready"),
    "claim_role": ("knowledge_role", "page_intent_hints", "concept_candidate_score"),
    "page_intent": ("page_intent",),
}


def _collect_known_ids(value: Any, *, key: str = "") -> set[str]:
    collected: set[str] = set()
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            collected.update(_collect_known_ids(child_value, key=str(child_key)))
    elif isinstance(value, list):
        if key.endswith("_ids"):
            collected.update(str(item).strip() for item in value if str(item).strip())
        else:
            for item in value:
                collected.update(_collect_known_ids(item, key=key))
    elif key.endswith("_id") and value is not None:
        normalized = str(value).strip()
        if normalized:
            collected.add(normalized)
    return collected


def _validate_semantic(arguments: dict[str, Any], payload: dict[str, Any]) -> None:
    input_ids = [
        str(item.get("item_id", "")).strip()
        for item in payload.get("items", [])
        if isinstance(item, dict) and str(item.get("item_id", "")).strip()
    ]
    output_ids = [str(item.get("item_id", "")).strip() for item in arguments["decisions"]]
    if len(output_ids) != len(set(output_ids)):
        raise ValueError("duplicate decision item_id")
    if set(output_ids) != set(input_ids):
        raise ValueError("decision item_ids must exactly match input item_ids")
    task_name = str(payload.get("task_name", "")).strip()
    required_fields = SEMANTIC_DECISION_FIELDS.get(task_name, ())
    input_items = {
        str(item.get("item_id", "")).strip(): item
        for item in payload.get("items", [])
        if isinstance(item, dict) and str(item.get("item_id", "")).strip()
    }
    for item in arguments["decisions"]:
        input_item = input_items.get(str(item.get("item_id", "")).strip(), {})
        allowed_supporting_ids = _collect_known_ids(input_item)
        if any(supporting_id not in allowed_supporting_ids for supporting_id in item["supporting_ids"]):
            raise ValueError(f"decision `{item['item_id']}` contains a supporting_id outside its input")
        decision_supporting_ids = item["decision"].get("supporting_ids", [])
        if any(supporting_id not in allowed_supporting_ids for supporting_id in decision_supporting_ids):
            raise ValueError(f"decision `{item['item_id']}` contains unsupported evidence")
        if item["decision_status"] != "accepted":
            continue
        missing = [field for field in required_fields if item["decision"].get(field) is None]
        if missing:
            raise ValueError(f"accepted decision `{item['item_id']}` has empty fields: {', '.join(missing)}")


def _validate_review_auto(arguments: dict[str, Any], payload: dict[str, Any]) -> None:
    if arguments["decision"] != "auto_apply":
        return
    review = payload.get("review", {}) if isinstance(payload.get("review"), dict) else {}
    allowed_actions = set(review.get("allowed_actions", []))
    action = arguments.get("action")
    if action not in allowed_actions:
        raise ValueError("auto_apply action is not allowed by the review")
    claim_ids = set(review.get("candidate_claim_ids", []))
    page_ids = set(review.get("candidate_page_ids", []))
    if action in {"merge", "archive_one"} and arguments.get("primary_claim_id") not in claim_ids:
        raise ValueError("primary_claim_id is not a review candidate")
    if action == "merge":
        secondary = arguments.get("secondary_claim_id")
        if secondary not in claim_ids or secondary == arguments.get("primary_claim_id"):
            raise ValueError("secondary_claim_id is not a distinct review candidate")
    if action in {"assign_alias", "remove_alias"}:
        if arguments.get("primary_page_id") not in page_ids:
            raise ValueError("primary_page_id is not a review candidate")
        alias_value = str(arguments.get("alias_value") or "").strip()
        if not alias_value:
            raise ValueError("alias_value is required for alias actions")
        alias_context = payload.get("alias_conflict_context", {})
        expected_alias = str(alias_context.get("alias_value", "")).strip() if isinstance(alias_context, dict) else ""
        if expected_alias and alias_value != expected_alias:
            raise ValueError("alias_value must match the reviewed alias")


def _validate_stable_promotion(arguments: dict[str, Any], payload: dict[str, Any]) -> None:
    if arguments["decision"] not in {"promote", "skip"}:
        raise ValueError("unsupported promotion decision")


def _validate_concept_candidate(arguments: dict[str, Any], payload: dict[str, Any]) -> None:
    if arguments["decision"] != "rename":
        return
    suggested_title = str(arguments.get("suggested_title") or "").strip()
    if not suggested_title:
        raise ValueError("rename requires suggested_title")
    evidence_text = "\n".join([
        str(payload.get("candidate_title", "")),
        str(payload.get("preferred_section_label", "")),
        str((payload.get("canonical_claim") or {}).get("text", "")),
        *[
            str(item.get("text", ""))
            for item in payload.get("supporting_claims", [])
            if isinstance(item, dict)
        ],
    ]).casefold()
    if suggested_title.casefold() not in evidence_text:
        raise ValueError("suggested_title is not supported by the supplied evidence")


def _validate_concept_render(arguments: dict[str, Any], payload: dict[str, Any]) -> None:
    allowed_ids = {
        str(item.get("claim_id", "")).strip()
        for item in payload.get("stable_claims", [])
        if isinstance(item, dict)
    }
    for key in ("key_points", "practical_notes"):
        ids = [str(item.get("claim_id", "")).strip() for item in arguments[key]]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{key} contains duplicate claim_id")
        if any(item_id not in allowed_ids for item_id in ids):
            raise ValueError(f"{key} references a claim outside the request")


def _validate_overview_render(arguments: dict[str, Any], payload: dict[str, Any]) -> None:
    allowed_ids = {
        str(item.get("page_id", "")).strip()
        for key in ("theme_rows", "reading_path_rows")
        for item in payload.get(key, [])
        if isinstance(item, dict)
    }
    for key in ("theme_rows", "reading_path"):
        ids = [str(item.get("page_id", "")).strip() for item in arguments[key]]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{key} contains duplicate page_id")
        if any(item_id not in allowed_ids for item_id in ids):
            raise ValueError(f"{key} references a page outside the request")


def _validate_image(arguments: dict[str, Any], payload: dict[str, Any]) -> None:
    if not arguments["extracted_text"].strip() and not arguments["summary"].strip():
        raise ValueError("image result must contain extracted_text or summary")


SEMANTIC_INSTRUCTIONS = (
    "Evaluate every supplied item from its structure, evidence and surrounding context. "
    "Submit exactly one decision for every item_id. When evidence is insufficient, use "
    "decision_status=abstained and explain the reason instead of inventing a decision."
)


_CONTRACTS: dict[str, LLMFunctionSpec] = {
    "document_analysis": LLMFunctionSpec(
        task_name="document_analysis",
        function_name="submit_document_analysis",
        description="Submit document type, structure quality and chunking guidance for each normalized document.",
        instructions=SEMANTIC_INSTRUCTIONS + " Use the supplied document content, not the path alone.",
        parameters_schema=_semantic_parameters({
            "document_kind": _string(nullable=True),
            "structure_quality": _string(nullable=True),
            "chunk_strategy_hint": _string(nullable=True),
            "risk_flags": _string_array(),
            "content_tags": _string_array(),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_semantic,
        context_builder=_document_context_builder,
    ),
    "claim_candidate_quality": LLMFunctionSpec(
        task_name="claim_candidate_quality",
        function_name="submit_claim_candidate_quality",
        description="Submit whether each claim candidate is complete, reviewable and safe for automatic processing.",
        instructions=SEMANTIC_INSTRUCTIONS,
        parameters_schema=_semantic_parameters({
            "quality_label": _string(nullable=True),
            "review_required": _boolean(nullable=True),
            "safe_auto_ready": _boolean(nullable=True),
            "reason": _string(nullable=True),
            "risk_flags": _string_array(),
            "content_tags": _string_array(),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_semantic,
    ),
    "claim_role": LLMFunctionSpec(
        task_name="claim_role",
        function_name="submit_claim_role_decisions",
        description="Submit the knowledge role, page intent hints and concept score for each claim.",
        instructions=SEMANTIC_INSTRUCTIONS + " Prefer evidence and structure over isolated words.",
        parameters_schema=_semantic_parameters({
            "knowledge_role": _string(nullable=True),
            "page_intent_hints": _string_array(),
            "concept_candidate_score": _number(nullable=True),
            "risk_flags": _string_array(),
            "content_tags": _string_array(),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_semantic,
    ),
    "page_intent": LLMFunctionSpec(
        task_name="page_intent",
        function_name="submit_page_intent_decisions",
        description="Submit the safest page intent for each claim group.",
        instructions=SEMANTIC_INSTRUCTIONS + " Keep supporting_ids tied to evidence provided in the group.",
        parameters_schema=_semantic_parameters({
            "page_intent": _string(nullable=True),
            "route_target": _string(nullable=True),
            "content_tags": _string_array(),
            "risk_flags": _string_array(),
            "supporting_ids": _string_array(),
            "rejected_alternatives": _string_array(),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_semantic,
    ),
    "review_auto_decision": LLMFunctionSpec(
        task_name="review_auto_decision",
        function_name="submit_review_decision",
        description="Submit a safe automatic action or request human review for one review record.",
        instructions="Only use an action listed in review.allowed_actions. Escalate when evidence is insufficient.",
        parameters_schema=_object({
            "decision": _string(enum=["auto_apply", "escalate", "skip"]),
            "action": _string(nullable=True, enum=["merge", "keep_both", "archive_one", "edit_then_resume", "assign_alias", "remove_alias"]),
            "primary_claim_id": _string(nullable=True),
            "secondary_claim_id": _string(nullable=True),
            "primary_page_id": _string(nullable=True),
            "alias_value": _string(nullable=True),
            "confidence": _number(),
            "reason": _string(),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_review_auto,
    ),
    "claim_stable_promotion": LLMFunctionSpec(
        task_name="claim_stable_promotion",
        function_name="submit_claim_promotion_decision",
        description="Submit whether one fully evidenced draft claim is safe to promote.",
        instructions="Promote only when the supplied claim can stand alone and has no unresolved risk.",
        parameters_schema=_object({
            "decision": _string(enum=["promote", "skip"]),
            "confidence": _number(),
            "reason": _string(),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_stable_promotion,
    ),
    "review_concept_candidate": LLMFunctionSpec(
        task_name="review_concept_candidate",
        function_name="submit_concept_candidate_review",
        description="Submit whether a proposed title is a reusable concept title and optionally rename it.",
        instructions="Judge from supplied claims and section context. Do not introduce a title unsupported by evidence.",
        parameters_schema=_object({
            "decision": _string(enum=["accept", "reject", "rename"]),
            "suggested_title": _string(nullable=True),
            "reason": _string(),
            "confidence": _number(),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_concept_candidate,
    ),
    "render_readable_concept_page": LLMFunctionSpec(
        task_name="render_readable_concept_page",
        function_name="submit_readable_concept_page",
        description="Submit a clearer concept summary and grounded claim-based bullets.",
        instructions="Rewrite only for readability. Every bullet must retain a claim_id supplied by the request.",
        parameters_schema=_object({
            "summary": _string(),
            "key_points": _array(_object({"claim_id": _string(), "text": _string()})),
            "practical_notes": _array(_object({"claim_id": _string(), "text": _string()})),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_concept_render,
    ),
    "render_workspace_overview_page": LLMFunctionSpec(
        task_name="render_workspace_overview_page",
        function_name="submit_workspace_overview_page",
        description="Submit a clearer workspace overview using only supplied concept pages.",
        instructions="Rewrite only for readability. Every row must retain a page_id supplied by the request.",
        parameters_schema=_object({
            "summary": _string(),
            "theme_rows": _array(_object({"page_id": _string(), "text": _string()})),
            "reading_path": _array(_object({"page_id": _string(), "text": _string()})),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=False,
        validate_business=_validate_overview_render,
    ),
    "describe_image": LLMFunctionSpec(
        task_name="describe_image",
        function_name="submit_image_description",
        description="Submit text visible in an image and a grounded description of its useful content.",
        instructions="Describe only visible content. Preserve readable text and state uncertainty instead of guessing.",
        parameters_schema=_object({
            "extracted_text": _string(),
            "summary": _string(),
            "confidence": _number(),
            "reason": _string(),
            "warnings": _string_array(),
        }),
        schema_version="v2",
        prompt_version="v2",
        supports_images=True,
        validate_business=_validate_image,
    ),
}


def get_function_spec(task_name: str) -> LLMFunctionSpec:
    try:
        return _CONTRACTS[task_name]
    except KeyError as exc:
        raise KeyError(f"No LLM Function Calling contract is registered for task `{task_name}`.") from exc


def registered_task_names() -> tuple[str, ...]:
    return tuple(_CONTRACTS)


def openai_function_tool(spec: LLMFunctionSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "name": spec.function_name,
        "description": spec.description,
        "parameters": copy.deepcopy(spec.parameters_schema),
        "strict": True,
    }


def chat_completions_function_tool(spec: LLMFunctionSpec) -> dict[str, Any]:
    tool = openai_function_tool(spec)
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
            "strict": tool["strict"],
        },
    }


def cli_result_schema(spec: LLMFunctionSpec) -> dict[str, Any]:
    return _object({
        "function_name": {"type": "string", "const": spec.function_name},
        "arguments_json": {"type": "string"},
    })


def build_task_context(
    spec: LLMFunctionSpec,
    payload: dict[str, Any],
    *,
    document_max_chars: int,
) -> dict[str, Any]:
    return spec.context_builder(payload, document_max_chars)
