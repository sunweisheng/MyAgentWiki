from __future__ import annotations

from pathlib import Path
from typing import Callable


def load_semantic_decisions(
    target: Path,
    *,
    semantic_decisions_rel_path: Path,
    load_jsonl: Callable[[Path], list[dict]],
) -> list[dict]:
    path = target / semantic_decisions_rel_path
    if not path.exists():
        return []
    return load_jsonl(path)


def append_semantic_decision_records(
    target: Path,
    records: list[dict],
    *,
    semantic_decisions_rel_path: Path,
    append_jsonl: Callable[[Path, dict], None],
) -> None:
    path = target / semantic_decisions_rel_path
    for record in records:
        append_jsonl(path, record)


def build_latest_semantic_decisions_by_fingerprint(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in records:
        fingerprint = str(record.get("input_fingerprint", "")).strip()
        if not fingerprint:
            continue
        current = latest.get(fingerprint)
        if current is None or record.get("created_at", "") >= current.get("created_at", ""):
            latest[fingerprint] = record
    return latest
