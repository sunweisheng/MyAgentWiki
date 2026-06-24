from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable


def load_query_page_records(
    target: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_page_lifecycle_defaults: Callable[[dict], dict],
) -> list[dict]:
    pages_path = target / "state" / "pages.jsonl"
    if not pages_path.exists():
        raise FileNotFoundError(f"Missing pages index: {pages_path}")
    return [
        ensure_page_lifecycle_defaults(record)
        for record in load_jsonl(pages_path)
    ]


def load_query_live_claim_records(
    target: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
    ensure_claim_lifecycle_defaults: Callable[[dict], dict],
    filter_live_claim_records: Callable[[list[dict]], list[dict]],
) -> list[dict]:
    claims_path = target / "state" / "claims.jsonl"
    if not claims_path.exists():
        return []
    claim_records = [
        ensure_claim_lifecycle_defaults(record)
        for record in load_jsonl(claims_path)
    ]
    return filter_live_claim_records(claim_records)


def load_chunk_records_by_id(
    target: Path,
    *,
    load_jsonl: Callable[[Path], list[dict]],
) -> dict[str, dict]:
    chunks_path = target / "state" / "chunks.jsonl"
    if not chunks_path.exists():
        return {}
    return {
        record["chunk_id"]: record
        for record in load_jsonl(chunks_path)
    }


def load_query_documents_from_search_index(index_records: list[dict]) -> list[dict]:
    documents: list[dict] = []
    for record in index_records:
        page_record = {
            "page_id": record["page_id"],
            "title": record.get("title", ""),
            "page_path": record.get("page_path", ""),
            "type": record.get("type", ""),
            "status": record.get("status", ""),
            "summary": record.get("summary", ""),
            "aliases": record.get("aliases", []),
            "canonical_id": record.get("canonical_id"),
            "claim_ids": record.get("claim_ids", []),
            "review_ids": record.get("review_ids", []),
            "source_refs": record.get("source_refs", []),
            "outgoing_page_ids": record.get("outgoing_page_ids", []),
            "incoming_page_ids": record.get("incoming_page_ids", []),
            "related_page_ids": record.get("related_page_ids", []),
        }
        documents.append({
            "page_record": page_record,
            "page_text": None,
            "field_texts": record.get("field_texts", {}),
            "field_tokens": record.get("field_tokens", {}),
        })
    return documents


def build_page_field_texts(
    page_record: dict,
    page_text: str,
    claim_records_by_id: dict[str, dict],
    *,
    parse_section_path: Callable[[str], dict],
    extract_markdown_headings: Callable[[str], list[str]],
    build_searchable_body_text: Callable[[str], str],
) -> dict[str, str]:
    claim_texts = []
    for claim_id in page_record.get("claim_ids", []):
        claim_record = claim_records_by_id.get(claim_id)
        if claim_record is None:
            continue
        claim_texts.append(claim_record.get("text", ""))

    source_ref_parts = []
    hierarchy_parts = []
    for source_ref in page_record.get("source_refs", []):
        source_ref_parts.append(source_ref.get("source_id", ""))
        source_ref_parts.append(source_ref.get("source_path", ""))
        hierarchy_parts.append(source_ref.get("section_path", ""))
        hierarchy_parts.append(source_ref.get("section_title", ""))
        hierarchy_parts.append(source_ref.get("parent_section_path", ""))
        section_path_parts = source_ref.get("section_path_parts", [])
        if isinstance(section_path_parts, list):
            hierarchy_parts.extend(str(part) for part in section_path_parts if str(part).strip())
        for chunk_ref in source_ref.get("chunks", []):
            chunk_section_path = chunk_ref.get("section_path", "")
            hierarchy_parts.append(chunk_section_path)
            parsed = parse_section_path(chunk_section_path)
            hierarchy_parts.extend(parsed.get("section_path_parts", []))
    hierarchy_parts.append(page_record.get("title", ""))
    hierarchy_parts.extend(page_record.get("aliases", []))

    return {
        "title": page_record.get("title", ""),
        "aliases": "\n".join(page_record.get("aliases", [])),
        "hierarchy": "\n".join(part for part in hierarchy_parts if part),
        "summary": page_record.get("summary", ""),
        "headings": "\n".join(extract_markdown_headings(page_text)),
        "body": build_searchable_body_text(page_text),
        "claim_text": "\n".join(claim_texts),
        "source_refs": "\n".join(source_ref_parts),
    }


def build_query_documents(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
    *,
    filter_live_page_records: Callable[[list[dict]], list[dict]],
    build_page_field_texts: Callable[[dict, str, dict[str, dict]], dict[str, str]],
    tokenize_for_search: Callable[[str], list[str]],
) -> list[dict]:
    documents: list[dict] = []
    for page_record in filter_live_page_records(page_records):
        page_path = target / page_record["page_path"]
        if not page_path.exists():
            continue
        page_text = page_path.read_text(encoding="utf-8")
        field_texts = build_page_field_texts(page_record, page_text, claim_records_by_id)
        field_tokens = {
            field_name: tokenize_for_search(field_text)
            for field_name, field_text in field_texts.items()
        }
        documents.append({
            "page_record": page_record,
            "page_text": page_text,
            "field_texts": field_texts,
            "field_tokens": field_tokens,
        })
    return documents


def build_search_index_record(
    document: dict,
    *,
    utc_now_iso: Callable[[], str],
    search_pages_index_version: str,
) -> dict:
    page_record = document["page_record"]
    field_texts = document["field_texts"]
    field_tokens = document["field_tokens"]
    signature_payload = {
        "page_path": page_record.get("page_path", ""),
        "title": page_record.get("title", ""),
        "type": page_record.get("type", ""),
        "status": page_record.get("status", ""),
        "summary": page_record.get("summary", ""),
        "aliases": page_record.get("aliases", []),
        "canonical_id": page_record.get("canonical_id"),
        "claim_ids": page_record.get("claim_ids", []),
        "review_ids": page_record.get("review_ids", []),
        "source_refs": page_record.get("source_refs", []),
        "outgoing_page_ids": page_record.get("outgoing_page_ids", []),
        "incoming_page_ids": page_record.get("incoming_page_ids", []),
        "related_page_ids": page_record.get("related_page_ids", []),
        "field_texts": field_texts,
    }
    document_signature = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "page_id": page_record["page_id"],
        "title": page_record.get("title", ""),
        "page_path": page_record.get("page_path", ""),
        "type": page_record.get("type", ""),
        "status": page_record.get("status", ""),
        "summary": page_record.get("summary", ""),
        "aliases": page_record.get("aliases", []),
        "canonical_id": page_record.get("canonical_id"),
        "claim_ids": page_record.get("claim_ids", []),
        "review_ids": page_record.get("review_ids", []),
        "source_refs": page_record.get("source_refs", []),
        "outgoing_page_ids": page_record.get("outgoing_page_ids", []),
        "incoming_page_ids": page_record.get("incoming_page_ids", []),
        "related_page_ids": page_record.get("related_page_ids", []),
        "field_texts": field_texts,
        "field_tokens": field_tokens,
        "page_signature": page_record.get("page_signature"),
        "document_signature": document_signature,
        "indexed_at": utc_now_iso(),
        "index_version": search_pages_index_version,
    }


def write_search_pages_index(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
    previous_records: list[dict] | None = None,
    *,
    search_pages_index_rel_path: str,
    search_pages_index_version: str,
    filter_live_page_records: Callable[[list[dict]], list[dict]],
    build_page_field_texts: Callable[[dict, str, dict[str, dict]], dict[str, str]],
    tokenize_for_search: Callable[[str], list[str]],
    write_jsonl: Callable[[Path, list[dict]], None],
    utc_now_iso: Callable[[], str],
) -> dict:
    index_path = target / search_pages_index_rel_path
    index_path.parent.mkdir(parents=True, exist_ok=True)
    previous_by_page_id = {
        record["page_id"]: record for record in (previous_records or [])
        if record.get("page_id")
    }
    records: list[dict] = []
    reused_count = 0
    rebuilt_count = 0

    for page_record in filter_live_page_records(page_records):
        previous_record = previous_by_page_id.get(page_record["page_id"])
        if (
            previous_record is not None
            and previous_record.get("page_signature") == page_record.get("page_signature")
            and previous_record.get("index_version") == search_pages_index_version
        ):
            records.append(dict(previous_record))
            reused_count += 1
            continue

        page_path = target / page_record["page_path"]
        if not page_path.exists():
            continue

        page_text = page_path.read_text(encoding="utf-8")
        field_texts = build_page_field_texts(page_record, page_text, claim_records_by_id)
        field_tokens = {
            field_name: tokenize_for_search(field_text)
            for field_name, field_text in field_texts.items()
        }
        record = build_search_index_record(
            {
                "page_record": page_record,
                "page_text": page_text,
                "field_texts": field_texts,
                "field_tokens": field_tokens,
            },
            utc_now_iso=utc_now_iso,
            search_pages_index_version=search_pages_index_version,
        )
        records.append(record)
        rebuilt_count += 1

    write_jsonl(index_path, records)
    return {
        "index_path": str(search_pages_index_rel_path),
        "record_count": len(records),
        "rebuilt_count": rebuilt_count,
        "reused_count": reused_count,
        "index_version": search_pages_index_version,
        "updated_at": utc_now_iso(),
    }


def ensure_query_documents(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
    *,
    load_search_pages_index: Callable[[Path], list[dict]],
    load_query_documents_from_search_index: Callable[[list[dict]], list[dict]],
    build_query_documents: Callable[[Path, list[dict], dict[str, dict]], list[dict]],
) -> tuple[list[dict], str]:
    index_records = load_search_pages_index(target)
    if index_records:
        return load_query_documents_from_search_index(index_records), "search_pages_index"
    return build_query_documents(target, page_records, claim_records_by_id), "live_scan"
