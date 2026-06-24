from __future__ import annotations

from pathlib import Path

from myagentwiki.app_services.claim_status_service import (
    ClaimSetStatusRequest,
    ClaimStatusServiceDeps,
    run_claim_set_status_service,
)
from myagentwiki.app_services.render_service import (
    RenderPageRequest,
    RenderPageServiceDeps,
    run_render_page_service,
)


def test_claim_status_service_updates_live_claim_and_rebuilds_pages(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    rebuild_calls: list[dict] = []
    live_claims = {
        "cl_1": {
            "claim_id": "cl_1",
            "status": "needs_review",
            "review_reason": "duplicate_candidate",
            "lifecycle_status": "active",
        }
    }
    live_reviews = {
        "rev_1": {
            "review_id": "rev_1",
            "candidate_claim_ids": ["cl_1"],
            "status": "open",
            "lifecycle_status": "active",
        }
    }

    result = run_claim_set_status_service(
        ClaimSetStatusRequest(
            target=workspace_dir,
            claim_id="cl_1",
            status="stable",
        ),
        deps=ClaimStatusServiceDeps(
            ensure_workspace_schema_supported=lambda target: None,
            load_claim_state_maps=lambda target: (live_claims, {}, list(live_claims.values())),
            load_review_state_maps=lambda target: (live_reviews, {}, list(live_reviews.values())),
            is_actionable_review_record=lambda record: record.get("status") == "open",
            utc_now_iso=lambda: "2026-06-24T00:00:00+00:00",
            rebuild_review_affected_pages=lambda **kwargs: rebuild_calls.append(kwargs),
        ),
    )

    assert result.payload["claim_id"] == "cl_1"
    assert result.payload["status"] == "stable"
    assert result.payload["active_review_ids"] == ["rev_1"]
    assert live_claims["cl_1"]["status"] == "stable"
    assert live_claims["cl_1"]["review_reason"] is None
    assert rebuild_calls and rebuild_calls[0]["target"] == workspace_dir


def test_render_page_service_rebuilds_and_returns_single_page_text(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    page_path = workspace_dir / "wiki" / "concept" / "sample.md"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text("# Sample\n\nPage body.\n", encoding="utf-8")

    rebuild_calls: list[dict] = []
    page_records = [
        {
            "page_id": "page_1",
            "title": "Sample",
            "render_target": "readable_concept",
            "canonical_id": "canon_sample",
            "status": "stable",
            "render_mode": "auto",
            "render_status": "rendered",
            "page_path": "wiki/concept/sample.md",
            "summary": "Sample summary",
            "claim_ids": ["cl_1"],
            "type": "concept",
        }
    ]

    result = run_render_page_service(
        RenderPageRequest(
            target=workspace_dir,
            render_target="readable_concept",
            page_id="page_1",
            canonical_id=None,
            claim_id=None,
        ),
        deps=RenderPageServiceDeps(
            ensure_workspace_schema_supported=lambda target: None,
            page_render_targets={
                "readable_concept": {
                    "rebuild_strategy": "review_affected_pages",
                }
            },
            load_claim_state_maps=lambda target: ({"cl_1": {"claim_id": "cl_1"}}, {}, []),
            load_review_state_maps=lambda target: ({}, {}, []),
            rebuild_review_affected_pages=lambda **kwargs: rebuild_calls.append(kwargs),
            load_page_state_records=lambda target: page_records,
            live_pages_for_render_target=lambda records, render_target: list(records),
            page_record_render_target=lambda record: record.get("render_target"),
        ),
    )

    assert rebuild_calls and rebuild_calls[0]["target"] == workspace_dir
    assert result.payload["summary"]["page_count"] == 1
    assert result.payload["pages"][0]["page_id"] == "page_1"
    assert result.payload["page_text"] == "# Sample\n\nPage body.\n"
