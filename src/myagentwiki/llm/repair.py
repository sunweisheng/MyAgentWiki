from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ValidatedFunctionResult:
    arguments: dict[str, Any]
    repaired: bool


def validate_function_schema(spec: LLMFunctionSpec) -> None:
    Draft202012Validator.check_schema(spec.parameters_schema)


def repair_and_validate(
    *,
    spec: LLMFunctionSpec,
    raw_call: RawFunctionCall,
    payload: dict[str, Any],
    backend: str,
) -> ValidatedFunctionResult:
    if raw_call.function_name != spec.function_name:
        raise LLMResponseError(
            f"Expected function `{spec.function_name}`, got `{raw_call.function_name or '(empty)'}`.",
            backend=backend,
        )
    raw_arguments = raw_call.arguments_json.strip()
    if not raw_arguments:
        raise LLMResponseError("Function arguments are empty.", backend=backend)

    repaired = False
    try:
        json.loads(raw_arguments)
    except json.JSONDecodeError:
        repaired = True
    try:
        arguments = repair_loads(raw_arguments)
    except Exception as exc:
        raise LLMResponseError(
            f"Function arguments could not be repaired: {exc}",
            backend=backend,
            repaired=repaired,
        ) from exc
    if not isinstance(arguments, dict):
        raise LLMResponseError(
            "Function arguments must be a JSON object.",
            backend=backend,
            repaired=repaired,
        )

    errors = sorted(
        Draft202012Validator(spec.parameters_schema).iter_errors(arguments),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        detail = "; ".join(error.message for error in errors[:3])
        raise LLMResponseError(
            f"Function arguments failed schema validation: {detail}",
            backend=backend,
            repaired=repaired,
        )
    try:
        spec.validate_business(arguments, payload)
    except ValueError as exc:
        raise LLMResponseError(
            f"Function arguments failed business validation: {exc}",
            backend=backend,
            repaired=repaired,
        ) from exc
    return ValidatedFunctionResult(arguments=arguments, repaired=repaired)
