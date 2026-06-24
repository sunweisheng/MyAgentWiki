from __future__ import annotations

from pathlib import Path

from myagentwiki.app_services.page_semantic_helpers import (
    append_frontmatter_list,
    build_page_semantic_frontmatter_projection,
    enrich_claim_records_with_structure_context,
    format_frontmatter_scalar,
    prepare_page_semantic_context,
)


def test_build_page_semantic_frontmatter_projection_merges_claim_and_structure_signals() -> None:
    result = build_page_semantic_frontmatter_projection(
        [
            {
                "claim_id": "cl_1",
                "semantic_projection": {
                    "content_tags": ["ops"],
                    "semantic_features": [{"tag": "process", "strength": "medium"}],
                },
                "structure_context": {
                    "content_tag_counts": {"rules": 2},
                    "semantic_feature_counts": {"reference_structure": 1},
                },
            }
        ],
        {
            "metadata_key_counts": {"负责人": 1},
            "evidence_block_kind_counts": {"table_row": 1, "list_item_with_body": 1},
        },
        claim_semantic_projection=lambda record: dict(record.get("semantic_projection") or {}),
        normalize_string_list=lambda value: value if isinstance(value, list) else [],
        coerce_int=lambda value, default: int(value) if str(value).isdigit() else default,
        sorted_counter_dict=lambda counter, limit=8: {
            key: count
            for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
        },
    )

    assert result["content_tags"] == ["rules", "ops"]
    assert result["semantic_feature_tags"] == [
        "reference_structure",
        "local_heading_body",
        "metadata_fact",
        "process",
        "rules",
    ]


def test_enrich_claim_records_with_structure_context_delegates_structure_lookup(tmp_path: Path) -> None:
    calls: list[dict] = []

    result = enrich_claim_records_with_structure_context(
        tmp_path,
        [{"claim_id": "cl_1", "text": "示例"}],
        semantic_structure_records_by_id=lambda target: (
            {"ev_1": {"evidence_block_id": "ev_1"}},
            {"ku_1": {"knowledge_unit_id": "ku_1"}},
        ),
        claim_structure_context=lambda claim_record, evidence_blocks_by_id, knowledge_units_by_id: calls.append(
            {
                "claim_id": claim_record["claim_id"],
                "evidence_keys": sorted(evidence_blocks_by_id.keys()),
                "knowledge_keys": sorted(knowledge_units_by_id.keys()),
            }
        ) or {"semantic_feature_counts": {"rules": 1}},
    )

    assert calls == [
        {
            "claim_id": "cl_1",
            "evidence_keys": ["ev_1"],
            "knowledge_keys": ["ku_1"],
        }
    ]
    assert result == [
        {
            "claim_id": "cl_1",
            "text": "示例",
            "structure_context": {"semantic_feature_counts": {"rules": 1}},
        }
    ]


def test_prepare_page_semantic_context_reuses_enriched_claims_for_projection(tmp_path: Path) -> None:
    result = prepare_page_semantic_context(
        tmp_path,
        [{"claim_id": "cl_1", "text": "示例"}],
        enrich_claim_records_with_structure_context=lambda target, claim_records: [
            {
                **claim_records[0],
                "structure_context": {
                    "content_tag_counts": {"rules": 1},
                    "semantic_feature_counts": {"reference_structure": 1},
                },
            }
        ],
        page_route_structure_projection=lambda claim_records: {
            "metadata_key_counts": {"负责人": 1},
            "evidence_block_kind_counts": {"table_row": 1},
            "content_tag_counts": {"rules": 1},
        },
        build_page_semantic_frontmatter_projection=lambda claim_records, structure_projection: {
            "content_tags": list(structure_projection["content_tag_counts"].keys()),
            "semantic_feature_tags": sorted({
                *claim_records[0]["structure_context"]["semantic_feature_counts"].keys(),
                *structure_projection["metadata_key_counts"].keys(),
            }),
        },
    )

    assert result == {
        "claim_records": [
            {
                "claim_id": "cl_1",
                "text": "示例",
                "structure_context": {
                    "content_tag_counts": {"rules": 1},
                    "semantic_feature_counts": {"reference_structure": 1},
                },
            }
        ],
        "structure_projection": {
            "metadata_key_counts": {"负责人": 1},
            "evidence_block_kind_counts": {"table_row": 1},
            "content_tag_counts": {"rules": 1},
        },
        "semantic_frontmatter": {
            "content_tags": ["rules"],
            "semantic_feature_tags": ["reference_structure", "负责人"],
        },
    }


def test_append_frontmatter_list_renders_yaml_scalars() -> None:
    lines = ["---"]
    append_frontmatter_list(lines, "semantic_feature_tags", ["rules", "负责人", "a\"b", ""])

    assert format_frontmatter_scalar(True) == "true"
    assert format_frontmatter_scalar(3) == "3"
    assert format_frontmatter_scalar('a"b') == '"a\\"b"'
    assert lines == [
        "---",
        "semantic_feature_tags:",
        '  - "rules"',
        '  - "负责人"',
        '  - "a\\"b"',
    ]
