from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from json_repair import loads as repair_loads
from jsonschema import Draft202012Validator

from .errors import LLMResponseError

if TYPE_CHECKING:
    from .contracts import LLMFunctionSpec


@dataclass(frozen=True)
class RawFunctionCall:
    function_name: str
    arguments_json: str
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidatedFunctionResult:
    arguments: dict[str, Any]
    repaired: bool
    validation: dict[str, Any]


def validate_function_schema(spec: LLMFunctionSpec) -> None:
    Draft202012Validator.check_schema(spec.parameters_schema)


def repair_and_validate(
    *,
    spec: LLMFunctionSpec,
    raw_call: RawFunctionCall,
    payload: dict[str, Any],
    backend: str,
) -> ValidatedFunctionResult:
    validation = {
        "function_name_check": "not_run",
        "json_repair": "not_run",
        "schema_check": "not_run",
        "business_check": "not_run",
    }
    if raw_call.function_name != spec.function_name:
        validation["function_name_check"] = "failed"
        raise LLMResponseError(
            f"Expected function `{spec.function_name}`, got `{raw_call.function_name or '(empty)'}`.",
            backend=backend,
            debug_details={"validation": validation},
        )
    validation["function_name_check"] = "success"
    raw_arguments = raw_call.arguments_json.strip()
    if not raw_arguments:
        validation["json_repair"] = "failed"
        raise LLMResponseError(
            "Function arguments are empty.",
            backend=backend,
            debug_details={"validation": validation},
        )

    repaired = False
    try:
        json.loads(raw_arguments)
    except json.JSONDecodeError:
        repaired = True
    try:
        arguments = repair_loads(raw_arguments)
    except Exception as exc:
        validation["json_repair"] = "failed"
        raise LLMResponseError(
            f"Function arguments could not be repaired: {exc}",
            backend=backend,
            repaired=repaired,
            debug_details={"validation": validation},
        ) from exc
    validation["json_repair"] = "repaired" if repaired else "not_needed"
    if not isinstance(arguments, dict):
        validation["schema_check"] = "failed"
        raise LLMResponseError(
            "Function arguments must be a JSON object.",
            backend=backend,
            repaired=repaired,
            debug_details={"validation": validation},
        )

    errors = sorted(
        Draft202012Validator(spec.parameters_schema).iter_errors(arguments),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        validation["schema_check"] = "failed"
        detail = "; ".join(error.message for error in errors[:3])
        raise LLMResponseError(
            f"Function arguments failed schema validation: {detail}",
            backend=backend,
            repaired=repaired,
            debug_details={"validation": validation},
        )
    validation["schema_check"] = "success"
    try:
        spec.validate_business(arguments, payload)
    except ValueError as exc:
        validation["business_check"] = "failed"
        raise LLMResponseError(
            f"Function arguments failed business validation: {exc}",
            backend=backend,
            repaired=repaired,
            debug_details={"validation": validation},
        ) from exc
    validation["business_check"] = "success"
    return ValidatedFunctionResult(
        arguments=arguments,
        repaired=repaired,
        validation=validation,
    )
