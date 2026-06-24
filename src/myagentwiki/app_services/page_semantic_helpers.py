from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable


def build_page_semantic_frontmatter_projection(
    claim_records: list[dict],
    structure_projection: dict | None = None,
    *,
    claim_semantic_projection: Callable[[dict], dict],
    normalize_string_list: Callable[[Any], list[str]],
    coerce_int: Callable[[Any, int], int],
    sorted_counter_dict: Callable[[Counter[str], int], dict[str, int]],
) -> dict:
    content_tag_counter: Counter[str] = Counter()
    semantic_feature_counter: Counter[str] = Counter()

    for claim_record in claim_records:
        projection = claim_semantic_projection(claim_record)
        for tag in normalize_string_list(projection.get("content_tags")):
            content_tag_counter[tag] += 1

        context = claim_record.get("structure_context", {})
        if not isinstance(context, dict):
            context = {}
        content_tag_counter.update(dict(context.get("content_tag_counts", {}) or {}))
        semantic_feature_counter.update(dict(context.get("semantic_feature_counts", {}) or {}))

        for feature in projection.get("semantic_features", []) or []:
            if not isinstance(feature, dict):
                continue
            tag = str(feature.get("tag", "")).strip()
            if tag:
                semantic_feature_counter[tag] += 1

    if not isinstance(structure_projection, dict):
        structure_projection = {}

    content_tag_counter.update(dict(structure_projection.get("content_tag_counts", {}) or {}))
    metadata_key_counts = dict(structure_projection.get("metadata_key_counts", {}) or {})
    evidence_block_kind_counts = dict(structure_projection.get("evidence_block_kind_counts", {}) or {})
    if metadata_key_counts:
        semantic_feature_counter["metadata_fact"] += sum(
            max(coerce_int(count, 0), 1) for count in metadata_key_counts.values()
        )
    if coerce_int(evidence_block_kind_counts.get("table_row", 0), 0) > 0:
        semantic_feature_counter["rules"] += max(coerce_int(evidence_block_kind_counts.get("table_row", 0), 0), 1)
        semantic_feature_counter["reference_structure"] += max(
            coerce_int(evidence_block_kind_counts.get("table_row", 0), 0), 1
        )
    if coerce_int(evidence_block_kind_counts.get("code_example", 0), 0) > 0:
        semantic_feature_counter["cases"] += max(coerce_int(evidence_block_kind_counts.get("code_example", 0), 0), 1)
        semantic_feature_counter["example_structure"] += max(
            coerce_int(evidence_block_kind_counts.get("code_example", 0), 0), 1
        )
    if coerce_int(evidence_block_kind_counts.get("list_item_with_body", 0), 0) > 0:
        semantic_feature_counter["local_heading_body"] += max(
            coerce_int(evidence_block_kind_counts.get("list_item_with_body", 0), 0), 1
        )

    return {
        "content_tags": list(sorted_counter_dict(content_tag_counter, limit=8).keys()),
        "semantic_feature_tags": list(sorted_counter_dict(semantic_feature_counter, limit=8).keys()),
    }


def enrich_claim_records_with_structure_context(
    target: Path,
    claim_records: list[dict],
    *,
    semantic_structure_records_by_id: Callable[[Path], tuple[dict[str, dict], dict[str, dict]]],
    claim_structure_context: Callable[[dict, dict[str, dict], dict[str, dict]], dict],
) -> list[dict]:
    evidence_blocks_by_id, knowledge_units_by_id = semantic_structure_records_by_id(target)
    enriched_records: list[dict] = []
    for claim_record in claim_records:
        enriched_record = dict(claim_record)
        enriched_record["structure_context"] = claim_structure_context(
            enriched_record,
            evidence_blocks_by_id=evidence_blocks_by_id,
            knowledge_units_by_id=knowledge_units_by_id,
        )
        enriched_records.append(enriched_record)
    return enriched_records


def prepare_page_semantic_context(
    target: Path,
    claim_records: list[dict],
    *,
    enrich_claim_records_with_structure_context: Callable[[Path, list[dict]], list[dict]],
    page_route_structure_projection: Callable[[list[dict]], dict],
    build_page_semantic_frontmatter_projection: Callable[[list[dict], dict | None], dict],
) -> dict:
    enriched_claim_records = enrich_claim_records_with_structure_context(target, claim_records)
    structure_projection = page_route_structure_projection(enriched_claim_records)
    semantic_frontmatter = build_page_semantic_frontmatter_projection(
        enriched_claim_records,
        structure_projection,
    )
    return {
        "claim_records": enriched_claim_records,
        "structure_projection": structure_projection,
        "semantic_frontmatter": semantic_frontmatter,
    }


def format_frontmatter_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def append_frontmatter_list(lines: list[str], key: str, values: list[str]) -> None:
    normalized_values = [
        str(value).strip()
        for value in values
        if str(value).strip()
    ]
    if not normalized_values:
        return
    lines.append(f"{key}:")
    for value in normalized_values:
        lines.append(f"  - {format_frontmatter_scalar(value)}")
