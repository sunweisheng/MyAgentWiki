from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class SemanticBatchRequest:
    target: Path
    task: str
    dry_run: bool


@dataclass(frozen=True)
class SemanticBatchServiceDeps:
    ensure_workspace_schema_supported: Callable[[Path], None]
    run_semantic_batch_task: Callable[..., dict[str, Any]]
    render_workspace_summary_message: Callable[..., str]


@dataclass(frozen=True)
class SemanticBatchServiceResult:
    payload: dict[str, Any]
    message: str


def run_semantic_batch_service(
    request: SemanticBatchRequest,
    *,
    deps: SemanticBatchServiceDeps,
) -> SemanticBatchServiceResult:
    target = request.target
    deps.ensure_workspace_schema_supported(target)
    payload = deps.run_semantic_batch_task(
        target=target,
        task_name=request.task,
        dry_run=bool(request.dry_run),
    )
    return SemanticBatchServiceResult(
        payload=payload,
        message=deps.render_workspace_summary_message(
            f"Semantic batch completed: {request.task}",
            target_dir=target,
            extra_lines=[
                (
                    "Summary: "
                    f"items={payload['summary']['item_count']}, "
                    f"cache_hits={payload['summary']['cache_hits']}, "
                    f"pending_batches={payload['summary']['pending_batch_count']}, "
                    f"written_decisions={payload['summary']['written_decision_count']}, "
                    f"dry_run={'yes' if payload['summary']['dry_run'] else 'no'}"
                ),
            ],
        ),
    )
