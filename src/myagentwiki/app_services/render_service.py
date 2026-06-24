from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .review_rebuild_service import ReviewRebuildRequest, ReviewRebuildServiceDeps, run_review_rebuild_service


@dataclass(frozen=True)
class RenderPageRequest:
    target: Path
    render_target: str
    page_id: str | None
    canonical_id: str | None
    claim_id: str | None


@dataclass(frozen=True)
class RenderPageServiceDeps:
    ensure_workspace_schema_supported: Callable[[Path], None]
    page_render_targets: dict[str, dict[str, Any]]
    load_claim_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]]
    load_review_state_maps: Callable[[Path], tuple[dict[str, dict], dict[str, dict], list[dict]]]
    rebuild_review_affected_pages: Callable[..., None]
    load_page_state_records: Callable[[Path], list[dict]]
    live_pages_for_render_target: Callable[[list[dict], str], list[dict]]
    page_record_render_target: Callable[[dict], str | None]


@dataclass(frozen=True)
class RenderPageServiceResult:
    payload: dict[str, Any]
    message: str


def run_render_page_service(
    request: RenderPageRequest,
    *,
    deps: RenderPageServiceDeps,
) -> RenderPageServiceResult:
    target = request.target
    deps.ensure_workspace_schema_supported(target)
    render_target = request.render_target
    render_target_spec = deps.page_render_targets.get(render_target)
    if render_target_spec is None:
        raise KeyError(f"Unknown render_target: {render_target}")

    if render_target_spec.get("rebuild_strategy") == "review_affected_pages":
        live_claims_by_id, _, _ = deps.load_claim_state_maps(target)
        live_reviews_by_id, _, _ = deps.load_review_state_maps(target)
        run_review_rebuild_service(
            ReviewRebuildRequest(
                target=target,
                live_claims_by_id=live_claims_by_id,
                live_reviews_by_id=live_reviews_by_id,
            ),
            deps=ReviewRebuildServiceDeps(
                rebuild_review_affected_pages_impl=lambda target, live_claims_by_id, live_reviews_by_id: deps.rebuild_review_affected_pages(
                    target=target,
                    live_claims_by_id=live_claims_by_id,
                    live_reviews_by_id=live_reviews_by_id,
                )
            ),
        )

    page_records = deps.load_page_state_records(target)
    live_rendered_pages = deps.live_pages_for_render_target(page_records, render_target)

    selected_pages = live_rendered_pages
    if request.page_id:
        selected_pages = [record for record in selected_pages if record.get("page_id") == request.page_id]
    elif request.canonical_id:
        selected_pages = [record for record in selected_pages if record.get("canonical_id") == request.canonical_id]
    elif request.claim_id:
        selected_pages = [record for record in selected_pages if request.claim_id in record.get("claim_ids", [])]

    if not selected_pages:
        raise KeyError(f"No page matched render_target={render_target} with the requested selector.")

    payload = {
        "workspace": str(target),
        "render_target": render_target,
        "pages": [
            {
                "page_id": record["page_id"],
                "title": record.get("title"),
                "render_target": record.get("render_target") or deps.page_record_render_target(record),
                "canonical_id": record.get("canonical_id"),
                "status": record.get("status"),
                "render_mode": record.get("render_mode"),
                "render_status": record.get("render_status"),
                "page_path": record.get("page_path"),
                "summary": record.get("summary"),
                "claim_ids": record.get("claim_ids", []),
            }
            for record in selected_pages
        ],
        "summary": {
            "page_count": len(selected_pages),
        },
    }
    if len(selected_pages) == 1:
        page_path = target / selected_pages[0]["page_path"]
        payload["page_text"] = page_path.read_text(encoding="utf-8")

    return RenderPageServiceResult(
        payload=payload,
        message=f"Rendered page target: {render_target}",
    )
