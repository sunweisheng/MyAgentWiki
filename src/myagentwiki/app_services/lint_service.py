from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class LintRequest:
    target_dir: str | None


@dataclass(frozen=True)
class LintServiceDeps:
    find_project_root: Callable[[], Path]
    workspace_schema_guard_payload: Callable[[Path], dict[str, Any]]
    load_simple_yaml: Callable[[Path], dict[str, Any]]
    resolve_workspace_path: Callable[[Path, str], Path]
    load_jsonl: Callable[[Path], list[dict]]
    load_semantic_decisions: Callable[[Path], list[dict]]
    ensure_claim_lifecycle_defaults: Callable[[dict], dict]
    filter_live_claim_records: Callable[[list[dict]], list[dict]]
    is_live_claim_record: Callable[[dict], bool]
    ensure_review_lifecycle_defaults: Callable[[dict], dict]
    filter_live_review_records: Callable[[list[dict]], list[dict]]
    is_live_review_record: Callable[[dict], bool]
    load_page_state_records: Callable[..., list[dict]]
    ensure_page_lifecycle_defaults: Callable[[dict], dict]
    filter_live_page_records: Callable[[list[dict]], list[dict]]
    is_live_page_record: Callable[[dict], bool]
    claim_semantic_risk_issues: Callable[[dict, dict[str, dict]], list[str]]
    rendered_page_grounding_issues: Callable[..., list[str]]
    concept_page_quality_issues: Callable[[dict, dict[str, dict]], list[str]]
    page_semantic_consistency_issues: Callable[[dict, dict[str, dict]], list[str]]
    page_intent_brake_issues: Callable[[dict], list[str]]
    load_alias_index: Callable[[Path], dict[str, Any]]
    alias_index_path: Callable[[Path], Path]
    unresolved_alias_conflicts: Callable[[dict[str, Any]], list[Any]]
    load_search_pages_index: Callable[[Path], list[dict]]
    atomic_write_text: Callable[..., None]
    build_workspace_summary: Callable[..., dict[str, Any]]
    render_workspace_summary_message: Callable[..., str]
    alias_index_rel_path: str
    search_pages_index_rel_path: str
    structure_blocks_rel_path: str
    evidence_blocks_rel_path: str
    knowledge_units_rel_path: str
    semantic_decisions_rel_path: str


@dataclass(frozen=True)
class LintServiceResult:
    exit_code: int
    payload: dict[str, Any]
    message: str


def _increment_source_counter(counter: dict[str, int], source_id: str) -> None:
    if not source_id:
        return
    counter[source_id] = counter.get(source_id, 0) + 1


def _collect_claim_coverage_sets(
    live_claim_records: list[dict],
) -> tuple[dict[str, int], set[str], set[str]]:
    live_claim_count_by_source: dict[str, int] = {}
    claimed_knowledge_unit_ids: set[str] = set()
    claimed_evidence_block_ids: set[str] = set()

    for claim_record in live_claim_records:
        source_ids = claim_record.get("source_ids", [])
        if isinstance(source_ids, list):
            for source_id in source_ids:
                if isinstance(source_id, str) and source_id.strip():
                    _increment_source_counter(live_claim_count_by_source, source_id.strip())

        for knowledge_unit_id in claim_record.get("knowledge_unit_ids", []):
            if isinstance(knowledge_unit_id, str) and knowledge_unit_id.strip():
                claimed_knowledge_unit_ids.add(knowledge_unit_id.strip())
        for evidence_block_id in claim_record.get("evidence_block_ids", []):
            if isinstance(evidence_block_id, str) and evidence_block_id.strip():
                claimed_evidence_block_ids.add(evidence_block_id.strip())

        source_refs = claim_record.get("source_refs", [])
        if not isinstance(source_refs, list):
            continue
        for source_ref in source_refs:
            if not isinstance(source_ref, dict):
                continue
            source_id = str(source_ref.get("source_id", "")).strip()
            if source_id:
                _increment_source_counter(live_claim_count_by_source, source_id)
            knowledge_unit_id = str(source_ref.get("knowledge_unit_id", "")).strip()
            if knowledge_unit_id:
                claimed_knowledge_unit_ids.add(knowledge_unit_id)
            for evidence_block_id in source_ref.get("evidence_block_ids", []):
                if isinstance(evidence_block_id, str) and evidence_block_id.strip():
                    claimed_evidence_block_ids.add(evidence_block_id.strip())

    return live_claim_count_by_source, claimed_knowledge_unit_ids, claimed_evidence_block_ids


def _collect_structured_claim_coverage_gaps(
    knowledge_unit_records: list[dict],
    evidence_block_records: list[dict],
    claimed_knowledge_unit_ids: set[str],
    claimed_evidence_block_ids: set[str],
) -> list[dict[str, Any]]:
    evidence_blocks_by_id = {
        str(record.get("evidence_block_id", "")).strip(): record
        for record in evidence_block_records
        if str(record.get("evidence_block_id", "")).strip()
    }
    suspicious_block_kinds = {"metadata_line", "table_row", "list_item_with_body"}
    suspicious_unit_kinds = {"metadata_fact", "table_fact", "statement"}
    gaps: list[dict[str, Any]] = []
    generic_table_header_cells = {"字段", "值", "名称", "说明", "内容", "key", "value"}

    for knowledge_unit_record in knowledge_unit_records:
        if knowledge_unit_record.get("lifecycle_status", "active") != "active":
            continue
        knowledge_unit_id = str(knowledge_unit_record.get("knowledge_unit_id", "")).strip()
        if not knowledge_unit_id or knowledge_unit_id in claimed_knowledge_unit_ids:
            continue

        unit_kind = str(knowledge_unit_record.get("unit_kind", "")).strip()
        if unit_kind not in suspicious_unit_kinds:
            continue

        evidence_block_ids = [
            str(item).strip()
            for item in knowledge_unit_record.get("evidence_block_ids", [])
            if str(item).strip()
        ]
        if evidence_block_ids and any(evidence_block_id in claimed_evidence_block_ids for evidence_block_id in evidence_block_ids):
            continue

        evidence_blocks = [
            evidence_blocks_by_id[evidence_block_id]
            for evidence_block_id in evidence_block_ids
            if evidence_block_id in evidence_blocks_by_id
        ]
        evidence_block_kinds = {
            str(record.get("block_kind", "")).strip()
            for record in evidence_blocks
            if str(record.get("block_kind", "")).strip()
        }
        metadata = knowledge_unit_record.get("metadata", {})
        if unit_kind == "table_fact" and isinstance(metadata, dict):
            cells = [
                str(cell).strip()
                for cell in metadata.get("cells", [])
                if str(cell).strip()
            ]
            if cells and all(cell.lower() in generic_table_header_cells for cell in cells):
                continue
        has_metadata = isinstance(metadata, dict) and any(
            str(key).strip() and key != "section_path_parts"
            for key in metadata
        )
        if not has_metadata and not (evidence_block_kinds & suspicious_block_kinds):
            continue

        text = str(knowledge_unit_record.get("text", "")).strip()
        if not text:
            continue

        section_path_parts = metadata.get("section_path_parts", []) if isinstance(metadata, dict) else []
        gaps.append({
            "source_id": str(knowledge_unit_record.get("source_id", "")).strip(),
            "knowledge_unit_id": knowledge_unit_id,
            "unit_kind": unit_kind,
            "evidence_block_ids": evidence_block_ids,
            "evidence_block_kinds": sorted(evidence_block_kinds),
            "section_path_parts": section_path_parts if isinstance(section_path_parts, list) else [],
            "text_preview": text[:120],
        })

    return gaps


def _build_structure_coverage_rows(
    *,
    source_records: list[dict],
    normalized_records: list[dict],
    structure_block_records: list[dict],
    evidence_block_records: list[dict],
    knowledge_unit_records: list[dict],
    chunk_records: list[dict],
    live_claim_count_by_source: dict[str, int],
    structured_claim_coverage_gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_by_source_id = {
        str(record.get("source_id", "")).strip(): record
        for record in normalized_records
        if str(record.get("source_id", "")).strip()
    }
    source_record_by_id = {
        str(record.get("source_id", "")).strip(): record
        for record in source_records
        if str(record.get("source_id", "")).strip()
    }

    structure_count_by_source: dict[str, int] = {}
    evidence_count_by_source: dict[str, int] = {}
    knowledge_count_by_source: dict[str, int] = {}
    chunk_count_by_source: dict[str, int] = {}
    gap_count_by_source: dict[str, int] = {}

    for record in structure_block_records:
        _increment_source_counter(structure_count_by_source, str(record.get("source_id", "")).strip())
    for record in evidence_block_records:
        _increment_source_counter(evidence_count_by_source, str(record.get("source_id", "")).strip())
    for record in knowledge_unit_records:
        if record.get("lifecycle_status", "active") != "active":
            continue
        _increment_source_counter(knowledge_count_by_source, str(record.get("source_id", "")).strip())
    for record in chunk_records:
        _increment_source_counter(chunk_count_by_source, str(record.get("source_id", "")).strip())
    for record in structured_claim_coverage_gaps:
        _increment_source_counter(gap_count_by_source, str(record.get("source_id", "")).strip())

    all_source_ids = set(source_record_by_id) | set(normalized_by_source_id)
    rows: list[dict[str, Any]] = []
    for source_id in sorted(all_source_ids):
        source_record = source_record_by_id.get(source_id, {})
        normalized_record = normalized_by_source_id.get(source_id, {})
        structure_block_count = structure_count_by_source.get(source_id, 0)
        evidence_block_count = evidence_count_by_source.get(source_id, 0)
        knowledge_unit_count = knowledge_count_by_source.get(source_id, 0)
        chunk_count = chunk_count_by_source.get(source_id, 0)
        live_claim_count = live_claim_count_by_source.get(source_id, 0)
        uncovered_knowledge_unit_count = gap_count_by_source.get(source_id, 0)
        normalized = bool(normalized_record)
        pipeline_complete = (
            not normalized
            or (
                structure_block_count > 0
                and evidence_block_count > 0
                and knowledge_unit_count > 0
                and chunk_count > 0
            )
        )
        rows.append({
            "source_id": source_id,
            "source_path": source_record.get("source_path") or normalized_record.get("source_path"),
            "status": source_record.get("status", "unknown"),
            "normalized": normalized,
            "document_kind": normalized_record.get("document_kind"),
            "structure_block_count": structure_block_count,
            "evidence_block_count": evidence_block_count,
            "knowledge_unit_count": knowledge_unit_count,
            "chunk_count": chunk_count,
            "live_claim_count": live_claim_count,
            "uncovered_structured_unit_count": uncovered_knowledge_unit_count,
            "structured_pipeline_complete": pipeline_complete,
        })

    return rows


def _classify_structured_claim_coverage_gap(record: dict[str, Any]) -> str:
    unit_kind = str(record.get("unit_kind", "")).strip()
    evidence_block_kinds = {
        str(item).strip()
        for item in record.get("evidence_block_kinds", [])
        if str(item).strip()
    }
    if unit_kind == "metadata_fact" or "metadata_line" in evidence_block_kinds:
        return "metadata_fact_missing_claim"
    if unit_kind == "table_fact" or "table_row" in evidence_block_kinds:
        return "table_fact_missing_claim"
    if unit_kind == "statement" and "list_item_with_body" in evidence_block_kinds:
        return "structured_statement_missing_claim"
    if unit_kind == "statement":
        return "statement_missing_claim"
    return "other_structured_gap"


def _summarize_structure_gap_classes(
    structured_claim_coverage_gaps: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in structured_claim_coverage_gaps:
        gap_class = _classify_structured_claim_coverage_gap(record)
        counts[gap_class] = counts.get(gap_class, 0) + 1
    return counts


def _collect_intentional_structure_skips(
    knowledge_unit_records: list[dict],
    evidence_block_records: list[dict],
) -> dict[str, int]:
    counts = {
        "structural_shell_units": 0,
        "code_example_units": 0,
        "section_heading_blocks": 0,
        "code_example_blocks": 0,
    }
    for record in knowledge_unit_records:
        if record.get("lifecycle_status", "active") != "active":
            continue
        unit_kind = str(record.get("unit_kind", "")).strip()
        if unit_kind == "structural_shell":
            counts["structural_shell_units"] += 1
        elif unit_kind == "code_example":
            counts["code_example_units"] += 1
    for record in evidence_block_records:
        block_kind = str(record.get("block_kind", "")).strip()
        if block_kind == "section_heading":
            counts["section_heading_blocks"] += 1
        elif block_kind == "code_example":
            counts["code_example_blocks"] += 1
    return counts


def run_lint_service(
    request: LintRequest,
    *,
    deps: LintServiceDeps,
) -> LintServiceResult:
    root = deps.find_project_root()
    target = Path(request.target_dir).expanduser().resolve() if request.target_dir else root

    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, details: str, severity: str = "error") -> None:
        checks.append({
            "name": name,
            "ok": ok,
            "severity": severity,
            "details": details,
        })

    if target == root:
        add_check("project_root", True, "Linting repository root scaffold.", severity="info")
        required_paths = [
            "README.md",
            "docs/MyAgentWiki系统详细设计.md",
            "pyproject.toml",
            "config/runtime_manifest.yml",
            "src/myagentwiki/cli.py",
            "templates/project/config/project.yml.tmpl",
        ]
    else:
        schema_guard_payload = deps.workspace_schema_guard_payload(target)
        add_check("workspace_target", True, f"Linting initialized workspace: {target}", severity="info")
        add_check(
            name="workspace_schema_supported",
            ok=schema_guard_payload.get("status") == "supported",
            details=(
                f"workspace.schema_version={schema_guard_payload.get('workspace_schema_version')} "
                f"(expected={schema_guard_payload.get('expected_schema_version')})"
            ),
        )
        required_paths = [
            "wiki/index.md",
            "wiki/log.md",
            "config/project.yml",
            "AGENTS.md",
            "CLAUDE.md",
            deps.alias_index_rel_path,
        ]

    for rel_path in required_paths:
        path = target / rel_path
        add_check(
            name=f"path_exists:{rel_path}",
            ok=path.exists(),
            details=f"Expected path: {path}",
        )

    if target != root:
        live_claim_records: list[dict] = []
        claim_records_by_id: dict[str, dict] = {}
        config_path = target / "config" / "project.yml"
        raw_dir = (
            deps.resolve_workspace_path(target, deps.load_simple_yaml(config_path)["paths"]["raw"])
            if config_path.exists()
            else target / "raw"
        )
        add_check(
            name="raw_exists",
            ok=raw_dir.exists(),
            details="The raw directory should exist next to the workspace.",
        )
        add_check(
            name="git_initialized",
            ok=(target / ".git").exists(),
            details="Initialized workspace should have a git repository.",
        )
        add_check(
            name="state_sources_exists",
            ok=(target / "state" / "sources.jsonl").exists(),
            details="Workspace should contain state/sources.jsonl.",
        )
        add_check(
            name="state_ingest_state_exists",
            ok=(target / "state" / "ingest_state.jsonl").exists(),
            details="Workspace should contain state/ingest_state.jsonl.",
        )
        add_check(
            name="state_normalized_exists",
            ok=(target / "state" / "normalized.jsonl").exists(),
            details="Workspace should contain state/normalized.jsonl.",
        )
        add_check(
            name="state_structure_blocks_exists",
            ok=(target / deps.structure_blocks_rel_path).exists(),
            details=f"Workspace should contain {target / deps.structure_blocks_rel_path}.",
        )
        add_check(
            name="state_evidence_blocks_exists",
            ok=(target / deps.evidence_blocks_rel_path).exists(),
            details=f"Workspace should contain {target / deps.evidence_blocks_rel_path}.",
        )
        add_check(
            name="state_knowledge_units_exists",
            ok=(target / deps.knowledge_units_rel_path).exists(),
            details=f"Workspace should contain {target / deps.knowledge_units_rel_path}.",
        )
        add_check(
            name="state_chunks_exists",
            ok=(target / "state" / "chunks.jsonl").exists(),
            details="Workspace should contain state/chunks.jsonl.",
        )
        add_check(
            name="state_claims_exists",
            ok=(target / "state" / "claims.jsonl").exists(),
            details="Workspace should contain state/claims.jsonl.",
        )
        add_check(
            name="state_reviews_exists",
            ok=(target / "state" / "reviews.jsonl").exists(),
            details="Workspace should contain state/reviews.jsonl.",
        )
        add_check(
            name="state_error_log_exists",
            ok=(target / "state" / "error_log.jsonl").exists(),
            details="Workspace should contain state/error_log.jsonl.",
        )
        add_check(
            name="state_pages_exists",
            ok=(target / "state" / "pages.jsonl").exists(),
            details="Workspace should contain state/pages.jsonl.",
        )
        add_check(
            name="index_search_pages_exists",
            ok=(target / deps.search_pages_index_rel_path).exists(),
            details=f"Workspace should contain {target / deps.search_pages_index_rel_path}.",
        )
        add_check(
            name="index_aliases_exists",
            ok=deps.alias_index_path(target).exists(),
            details=f"Workspace should contain {deps.alias_index_path(target)}.",
        )

        chunk_records = (
            deps.load_jsonl(target / "state" / "chunks.jsonl")
            if (target / "state" / "chunks.jsonl").exists()
            else []
        )
        source_records = (
            deps.load_jsonl(target / "state" / "sources.jsonl")
            if (target / "state" / "sources.jsonl").exists()
            else []
        )
        normalized_records = (
            deps.load_jsonl(target / "state" / "normalized.jsonl")
            if (target / "state" / "normalized.jsonl").exists()
            else []
        )
        structure_block_records = (
            deps.load_jsonl(target / deps.structure_blocks_rel_path)
            if (target / deps.structure_blocks_rel_path).exists()
            else []
        )
        if structure_block_records:
            structure_block_ids = [record.get("structure_block_id") for record in structure_block_records]
            add_check(
                name="structure_block_ids_unique",
                ok=len(structure_block_ids) == len(set(structure_block_ids)),
                details=f"All structure_block_id values in {deps.structure_blocks_rel_path} should be unique.",
            )

        evidence_block_records = (
            deps.load_jsonl(target / deps.evidence_blocks_rel_path)
            if (target / deps.evidence_blocks_rel_path).exists()
            else []
        )
        if evidence_block_records:
            evidence_block_ids = [record.get("evidence_block_id") for record in evidence_block_records]
            add_check(
                name="evidence_block_ids_unique",
                ok=len(evidence_block_ids) == len(set(evidence_block_ids)),
                details=f"All evidence_block_id values in {deps.evidence_blocks_rel_path} should be unique.",
            )
            add_check(
                name="evidence_blocks_trace_structure",
                ok=all(record.get("structure_block_ids") for record in evidence_block_records),
                details="Each evidence block should point back to at least one structure block.",
            )

        knowledge_unit_records = (
            deps.load_jsonl(target / deps.knowledge_units_rel_path)
            if (target / deps.knowledge_units_rel_path).exists()
            else []
        )
        if knowledge_unit_records:
            knowledge_unit_ids = [record.get("knowledge_unit_id") for record in knowledge_unit_records]
            add_check(
                name="knowledge_unit_ids_unique",
                ok=len(knowledge_unit_ids) == len(set(knowledge_unit_ids)),
                details=f"All knowledge_unit_id values in {deps.knowledge_units_rel_path} should be unique.",
            )
            add_check(
                name="knowledge_units_trace_evidence",
                ok=all(record.get("evidence_block_ids") for record in knowledge_unit_records),
                details="Each knowledge unit should point back to at least one evidence block.",
            )

        if chunk_records:
            chunk_ids = [record.get("chunk_id") for record in chunk_records]
            add_check(
                name="chunk_ids_unique",
                ok=len(chunk_ids) == len(set(chunk_ids)),
                details="All chunk_id values in state/chunks.jsonl should be unique.",
            )

        claim_records = (
            deps.load_jsonl(target / "state" / "claims.jsonl")
            if (target / "state" / "claims.jsonl").exists()
            else []
        )
        semantic_decision_records = (
            deps.load_semantic_decisions(target)
            if (target / deps.semantic_decisions_rel_path).exists()
            else []
        )
        semantic_decisions_by_id = {
            str(record.get("decision_id", "")).strip(): record
            for record in semantic_decision_records
            if str(record.get("decision_id", "")).strip()
        }
        if claim_records:
            claim_records = [deps.ensure_claim_lifecycle_defaults(record) for record in claim_records]
            live_claim_records = deps.filter_live_claim_records(claim_records)
            claim_records_by_id = {record["claim_id"]: record for record in live_claim_records}
            (
                live_claim_count_by_source,
                claimed_knowledge_unit_ids,
                claimed_evidence_block_ids,
            ) = _collect_claim_coverage_sets(live_claim_records)
            historical_claim_records = [
                record for record in claim_records
                if not deps.is_live_claim_record(record)
            ]
            claim_ids = [record.get("claim_id") for record in claim_records]
            add_check(
                name="claim_ids_unique",
                ok=len(claim_ids) == len(set(claim_ids)),
                details="All claim_id values in state/claims.jsonl should be unique.",
            )
            add_check(
                name="live_claim_source_refs_present",
                ok=all(record.get("source_refs") for record in live_claim_records),
                details="Each live claim should keep at least one source_ref for traceability.",
            )
            add_check(
                name="live_claim_source_ids_present",
                ok=all(record.get("source_ids") for record in live_claim_records),
                details="Each live claim should keep at least one source_id.",
            )
            add_check(
                name="historical_claims_not_live",
                ok=all(record.get("lifecycle_status") in {"superseded", "archived"} for record in historical_claim_records),
                details="Historical claim records should not remain in active lifecycle state.",
            )
            claim_semantic_risk_issues_by_id = {
                record["claim_id"]: deps.claim_semantic_risk_issues(record, semantic_decisions_by_id)
                for record in live_claim_records
            }
            claim_semantic_risk_issues_by_id = {
                claim_id: issues
                for claim_id, issues in claim_semantic_risk_issues_by_id.items()
                if issues
            }
            claim_semantic_risk_preview = ", ".join(
                issues[0]
                for issues in list(claim_semantic_risk_issues_by_id.values())[:8]
            ) or "No live claims carry unreviewed ambiguous semantic decision risk flags."
            add_check(
                name="claim_semantic_risk_flags_reviewed",
                ok=len(claim_semantic_risk_issues_by_id) == 0,
                details=claim_semantic_risk_preview,
                severity="warning",
            )
        else:
            live_claim_count_by_source = {}
            claimed_knowledge_unit_ids = set()
            claimed_evidence_block_ids = set()

        structured_claim_coverage_gaps = _collect_structured_claim_coverage_gaps(
            knowledge_unit_records,
            evidence_block_records,
            claimed_knowledge_unit_ids,
            claimed_evidence_block_ids,
        )
        structured_gap_class_counts = _summarize_structure_gap_classes(
            structured_claim_coverage_gaps
        )
        intentional_structure_skip_counts = _collect_intentional_structure_skips(
            knowledge_unit_records,
            evidence_block_records,
        )
        structure_coverage_rows = _build_structure_coverage_rows(
            source_records=source_records,
            normalized_records=normalized_records,
            structure_block_records=structure_block_records,
            evidence_block_records=evidence_block_records,
            knowledge_unit_records=knowledge_unit_records,
            chunk_records=chunk_records,
            live_claim_count_by_source=live_claim_count_by_source,
            structured_claim_coverage_gaps=structured_claim_coverage_gaps,
        )
        incomplete_structure_rows = [
            row for row in structure_coverage_rows
            if row["normalized"] and not row["structured_pipeline_complete"]
        ]
        incomplete_structure_preview = ", ".join(
            f"{row['source_id']}:sb={row['structure_block_count']},ev={row['evidence_block_count']},ku={row['knowledge_unit_count']},chunk={row['chunk_count']}"
            for row in incomplete_structure_rows[:8]
        ) or "All normalized sources completed the structure -> evidence -> knowledge -> chunk chain."
        add_check(
            name="structured_pipeline_complete",
            ok=len(incomplete_structure_rows) == 0,
            details=incomplete_structure_preview,
        )
        structured_gap_preview = ", ".join(
            f"{_classify_structured_claim_coverage_gap(item)}:{item['knowledge_unit_id']}:{item['text_preview']}"
            for item in structured_claim_coverage_gaps[:8]
        ) or "No high-signal structured knowledge units look missing from live claims."
        add_check(
            name="structured_claim_coverage_reviewed",
            ok=len(structured_claim_coverage_gaps) == 0,
            details=structured_gap_preview,
            severity="warning",
        )

        review_records = (
            deps.load_jsonl(target / "state" / "reviews.jsonl")
            if (target / "state" / "reviews.jsonl").exists()
            else []
        )
        if review_records:
            review_records = [deps.ensure_review_lifecycle_defaults(record) for record in review_records]
            live_review_records = deps.filter_live_review_records(review_records)
            historical_review_records = [
                record for record in review_records
                if not deps.is_live_review_record(record)
            ]
            review_ids = [record.get("review_id") for record in review_records]
            add_check(
                name="review_ids_unique",
                ok=len(review_ids) == len(set(review_ids)),
                details="All review_id values in state/reviews.jsonl should be unique.",
            )
            add_check(
                name="live_review_candidate_claims_present",
                ok=all(
                    record.get("candidate_claim_ids") or record.get("kind") == "alias_conflict"
                    for record in live_review_records
                ),
                details="Claim-oriented live reviews should contain candidate_claim_ids; alias_conflict may use candidate_page_ids only.",
            )
            add_check(
                name="live_review_candidate_pages_present",
                ok=all("candidate_page_ids" in record for record in live_review_records),
                details="Each live review record should contain candidate_page_ids for reverse page lookup.",
            )
            add_check(
                name="historical_reviews_not_live",
                ok=all(record.get("lifecycle_status") in {"superseded", "archived"} for record in historical_review_records),
                details="Historical review records should not remain in active lifecycle state.",
            )

        page_records = deps.load_page_state_records(target)
        if page_records:
            live_page_records = deps.filter_live_page_records(page_records)
            removed_page_records = [
                record for record in page_records
                if record.get("lifecycle_status") == "removed"
            ]
            page_ids = [record.get("page_id") for record in page_records]
            add_check(
                name="page_ids_unique",
                ok=len(page_ids) == len(set(page_ids)),
                details="All page_id values in state/pages.jsonl should be unique.",
            )
            add_check(
                name="page_paths_present",
                ok=all(record.get("page_path") for record in page_records),
                details="Each page record should include page_path.",
            )
            add_check(
                name="page_titles_present",
                ok=all(record.get("title") for record in live_page_records),
                details="Each live page should include title.",
            )
            add_check(
                name="page_types_present",
                ok=all(record.get("type") for record in live_page_records),
                details="Each live page should include type.",
            )
            add_check(
                name="page_canonical_ids_present",
                ok=all(record.get("canonical_id") for record in live_page_records),
                details="Each live page should include canonical_id.",
            )
            add_check(
                name="live_pages_exist_on_disk",
                ok=all((target / record["page_path"]).exists() for record in live_page_records),
                details="Each live page record should have a corresponding wiki markdown file on disk.",
            )
            add_check(
                name="removed_pages_absent_on_disk",
                ok=all(not (target / record["page_path"]).exists() for record in removed_page_records),
                details="Removed page records should keep history in state/pages.jsonl, but their markdown files should already be deleted.",
            )
            add_check(
                name="removed_pages_not_in_live_set",
                ok=all(not deps.is_live_page_record(record) for record in removed_page_records),
                details="Removed page records should not be treated as live pages for index/query rebuilds.",
            )

            canonical_groups: dict[str, list[str]] = {}
            live_page_records_by_id = {record["page_id"]: record for record in live_page_records}
            for record in live_page_records:
                canonical_id = record.get("canonical_id")
                if not canonical_id:
                    continue
                canonical_groups.setdefault(canonical_id, []).append(record.get("type", ""))
            add_check(
                name="canonical_page_family_valid",
                ok=all(
                    len(page_types) == len(set(page_types))
                    and len(page_types) == 1
                    for page_types in canonical_groups.values()
                ),
                details="Each canonical_id should map to at most one live page type.",
            )
            concept_pages = [record for record in live_page_records if record.get("type") == "concept"]
            concept_like_pages = [
                record for record in live_page_records
                if record.get("type") == "concept"
            ]
            add_check(
                name="readable_concept_render_metadata_present",
                ok=all(
                    record.get("render_target") and record.get("render_mode") and record.get("render_status")
                    for record in concept_pages
                ),
                details="Each readable concept page should record render_target, render_mode and render_status for traceability.",
            )
            grounded_concept_issues = {
                record["page_id"]: deps.rendered_page_grounding_issues(
                    target=target,
                    page_record=record,
                    claim_records_by_id=claim_records_by_id,
                    page_records_by_id=live_page_records_by_id,
                )
                for record in concept_pages
            }
            grounded_concept_issues = {
                page_id: issues
                for page_id, issues in grounded_concept_issues.items()
                if issues
            }
            grounded_issue_preview = ", ".join(
                f"{page_id}:{'/'.join(issues[:2])}"
                for page_id, issues in list(grounded_concept_issues.items())[:5]
            ) or "All readable concept pages remain grounded in their linked claims."
            add_check(
                name="readable_concept_pages_grounded",
                ok=len(grounded_concept_issues) == 0,
                details=grounded_issue_preview,
            )
            overview_pages = [record for record in live_page_records if record.get("type") == "overview"]
            add_check(
                name="overview_render_metadata_present",
                ok=all(
                    record.get("render_target") and record.get("render_mode") and record.get("render_status")
                    for record in overview_pages
                ),
                details="Each overview page should record render_target, render_mode and render_status for traceability.",
            )
            grounded_overview_issues = {
                record["page_id"]: deps.rendered_page_grounding_issues(
                    target=target,
                    page_record=record,
                    claim_records_by_id=claim_records_by_id,
                    page_records_by_id=live_page_records_by_id,
                )
                for record in overview_pages
            }
            grounded_overview_issues = {
                page_id: issues
                for page_id, issues in grounded_overview_issues.items()
                if issues
            }
            overview_issue_preview = ", ".join(
                f"{page_id}:{'/'.join(issues[:2])}"
                for page_id, issues in list(grounded_overview_issues.items())[:5]
            ) or "All overview pages remain grounded in their linked concept pages."
            add_check(
                name="overview_pages_grounded",
                ok=len(grounded_overview_issues) == 0,
                details=overview_issue_preview,
            )
            concept_quality_issues = {
                record["page_id"]: deps.concept_page_quality_issues(record, claim_records_by_id)
                for record in concept_like_pages
            }
            concept_quality_issues = {
                page_id: issues
                for page_id, issues in concept_quality_issues.items()
                if issues
            }
            concept_quality_preview = ", ".join(
                f"{page_id}:{'/'.join(issues[:2])}"
                for page_id, issues in list(concept_quality_issues.items())[:8]
            ) or "All concept pages passed title-quality checks."
            add_check(
                name="concept_pages_title_quality",
                ok=len(concept_quality_issues) == 0,
                details=concept_quality_preview,
                severity="warning",
            )
            semantic_consistency_issues = {
                record["page_id"]: deps.page_semantic_consistency_issues(record, claim_records_by_id)
                for record in live_page_records
            }
            semantic_consistency_issues = {
                page_id: issues
                for page_id, issues in semantic_consistency_issues.items()
                if issues
            }
            semantic_consistency_preview = ", ".join(
                f"{page_id}:{'/'.join(issues[:2])}"
                for page_id, issues in list(semantic_consistency_issues.items())[:8]
            ) or "All semantic page types remain consistent with their linked claim roles."
            add_check(
                name="page_semantic_consistency",
                ok=len(semantic_consistency_issues) == 0,
                details=semantic_consistency_preview,
                severity="warning",
            )
            page_brake_issues = {
                record["page_id"]: deps.page_intent_brake_issues(record)
                for record in live_page_records
            }
            page_brake_issues = {
                page_id: issues
                for page_id, issues in page_brake_issues.items()
                if issues
            }
            page_brake_preview = ", ".join(
                f"{page_id}:{'/'.join(issues[:2])}"
                for page_id, issues in list(page_brake_issues.items())[:8]
            ) or "No live pages were routed through semantic page-intent downgrade brakes."
            add_check(
                name="semantic_page_intent_brakes_reviewed",
                ok=len(page_brake_issues) == 0,
                details=page_brake_preview,
                severity="warning",
            )

            alias_index = deps.load_alias_index(target) if deps.alias_index_path(target).exists() else {}
            alias_conflicts = deps.unresolved_alias_conflicts(alias_index) if alias_index else []
            add_check(
                name="alias_conflicts_absent",
                ok=len(alias_conflicts) == 0,
                details="Alias registry should not contain unresolved alias conflicts.",
                severity="warning",
            )

            alias_canonical_ids = set(alias_index.get("canonical_map", {}).keys()) if alias_index else set()
            live_page_canonical_ids = {record.get("canonical_id") for record in live_page_records if record.get("canonical_id")}
            add_check(
                name="alias_index_covers_live_pages",
                ok=live_page_canonical_ids.issubset(alias_canonical_ids),
                details="Alias registry should cover every live page canonical_id.",
            )

            search_index_records = (
                deps.load_search_pages_index(target)
                if (target / deps.search_pages_index_rel_path).exists()
                else []
            )
            indexed_page_ids = {record.get("page_id") for record in search_index_records}
            expected_live_page_ids = {record.get("page_id") for record in live_page_records}
            add_check(
                name="search_index_covers_live_pages",
                ok=expected_live_page_ids.issubset(indexed_page_ids),
                details="Search index should contain every live page.",
            )

    if target != root:
        report_lines = [
            "# Lint Report",
            "",
            f"- 目标目录: `{target}`",
            f"- 错误数量: `{len([check for check in checks if not check['ok'] and check['severity'] == 'error'])}`",
            f"- 警告数量: `{len([check for check in checks if not check['ok'] and check['severity'] == 'warning'])}`",
            "",
            "## 结构覆盖率 / Structure Coverage",
            "",
            "| source_id | status | doc_kind | structure | evidence | knowledge | chunks | live_claims | uncovered_structured_units | pipeline_complete |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for row in structure_coverage_rows:
            report_lines.append(
                "| "
                f"{row['source_id']} | {row['status']} | {row.get('document_kind') or '-'} | "
                f"{row['structure_block_count']} | {row['evidence_block_count']} | {row['knowledge_unit_count']} | "
                f"{row['chunk_count']} | {row['live_claim_count']} | {row['uncovered_structured_unit_count']} | "
                f"{'yes' if row['structured_pipeline_complete'] else 'no'} |"
            )
        report_lines.extend([
            "",
            "### 结构跳过与漏抽分类 / Intentional Skips And Gap Classes",
            "",
            f"- intentional_skips: {intentional_structure_skip_counts}",
            f"- uncovered_gap_classes: {structured_gap_class_counts}",
        ])
        report_lines.extend([
            "",
            "## 检查结果 / Checks",
            "",
        ])
        for check in checks:
            marker = "PASS" if check["ok"] else ("WARN" if check["severity"] == "warning" else "FAIL")
            report_lines.append(f"- [{marker}] `{check['name']}`: {check['details']}")
        deps.atomic_write_text(
            target / "reports" / "lint" / "lint_latest.md",
            "\n".join(report_lines).strip() + "\n",
            encoding="utf-8",
        )

    errors = [check for check in checks if not check["ok"] and check["severity"] == "error"]
    warnings = [check for check in checks if not check["ok"] and check["severity"] == "warning"]
    payload = {
        "target": str(target),
        "workspace_summary": deps.build_workspace_summary(target),
        "checks": checks,
        "structure_coverage": {
            "rows": structure_coverage_rows,
            "incomplete_source_count": len(incomplete_structure_rows),
            "uncovered_structured_unit_count": len(structured_claim_coverage_gaps),
            "uncovered_structured_units": structured_claim_coverage_gaps,
            "uncovered_gap_class_counts": structured_gap_class_counts,
            "intentional_skip_counts": intentional_structure_skip_counts,
        },
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "ok": len(errors) == 0,
        },
    }
    return LintServiceResult(
        exit_code=0 if len(errors) == 0 else 1,
        payload=payload,
        message=deps.render_workspace_summary_message(
            "Lint completed." if len(errors) == 0 else "Lint found issues.",
            target_dir=target,
            extra_lines=[
                (
                    "Summary: "
                    f"errors={payload['summary']['errors']}, "
                    f"warnings={payload['summary']['warnings']}, "
                    f"ok={'yes' if payload['summary']['ok'] else 'no'}"
                ),
            ],
        ),
    )
