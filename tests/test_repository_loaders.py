from __future__ import annotations

import json
from pathlib import Path

from myagentwiki.repositories.state_views import (
    build_claim_state_maps_loader,
    build_page_state_records_loader,
    build_review_state_maps_loader,
    load_alias_index,
    load_page_links_index,
)


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_state_view_loader_builders_split_live_and_historical_records(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    state_dir = workspace_dir / "state"
    write_jsonl(
        state_dir / "claims.jsonl",
        [
            {"claim_id": "cl_live", "lifecycle_status": "active"},
            {"claim_id": "cl_hist", "lifecycle_status": "archived"},
        ],
    )
    write_jsonl(
        state_dir / "reviews.jsonl",
        [
            {"review_id": "rev_live", "lifecycle_status": "active"},
            {"review_id": "rev_hist", "lifecycle_status": "superseded"},
        ],
    )
    write_jsonl(
        state_dir / "pages.jsonl",
        [
            {"page_id": "page_live", "lifecycle_status": "active"},
            {"page_id": "page_removed", "lifecycle_status": "removed"},
        ],
    )

    claim_loader = build_claim_state_maps_loader(
        load_jsonl=read_jsonl,
        ensure_claim_lifecycle_defaults=lambda record: {**record, "claim_ready": True},
        filter_live_claim_records=lambda records: [
            item for item in records if item.get("lifecycle_status") == "active"
        ],
        is_live_claim_record=lambda record: record.get("lifecycle_status") == "active",
    )
    review_loader = build_review_state_maps_loader(
        load_jsonl=read_jsonl,
        ensure_review_lifecycle_defaults=lambda record: {**record, "review_ready": True},
        filter_live_review_records=lambda records: [
            item for item in records if item.get("lifecycle_status") == "active"
        ],
        is_live_review_record=lambda record: record.get("lifecycle_status") == "active",
    )
    page_loader = build_page_state_records_loader(
        load_jsonl=read_jsonl,
        ensure_page_lifecycle_defaults=lambda record: {**record, "page_ready": True},
    )

    live_claims, historical_claims, claim_records = claim_loader(workspace_dir)
    live_reviews, historical_reviews, review_records = review_loader(workspace_dir)
    page_records = page_loader(workspace_dir)

    assert set(live_claims) == {"cl_live"}
    assert set(historical_claims) == {"cl_hist"}
    assert all(record["claim_ready"] is True for record in claim_records)

    assert set(live_reviews) == {"rev_live"}
    assert set(historical_reviews) == {"rev_hist"}
    assert all(record["review_ready"] is True for record in review_records)

    assert [record["page_id"] for record in page_records] == ["page_live", "page_removed"]
    assert all(record["page_ready"] is True for record in page_records)


def test_index_loaders_return_defaults_when_index_files_are_missing(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    alias_index = load_alias_index(
        workspace_dir,
        alias_index_rel_path=Path("indexes") / "aliases.json",
        default_index_version="aliases_v1",
    )
    page_links_index = load_page_links_index(
        workspace_dir,
        page_links_index_rel_path=Path("indexes") / "page_links.json",
        default_index_version="page_links_v1",
    )

    assert alias_index == {
        "index_version": "aliases_v1",
        "updated_at": None,
        "canonical_map": {},
        "alias_map": {},
        "conflicts": [],
    }
    assert page_links_index == {
        "index_version": "page_links_v1",
        "updated_at": None,
        "page_count": 0,
        "pages": {},
    }
