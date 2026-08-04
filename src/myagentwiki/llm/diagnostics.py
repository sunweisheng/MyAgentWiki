from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LLM_REQUEST_LOG_REL_PATH = Path("logs") / "llm_requests.jsonl"


def append_request_record(workspace: Path, record: dict[str, Any]) -> None:
    path = workspace / LLM_REQUEST_LOG_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
