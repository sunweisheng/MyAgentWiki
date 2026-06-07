from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


SEMANTIC_TASK_ITEM_TYPES = {
    "document_analysis": "normalized_document",
    "claim_role": "claim",
    "page_intent": "claim_group",
}


@dataclass
class SemanticTaskConfig:
    task_name: str
    strategy: str
    command: list[str]
    timeout_seconds: int
    min_confidence: float
    batch_size: int
    enabled: bool
    model_key: str
    prompt_version: str
    schema_version: str


def fingerprint_payload(task_name: str, item_payloads: list[dict], prompt_version: str, schema_version: str) -> str:
    raw = json.dumps(
        {
            "task_name": task_name,
            "items": item_payloads,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
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

