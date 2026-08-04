from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SEMANTIC_TASK_ITEM_TYPES = {
    "document_analysis": "normalized_document",
    "claim_candidate_quality": "claim_candidate",
    "claim_role": "claim",
    "page_intent": "claim_group",
    "page_route": "claim_group",
}

SEMANTIC_DECISION_STATUS_ACCEPTED = "accepted"
SEMANTIC_DECISION_STATUS_ABSTAINED = "abstained"
SEMANTIC_DECISION_STATUS_REJECTED = "rejected"

SEMANTIC_DECISION_STATUSES = {
    SEMANTIC_DECISION_STATUS_ACCEPTED,
    SEMANTIC_DECISION_STATUS_ABSTAINED,
    SEMANTIC_DECISION_STATUS_REJECTED,
}

SEMANTIC_TASK_CONTRACTS = {
    "document_analysis": {
        "decision_fields": ("document_kind", "structure_quality", "chunk_strategy_hint"),
        "optional_decision_fields": ("risk_flags", "content_tags"),
    },
    "claim_candidate_quality": {
        "decision_fields": ("quality_label", "review_required", "safe_auto_ready"),
        "optional_decision_fields": ("risk_flags", "content_tags"),
    },
    "claim_role": {
        "decision_fields": ("knowledge_role", "page_intent_hints", "concept_candidate_score"),
        "optional_decision_fields": ("risk_flags", "content_tags"),
    },
    "page_intent": {
        "decision_fields": ("page_intent",),
        "optional_decision_fields": (
            "route_target",
            "content_tags",
            "risk_flags",
            "supporting_ids",
            "rejected_alternatives",
        ),
    },
    "page_route": {
        "decision_fields": ("page_intent", "route_target", "route_reason"),
        "optional_decision_fields": ("supporting_ids", "risk_flags", "rejected_alternatives"),
    },
}


@dataclass
class SemanticTaskConfig:
    task_name: str
    strategy: str
    timeout_seconds: int
    min_confidence: float
    batch_size: int
    enabled: bool
    model_key: str
    prompt_version: str
    schema_version: str


def semantic_task_contract(task_name: str) -> dict:
    return SEMANTIC_TASK_CONTRACTS.get(task_name, {})


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = [value]
    normalized: list[str] = []
    for item in candidates:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def semantic_decision_contract_fields(task_name: str) -> tuple[str, ...]:
    contract = semantic_task_contract(task_name)
    return tuple(contract.get("decision_fields", ()))


def semantic_decision_missing_fields(task_name: str, decision: dict) -> list[str]:
    return [
        field
        for field in semantic_decision_contract_fields(task_name)
        if field not in decision
    ]


def normalize_semantic_model_decision(task_name: str, raw_decision: dict) -> dict:
    decision_payload = raw_decision.get("decision")
    decision_status = str(raw_decision.get("decision_status", "")).strip().lower()
    if not decision_status:
        decision_status = SEMANTIC_DECISION_STATUS_ACCEPTED

    if raw_decision.get("abstain") is True or decision_payload == "abstain":
        decision_status = SEMANTIC_DECISION_STATUS_ABSTAINED
        decision_payload = {}
    elif decision_status not in SEMANTIC_DECISION_STATUSES:
        decision_status = SEMANTIC_DECISION_STATUS_REJECTED

    if not isinstance(decision_payload, dict):
        decision_payload = {}
        decision_status = SEMANTIC_DECISION_STATUS_REJECTED

    risk_flags = normalize_string_list(raw_decision.get("risk_flags"))
    supporting_ids = normalize_string_list(raw_decision.get("supporting_ids"))
    abstain_reason = str(raw_decision.get("abstain_reason", "")).strip()

    missing_fields = semantic_decision_missing_fields(task_name, decision_payload)
    if decision_status == SEMANTIC_DECISION_STATUS_ACCEPTED and missing_fields:
        decision_status = SEMANTIC_DECISION_STATUS_REJECTED
        risk_flags = sorted(set([*risk_flags, "semantic_decision_missing_required_fields"]))
        if not abstain_reason:
            abstain_reason = f"missing_required_fields:{','.join(missing_fields)}"

    return {
        "decision": decision_payload,
        "decision_status": decision_status,
        "risk_flags": risk_flags,
        "supporting_ids": supporting_ids,
        "abstain_reason": abstain_reason,
        "missing_fields": missing_fields,
    }


def fingerprint_payload(
    task_name: str,
    item_payloads: list[dict],
    prompt_version: str,
    schema_version: str,
    route_identity: dict | None = None,
) -> str:
    raw = json.dumps(
        {
            "task_name": task_name,
            "items": item_payloads,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "route_identity": route_identity or {},
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_semantic_decision_id(task_name: str, input_fingerprint: str) -> str:
    return f"sem_{task_name}_{input_fingerprint[:16]}"


def item_type_for_task(task_name: str) -> str:
    return SEMANTIC_TASK_ITEM_TYPES.get(task_name, "unknown")


def semantic_batches_dir(target: Path) -> Path:
    return target / "semantic" / "batches"
