from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import hashlib
import re
import csv
import zipfile
import struct
import zlib
import math
import difflib
import shlex
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Template
import tempfile
import fcntl
import mimetypes
import ssl
import urllib.error
import urllib.request
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from .cli_parser import build_parser as build_cli_parser
from .app_services.claim_status_service import (
    ClaimSetStatusRequest,
    ClaimStatusServiceDeps,
    run_claim_set_status_service,
)
from .app_services.answer_ready_helpers import (
    build_answer_ready_messages as build_answer_ready_messages_helper,
    build_answer_ready_payload as build_answer_ready_payload_helper,
    render_answer_ready_chatml as render_answer_ready_chatml_helper,
    render_answer_ready_message as render_answer_ready_message_helper,
    render_answer_ready_prompt as render_answer_ready_prompt_helper,
)
from .app_services.query_reading_helpers import (
    alias_match_boost as alias_match_boost_helper,
    build_answer_guardrails as build_answer_guardrails_helper,
    build_answer_handoff as build_answer_handoff_helper,
    build_chunk_reading_brief as build_chunk_reading_brief_helper,
    build_result_reading_pack as build_result_reading_pack_helper,
    build_hierarchy_match_explanation as build_hierarchy_match_explanation_helper,
    build_scored_query_result as build_scored_query_result_helper,
    build_source_brief as build_source_brief_helper,
    build_source_trail as build_source_trail_helper,
    build_timeline_sources as build_timeline_sources_helper,
    compute_query_scoring_context as compute_query_scoring_context_helper,
    detect_query_intent as detect_query_intent_helper,
    expand_related_pages_for_query_result as expand_related_pages_for_query_result_helper,
    expand_query_with_alias_registry as expand_query_with_alias_registry_helper,
    normalize_query_text as normalize_query_text_helper,
    prepare_query_runtime_context as prepare_query_runtime_context_helper,
    query_intent_field_multiplier as query_intent_field_multiplier_helper,
    query_intent_page_type_boost as query_intent_page_type_boost_helper,
    query_reading_focus as query_reading_focus_helper,
    score_chunk_for_query as score_chunk_for_query_helper,
    score_claim_for_query as score_claim_for_query_helper,
    select_top_matches as select_top_matches_helper,
)
from .app_services.query_service import build_query_payload_via_runtime as build_query_payload_via_runtime_helper
from .app_services.page_semantic_helpers import (
    append_frontmatter_list,
    build_page_semantic_frontmatter_projection as build_page_semantic_frontmatter_projection_helper,
    enrich_claim_records_with_structure_context as enrich_claim_records_with_structure_context_helper,
    format_frontmatter_scalar,
    prepare_page_semantic_context as prepare_page_semantic_context_helper,
)
from .app_services.page_render_helpers import (
    build_readable_concept_summary_text as build_readable_concept_summary_text_helper,
    build_concept_page_output as build_concept_page_output_helper,
    build_intent_page_descriptor as build_intent_page_descriptor_helper,
    build_intent_routed_page_output as build_intent_routed_page_output_helper,
    build_workspace_overview_key_theme_rows as build_workspace_overview_key_theme_rows_helper,
    build_workspace_overview_page_output as build_workspace_overview_page_output_helper,
    build_workspace_overview_summary_text as build_workspace_overview_summary_text_helper,
    build_workspace_source_coverage_rows as build_workspace_source_coverage_rows_helper,
    finalize_concept_render_result as finalize_concept_render_result_helper,
    finalize_workspace_overview_render_result as finalize_workspace_overview_render_result_helper,
    prepare_concept_claim_selection as prepare_concept_claim_selection_helper,
    prepare_concept_page_context as prepare_concept_page_context_helper,
    prepare_concept_page_title as prepare_concept_page_title_helper,
    prepare_concept_render_inputs as prepare_concept_render_inputs_helper,
    prepare_workspace_overview_context as prepare_workspace_overview_context_helper,
    prepare_workspace_overview_render_inputs as prepare_workspace_overview_render_inputs_helper,
    summarize_concept_page_for_overview as summarize_concept_page_for_overview_helper,
)
from .app_services.lint_service import LintRequest, LintServiceDeps, run_lint_service
from .app_services.render_service import RenderPageRequest, RenderPageServiceDeps, run_render_page_service
from .app_services import runtime_services
from .app_services.review_rebuild_service import (
    ReviewRebuildPageContext,
    ReviewRebuildPageDeps,
    ReviewRebuildPersistContext,
    ReviewRebuildPersistDeps,
    run_review_rebuild_page_regeneration,
    run_review_rebuild_persistence,
)
from .app_services.review_state_helpers import (
    archive_live_claim as archive_live_claim_helper,
    cleanup_superseded_record_files as cleanup_superseded_record_files_helper,
    normalize_claim_review_flags as normalize_claim_review_flags_helper,
    reload_claims_from_disk_for_review as reload_claims_from_disk_for_review_helper,
    resolve_claim_record_for_action as resolve_claim_record_for_action_helper,
    rewrite_open_reviews_for_claim_change as rewrite_open_reviews_for_claim_change_helper,
    sync_claim_review_state_from_open_reviews as sync_claim_review_state_from_open_reviews_helper,
)
from .app_services.review_auto_helpers import (
    build_review_auto_decision_payload as build_review_auto_decision_payload_helper,
    build_review_auto_agent_handoff as build_review_auto_agent_handoff_helper,
    build_review_auto_escalation_entry as build_review_auto_escalation_entry_helper,
    build_review_auto_messages as build_review_auto_messages_helper,
    build_stable_promotion_payload as build_stable_promotion_payload_helper,
    claim_record_is_safe_auto_stable_candidate as claim_record_is_safe_auto_stable_candidate_helper,
    maybe_get_agent_assisted_review_plan as maybe_get_agent_assisted_review_plan_helper,
    maybe_get_agent_assisted_stable_promotion as maybe_get_agent_assisted_stable_promotion_helper,
    normalize_review_auto_hook_plan as normalize_review_auto_hook_plan_helper,
    propose_review_auto_action as propose_review_auto_action_helper,
    render_review_auto_chatml as render_review_auto_chatml_helper,
    render_review_auto_message as render_review_auto_message_helper,
    render_review_auto_prompt as render_review_auto_prompt_helper,
    review_action_plain_label as review_action_plain_label_helper,
)
from .app_services.review_action_helpers import (
    ReviewActionDeps,
    apply_review_action_via_helpers,
)
from .app_services.semantic_batch_service import (
    SemanticBatchRequest,
    SemanticBatchServiceDeps,
    run_semantic_batch_service,
)
from .app_services.review_apply_service import ReviewApplyRequest, run_review_apply_service
from .cli_components.doctor_bootstrap import register_doctor_bootstrap_subparsers
from .cli_components import init_command as init_cli_component
from .cli_components import ingest as ingest_cli_component
from .cli_components import misc_commands as misc_cli_component
from .cli_components import query_commands as query_cli_component
from .cli_components import review_commands as review_cli_component
from .cli_components.init_command import InitCliDeps, build_init_cli_deps as build_init_cli_component_deps
from .cli_components.ingest import IngestCliDeps
from .cli_components.misc_commands import MiscCliDeps, build_misc_cli_deps as build_misc_cli_component_deps
from .cli_components.query_commands import QueryCliDeps
from .cli_components.review_commands import ReviewCliDeps
from .cli_components.result import CommandResult, print_result
from .hook_protocol import HookExecutionError, is_online_hook_command, parse_online_hook_error
from .repositories.state_views import (
    build_claim_state_maps_loader as repo_build_claim_state_maps_loader,
    build_page_state_records_loader as repo_build_page_state_records_loader,
    build_review_state_maps_loader as repo_build_review_state_maps_loader,
    load_alias_index as repo_load_alias_index,
    load_claim_state_maps as repo_load_claim_state_maps,
    load_page_links_index as repo_load_page_links_index,
    load_page_state_records as repo_load_page_state_records,
    load_review_state_maps as repo_load_review_state_maps,
    load_search_pages_index as repo_load_search_pages_index,
    load_semantic_decisions as repo_load_semantic_decisions,
)
from .repositories.query_state import (
    build_page_field_texts as repo_build_page_field_texts,
    build_query_documents as repo_build_query_documents,
    ensure_query_documents as repo_ensure_query_documents,
    build_search_index_record as repo_build_search_index_record,
    load_query_documents_from_search_index as repo_load_query_documents_from_search_index,
    load_chunk_records_by_id as repo_load_chunk_records_by_id,
    load_query_live_claim_records as repo_load_query_live_claim_records,
    load_query_page_records as repo_load_query_page_records,
    write_search_pages_index as repo_write_search_pages_index,
)
from .repositories.semantic_state import (
    append_semantic_decision_records as repo_append_semantic_decision_records,
    build_latest_semantic_decisions_by_fingerprint as repo_build_latest_semantic_decisions_by_fingerprint,
    load_semantic_decisions as repo_load_semantic_decisions_records,
)
from .repositories.ingest_state import (
    build_chunk_records_by_source_loader as repo_build_chunk_records_by_source_loader,
    build_chunk_records_loader as repo_build_chunk_records_loader,
    build_existing_chunked_by_source_loader as repo_build_existing_chunked_by_source_loader,
    build_existing_claim_state_loader as repo_build_existing_claim_state_loader,
    build_existing_pages_loader as repo_build_existing_pages_loader,
    build_existing_review_state_loader as repo_build_existing_review_state_loader,
    build_existing_sources_loader as repo_build_existing_sources_loader,
    load_chunk_records as repo_load_chunk_records,
    load_chunk_records_by_source as repo_load_chunk_records_by_source,
    load_current_claim_records as repo_load_current_claim_records,
    load_active_knowledge_units_by_source as repo_load_active_knowledge_units_by_source,
    load_existing_chunked_by_source as repo_load_existing_chunked_by_source,
    load_existing_claim_state as repo_load_existing_claim_state,
    load_existing_pages as repo_load_existing_pages,
    load_existing_normalized_by_source as repo_load_existing_normalized_by_source,
    load_existing_review_state as repo_load_existing_review_state,
    load_existing_sources as repo_load_existing_sources,
    load_existing_structured_source_ids as repo_load_existing_structured_source_ids,
    load_normalized_records as repo_load_normalized_records,
    load_normalized_records_by_source as repo_load_normalized_records_by_source,
    load_source_records as repo_load_source_records,
)
from .repositories.ingest_persistence import (
    persist_claim_records as repo_persist_ingest_claim_records,
    persist_ordered_claim_state as repo_persist_ingest_ordered_claim_state,
    persist_ordered_review_state as repo_persist_ingest_ordered_review_state,
    persist_page_records as repo_persist_page_records,
    persist_review_records as repo_persist_ingest_review_records,
)
from .repositories.review_persistence import (
    cleanup_review_related_record_files as repo_cleanup_review_related_record_files,
    persist_claim_records as repo_persist_claim_records,
    persist_ordered_claim_state as repo_persist_ordered_claim_state,
    persist_ordered_review_state as repo_persist_ordered_review_state,
    persist_review_records as repo_persist_review_records,
)
from .runtime_env import command_exists, find_project_root, load_simple_yaml
from .semantic import (
    SemanticTaskConfig,
    build_semantic_decision_id,
    fingerprint_payload,
    item_type_for_task,
    normalize_string_list,
    normalize_semantic_hook_decision,
    semantic_batches_dir,
)

runtime_services = runtime_services
convert_image_to_markdown = runtime_services.convert_image_to_markdown
convert_legacy_doc_to_markdown = runtime_services.convert_legacy_doc_to_markdown
convert_legacy_xls_to_markdown = runtime_services.convert_legacy_xls_to_markdown
enrich_markdown_with_embedded_images = runtime_services.enrich_markdown_with_embedded_images
normalize_source_record = runtime_services.normalize_source_record

DEFAULT_CHUNK_TARGET_TOKENS = 1000
DEFAULT_CHUNK_MAX_TOKENS = 1600
DEFAULT_CHUNK_MIN_TOKENS = 200
MAX_FILENAME_COMPONENT_BYTES = 240
FILENAME_HASH_LENGTH = 12
QUERY_READING_DEPTH_LIMITS = {
    "standard": {
        "claim_limit": 3,
        "chunk_limit": 2,
    },
    "deep": {
        "claim_limit": 6,
        "chunk_limit": 5,
    },
}
QUERY_LINK_EXPANSION_CHOICES = ("off", "auto", "deep")
ALIAS_INDEX_REL_PATH = Path("indexes") / "aliases.json"
PAGE_LINKS_INDEX_REL_PATH = Path("indexes") / "page_links.json"
PAGE_ALIAS_OVERRIDES_REL_PATH = Path("state") / "page_alias_overrides.json"
PAGE_ALIAS_OVERRIDES_LOCK_REL_PATH = Path("state") / ".page_alias_overrides.lock"
STRUCTURE_BLOCKS_REL_PATH = Path("state") / "structure_blocks.jsonl"
EVIDENCE_BLOCKS_REL_PATH = Path("state") / "evidence_blocks.jsonl"
KNOWLEDGE_UNITS_REL_PATH = Path("state") / "knowledge_units.jsonl"
SEMANTIC_DECISIONS_REL_PATH = Path("state") / "semantic_decisions.jsonl"
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
NEGATION_MARKERS = ("not ", "no ", "never ", "cannot ")
PAGE_RENDER_TARGETS = {
    "readable_concept": {
        "page_types": {"concept"},
        "rebuild_strategy": "review_affected_pages",
        "grounding_checker": "readable_concept",
    },
    "guide": {
        "page_types": {"guide"},
        "rebuild_strategy": "review_affected_pages",
        "grounding_checker": None,
    },
    "duty": {
        "page_types": {"duty"},
        "rebuild_strategy": "review_affected_pages",
        "grounding_checker": None,
    },
    "example": {
        "page_types": {"example"},
        "rebuild_strategy": "review_affected_pages",
        "grounding_checker": None,
    },
    "topic": {
        "page_types": {"topic"},
        "rebuild_strategy": "review_affected_pages",
        "grounding_checker": None,
    },
    "reference": {
        "page_types": {"reference"},
        "rebuild_strategy": "review_affected_pages",
        "grounding_checker": None,
    },
    "timeline": {
        "page_types": {"timeline"},
        "rebuild_strategy": "review_affected_pages",
        "grounding_checker": None,
    },
    "overview": {
        "page_types": {"overview"},
        "rebuild_strategy": "review_affected_pages",
        "grounding_checker": None,
    },
    "qa_note": {
        "page_types": {"qa-note"},
        "rebuild_strategy": "none",
        "grounding_checker": None,
    },
    "concept_update": {
        "page_types": {"concept-update"},
        "rebuild_strategy": "none",
        "grounding_checker": None,
    },
}
QUERY_FIELD_WEIGHTS = {
    "title": 5.0,
    "aliases": 4.0,
    "hierarchy": 3.5,
    "summary": 3.0,
    "headings": 2.5,
    "body": 1.0,
    "claim_text": 2.0,
    "source_refs": 0.5,
}
QUERY_PAGE_TYPE_WEIGHTS = {
    "overview": 1.25,
    "concept": 1.22,
    "duty": 1.12,
    "topic": 1.08,
    "guide": 1.05,
    "example": 0.95,
    "reference": 1.04,
    "timeline": 1.02,
    "source-summary": 1.00,
    "draft": 0.70,
}
QUERY_PAGE_STATUS_WEIGHTS = {
    "stable": 1.10,
    "draft": 0.80,
    "disputed": 0.90,
    "outdated": 0.60,
    # 设计文档里没有 needs_review，这里把它视为比 draft 更需要谨慎的状态。
    "needs_review": 0.75,
}
QUERY_BM25_K1 = 1.5
QUERY_BM25_B = 0.75
QUERY_EXACT_MATCH_MAX_BOOST = 1.35
QUERY_HEADING_BLACKLIST = {
    "原文概览 / source overview",
    "核心观点 / key points",
    "知识声明 / claims",
    "证据切块 / chunks",
    "后续建议 / next steps",
    "概念摘要 / concept summary",
    "核心陈述 / canonical claim",
    "支撑声明 / supporting claims",
    "来源页面 / source pages",
    "来源证据 / source evidence",
    "审核提示 / review notes",
    "工作区综述 / workspace overview",
    "稳定概念 / stable concepts",
    "来源覆盖 / source coverage",
    "维护状态 / maintenance",
}
SEARCH_PAGES_INDEX_REL_PATH = Path("indexes") / "search_pages.jsonl"
SEARCH_PAGES_INDEX_VERSION = "search_pages_v2"
ALIAS_INDEX_VERSION = "aliases_v1"
PAGE_LINKS_INDEX_VERSION = "page_links_v1"
QUERY_ANSWER_HANDOFF_CONTRACT_VERSION = "query_answer_handoff/v1"
REVIEW_AUTO_HANDOFF_CONTRACT_VERSION = "review_auto_handoff/v1"
ANSWER_READY_OUTPUT_VERSION = "answer_ready_query/v1"
AUTOMATION_STRATEGIES = {"safe_auto", "agent_assisted"}
SEMANTIC_TASK_NAMES = ("document_analysis", "claim_candidate_quality", "claim_role", "page_intent", "page_route")
WORKSPACE_SCHEMA_VERSION = "v1"
QUERY_INTENT_MARKERS = {
    "overview": (
        "overview", "summary",
    ),
    "definition": (
        "what is", "define", "definition",
    ),
    "compare": (
        "vs", "versus", "compare", "difference",
    ),
    "timeline": (
        "timeline", "history",
    ),
    "reference": (
        "faq", "reference",
    ),
    "how_to": (
        "how to", "tutorial",
    ),
    "evidence": (
        "source", "evidence", "trace", "citation",
    ),
}
QUERY_INTENT_CHOICES = ("lookup", *QUERY_INTENT_MARKERS.keys())
QUERY_INTENT_FIELD_MULTIPLIERS = {
    "lookup": {},
    "overview": {
        "title": 1.15,
        "summary": 1.20,
        "headings": 1.15,
        "body": 1.08,
        "claim_text": 1.05,
    },
    "definition": {
        "title": 1.15,
        "summary": 1.15,
        "aliases": 1.10,
        "hierarchy": 1.08,
    },
    "compare": {
        "claim_text": 1.15,
        "body": 1.10,
        "headings": 1.05,
        "hierarchy": 1.08,
    },
    "timeline": {
        "body": 1.10,
        "summary": 1.05,
        "source_refs": 1.10,
    },
    "reference": {
        "title": 1.10,
        "headings": 1.12,
        "body": 1.08,
        "claim_text": 1.06,
        "hierarchy": 1.10,
    },
    "how_to": {
        "headings": 1.15,
        "body": 1.15,
        "claim_text": 1.10,
        "hierarchy": 1.12,
    },
    "evidence": {
        "source_refs": 1.80,
        "claim_text": 1.20,
        "body": 1.05,
        "hierarchy": 1.08,
    },
}
CLAIM_DEPENDENT_PREFIXES = ()
CLAIM_META_PREFIXES = ()


def build_workspace_summary(target_dir: Path, raw_dir: Path | None = None) -> dict:
    # 给上层 Agent 和人类读者一份“可以直接复述”的路径摘要，避免只剩目录名。
    lint_report_path = target_dir / "reports" / "lint" / "lint_latest.md"
    schema_version = None
    schema_guard = {
        "status": "unknown",
        "expected_schema_version": WORKSPACE_SCHEMA_VERSION,
    }
    config_path = target_dir / "config" / "project.yml"
    if config_path.exists():
        workspace_config = load_simple_yaml(config_path)
        workspace_block = workspace_config.get("workspace", {})
        if not isinstance(workspace_block, dict):
            workspace_block = {}
        schema_version = str(workspace_block.get("schema_version", "")).strip() or None
        schema_guard["status"] = workspace_schema_guard_status(schema_version).replace("_schema_version", "")
    summary = {
        "workspace_dir": str(target_dir),
        "workspace_name": target_dir.name,
        "entry_page_path": str(target_dir / "wiki" / "index.md"),
        "wiki_log_path": str(target_dir / "wiki" / "log.md"),
        "lint_report_path": str(lint_report_path),
        "lint_report_exists": lint_report_path.exists(),
        "schema_version": schema_version,
        "schema_guard": schema_guard,
    }
    if raw_dir is not None:
        summary["raw_dir"] = str(raw_dir)
    return summary


def render_workspace_summary_message(
    action_label: str,
    target_dir: Path,
    raw_dir: Path | None = None,
    extra_lines: list[str] | None = None,
) -> str:
    # 纯文本模式也显式带绝对路径，减少 UI 把链接文案压缩成目录名后的歧义。
    summary = build_workspace_summary(target_dir, raw_dir)
    lines = [
        f"{action_label}",
        f"Workspace: {summary['workspace_dir']}",
    ]
    if raw_dir is not None:
        lines.append(f"Raw sibling: {summary['raw_dir']}")
    lines.extend(
        [
            f"Entry page: {summary['entry_page_path']}",
            (
                f"Lint report: {summary['lint_report_path']}"
                if summary["lint_report_exists"]
                else f"Lint report: {summary['lint_report_path']} (will be created after the first lint run)"
            ),
        ]
    )
    schema_guard = summary.get("schema_guard", {})
    if schema_guard.get("status") == "unsupported":
        lines.append(
            "Schema guard: "
            f"workspace_schema={summary.get('schema_version')}, "
            f"expected={schema_guard.get('expected_schema_version')}"
        )
    elif summary.get("schema_version"):
        lines.append(f"Schema version: {summary.get('schema_version')}")
    if extra_lines:
        lines.extend(line for line in extra_lines if line)
    return "\n".join(lines)


def render_template(template_path: Path, context: dict[str, str]) -> str:
    # 用户工程初始化时，大部分文本文件都通过模板渲染生成。
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.safe_substitute(context)


def ensure_clean_target(target: Path) -> None:
    # init 不应覆盖已有非空目录，否则非常容易误伤用户自己的文件。
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Target directory already exists and is not empty: {target}")


def ensure_directory(path: Path) -> None:
    # 原始资料目录与工作区子目录都统一走这里，避免各处重复 mkdir 参数。
    path.mkdir(parents=True, exist_ok=True)


def baseline_git_paths(target: Path) -> list[str]:
    # 基线提交只纳入 MyAgentWiki 自己生成的骨架与状态文件；
    # 外部 raw/ 不属于工作区仓库，基线里也不应试图追踪它。
    candidates = [
        ".gitignore",
        "AGENTS.md",
        "CLAUDE.md",
        "config/llm.local.example.yml",
        "config/project.yml",
        "config/runtime_manifest.yml",
        "indexes/aliases.json",
        str(SEARCH_PAGES_INDEX_REL_PATH),
        "reports/lint/lint_latest.md",
        "state/claims.jsonl",
        "state/chunks.jsonl",
        str(EVIDENCE_BLOCKS_REL_PATH),
        "state/error_log.jsonl",
        "state/ingest_state.jsonl",
        str(KNOWLEDGE_UNITS_REL_PATH),
        "state/normalized.jsonl",
        "state/pages.jsonl",
        "state/reviews.jsonl",
        str(SEMANTIC_DECISIONS_REL_PATH),
        "state/sources.jsonl",
        str(STRUCTURE_BLOCKS_REL_PATH),
        "wiki/index.md",
        "wiki/log.md",
    ]
    return [path for path in candidates if (target / path).exists()]


def git_init_and_commit(target: Path) -> list[str]:
    # 初始化工作区时自动建一个 Git 基线，方便后续所有自动化改动都可回滚。
    steps: list[str] = []
    # 这里故意拆成三步记录，后面如果你要把这些步骤展示到日志或界面，会更直观。
    subprocess.run(["git", "init"], cwd=target, check=True, capture_output=True, text=True)
    steps.append("git init")
    tracked_paths = baseline_git_paths(target)
    subprocess.run(
        ["git", "add", "--", *tracked_paths],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    )
    steps.append("git add whitelist")
    # 用固定的本地身份提交第一次基线，避免依赖用户电脑上是否已经配置 git 用户名邮箱。
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=MyAgentWiki",
            "-c",
            "user.email=myagentwiki@local",
            "commit",
            "-m",
            "init: bootstrap MyAgentWiki workspace",
        ],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    )
    steps.append("git commit")
    return steps


def utc_now_iso() -> str:
    # 统一使用 UTC 时间戳，避免不同机器和时区写出来的状态难对齐。
    return datetime.now(timezone.utc).isoformat()


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    # 关键状态文件和页面文件统一走原子写：
    # 先写同目录临时文件，再 replace 到目标路径，尽量避免留下半截文件。
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding=encoding,
        dir=path.parent,
        prefix=f".{path.name}.tmp-",
        delete=False,
    ) as fh:
        fh.write(text)
        temp_path = Path(fh.name)
    temp_path.replace(path)


def write_jsonl(path: Path, records: list[dict]) -> None:
    # 初始化占位文件时统一覆盖写入，保证 JSONL 文件总是处于可读状态。
    # JSONL 的优点是“每行一个 JSON 对象”，增量追加和排查问题都很方便。
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    text = "\n".join(lines)
    if lines:
        # 末尾补一个换行，后续 append 时不用担心和上一条黏在一起。
        text += "\n"
    atomic_write_text(path, text, encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    # 运行中的状态和来源登记采用 append-only，尽量减少覆盖写坏文件的风险。
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False))
        fh.write("\n")


def load_jsonl(path: Path) -> list[dict]:
    # JSONL 读取保持极简：逐行解析，后续状态恢复和 lint 都会复用。
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        # 每一行都应该是一个独立 JSON 对象，所以这里不需要做复杂的流式解析。
        records.append(json.loads(line))
    return records


def load_json(path: Path) -> dict:
    # claim / review 单文件读取统一走这里，避免各处重复写编码与 JSON 解析逻辑。
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    # 文件去重和 source_id 稳定性都依赖内容哈希，因此统一走分块读取。
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_source_key(value: str) -> str:
    # 把路径名压成适合放进 source_id 的安全片段。
    # 例如 "topic-a/Note 01" 会变成 "topic_a_note_01"。
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        else:
            cleaned.append("_")
    compact = "".join(cleaned)
    # 连续下划线压缩一下，避免生成过于难读的 ID。
    while "__" in compact:
        compact = compact.replace("__", "_")
    return compact.strip("_") or "source"


def truncate_utf8_text(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    truncated = encoded[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8").rstrip(" ._-")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""


def stabilize_filename_component(
    value: str,
    *,
    max_bytes: int = MAX_FILENAME_COMPONENT_BYTES,
    separator: str = "__",
) -> str:
    cleaned = value.strip(" .")
    if not cleaned:
        return ""
    if len(cleaned.encode("utf-8")) <= max_bytes:
        return cleaned

    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:FILENAME_HASH_LENGTH]
    suffix = f"{separator}{digest}"
    prefix_budget = max(max_bytes - len(suffix.encode("utf-8")), 1)
    prefix = truncate_utf8_text(cleaned, prefix_budget)
    if not prefix:
        return digest
    return f"{prefix}{suffix}"


def build_source_id(raw_root: Path, file_path: Path, source_hash: str) -> str:
    # source_id 不能只看文件名 stem，否则 raw 子目录里同名文件会互相挤占命名空间。
    relative = file_path.relative_to(raw_root).with_suffix("")
    relative_key = sanitize_source_key(relative.as_posix())
    return f"src_{relative_key}_{source_hash[:12]}"


def build_source_version_group(raw_root: Path, file_path: Path) -> str:
    # version_group 用来表达“同一路径来源的多次版本演进”。
    # 它不跟随内容 hash 变化，便于后面做路径级更新和版本链追踪。
    relative = file_path.relative_to(raw_root).with_suffix("")
    relative_key = sanitize_source_key(relative.as_posix())
    return f"vgrp_{relative_key}"


def source_path_to_raw_relative(source_path: str) -> str:
    # source_path 可能是 raw/topic/a.md，也可能是 ../raw/topic/a.md；
    # 这里统一裁成“相对 raw 根目录的路径”，供 version_group 与展示逻辑复用。
    path = Path(source_path)
    parts = list(path.parts)
    if "raw" in parts:
        raw_index = parts.index("raw")
        relative = Path(*parts[raw_index + 1:]) if raw_index + 1 < len(parts) else Path()
    else:
        relative = path
    return relative.with_suffix("").as_posix().lstrip("./")


def build_source_version_group_from_source_path(source_path: str) -> str:
    # sources.jsonl 里保存的是可回到 raw 的路径，例如 raw/topic/a.md 或 ../raw/topic/a.md。
    # 这里补一个从已存记录反推 version_group 的帮助函数。
    raw_relative = source_path_to_raw_relative(source_path)
    relative_key = sanitize_source_key(raw_relative)
    return f"vgrp_{relative_key}"


def build_latest_source_record_by_path(records: list[dict]) -> dict[str, dict]:
    # 同一路径可能被重复导入，这里统一选“最近导入”的那条。
    latest_by_path: dict[str, dict] = {}
    for record in records:
        source_path = record.get("source_path")
        if not source_path:
            continue
        current = latest_by_path.get(source_path)
        if current is None or record.get("imported_at", "") >= current.get("imported_at", ""):
            latest_by_path[source_path] = record
    return latest_by_path


def path_is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def collect_files(root: Path) -> list[Path]:
    # 递归遍历 raw 下所有文件，允许用户按主题、来源、年份自由分子目录管理原始资料。
    return sorted(
        path
        for path in root.rglob("*")
        if (
            path.is_file()
            and path_is_within_root(path, root)
            and not any(part.startswith(".") for part in path.relative_to(root).parts)
        )
    )


def infer_source_type(path: Path) -> str:
    # 这里只做最基础的后缀判断，后面可以再升级成 MIME / 魔数检测。
    suffix = path.suffix.lower()
    mapping = {
        ".md": "markdown",
        ".markdown": "markdown",
        ".txt": "plain_text",
        ".pdf": "pdf",
        ".docx": "docx",
        ".doc": "doc",
        ".xlsx": "spreadsheet",
        ".xls": "spreadsheet",
        ".csv": "spreadsheet",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webp": "image",
    }
    return mapping.get(suffix, "unknown")


def load_workspace_config(target: Path) -> dict:
    # 工作区自己的配置放在 config/project.yml，后续 chunk/query 也会继续依赖它。
    config_path = target / "config" / "project.yml"
    return load_simple_yaml(config_path)


def workspace_schema_guard_status(schema_version: str | None) -> str:
    normalized = str(schema_version or "").strip() or None
    if normalized is None:
        return "missing_schema_version"
    return "supported" if normalized == WORKSPACE_SCHEMA_VERSION else "unsupported"


def normalize_optional_cli_string(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() == "none":
        return None
    return normalized


def workspace_schema_guard_payload(target: Path) -> dict:
    config_path = target / "config" / "project.yml"
    if not config_path.exists():
        return {
            "status": "missing_config",
            "workspace_schema_version": None,
            "expected_schema_version": WORKSPACE_SCHEMA_VERSION,
        }
    config = load_simple_yaml(config_path)
    workspace_block = config.get("workspace", {})
    if not isinstance(workspace_block, dict):
        workspace_block = {}
    schema_version = str(workspace_block.get("schema_version", "")).strip() or None
    status = workspace_schema_guard_status(schema_version)
    return {
        "status": status,
        "workspace_schema_version": schema_version,
        "expected_schema_version": WORKSPACE_SCHEMA_VERSION,
    }


def ensure_workspace_schema_supported(target: Path) -> None:
    payload = workspace_schema_guard_payload(target)
    if payload["status"] == "supported":
        return
    if payload["status"] == "missing_config":
        raise ValueError(
            f"Workspace schema guard failed: missing config/project.yml in {target}. "
            "Re-initialize the workspace or point the command at a valid workspace."
        )
    if payload["status"] == "missing_schema_version":
        raise ValueError(
            "Workspace schema guard failed: workspace.schema_version is missing in config/project.yml. "
            "Re-initialize the workspace or update config/project.yml to the current scaffold."
        )
    raise ValueError(
        "Workspace schema guard failed: "
        f"workspace.schema_version={payload['workspace_schema_version']} is not supported by this CLI "
        f"(expected={payload['expected_schema_version']}). "
        "Re-initialize the workspace with the current CLI before attempting mutating commands."
    )


def coerce_int(value, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = value.strip()
        if digits.isdigit():
            return int(digits)
    return default


def coerce_float(value, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return float(stripped)
        except ValueError:
            return default
    return default

def normalize_command_config(value) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return shlex.split(stripped) if stripped else []
    if isinstance(value, list):
        normalized = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized
    return []


def load_automation_target_config(config: dict, target_name: str) -> dict:
    automation_config = config.get("automation", {})
    if not isinstance(automation_config, dict):
        automation_config = {}

    target_config = automation_config.get(target_name, {})
    if not isinstance(target_config, dict):
        target_config = {}

    inherited_strategy = str(automation_config.get("mode", "safe_auto")).strip() or "safe_auto"
    strategy = str(target_config.get("strategy", inherited_strategy)).strip() or inherited_strategy
    if strategy not in AUTOMATION_STRATEGIES:
        strategy = "safe_auto"

    command = normalize_command_config(target_config.get("command", []))
    timeout_seconds = max(coerce_int(target_config.get("timeout_seconds", 45), 45), 5)
    min_confidence = min(max(coerce_float(target_config.get("min_confidence", 0.8), 0.8), 0.0), 1.0)
    return {
        "strategy": strategy,
        "command": command,
        "timeout_seconds": timeout_seconds,
        "min_confidence": min_confidence,
        "enabled": strategy == "agent_assisted" and bool(command),
    }


def load_post_ingest_review_auto_config(config: dict) -> dict:
    automation_config = config.get("automation", {})
    if not isinstance(automation_config, dict):
        automation_config = {}

    post_ingest_config = automation_config.get("post_ingest", {})
    if not isinstance(post_ingest_config, dict):
        post_ingest_config = {}

    review_auto_enabled = post_ingest_config.get("review_auto", True)
    return {
        "review_auto": bool(review_auto_enabled),
    }


def load_semantic_task_config(config: dict, task_name: str) -> SemanticTaskConfig:
    semantic_config = config.get("semantic", {})
    if not isinstance(semantic_config, dict):
        semantic_config = {}

    scheduler_config = semantic_config.get("batch_scheduler", {})
    if not isinstance(scheduler_config, dict):
        scheduler_config = {}

    task_config = semantic_config.get(task_name, {})
    if not isinstance(task_config, dict):
        task_config = {}

    strategy = str(task_config.get("strategy", "agent_assisted")).strip() or "agent_assisted"
    if strategy not in AUTOMATION_STRATEGIES:
        strategy = "agent_assisted"

    command = normalize_command_config(task_config.get("command", []))
    timeout_seconds = max(coerce_int(task_config.get("timeout_seconds", 45), 45), 5)
    min_confidence = min(max(coerce_float(task_config.get("min_confidence", 0.75), 0.75), 0.0), 1.0)
    batch_size = max(
        coerce_int(
            task_config.get("batch_size", scheduler_config.get("default_batch_size", 12)),
            12,
        ),
        1,
    )
    model_key = str(task_config.get("model_key", "local-default")).strip() or "local-default"
    prompt_version = str(task_config.get("prompt_version", "v1")).strip() or "v1"
    schema_version = str(task_config.get("schema_version", "v1")).strip() or "v1"
    enabled = strategy == "agent_assisted" and bool(command)
    return SemanticTaskConfig(
        task_name=task_name,
        strategy=strategy,
        command=command,
        timeout_seconds=timeout_seconds,
        min_confidence=min_confidence,
        batch_size=batch_size,
        enabled=enabled,
        model_key=model_key,
        prompt_version=prompt_version,
        schema_version=schema_version,
    )


def run_json_automation_command(
    target: Path,
    command: list[str],
    payload: dict,
    timeout_seconds: int,
) -> dict | None:
    if not command:
        return None
    try:
        completed = subprocess.run(
            command,
            cwd=target,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode != 0:
        if is_online_hook_command(command):
            hook_error = parse_online_hook_error(completed.stdout, completed.stderr)
            if hook_error is not None:
                raise hook_error
        return None

    stdout = (completed.stdout or "").strip()
    if not stdout:
        return None

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        if is_online_hook_command(command):
            hook_error = parse_online_hook_error(stdout, completed.stderr)
            if hook_error is not None:
                raise hook_error
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_hook_process_result(
    command: list[str],
    completed: subprocess.CompletedProcess[str],
) -> dict | None:
    if completed.returncode != 0:
        if is_online_hook_command(command):
            hook_error = parse_online_hook_error(completed.stdout, completed.stderr)
            if hook_error is not None:
                raise hook_error
        return None

    stdout = (completed.stdout or "").strip()
    if not stdout:
        return None

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        if is_online_hook_command(command):
            hook_error = parse_online_hook_error(stdout, completed.stderr)
            if hook_error is not None:
                raise hook_error
        return None
    return parsed if isinstance(parsed, dict) else None


def semantic_structure_records_by_id(target: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    evidence_blocks = {
        str(record.get("evidence_block_id", "")).strip(): record
        for record in load_jsonl(target / EVIDENCE_BLOCKS_REL_PATH)
        if str(record.get("evidence_block_id", "")).strip()
    }
    knowledge_units = {
        str(record.get("knowledge_unit_id", "")).strip(): record
        for record in load_jsonl(target / KNOWLEDGE_UNITS_REL_PATH)
        if str(record.get("knowledge_unit_id", "")).strip()
    }
    return evidence_blocks, knowledge_units


def sorted_counter_dict(counter: Counter[str], limit: int = 12) -> dict[str, int]:
    return {
        key: count
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
        if key
    }


def first_non_empty_string(values: list[object]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def claim_structure_context(
    claim_record: dict,
    evidence_blocks_by_id: dict[str, dict],
    knowledge_units_by_id: dict[str, dict],
) -> dict:
    knowledge_unit_ids = normalize_string_list(claim_record.get("knowledge_unit_ids"))
    evidence_block_ids = normalize_string_list(claim_record.get("evidence_block_ids"))
    source_refs = claim_record.get("source_refs", [])
    if not isinstance(source_refs, list):
        source_refs = []

    for source_ref in source_refs:
        if not isinstance(source_ref, dict):
            continue
        for knowledge_unit_id in normalize_string_list(source_ref.get("knowledge_unit_id")):
            if knowledge_unit_id not in knowledge_unit_ids:
                knowledge_unit_ids.append(knowledge_unit_id)
        for evidence_block_id in normalize_string_list(source_ref.get("evidence_block_ids")):
            if evidence_block_id not in evidence_block_ids:
                evidence_block_ids.append(evidence_block_id)

    knowledge_units = [
        knowledge_units_by_id[unit_id]
        for unit_id in knowledge_unit_ids
        if unit_id in knowledge_units_by_id
    ]
    evidence_blocks = [
        evidence_blocks_by_id[evidence_id]
        for evidence_id in evidence_block_ids
        if evidence_id in evidence_blocks_by_id
    ]

    section_path_parts: list[str] = []
    section_title = ""
    parent_section_path = ""
    heading_level = 0
    for source_ref in source_refs:
        if not isinstance(source_ref, dict):
            continue
        if not section_path_parts:
            section_path_parts = normalize_string_list(source_ref.get("section_path_parts"))
        if not section_title:
            section_title = str(source_ref.get("section_title", "")).strip()
        if not parent_section_path:
            parent_section_path = str(source_ref.get("parent_section_path", "")).strip()
        if not heading_level:
            heading_level = coerce_int(source_ref.get("heading_level", 0), 0)

    if not section_path_parts:
        for evidence_block in evidence_blocks:
            section_path_parts = normalize_string_list(evidence_block.get("section_path_parts"))
            if section_path_parts:
                break
    if not section_title and section_path_parts:
        section_title = section_path_parts[-1]
    if not parent_section_path and len(section_path_parts) > 1:
        parent_section_path = " > ".join(section_path_parts[:-1])
    if not heading_level and section_path_parts:
        heading_level = len(section_path_parts)

    content_tag_counter: Counter[str] = Counter()
    semantic_feature_counter: Counter[str] = Counter()
    semantic_feature_strength_counter: Counter[str] = Counter()
    unit_kind_counter: Counter[str] = Counter()
    evidence_kind_counter: Counter[str] = Counter()
    metadata_key_counter: Counter[str] = Counter()
    local_headings: list[str] = []
    seen_content_tag_sources: set[tuple[str, str]] = set()

    for knowledge_unit in knowledge_units:
        unit_kind = str(knowledge_unit.get("unit_kind", "")).strip()
        if unit_kind:
            unit_kind_counter[unit_kind] += 1
        local_heading = str(knowledge_unit.get("local_heading", "") or "").strip()
        if local_heading and local_heading not in local_headings:
            local_headings.append(local_heading)
        metadata = knowledge_unit.get("metadata", {})
        if isinstance(metadata, dict):
            for key in metadata:
                if str(key).strip():
                    metadata_key_counter[str(key).strip()] += 1
        projection = knowledge_unit.get("semantic_projection", {})
        if isinstance(projection, dict):
            source_key = first_non_empty_string(
                normalize_string_list(knowledge_unit.get("evidence_block_ids"))
                + [knowledge_unit.get("knowledge_unit_id", "")]
            )
            for tag in normalize_string_list(projection.get("content_tags")):
                tag_key = (source_key or f"knowledge_unit:{len(seen_content_tag_sources)}", tag)
                if tag_key not in seen_content_tag_sources:
                    seen_content_tag_sources.add(tag_key)
                    content_tag_counter[tag] += 1
            for feature in projection.get("semantic_features", []) or []:
                if not isinstance(feature, dict):
                    continue
                tag = str(feature.get("tag", "")).strip()
                strength = str(feature.get("strength", "")).strip()
                if tag:
                    semantic_feature_counter[tag] += 1
                if strength:
                    semantic_feature_strength_counter[strength] += 1

    for evidence_block in evidence_blocks:
        block_kind = str(evidence_block.get("block_kind", "")).strip()
        if block_kind:
            evidence_kind_counter[block_kind] += 1
        local_heading = str(evidence_block.get("local_heading", "") or "").strip()
        if local_heading and local_heading not in local_headings:
            local_headings.append(local_heading)
        metadata = evidence_block.get("metadata", {})
        if isinstance(metadata, dict):
            for key in metadata:
                if str(key).strip():
                    metadata_key_counter[str(key).strip()] += 1
        source_key = str(evidence_block.get("evidence_block_id", "")).strip()
        for tag in normalize_string_list(evidence_block.get("content_tags")):
            tag_key = (source_key or f"evidence_block:{len(seen_content_tag_sources)}", tag)
            if tag_key not in seen_content_tag_sources:
                seen_content_tag_sources.add(tag_key)
                content_tag_counter[tag] += 1
        for feature in evidence_block.get("semantic_features", []) or []:
            if not isinstance(feature, dict):
                continue
            tag = str(feature.get("tag", "")).strip()
            strength = str(feature.get("strength", "")).strip()
            if tag:
                semantic_feature_counter[tag] += 1
            if strength:
                semantic_feature_strength_counter[strength] += 1

    return {
        "section_path_parts": section_path_parts,
        "section_title": section_title,
        "parent_section_path": parent_section_path,
        "heading_level": heading_level,
        "local_headings": local_headings[:5],
        "unit_kind_counts": sorted_counter_dict(unit_kind_counter),
        "evidence_block_kind_counts": sorted_counter_dict(evidence_kind_counter),
        "content_tag_counts": sorted_counter_dict(content_tag_counter),
        "semantic_feature_counts": sorted_counter_dict(semantic_feature_counter),
        "semantic_feature_strength_counts": sorted_counter_dict(semantic_feature_strength_counter),
        "metadata_key_counts": sorted_counter_dict(metadata_key_counter),
        "source_ref_count": len(source_refs),
        "knowledge_unit_ids": knowledge_unit_ids[:8],
        "evidence_block_ids": evidence_block_ids[:12],
    }


def page_intent_group_context(grouped_claims: list[dict]) -> dict:
    role_counter: Counter[str] = Counter()
    hint_counter: Counter[str] = Counter()
    content_tag_counter: Counter[str] = Counter()
    unit_kind_counter: Counter[str] = Counter()
    evidence_kind_counter: Counter[str] = Counter()
    semantic_feature_counter: Counter[str] = Counter()
    section_counter: Counter[str] = Counter()
    local_headings: list[str] = []

    for claim_record in grouped_claims:
        role = claim_knowledge_role(claim_record)
        if role:
            role_counter[role] += 1
        hint_counter.update(claim_page_intent_hints(claim_record))

        context = claim_record.get("structure_context", {})
        if not isinstance(context, dict):
            context = {}
        content_tag_counter.update(dict(context.get("content_tag_counts", {}) or {}))
        unit_kind_counter.update(dict(context.get("unit_kind_counts", {}) or {}))
        evidence_kind_counter.update(dict(context.get("evidence_block_kind_counts", {}) or {}))
        semantic_feature_counter.update(dict(context.get("semantic_feature_counts", {}) or {}))
        section_path = " > ".join(normalize_string_list(context.get("section_path_parts")))
        if section_path:
            section_counter[section_path] += 1
        for heading in normalize_string_list(context.get("local_headings")):
            if heading not in local_headings:
                local_headings.append(heading)

    return {
        "knowledge_role_counts": sorted_counter_dict(role_counter),
        "page_intent_hint_counts": sorted_counter_dict(hint_counter),
        "content_tag_counts": sorted_counter_dict(content_tag_counter),
        "unit_kind_counts": sorted_counter_dict(unit_kind_counter),
        "evidence_block_kind_counts": sorted_counter_dict(evidence_kind_counter),
        "semantic_feature_counts": sorted_counter_dict(semantic_feature_counter),
        "section_path_counts": sorted_counter_dict(section_counter),
        "representative_local_headings": local_headings[:8],
    }


def page_route_structure_projection(grouped_claims: list[dict]) -> dict:
    section_counter: Counter[str] = Counter()
    metadata_key_counter: Counter[str] = Counter()
    evidence_kind_counter: Counter[str] = Counter()
    content_tag_counter: Counter[str] = Counter()
    supporting_unit_ids: list[str] = []
    supporting_evidence_block_ids: list[str] = []

    for claim_record in grouped_claims:
        context = claim_record.get("structure_context", {})
        if not isinstance(context, dict):
            context = {}

        section_path = " > ".join(normalize_string_list(context.get("section_path_parts")))
        if section_path:
            section_counter[section_path] += 1

        for key, count in dict(context.get("metadata_key_counts", {}) or {}).items():
            cleaned_key = str(key).strip()
            if cleaned_key:
                metadata_key_counter[cleaned_key] += coerce_int(count, 0) or 1

        for key, count in dict(context.get("evidence_block_kind_counts", {}) or {}).items():
            cleaned_key = str(key).strip()
            if cleaned_key:
                evidence_kind_counter[cleaned_key] += coerce_int(count, 0) or 1

        for key, count in dict(context.get("content_tag_counts", {}) or {}).items():
            cleaned_key = str(key).strip()
            if cleaned_key:
                content_tag_counter[cleaned_key] += coerce_int(count, 0) or 1

        for unit_id in normalize_string_list(context.get("knowledge_unit_ids")):
            append_unique(supporting_unit_ids, unit_id)
        for evidence_block_id in normalize_string_list(context.get("evidence_block_ids")):
            append_unique(supporting_evidence_block_ids, evidence_block_id)

    return {
        "section_path_counts": sorted_counter_dict(section_counter, limit=8),
        "metadata_key_counts": sorted_counter_dict(metadata_key_counter, limit=8),
        "evidence_block_kind_counts": sorted_counter_dict(evidence_kind_counter, limit=8),
        "content_tag_counts": sorted_counter_dict(content_tag_counter, limit=8),
        "supporting_unit_ids": supporting_unit_ids[:16],
        "supporting_evidence_block_ids": supporting_evidence_block_ids[:24],
    }


def page_semantic_frontmatter_projection(
    claim_records: list[dict],
    structure_projection: dict | None = None,
) -> dict:
    return build_page_semantic_frontmatter_projection_helper(
        claim_records,
        structure_projection,
        claim_semantic_projection=claim_semantic_projection,
        normalize_string_list=normalize_string_list,
        coerce_int=coerce_int,
        sorted_counter_dict=sorted_counter_dict,
    )


def enrich_claim_records_with_structure_context(target: Path, claim_records: list[dict]) -> list[dict]:
    return enrich_claim_records_with_structure_context_helper(
        target,
        claim_records,
        semantic_structure_records_by_id=semantic_structure_records_by_id,
        claim_structure_context=claim_structure_context,
    )


def prepare_page_semantic_context(target: Path, claim_records: list[dict]) -> dict:
    return prepare_page_semantic_context_helper(
        target,
        claim_records,
        enrich_claim_records_with_structure_context=enrich_claim_records_with_structure_context,
        page_route_structure_projection=page_route_structure_projection,
        build_page_semantic_frontmatter_projection=page_semantic_frontmatter_projection,
    )


def collect_semantic_task_items(target: Path, task_name: str) -> list[dict]:
    if task_name == "document_analysis":
        records = load_jsonl(target / "state" / "normalized.jsonl")
        items = []
        for record in records:
            source_id = str(record.get("source_id", "")).strip()
            normalized_path = str(record.get("normalized_path", "")).strip()
            if not source_id or not normalized_path:
                continue
            items.append(
                {
                    "item_id": source_id,
                    "source_id": source_id,
                    "normalized_path": normalized_path,
                    "title": record.get("title", ""),
                    "extraction_quality": record.get("extraction_quality"),
                }
            )
        return items

    if task_name == "claim_candidate_quality":
        records = load_jsonl(target / "state" / "claims.jsonl")
        items = []
        for record in records:
            claim_id = str(record.get("claim_id", "")).strip()
            text = str(record.get("text", "")).strip()
            if (
                not claim_id
                or not text
                or record.get("lifecycle_status", "active") != "active"
                or not claim_candidate_has_short_gray_zone(text)
            ):
                continue
            cleaned_text = clean_claim_candidate_text(text)
            natural_char_count = len([
                char for char in cleaned_text
                if char.isalnum() or "\u4e00" <= char <= "\u9fff"
            ])
            items.append(
                {
                    "item_id": claim_id,
                    "claim_id": claim_id,
                    "text": text,
                    "cleaned_text": cleaned_text,
                    "claim_type": record.get("claim_type"),
                    "natural_char_count": natural_char_count,
                    "source_ids": record.get("source_ids", []),
                    "source_refs": record.get("source_refs", []),
                }
            )
        return items

    if task_name == "claim_role":
        records = load_jsonl(target / "state" / "claims.jsonl")
        evidence_blocks_by_id, knowledge_units_by_id = semantic_structure_records_by_id(target)
        items = []
        for record in records:
            claim_id = str(record.get("claim_id", "")).strip()
            if not claim_id or record.get("lifecycle_status", "active") != "active":
                continue
            items.append(
                {
                    "item_id": claim_id,
                    "claim_id": claim_id,
                    "text": record.get("text", ""),
                    "claim_type": record.get("claim_type"),
                    "quality_label": record.get("quality_label"),
                    "quality_reason": record.get("quality_reason"),
                    "quality_safe_auto_ready": record.get("quality_safe_auto_ready"),
                    "source_ids": record.get("source_ids", []),
                    "source_refs": record.get("source_refs", []),
                    "structure_context": claim_structure_context(
                        record,
                        evidence_blocks_by_id=evidence_blocks_by_id,
                        knowledge_units_by_id=knowledge_units_by_id,
                    ),
                }
            )
        return items

    if task_name == "page_intent":
        records = load_jsonl(target / "state" / "claims.jsonl")
        evidence_blocks_by_id, knowledge_units_by_id = semantic_structure_records_by_id(target)
        groups: dict[str, list[dict]] = {}
        for record in records:
            if record.get("lifecycle_status", "active") != "active":
                continue
            bucket_key = build_concept_group_key(record)
            if not bucket_key:
                continue
            enriched_record = dict(record)
            enriched_record["structure_context"] = claim_structure_context(
                record,
                evidence_blocks_by_id=evidence_blocks_by_id,
                knowledge_units_by_id=knowledge_units_by_id,
            )
            groups.setdefault(bucket_key, []).append(enriched_record)

        items = []
        for bucket_key, grouped_claims in sorted(groups.items()):
            items.append(build_page_intent_item_payload(bucket_key, grouped_claims))
        return items

    raise KeyError(f"Unsupported semantic task: {task_name}")


def chunk_semantic_items(items: list[dict], batch_size: int) -> list[list[dict]]:
    if batch_size <= 0:
        batch_size = 1
    return [items[index:index + batch_size] for index in range(0, len(items), batch_size)]


def normalize_semantic_batch_results(
    task_name: str,
    hook_result: dict,
    batch_items: list[dict],
    config: SemanticTaskConfig,
) -> tuple[list[dict], list[dict]]:
    decisions = hook_result.get("decisions", [])
    if not isinstance(decisions, list):
        return [], []

    item_map = {str(item.get("item_id")): item for item in batch_items if item.get("item_id")}
    normalized: list[dict] = []
    skipped: list[dict] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        item_id = str(decision.get("item_id", "")).strip()
        if not item_id or item_id not in item_map:
            continue
        confidence = coerce_float(decision.get("confidence", 0.0), 0.0)
        if confidence < config.min_confidence:
            skipped.append({
                "item_id": item_id,
                "decision_status": "rejected",
                "reason_code": str(decision.get("reason_code", "")).strip() or "semantic_batch_low_confidence",
                "confidence": confidence,
                "risk_flags": ["semantic_decision_low_confidence"],
            })
            continue
        normalized_decision = normalize_semantic_hook_decision(task_name, decision)
        if normalized_decision["decision_status"] != "accepted":
            skipped.append({
                "item_id": item_id,
                "decision_status": normalized_decision["decision_status"],
                "reason_code": str(decision.get("reason_code", "")).strip() or "semantic_batch_result",
                "confidence": confidence,
                "risk_flags": normalized_decision["risk_flags"],
                "abstain_reason": normalized_decision["abstain_reason"],
                "missing_fields": normalized_decision["missing_fields"],
            })
            continue
        item_payload = item_map[item_id]
        input_fingerprint = fingerprint_payload(
            task_name=task_name,
            item_payloads=[item_payload],
            prompt_version=config.prompt_version,
            schema_version=config.schema_version,
        )
        normalized.append(
            {
                "decision_id": build_semantic_decision_id(task_name, input_fingerprint),
                "task_type": task_name,
                "item_type": item_type_for_task(task_name),
                "item_ids": [item_id],
                "decision": normalized_decision["decision"],
                "decision_status": normalized_decision["decision_status"],
                "confidence": confidence,
                "reason_code": str(decision.get("reason_code", "")).strip() or "semantic_batch_result",
                "risk_flags": normalized_decision["risk_flags"],
                "supporting_ids": normalized_decision["supporting_ids"],
                "abstain_reason": normalized_decision["abstain_reason"],
                "prompt_version": config.prompt_version,
                "model_key": config.model_key,
                "schema_version": config.schema_version,
                "input_fingerprint": input_fingerprint,
                "created_at": utc_now_iso(),
                "superseded_by": [],
            }
        )
    return normalized, skipped


def run_semantic_batch_task(
    target: Path,
    task_name: str,
    dry_run: bool = False,
) -> dict:
    config = load_semantic_task_config(load_workspace_config(target), task_name)
    items = collect_semantic_task_items(target, task_name)
    existing_records = load_semantic_decisions(target)
    existing_by_fingerprint = build_latest_semantic_decisions_by_fingerprint(existing_records)

    cache_hits = 0
    pending_batches: list[tuple[list[dict], list[str]]] = []
    for batch_items in chunk_semantic_items(items, config.batch_size):
        pending_items = []
        cached_ids = []
        for item in batch_items:
            input_fingerprint = fingerprint_payload(
                task_name=task_name,
                item_payloads=[item],
                prompt_version=config.prompt_version,
                schema_version=config.schema_version,
            )
            if input_fingerprint in existing_by_fingerprint:
                cache_hits += 1
                cached_ids.append(str(item.get("item_id")))
            else:
                pending_items.append(item)
        if pending_items:
            pending_batches.append((pending_items, cached_ids))

    written_decisions: list[dict] = []
    batch_reports = []
    ensure_directory(semantic_batches_dir(target))

    for batch_index, (batch_items, cached_ids) in enumerate(pending_batches, start=1):
        payload = {
            "task": f"review_{task_name}_batch",
            "task_name": task_name,
            "prompt_version": config.prompt_version,
            "schema_version": config.schema_version,
            "items": batch_items,
        }
        hook_result = run_json_automation_command(
            target=target,
            command=config.command,
            payload=payload,
            timeout_seconds=config.timeout_seconds,
        ) if config.enabled else None
        normalized_results, skipped_results = normalize_semantic_batch_results(task_name, hook_result or {}, batch_items, config)

        batch_report = {
            "task_name": task_name,
            "batch_index": batch_index,
            "item_ids": [str(item.get("item_id")) for item in batch_items],
            "cached_item_ids": cached_ids,
            "decision_count": len(normalized_results),
            "skipped_decision_count": len(skipped_results),
            "skipped_decisions": skipped_results,
            "created_at": utc_now_iso(),
        }
        write_json(
            semantic_batches_dir(target) / f"{task_name}_batch_{batch_index:04d}.json",
            batch_report,
        )
        batch_reports.append(batch_report)
        written_decisions.extend(normalized_results)

    if written_decisions and not dry_run:
        repo_append_semantic_decision_records(
            target,
            written_decisions,
            semantic_decisions_rel_path=SEMANTIC_DECISIONS_REL_PATH,
            append_jsonl=append_jsonl,
        )

    return {
        "task_name": task_name,
        "workspace_summary": build_workspace_summary(target),
        "summary": {
            "item_count": len(items),
            "cache_hits": cache_hits,
            "pending_batch_count": len(pending_batches),
            "written_decision_count": 0 if dry_run else len(written_decisions),
            "dry_run": dry_run,
        },
        "config": {
            "strategy": config.strategy,
            "batch_size": config.batch_size,
            "model_key": config.model_key,
            "prompt_version": config.prompt_version,
            "schema_version": config.schema_version,
            "enabled": config.enabled,
        },
        "batch_reports": batch_reports,
        "decisions": written_decisions,
    }


def apply_document_analysis_decisions_to_normalized_records(
    target: Path,
    normalized_records: list[dict],
    task_config: SemanticTaskConfig,
) -> list[dict]:
    latest_decisions = build_latest_semantic_decisions_by_fingerprint(load_semantic_decisions(target))
    normalized_by_source_id = {record["source_id"]: dict(record) for record in normalized_records}
    changed_records: list[dict] = []

    for record in normalized_records:
        item_payload = {
            "item_id": record["source_id"],
            "source_id": record["source_id"],
            "normalized_path": record.get("normalized_path", ""),
            "title": record.get("title", ""),
            "extraction_quality": record.get("extraction_quality"),
        }
        fingerprint = fingerprint_payload(
            task_name="document_analysis",
            item_payloads=[item_payload],
            prompt_version=task_config.prompt_version,
            schema_version=task_config.schema_version,
        )
        decision_record = latest_decisions.get(fingerprint)
        if decision_record is None:
            continue
        decision = decision_record.get("decision", {})
        if not isinstance(decision, dict):
            continue

        updated_record = dict(normalized_by_source_id[record["source_id"]])
        updated_record["document_kind"] = decision.get("document_kind", updated_record.get("document_kind", "note"))
        updated_record["structure_quality"] = decision.get("structure_quality", updated_record.get("structure_quality", "unknown"))
        updated_record["chunk_strategy_hint"] = decision.get("chunk_strategy_hint", updated_record.get("chunk_strategy_hint", "heading_first"))
        normalized_by_source_id[record["source_id"]] = updated_record
        changed_records.append(updated_record)

    if changed_records:
        ordered_records = []
        for record in normalized_records:
            ordered_records.append(normalized_by_source_id[record["source_id"]])
        write_jsonl(target / "state" / "normalized.jsonl", ordered_records)
        return ordered_records
    return normalized_records


def apply_claim_role_decisions_to_claim_records(
    target: Path,
    claim_records: list[dict],
    task_config: SemanticTaskConfig,
) -> list[dict]:
    latest_decisions = build_latest_semantic_decisions_by_fingerprint(load_semantic_decisions(target))
    claims_by_id = {record["claim_id"]: dict(record) for record in claim_records}
    evidence_blocks_by_id, knowledge_units_by_id = semantic_structure_records_by_id(target)
    changed = False

    for record in claim_records:
        item_payload = {
            "item_id": record["claim_id"],
            "claim_id": record["claim_id"],
            "text": record.get("text", ""),
            "claim_type": record.get("claim_type"),
            "quality_label": record.get("quality_label"),
            "quality_reason": record.get("quality_reason"),
            "quality_safe_auto_ready": record.get("quality_safe_auto_ready"),
            "source_ids": record.get("source_ids", []),
            "source_refs": record.get("source_refs", []),
            "structure_context": claim_structure_context(
                record,
                evidence_blocks_by_id=evidence_blocks_by_id,
                knowledge_units_by_id=knowledge_units_by_id,
            ),
        }
        fingerprint = fingerprint_payload(
            task_name="claim_role",
            item_payloads=[item_payload],
            prompt_version=task_config.prompt_version,
            schema_version=task_config.schema_version,
        )
        decision_record = latest_decisions.get(fingerprint)
        if decision_record is None:
            continue
        decision = decision_record.get("decision", {})
        if not isinstance(decision, dict):
            continue

        updated = dict(claims_by_id[record["claim_id"]])
        updated["knowledge_role"] = decision.get("knowledge_role", updated.get("knowledge_role"))
        updated["page_intent_hints"] = list(decision.get("page_intent_hints", updated.get("page_intent_hints", [])) or [])
        updated["concept_candidate_score"] = coerce_float(
            decision.get("concept_candidate_score", updated.get("concept_candidate_score", 0.0)),
            coerce_float(updated.get("concept_candidate_score", 0.0), 0.0),
        )
        append_unique(updated.setdefault("semantic_decision_ids", []), decision_record["decision_id"])
        updated = sync_claim_semantic_projection(updated)
        updated["updated_at"] = utc_now_iso()
        claims_by_id[record["claim_id"]] = updated
        changed = True

    ordered_records = []
    for record in claim_records:
        ordered_records.append(claims_by_id[record["claim_id"]])

    if changed:
        write_jsonl(target / "state" / "claims.jsonl", ordered_records)
        for record in ordered_records:
            write_claim_file(target, record)
    return ordered_records


def apply_claim_candidate_quality_decisions_to_claim_records(
    target: Path,
    claim_records: list[dict],
    task_config: SemanticTaskConfig,
) -> tuple[list[dict], set[str], set[str]]:
    latest_decisions = build_latest_semantic_decisions_by_fingerprint(load_semantic_decisions(target))
    live_claims_by_id = {
        record["claim_id"]: dict(record)
        for record in claim_records
        if is_live_claim_record(record)
    }
    historical_claims_by_id = {
        record["claim_id"]: dict(record)
        for record in claim_records
        if not is_live_claim_record(record)
    }
    live_reviews_by_id, historical_reviews_by_id, _ = load_review_state_maps(target)
    changed = False
    archived_claim_ids: set[str] = set()
    affected_review_ids: set[str] = set()

    for record in claim_records:
        if not is_live_claim_record(record):
            continue
        if not claim_candidate_has_short_gray_zone(record.get("text", "")):
            continue
        item_payload = {
            "item_id": record["claim_id"],
            "claim_id": record["claim_id"],
            "text": record.get("text", ""),
            "cleaned_text": clean_claim_candidate_text(record.get("text", "")),
            "claim_type": record.get("claim_type"),
            "natural_char_count": len([
                char for char in clean_claim_candidate_text(record.get("text", ""))
                if char.isalnum() or "\u4e00" <= char <= "\u9fff"
            ]),
            "source_ids": record.get("source_ids", []),
            "source_refs": record.get("source_refs", []),
        }
        fingerprint = fingerprint_payload(
            task_name="claim_candidate_quality",
            item_payloads=[item_payload],
            prompt_version=task_config.prompt_version,
            schema_version=task_config.schema_version,
        )
        decision_record = latest_decisions.get(fingerprint)
        if decision_record is None:
            continue
        decision = decision_record.get("decision", {})
        if not isinstance(decision, dict):
            continue

        claim_id = record["claim_id"]
        updated = dict(live_claims_by_id[claim_id])
        updated["quality_label"] = str(decision.get("quality_label", "")).strip() or updated.get("quality_label")
        updated["quality_reason"] = str(decision.get("reason", "")).strip() or updated.get("quality_reason")
        updated["quality_confidence"] = coerce_float(
            decision_record.get("confidence", updated.get("quality_confidence", 0.0)),
            coerce_float(updated.get("quality_confidence", 0.0), 0.0),
        )
        quality_review_required = decision.get("review_required")
        if quality_review_required is not None:
            updated["quality_review_required"] = bool(quality_review_required)
        quality_safe_auto_ready = decision.get("safe_auto_ready")
        if quality_safe_auto_ready is not None:
            updated["quality_safe_auto_ready"] = bool(quality_safe_auto_ready)
        updated["quality_decision_source"] = "semantic_batch"
        append_unique(updated.setdefault("semantic_decision_ids", []), decision_record["decision_id"])
        updated = sync_claim_semantic_projection(updated)
        updated["updated_at"] = utc_now_iso()

        quality_label = str(updated.get("quality_label") or "").strip().lower()
        if quality_label in {"noise", "title_shell"}:
            archived_claim_ids.add(claim_id)
            archived_record = archive_live_claim(
                claim_record=updated,
                live_claims_by_id=live_claims_by_id,
                historical_claims_by_id=historical_claims_by_id,
            )
            affected_review_ids.update(
                purge_deleted_claims_from_reviews(
                    reviews_by_id=live_reviews_by_id,
                    historical_reviews_by_id=historical_reviews_by_id,
                    deleted_claim_ids={claim_id},
                )[0]
            )
            live_claims_by_id.pop(claim_id, None)
            historical_claims_by_id[archived_record["claim_id"]] = archived_record
            changed = True
            continue

        if updated.get("quality_review_required") and updated.get("status") == "draft":
            updated["status"] = "needs_review"
            updated["review_reason"] = "claim_quality_requires_human_review"
        live_claims_by_id[claim_id] = updated
        changed = True

    ordered_records = build_ordered_claim_state_records(
        live_claims_by_id=live_claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
    )
    if changed:
        write_jsonl(target / "state" / "claims.jsonl", ordered_records)
        for record in ordered_records:
            write_claim_file(target, record)
        review_state_records = build_ordered_review_state_records(
            live_reviews_by_id=live_reviews_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
        )
        write_jsonl(target / "state" / "reviews.jsonl", review_state_records)
        for review_record in review_state_records:
            write_review_file(target, review_record)
        cleanup_superseded_record_files(
            target=target,
            historical_claims_by_id=historical_claims_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
        )
    return ordered_records, archived_claim_ids, affected_review_ids


SPECIALIZED_PAGE_INTENTS = {"guide", "duty", "example", "reference", "timeline"}
PAGE_INTENT_ROLE_SIGNALS = {
    "guide": {"procedure"},
    "duty": {"fact"},
    "example": {"example"},
}
PAGE_INTENT_CONTENT_TAG_SIGNALS = {
    "guide": {"procedural_language"},
    "duty": {"organization_structure"},
    "example": {"cases"},
    "reference": {"rules"},
    "timeline": {"temporal_language"},
}
PAGE_INTENT_BLOCK_SIGNALS = {
    "duty": {"metadata_line"},
    "reference": {"table_row", "metadata_line"},
    "example": {"code_example"},
}


def counter_value(counter_payload: dict, key: str) -> int:
    if not isinstance(counter_payload, dict):
        return 0
    return coerce_int(counter_payload.get(key, 0), 0)


def sum_counter_values(counter_payload: dict, keys: set[str]) -> int:
    return sum(counter_value(counter_payload, key) for key in keys)


def page_intent_signal_counts(page_intent: str, item_payload: dict) -> dict[str, int]:
    group_context = item_payload.get("group_context", {})
    if not isinstance(group_context, dict):
        group_context = {}
    return {
        "hint_count": counter_value(group_context.get("page_intent_hint_counts", {}), page_intent),
        "role_count": sum_counter_values(
            group_context.get("knowledge_role_counts", {}),
            PAGE_INTENT_ROLE_SIGNALS.get(page_intent, set()),
        ),
        "content_tag_count": sum_counter_values(
            group_context.get("content_tag_counts", {}),
            PAGE_INTENT_CONTENT_TAG_SIGNALS.get(page_intent, set()),
        ),
        "block_count": sum_counter_values(
            group_context.get("evidence_block_kind_counts", {}),
            PAGE_INTENT_BLOCK_SIGNALS.get(page_intent, set()),
        ),
    }


def downgrade_specialized_page_intent(grouped_claims: list[dict]) -> str:
    return "concept" if should_generate_concept_page(grouped_claims) else "topic"


def page_intent_has_enough_group_evidence(page_intent: str, item_payload: dict) -> bool:
    if page_intent not in SPECIALIZED_PAGE_INTENTS:
        return True
    counts = page_intent_signal_counts(page_intent, item_payload)
    multi_signal_count = counts["hint_count"] + counts["role_count"] + counts["content_tag_count"]
    return multi_signal_count >= 2 or counts["block_count"] >= 1


def validate_page_intent_candidate(
    page_intent: str,
    grouped_claims: list[dict],
    item_payload: dict,
    decision_record: dict | None,
    route_reason: str,
) -> tuple[str, str]:
    normalized_intent = str(page_intent or "").strip().lower() or "topic"
    if normalized_intent not in SPECIALIZED_PAGE_INTENTS:
        return normalized_intent, route_reason

    counts = page_intent_signal_counts(normalized_intent, item_payload)
    if page_intent_has_enough_group_evidence(normalized_intent, item_payload):
        return normalized_intent, route_reason

    risk_flags = []
    decision_content_tags: list[str] = []
    if isinstance(decision_record, dict):
        risk_flags = normalize_string_list(decision_record.get("risk_flags"))
        decision = decision_record.get("decision", {})
        if isinstance(decision, dict):
            decision_content_tags = normalize_string_list(decision.get("content_tags"))
    expected_content_tags = PAGE_INTENT_CONTENT_TAG_SIGNALS.get(normalized_intent, set())
    decision_tag_signal = bool(expected_content_tags & set(decision_content_tags))
    source_is_strong = (
        decision_record is not None
        and "strong_" in str(route_reason)
        and not any("ambiguous" in flag for flag in risk_flags)
    )
    has_any_signal = any(count > 0 for count in counts.values())
    if source_is_strong and (has_any_signal or decision_tag_signal):
        return normalized_intent, route_reason

    downgraded_intent = downgrade_specialized_page_intent(grouped_claims)
    return downgraded_intent, f"page_intent_validation_downgraded_{normalized_intent}_insufficient_group_evidence"


def choose_bucket_page_intent(grouped_claims: list[dict]) -> str:
    if not grouped_claims:
        return "reject"
    item_payload = build_page_intent_item_payload("heuristic_bucket", grouped_claims)
    section_path_counts = dict(item_payload.get("group_context", {}).get("section_path_counts", {}) or {})
    if any(
        any(marker in section_path for marker in ("岗位职责", "部门职责", "工作职责", "小组职责", "岗位角色", "部门角色", "组织角色"))
        for section_path in section_path_counts
    ):
        if page_intent_has_enough_group_evidence("duty", item_payload):
            return "duty"
    hint_counts: Counter[str] = Counter()
    for claim_record in grouped_claims:
        for hint in claim_page_intent_hints(claim_record):
            normalized_hint = str(hint).strip().lower()
            if normalized_hint:
                hint_counts[normalized_hint] += 1
    for preferred in ("reject", "timeline", "reference", "guide", "duty", "example", "concept", "topic"):
        if not hint_counts.get(preferred):
            continue
        if preferred in SPECIALIZED_PAGE_INTENTS and not page_intent_has_enough_group_evidence(preferred, item_payload):
            continue
        if preferred == "reject" and hint_counts[preferred] < len(grouped_claims):
            continue
        return preferred
    return "concept" if should_generate_concept_page(grouped_claims) else "topic"


def build_page_intent_item_payload(bucket_key: str, grouped_claims: list[dict]) -> dict:
    ordered_claims = sorted(
        grouped_claims,
        key=lambda item: str(item.get("claim_id", "")).strip(),
    )
    claim_ids = [
        str(item.get("claim_id", "")).strip()
        for item in ordered_claims
        if str(item.get("claim_id", "")).strip()
    ]
    preview_texts = [
        str(item.get("text", "")).strip()
        for item in ordered_claims[:5]
        if str(item.get("text", "")).strip()
    ]
    claim_semantics = []
    for item in ordered_claims:
        claim_id = str(item.get("claim_id", "")).strip()
        if not claim_id:
            continue
        claim_semantics.append(
            {
                "claim_id": claim_id,
                "knowledge_role": claim_knowledge_role(item),
                "page_intent_hints": claim_page_intent_hints(item),
                "concept_candidate_score": claim_concept_candidate_score(item),
            }
        )
    return {
        "item_id": bucket_key,
        "bucket_key": bucket_key,
        "claim_ids": claim_ids,
        "claim_texts": preview_texts,
        "claim_count": len(claim_ids),
        "claim_semantics": claim_semantics,
        "group_context": page_intent_group_context(ordered_claims),
    }


def apply_page_intent_decisions_to_claim_groups(
    target: Path,
    concept_claim_groups: dict[str, list[dict]],
    task_config: SemanticTaskConfig,
) -> dict[str, dict]:
    latest_decisions = build_latest_semantic_decisions_by_fingerprint(load_semantic_decisions(target))
    evidence_blocks_by_id, knowledge_units_by_id = semantic_structure_records_by_id(target)
    page_routes: dict[str, dict] = {}
    new_route_decisions: list[dict] = []

    for bucket_key, grouped_claims in concept_claim_groups.items():
        enriched_grouped_claims = []
        for record in grouped_claims:
            enriched_record = dict(record)
            enriched_record["structure_context"] = claim_structure_context(
                record,
                evidence_blocks_by_id=evidence_blocks_by_id,
                knowledge_units_by_id=knowledge_units_by_id,
            )
            enriched_grouped_claims.append(enriched_record)
        item_payload = build_page_intent_item_payload(bucket_key, enriched_grouped_claims)
        fingerprint = fingerprint_payload(
            task_name="page_intent",
            item_payloads=[item_payload],
            prompt_version=task_config.prompt_version,
            schema_version=task_config.schema_version,
        )
        decision_record = latest_decisions.get(fingerprint)
        page_intent = ""
        route_reason = "heuristic_page_intent"
        source_decision_id = None
        if decision_record is not None:
            decision = decision_record.get("decision", {})
            if isinstance(decision, dict):
                page_intent = str(decision.get("page_intent", "")).strip().lower()
                if page_intent:
                    route_reason = str(decision_record.get("reason_code", "")).strip() or "semantic_page_intent"
                    source_decision_id = decision_record.get("decision_id")
        if not page_intent:
            page_intent = choose_bucket_page_intent(grouped_claims)

        original_page_intent = page_intent
        page_intent, route_reason = validate_page_intent_candidate(
            page_intent=page_intent,
            grouped_claims=grouped_claims,
            item_payload=item_payload,
            decision_record=decision_record,
            route_reason=route_reason,
        )
        section_path_counts = dict(item_payload.get("group_context", {}).get("section_path_counts", {}) or {})
        if page_intent in {"topic", "concept"} and any(
            any(marker in section_path for marker in ("岗位职责", "部门职责", "工作职责", "小组职责", "岗位角色", "部门角色", "组织角色"))
            for section_path in section_path_counts
        ):
            if page_intent_has_enough_group_evidence("duty", item_payload):
                page_intent = "duty"
                route_reason = "duty_structure_section_path_promoted"
        if page_intent == "topic" and should_generate_concept_page(grouped_claims):
            page_intent = "concept"
            route_reason = "topic_promoted_to_concept_by_claim_group"

        route_payload = {
            "item_id": bucket_key,
            "bucket_key": bucket_key,
            "claim_ids": item_payload["claim_ids"],
            "source_page_intent": original_page_intent,
            "page_intent": page_intent,
            "route_target": page_intent,
            "route_reason": route_reason,
            "source_decision_id": source_decision_id,
            "supporting_unit_ids": sorted({
                unit_id
                for claim_record in grouped_claims
                for unit_id in claim_record.get("knowledge_unit_ids", [])
            }),
            "rejected_alternatives": [
                candidate
                for candidate in ("concept", "guide", "duty", "example", "topic", "reference", "timeline")
                if candidate != page_intent
            ],
        }
        route_payload.update(page_route_structure_projection(enriched_grouped_claims))
        route_fingerprint = fingerprint_payload(
            task_name="page_route",
            item_payloads=[route_payload],
            prompt_version=task_config.prompt_version,
            schema_version=task_config.schema_version,
        )
        existing_route_decision = latest_decisions.get(route_fingerprint)
        if existing_route_decision is None:
            existing_route_decision = {
                "decision_id": build_semantic_decision_id("page_route", route_fingerprint),
                "task_type": "page_route",
                "item_type": item_type_for_task("page_route"),
                "item_ids": [bucket_key],
                "decision": route_payload,
                "confidence": 1.0 if source_decision_id else 0.75,
                "reason_code": route_reason,
                "prompt_version": task_config.prompt_version,
                "model_key": task_config.model_key,
                "schema_version": task_config.schema_version,
                "input_fingerprint": route_fingerprint,
                "created_at": utc_now_iso(),
                "superseded_by": [],
            }
            new_route_decisions.append(existing_route_decision)

        page_routes[bucket_key] = {
            "page_intent": page_intent,
            "semantic_decision_id": existing_route_decision["decision_id"],
            "route_reason": route_reason,
            "route_target": page_intent,
            "source_decision_id": source_decision_id,
            "supporting_unit_ids": route_payload["supporting_unit_ids"],
            "supporting_evidence_block_ids": route_payload["supporting_evidence_block_ids"],
            "section_path_counts": route_payload["section_path_counts"],
            "metadata_key_counts": route_payload["metadata_key_counts"],
            "evidence_block_kind_counts": route_payload["evidence_block_kind_counts"],
            "content_tag_counts": route_payload["content_tag_counts"],
            "rejected_alternatives": route_payload["rejected_alternatives"],
        }

    repo_append_semantic_decision_records(
        target,
        new_route_decisions,
        semantic_decisions_rel_path=SEMANTIC_DECISIONS_REL_PATH,
        append_jsonl=append_jsonl,
    )

    return page_routes


def preferred_page_intent_for_claim_group(
    grouped_claims: list[dict],
    page_intent: str,
) -> str:
    if page_intent == "topic" and should_generate_concept_page(grouped_claims):
        return "concept"
    return page_intent


def page_route_for_bucket(page_routes_by_bucket: dict[str, dict], bucket_key: str) -> dict:
    route = dict(page_routes_by_bucket.get(bucket_key) or {})
    route.setdefault("page_intent", "topic")
    route.setdefault("route_target", route["page_intent"])
    route.setdefault("semantic_decision_id", None)
    route.setdefault("route_reason", "missing_page_route_fallback")
    route.setdefault("source_decision_id", None)
    route.setdefault("supporting_unit_ids", [])
    route.setdefault("supporting_evidence_block_ids", [])
    route.setdefault("section_path_counts", {})
    route.setdefault("metadata_key_counts", {})
    route.setdefault("evidence_block_kind_counts", {})
    route.setdefault("content_tag_counts", {})
    route.setdefault("rejected_alternatives", [])
    return route


def apply_page_route_to_page_record(page_record: dict, page_route: dict) -> dict:
    updated = dict(page_record)
    decision_ids = list(updated.get("semantic_decision_ids", []) or [])
    semantic_decision_id = page_route.get("semantic_decision_id")
    if semantic_decision_id:
        append_unique(decision_ids, semantic_decision_id)
    source_decision_id = page_route.get("source_decision_id")
    if source_decision_id:
        append_unique(decision_ids, source_decision_id)
    updated["semantic_decision_ids"] = decision_ids
    updated["page_route"] = {
        "page_intent": page_route.get("page_intent"),
        "route_target": page_route.get("route_target"),
        "route_reason": page_route.get("route_reason"),
        "semantic_decision_id": semantic_decision_id,
        "source_decision_id": source_decision_id,
        "supporting_unit_ids": list(page_route.get("supporting_unit_ids", []) or []),
        "supporting_evidence_block_ids": list(page_route.get("supporting_evidence_block_ids", []) or []),
        "section_path_counts": dict(page_route.get("section_path_counts", {}) or {}),
        "metadata_key_counts": dict(page_route.get("metadata_key_counts", {}) or {}),
        "evidence_block_kind_counts": dict(page_route.get("evidence_block_kind_counts", {}) or {}),
        "content_tag_counts": dict(page_route.get("content_tag_counts", {}) or {}),
        "rejected_alternatives": list(page_route.get("rejected_alternatives", []) or []),
    }
    return updated


def supported_page_render_targets() -> tuple[str, ...]:
    return tuple(PAGE_RENDER_TARGETS.keys())


def page_record_render_target(page_record: dict) -> str | None:
    explicit_target = page_record.get("render_target")
    if explicit_target in PAGE_RENDER_TARGETS:
        return explicit_target

    page_type = page_record.get("type")
    for render_target, spec in PAGE_RENDER_TARGETS.items():
        if page_type in spec.get("page_types", set()):
            return render_target
    return None


def page_record_matches_render_target(page_record: dict, render_target: str) -> bool:
    return page_record_render_target(page_record) == render_target


def live_pages_for_render_target(page_records: list[dict], render_target: str) -> list[dict]:
    return [
        record
        for record in filter_live_page_records(page_records)
        if page_record_matches_render_target(record, render_target)
    ]


def load_page_render_config(config: dict, render_target: str) -> dict:
    if render_target not in PAGE_RENDER_TARGETS:
        raise KeyError(f"Unknown render target: {render_target}")
    rendering_config = config.get("rendering", {})
    target_config = (
        rendering_config.get(render_target, {})
        if isinstance(rendering_config, dict)
        else {}
    )
    if not isinstance(target_config, dict):
        target_config = {}

    mode = str(target_config.get("mode", "llm_assisted")).strip() or "llm_assisted"
    if mode not in {"deterministic", "llm_assisted"}:
        mode = "llm_assisted"

    command = normalize_command_config(target_config.get("command", []))
    timeout_seconds = coerce_int(target_config.get("timeout_seconds", 20), 20)
    timeout_seconds = max(timeout_seconds, 5)
    return {
        "render_target": render_target,
        "mode": mode,
        "command": command,
        "timeout_seconds": timeout_seconds,
    }


def load_readable_concept_render_config(config: dict) -> dict:
    return load_page_render_config(config, "readable_concept")


def resolve_workspace_path(target: Path, configured_path: str) -> Path:
    # config 里的路径既可能是相对工作区，也可能是绝对路径。
    path = Path(configured_path).expanduser()
    if path.is_absolute():
        return path
    return (target / path).resolve()


def raw_assets_dir_for_workspace(target: Path, raw_dir: Path | None = None) -> Path:
    resolved_raw_dir = raw_dir or resolve_workspace_raw_dir(target)
    return (resolved_raw_dir.parent / "assets").resolve()


def resolve_workspace_raw_dir(target: Path) -> Path:
    config = load_workspace_config(target)
    raw_dir = resolve_workspace_path(target, config["paths"]["raw"])
    if raw_dir.name != "raw":
        raise ValueError(f"Workspace raw directory must be named 'raw': {raw_dir}")
    if raw_dir.parent != target.parent:
        raise ValueError(
            f"Workspace raw directory must be a sibling of the workspace: raw={raw_dir} target={target}"
        )
    return raw_dir


def resolve_source_record_path(target: Path, source_path: str) -> Path:
    # source_path 默认按“相对工作区可访问路径”解释，这样 ../raw/... 也能稳定解析。
    path = Path(source_path).expanduser()
    if path.is_absolute():
        return path
    return (target / path).resolve()


def ensure_path_within_raw_root(path: Path, raw_root: Path, *, purpose: str) -> Path:
    resolved_path = path.resolve()
    resolved_root = raw_root.resolve()
    if not path_is_within_root(resolved_path, resolved_root):
        raise ValueError(
            f"{purpose} must stay within raw directory: path={resolved_path} raw={resolved_root}"
        )
    return resolved_path


def alias_index_path(target: Path) -> Path:
    # alias registry 是工作区级派生索引，和 search index 一样放在 indexes/ 下。
    return target / ALIAS_INDEX_REL_PATH


def page_links_index_path(target: Path) -> Path:
    # 页面链接索引记录 page -> page 的显式与派生关联，用于 query 扩展读取。
    return target / PAGE_LINKS_INDEX_REL_PATH


def page_alias_overrides_path(target: Path) -> Path:
    # 人工对页面 alias 的修订单独存一层覆盖，避免被后续自动页面重建直接抹掉。
    return target / PAGE_ALIAS_OVERRIDES_REL_PATH


def page_alias_overrides_lock_path(target: Path) -> Path:
    # review-apply 可能被多个 Agent/进程同时触发，覆盖层更新要串行化。
    return target / PAGE_ALIAS_OVERRIDES_LOCK_REL_PATH


def semantic_decisions_path(target: Path) -> Path:
    return target / SEMANTIC_DECISIONS_REL_PATH


def load_semantic_decisions(target: Path) -> list[dict]:
    return repo_load_semantic_decisions_records(
        target,
        semantic_decisions_rel_path=SEMANTIC_DECISIONS_REL_PATH,
        load_jsonl=load_jsonl,
    )


def build_latest_semantic_decisions_by_fingerprint(records: list[dict]) -> dict[str, dict]:
    return repo_build_latest_semantic_decisions_by_fingerprint(records)


def normalize_alias_value(text: str) -> str:
    # alias / canonical 查询归一化尽量沿用 claim 文本清洗逻辑，
    # 这样页面标题、别名、查询词之间更容易对齐。
    return normalize_claim_text(text)


def load_alias_index(target: Path) -> dict:
    return repo_load_alias_index(
        target,
        alias_index_rel_path=ALIAS_INDEX_REL_PATH,
        load_json=load_json,
        default_index_version=ALIAS_INDEX_VERSION,
    )


def load_page_alias_overrides(target: Path) -> dict:
    path = page_alias_overrides_path(target)
    if not path.exists():
        return {"page_aliases": {}, "accepted_conflicts": []}
    payload = load_json(path)
    payload.setdefault("page_aliases", {})
    payload.setdefault("accepted_conflicts", [])
    return payload


def write_page_alias_overrides(target: Path, payload: dict) -> None:
    payload.setdefault("page_aliases", {})
    payload.setdefault("accepted_conflicts", [])
    write_json(page_alias_overrides_path(target), payload)


@dataclass
class FileLockHandle:
    path: Path
    file_handle: object


def acquire_file_lock(path: Path) -> FileLockHandle:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handle = path.open("w", encoding="utf-8")
    fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
    return FileLockHandle(path=path, file_handle=file_handle)


def release_file_lock(lock_handle: FileLockHandle | None) -> None:
    if lock_handle is None:
        return
    fcntl.flock(lock_handle.file_handle.fileno(), fcntl.LOCK_UN)
    lock_handle.file_handle.close()


def apply_page_alias_overrides_payload(page_record: dict, overrides: dict) -> dict:
    page_aliases = overrides.get("page_aliases", {})
    override = page_aliases.get(page_record.get("page_id"), {})
    if not override:
        return page_record

    updated_record = dict(page_record)
    if "aliases" in override:
        updated_record["aliases"] = sorted(set(override.get("aliases", [])))
    if "title" in override and override.get("title"):
        updated_record["title"] = override["title"]
    updated_record["updated"] = utc_now_iso()
    return updated_record


def load_live_page_aliases_by_id(target: Path) -> dict[str, list[str]]:
    # alias 覆盖层只记录“人工最终想保留的页面 alias 集合”，
    # 但在第一次人工处理前，覆盖层里往往还没有任何内容。
    # 这里补一层从 pages.jsonl 读取当前 live alias 的快照，
    # 让 assign/remove 基于“页面现状”增删，而不是误把别名列表清成只剩人工刚操作的那一项。
    pages_path = target / "state" / "pages.jsonl"
    if not pages_path.exists():
        return {}

    aliases_by_page_id: dict[str, list[str]] = {}
    for record in load_jsonl(pages_path):
        record = ensure_page_lifecycle_defaults(record)
        if not is_live_page_record(record):
            continue
        aliases_by_page_id[record["page_id"]] = sorted(set(record.get("aliases", [])))
    return aliases_by_page_id


def remove_alias_from_overrides(
    target: Path,
    page_ids: list[str],
    alias_value: str,
) -> dict:
    # 从指定页面的人工 alias 覆盖层里移除某个 alias。
    overrides = load_page_alias_overrides(target)
    page_aliases = overrides.setdefault("page_aliases", {})
    live_aliases_by_page_id = load_live_page_aliases_by_id(target)
    normalized_alias = normalize_alias_value(alias_value)

    for page_id in page_ids:
        page_override = page_aliases.setdefault(page_id, {})
        aliases = sorted(set(page_override.get("aliases", live_aliases_by_page_id.get(page_id, []))))
        aliases = [alias for alias in aliases if normalize_alias_value(alias) != normalized_alias]
        page_override["aliases"] = aliases

    write_page_alias_overrides(target, overrides)
    return overrides


def apply_alias_override_action(
    overrides: dict,
    live_aliases_by_page_id: dict[str, list[str]],
    candidate_page_ids: list[str],
    primary_page_id: str,
    alias_value: str,
    action: str,
) -> dict:
    updated_overrides = copy.deepcopy(overrides)
    page_aliases = updated_overrides.setdefault("page_aliases", {})
    normalized_alias = normalize_alias_value(alias_value)

    for page_id in candidate_page_ids:
        page_override = page_aliases.setdefault(page_id, {})
        aliases = sorted(set(page_override.get("aliases", live_aliases_by_page_id.get(page_id, []))))
        aliases = [alias for alias in aliases if normalize_alias_value(alias) != normalized_alias]
        if action == "assign_alias" and page_id == primary_page_id and alias_value not in aliases:
            aliases.append(alias_value)
        page_override["aliases"] = sorted(set(aliases))
    return updated_overrides


def accepted_alias_conflict_signature(alias_value: str, canonical_ids: list[str]) -> str:
    normalized_alias = normalize_alias_value(alias_value)
    canonical_part = "|".join(sorted(str(item).strip() for item in canonical_ids if str(item).strip()))
    return f"{normalized_alias}::{canonical_part}"


def build_accepted_alias_conflict_signatures(overrides: dict) -> set[str]:
    accepted = overrides.get("accepted_conflicts", [])
    signatures: set[str] = set()
    for item in accepted:
        if isinstance(item, str) and item.strip():
            signatures.add(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        alias_value = str(item.get("alias", "")).strip()
        canonical_ids = [str(value).strip() for value in item.get("canonical_ids", []) if str(value).strip()]
        if not alias_value or not canonical_ids:
            continue
        signatures.add(accepted_alias_conflict_signature(alias_value, canonical_ids))
    return signatures


def persist_accepted_alias_conflict(
    overrides: dict,
    alias_value: str,
    canonical_ids: list[str],
) -> dict:
    updated_overrides = copy.deepcopy(overrides)
    accepted = [
        item for item in updated_overrides.get("accepted_conflicts", [])
        if isinstance(item, dict) or (isinstance(item, str) and item.strip())
    ]
    normalized_canonical_ids = sorted({
        str(item).strip()
        for item in canonical_ids
        if str(item).strip()
    })
    signature = accepted_alias_conflict_signature(alias_value, normalized_canonical_ids)

    filtered_accepted: list[dict | str] = []
    for item in accepted:
        if isinstance(item, str):
            if item.strip() != signature:
                filtered_accepted.append(item)
            continue
        existing_signature = accepted_alias_conflict_signature(
            str(item.get("alias", "")).strip(),
            [str(value).strip() for value in item.get("canonical_ids", []) if str(value).strip()],
        )
        if existing_signature != signature:
            filtered_accepted.append(item)

    filtered_accepted.append({
        "alias": alias_value,
        "canonical_ids": normalized_canonical_ids,
        "accepted_at": utc_now_iso(),
    })
    updated_overrides["accepted_conflicts"] = filtered_accepted
    return updated_overrides


def clear_accepted_alias_conflict(
    overrides: dict,
    alias_value: str,
    canonical_ids: list[str],
) -> dict:
    updated_overrides = copy.deepcopy(overrides)
    signature = accepted_alias_conflict_signature(alias_value, canonical_ids)
    filtered_accepted: list[dict | str] = []
    for item in updated_overrides.get("accepted_conflicts", []):
        if isinstance(item, str):
            if item.strip() != signature:
                filtered_accepted.append(item)
            continue
        existing_signature = accepted_alias_conflict_signature(
            str(item.get("alias", "")).strip(),
            [str(value).strip() for value in item.get("canonical_ids", []) if str(value).strip()],
        )
        if existing_signature != signature:
            filtered_accepted.append(item)
    updated_overrides["accepted_conflicts"] = filtered_accepted
    return updated_overrides


def unresolved_alias_conflicts(alias_index: dict) -> list[dict]:
    return [
        conflict
        for conflict in alias_index.get("conflicts", [])
        if not conflict.get("accepted")
    ]


def update_page_alias_overrides_with_lock(
    target: Path,
    updater,
) -> dict:
    lock_handle = acquire_file_lock(page_alias_overrides_lock_path(target))
    try:
        overrides = load_page_alias_overrides(target)
        updated_overrides = updater(overrides)
        write_page_alias_overrides(target, updated_overrides)
        return updated_overrides
    finally:
        release_file_lock(lock_handle)


def build_alias_index(page_records: list[dict], accepted_conflict_signatures: set[str] | None = None) -> dict:
    # alias registry 统一记录 canonical_id、title、aliases 的双向映射关系。
    # query、lint、Agent 约定都依赖它，避免各自维护一份别名世界观。
    canonical_map: dict[str, dict] = {}
    alias_map: dict[str, list[dict]] = {}
    accepted_conflict_signatures = accepted_conflict_signatures or set()
    live_page_records = filter_live_page_records(page_records)
    pages_by_canonical_id: dict[str, list[dict]] = {}
    title_owners_by_alias: dict[str, list[dict]] = {}
    noisy_title_alias_values = {
        normalize_alias_value("一句话总结"),
        normalize_alias_value("注意"),
    }

    def canonical_page_rank_key(page_record: dict) -> tuple:
        page_type = page_record.get("type", "")
        page_status = page_record.get("status", "")
        return (
            1 if page_type == "concept" else 0,
            1 if page_status == "stable" else 0,
            QUERY_PAGE_TYPE_WEIGHTS.get(page_type, QUERY_PAGE_TYPE_WEIGHTS["draft"]),
            QUERY_PAGE_STATUS_WEIGHTS.get(page_status, QUERY_PAGE_STATUS_WEIGHTS["draft"]),
            len(page_record.get("claim_ids", [])),
        )

    for page_record in live_page_records:
        canonical_id = page_record.get("canonical_id") or page_record.get("page_id")
        pages_by_canonical_id.setdefault(canonical_id, []).append(page_record)
        normalized_title = normalize_alias_value(page_record.get("title", ""))
        if normalized_title:
            title_owners_by_alias.setdefault(normalized_title, []).append(page_record)

    def should_register_title_alias(page_record: dict, normalized_title: str) -> bool:
        if normalized_title in noisy_title_alias_values:
            owners = title_owners_by_alias.get(normalized_title, [])
            return len({
                owner.get("canonical_id") or owner.get("page_id")
                for owner in owners
            }) <= 1
        # source-summary 的标题常常只是原文文件名或章节名，
        # 如果它与概念/综述页重名，再把它注册成 alias 只会制造噪声和伪冲突。
        # 这里保留 source-summary 的正文/标题检索能力，但在 alias registry 里更保守。
        if page_record.get("type") != "source-summary":
            return True
        owners = title_owners_by_alias.get(normalized_title, [])
        if len(owners) <= 1:
            return True
        return not any(
            owner.get("type") in {"concept", "overview", "duty"}
            and owner.get("canonical_id") != page_record.get("canonical_id")
            for owner in owners
        )

    for canonical_id, grouped_pages in pages_by_canonical_id.items():
        representative_page = max(grouped_pages, key=canonical_page_rank_key)
        combined_aliases = sorted({
            alias
            for page_record in grouped_pages
            for alias in page_record.get("aliases", [])
            if alias
        })
        canonical_map[canonical_id] = {
            "canonical_id": canonical_id,
            "page_id": representative_page.get("page_id"),
            "title": representative_page.get("title", ""),
            "page_path": representative_page.get("page_path", ""),
            "type": representative_page.get("type", ""),
            "status": representative_page.get("status", ""),
            "aliases": combined_aliases,
        }

    for page_record in live_page_records:
        page_id = page_record.get("page_id")
        canonical_id = page_record.get("canonical_id") or page_id
        title = page_record.get("title", "")
        page_path = page_record.get("page_path", "")
        page_type = page_record.get("type", "")
        page_status = page_record.get("status", "")
        normalized_title = normalize_alias_value(title)
        candidates = [canonical_id, *page_record.get("aliases", [])]
        if normalized_title and should_register_title_alias(page_record, normalized_title):
            candidates.insert(0, title)
        seen_keys: set[str] = set()
        for candidate in candidates:
            normalized_candidate = normalize_alias_value(candidate)
            if not normalized_candidate or normalized_candidate in seen_keys:
                continue
            seen_keys.add(normalized_candidate)
            alias_map.setdefault(normalized_candidate, []).append({
                "canonical_id": canonical_id,
                "page_id": page_id,
                "title": title,
                "page_path": page_path,
                "type": page_type,
                "status": page_status,
                "matched_from": candidate,
            })

    conflicts = []
    for alias_key, matches in sorted(alias_map.items()):
        canonical_ids = sorted({item["canonical_id"] for item in matches})
        if len(canonical_ids) <= 1:
            continue
        signature = accepted_alias_conflict_signature(alias_key, canonical_ids)
        conflicts.append({
            "alias": alias_key,
            "canonical_ids": canonical_ids,
            "page_ids": sorted({item["page_id"] for item in matches}),
            "accepted": signature in accepted_conflict_signatures,
        })

    return {
        "index_version": ALIAS_INDEX_VERSION,
        "updated_at": utc_now_iso(),
        "canonical_map": canonical_map,
        "alias_map": alias_map,
        "conflicts": conflicts,
    }


def write_alias_index(target: Path, page_records: list[dict]) -> dict:
    overrides = load_page_alias_overrides(target)
    alias_index = build_alias_index(
        page_records,
        accepted_conflict_signatures=build_accepted_alias_conflict_signatures(overrides),
    )
    write_json(alias_index_path(target), alias_index)
    return alias_index


def extract_page_markdown_links(page_text: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", page_text):
        target = match.group(1).strip()
        if not target:
            continue
        target = target.split()[0].strip()
        if target and target not in links:
            links.append(target)
    return links


def canonical_family_id(canonical_id: str | None) -> str | None:
    cleaned = str(canonical_id or "").strip()
    if not cleaned or ":" not in cleaned:
        return cleaned or None
    return cleaned.split(":", 1)[1] or None


def build_page_links_index(target: Path, page_records: list[dict]) -> dict:
    live_pages = filter_live_page_records(page_records)
    live_pages_by_id = {record.get("page_id"): record for record in live_pages if record.get("page_id")}
    path_to_page_id = {
        str(Path(record.get("page_path", ""))).strip(): record.get("page_id")
        for record in live_pages
        if record.get("page_id") and record.get("page_path")
    }
    canonical_family_to_page_ids: dict[str, list[str]] = {}
    page_entries: dict[str, dict] = {}

    for record in live_pages:
        canonical_family = canonical_family_id(record.get("canonical_id"))
        if canonical_family:
            canonical_family_to_page_ids.setdefault(canonical_family, []).append(record["page_id"])

    page_ids_by_source_id: dict[str, list[str]] = {}
    for record in live_pages:
        for source_ref in record.get("source_refs", []):
            source_id = source_ref.get("source_id")
            if not source_id:
                continue
            page_ids_by_source_id.setdefault(source_id, []).append(record["page_id"])

    for record in live_pages:
        page_id = record["page_id"]
        page_path = record.get("page_path", "")
        outgoing_page_ids: list[str] = []
        outgoing_links: list[dict] = []
        page_file = target / page_path
        if page_path and page_file.exists():
            page_text = page_file.read_text(encoding="utf-8")
            for link_target in extract_page_markdown_links(page_text):
                normalized_target = unquote(link_target).strip()
                if not normalized_target or normalized_target.startswith(("http://", "https://", "mailto:")):
                    continue
                target_path = (Path(page_path).parent / normalized_target).resolve()
                matched_page_id = None
                for candidate_path, candidate_page_id in path_to_page_id.items():
                    candidate_resolved = (target / candidate_path).resolve()
                    if candidate_resolved == target_path:
                        matched_page_id = candidate_page_id
                        break
                if not matched_page_id or matched_page_id == page_id:
                    continue
                if matched_page_id not in outgoing_page_ids:
                    outgoing_page_ids.append(matched_page_id)
                    outgoing_links.append({
                        "target_page_id": matched_page_id,
                        "target_page_path": live_pages_by_id[matched_page_id].get("page_path", ""),
                        "target_title": live_pages_by_id[matched_page_id].get("title", ""),
                        "reason": "markdown_link",
                    })
        page_entries[page_id] = {
            "page_id": page_id,
            "canonical_id": record.get("canonical_id"),
            "canonical_family_id": canonical_family_id(record.get("canonical_id")),
            "page_path": page_path,
            "title": record.get("title", ""),
            "type": record.get("type", ""),
            "status": record.get("status", ""),
            "outgoing_page_ids": outgoing_page_ids,
            "outgoing_links": outgoing_links,
            "incoming_page_ids": [],
            "incoming_links": [],
            "linked_canonical_ids": sorted({
                live_pages_by_id[target_page_id].get("canonical_id")
                for target_page_id in outgoing_page_ids
                if live_pages_by_id.get(target_page_id, {}).get("canonical_id")
            }),
            "related_page_ids": [],
        }

    for page_id, entry in page_entries.items():
        for outgoing_page_id in entry["outgoing_page_ids"]:
            incoming_entry = page_entries.get(outgoing_page_id)
            if incoming_entry is None:
                continue
            if page_id not in incoming_entry["incoming_page_ids"]:
                incoming_entry["incoming_page_ids"].append(page_id)
                incoming_entry["incoming_links"].append({
                    "source_page_id": page_id,
                    "source_page_path": entry.get("page_path", ""),
                    "source_title": entry.get("title", ""),
                    "reason": "markdown_link",
                })

    for page_id, entry in page_entries.items():
        related_page_ids: list[str] = []
        family_id = entry.get("canonical_family_id")
        if family_id:
            for candidate_page_id in canonical_family_to_page_ids.get(family_id, []):
                if candidate_page_id != page_id and candidate_page_id not in related_page_ids:
                    related_page_ids.append(candidate_page_id)
        source_overlap_ids: list[str] = []
        source_ids = [
            source_ref.get("source_id")
            for source_ref in live_pages_by_id.get(page_id, {}).get("source_refs", [])
            if source_ref.get("source_id")
        ]
        for source_id in source_ids:
            for candidate_page_id in page_ids_by_source_id.get(source_id, []):
                if candidate_page_id != page_id and candidate_page_id not in source_overlap_ids:
                    source_overlap_ids.append(candidate_page_id)
        for candidate_page_id in source_overlap_ids:
            if candidate_page_id not in related_page_ids:
                related_page_ids.append(candidate_page_id)
        for candidate_page_id in entry.get("outgoing_page_ids", []):
            if candidate_page_id not in related_page_ids:
                related_page_ids.append(candidate_page_id)
        for candidate_page_id in entry.get("incoming_page_ids", []):
            if candidate_page_id not in related_page_ids:
                related_page_ids.append(candidate_page_id)
        entry["incoming_page_ids"] = sorted(entry.get("incoming_page_ids", []))
        entry["outgoing_page_ids"] = sorted(entry.get("outgoing_page_ids", []))
        entry["related_page_ids"] = related_page_ids[:8]

    return {
        "index_version": PAGE_LINKS_INDEX_VERSION,
        "updated_at": utc_now_iso(),
        "page_count": len(page_entries),
        "pages": page_entries,
    }


def write_page_links_index(target: Path, page_records: list[dict]) -> dict:
    page_links_index = build_page_links_index(target, page_records)
    write_json(page_links_index_path(target), page_links_index)
    return page_links_index


def load_page_links_index(target: Path) -> dict:
    return repo_load_page_links_index(
        target,
        page_links_index_rel_path=PAGE_LINKS_INDEX_REL_PATH,
        load_json=load_json,
        default_index_version=PAGE_LINKS_INDEX_VERSION,
    )


def apply_page_alias_overrides(target: Path, page_record: dict) -> dict:
    # 自动页面重建前先叠加人工 alias 覆盖层。
    overrides = load_page_alias_overrides(target)
    return apply_page_alias_overrides_payload(page_record, overrides)


def apply_page_alias_overrides_to_records(target: Path, page_records: list[dict]) -> list[dict]:
    overrides = load_page_alias_overrides(target)
    return [apply_page_alias_overrides_payload(record, overrides) for record in page_records]


def build_alias_conflict_reviews(
    alias_index: dict,
    existing_reviews: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    # alias registry 里一旦出现“一词多义”的冲突，就应进入 review 队列而不是只留在 lint 里。
    created_reviews: list[dict] = []
    touched_review_ids: list[str] = []

    for conflict in alias_index.get("conflicts", []):
        if conflict.get("accepted"):
            continue
        canonical_ids = sorted(conflict.get("canonical_ids", []))
        page_ids = sorted(conflict.get("page_ids", []))
        review_record = build_review_record(
            kind="alias_conflict",
            candidate_claim_ids=[],
            reason="Detected alias key mapped to multiple canonical pages and requires manual disambiguation.",
            evidence=[{
                "alias": conflict.get("alias"),
                "canonical_ids": canonical_ids,
                "page_ids": page_ids,
            }],
            recommended_action="keep_both",
            signature_parts=[
                conflict.get("alias", ""),
                *canonical_ids,
            ],
        )
        review_record["candidate_page_ids"] = page_ids
        review_record["allowed_actions"] = ["keep_both", "edit_then_resume", "assign_alias", "remove_alias"]
        review_record["resume_from"] = "alias_registry"

        existing_review = existing_reviews.get(review_record["review_id"])
        if existing_review is not None:
            # 冲突仍然存在时，把 page_ids 刷新到最新集合即可。
            existing_review["candidate_page_ids"] = page_ids
            existing_review["evidence"] = review_record["evidence"]
            existing_review["reason"] = review_record["reason"]
            existing_review["recommended_action"] = review_record["recommended_action"]
            touched_review_ids.append(existing_review["review_id"])
            continue

        created_reviews.append(review_record)
        touched_review_ids.append(review_record["review_id"])

    return created_reviews, touched_review_ids


def archive_stale_alias_conflict_reviews(
    live_reviews_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
    active_alias_review_ids: set[str],
) -> set[str]:
    # alias 冲突一旦在当前 alias index 中消失，旧 review 就不该继续伪装成 active。
    # 这里把“仍为 alias_conflict、但已不在当前冲突集合里”的记录自动转入历史态。
    archived_review_ids: set[str] = set()
    for review_id, review_record in list(live_reviews_by_id.items()):
        if review_record.get("kind") != "alias_conflict":
            continue
        if review_id in active_alias_review_ids:
            continue
        archived_record = dict(review_record)
        archived_record["status"] = "resolved"
        archived_record["resolved_at"] = archived_record.get("resolved_at") or utc_now_iso()
        archived_record["lifecycle_status"] = "superseded"
        archived_record["archived_at"] = utc_now_iso()
        live_reviews_by_id.pop(review_id, None)
        historical_record = convert_review_record_to_historical(archived_record)
        historical_reviews_by_id[historical_record["review_id"]] = historical_record
        archived_review_ids.add(review_id)
    return archived_review_ids


def refresh_alias_conflict_reviews(
    target: Path,
    live_reviews_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
    page_records: list[dict] | None = None,
) -> tuple[dict, set[str], set[str]]:
    # 把 alias index 与 review 账本在一个入口里重新对齐：
    # 1. 基于当前 live pages 重建 alias index
    # 2. 刷新仍存在的 alias_conflict review
    # 3. 将已消失的 alias_conflict review 转成历史态
    if page_records is None:
        page_records = repo_load_page_state_records(
            target,
            load_jsonl=load_jsonl,
            ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
        )
    page_records = apply_page_alias_overrides_to_records(target, page_records)
    alias_index = write_alias_index(target, page_records)
    created_reviews, touched_review_ids = build_alias_conflict_reviews(alias_index, live_reviews_by_id)
    for review_record in created_reviews:
        live_reviews_by_id[review_record["review_id"]] = review_record
    archived_review_ids = archive_stale_alias_conflict_reviews(
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
        active_alias_review_ids=set(touched_review_ids),
    )
    return alias_index, set(touched_review_ids), archived_review_ids


def alias_index_matches_for_value(alias_index: dict, alias_value: str) -> list[dict]:
    normalized_alias = normalize_alias_value(alias_value)
    return list(alias_index.get("alias_map", {}).get(normalized_alias, []))


def replace_jsonl_record(path: Path, key_field: str, key_value: str, new_record: dict) -> None:
    # JSONL 天然适合追加，但“更新某条记录”就需要整文件重写一遍。
    # 这里先用最直白、最容易读懂的实现，后面数据量大了再考虑索引化。
    records = load_jsonl(path)
    replaced = False
    updated_records = []
    for record in records:
        if record.get(key_field) == key_value and not replaced:
            updated_records.append(new_record)
            replaced = True
        else:
            updated_records.append(record)
    if not replaced:
        updated_records.append(new_record)
    write_jsonl(path, updated_records)


def replace_jsonl_records_by_filter(path: Path, keep_predicate, replacement_records: list[dict]) -> None:
    # 有些 state 文件需要“替换同一来源的一组记录”，例如 chunks.jsonl。
    # 这里统一做成一个小工具，避免在主流程里反复手写整文件过滤逻辑。
    records = load_jsonl(path)
    kept_records = [record for record in records if keep_predicate(record)]
    write_jsonl(path, kept_records + replacement_records)


def replace_source_scoped_jsonl_records(path: Path, source_id: str, replacement_records: list[dict]) -> None:
    # V2 结构账本按 source_id 整体替换，保证重复 ingest 不会让结构记录膨胀。
    replace_jsonl_records_by_filter(
        path,
        keep_predicate=lambda record, source_id=source_id: record.get("source_id") != source_id,
        replacement_records=replacement_records,
    )




def estimate_token_count(text: str) -> int:
    # 这里先用一个很保守的近似估算：中文/英文混排时，按字符数粗估 token 数量。
    # 真实 tokenizer 以后可以替换这里，但 V1 先保证逻辑可跑、阈值可控。
    compact = text.strip()
    if not compact:
        return 0
    return max(1, len(compact) // 4)


def summarize_chunk_text(text: str, max_chars: int = 120) -> str:
    # 给 chunk 生成一个非常短的摘要，优先用于调试、人工检查和后续 review 界面。
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def sanitize_section_label(value: str) -> str:
    # section_path 需要既可读又稳定，这里做一层轻量清洗。
    compact = re.sub(r"\s+", " ", value.strip())
    return compact or "未命名章节"


def build_section_hierarchy(section_parts: list[str]) -> dict:
    cleaned_parts = [sanitize_section_label(part) for part in section_parts if sanitize_section_label(part)]
    current_label = cleaned_parts[-1] if cleaned_parts else "未命名章节"
    parent_parts = cleaned_parts[:-1]
    return {
        "section_path_parts": cleaned_parts,
        "section_title": current_label,
        "parent_section_path": " > ".join(parent_parts),
        "heading_level": len(cleaned_parts),
    }


def parse_section_path(section_path: str) -> dict:
    return build_section_hierarchy([part.strip() for part in section_path.split(">") if part.strip()])


def markdown_heading_match(line: str):
    return re.match(r"^(#{1,6})\s+(.+?)\s*$", line)


def strip_markdown_inline_formatting(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("~~", "")
    cleaned = cleaned.strip("`*_ ")
    return cleaned.strip()


def detect_structure_block_type(text: str) -> tuple[str, dict]:
    stripped = text.strip()
    if not stripped:
        return "blank", {}
    heading = markdown_heading_match(stripped)
    if heading:
        return "heading", {
            "heading_level": len(heading.group(1)),
            "heading_text": strip_markdown_inline_formatting(heading.group(2)),
        }
    if stripped.startswith("```"):
        return "code_block", {"fence": "```"}
    if re.match(r"^\s{0,3}>\s+", stripped):
        return "blockquote", {}
    if re.match(r"^\s*([-*+])\s+", stripped):
        marker = re.match(r"^\s*([-*+])\s+", stripped).group(1)
        indent = len(text) - len(text.lstrip(" "))
        return "list_item", {"list_marker": marker, "list_indent": indent}
    if re.match(r"^\s*\d+[.)]\s+", stripped):
        indent = len(text) - len(text.lstrip(" "))
        return "list_item", {"list_marker": "ordered", "list_indent": indent}
    if "|" in stripped and re.match(r"^\s*\|?.+\|.+\|?\s*$", stripped):
        if re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", stripped):
            return "table_separator", {}
        return "table_row", {}
    return "paragraph", {}


def build_structure_block_id(source_id: str, start_line: int, end_line: int, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return f"sb_{source_id}_{start_line}_{end_line}_{digest}"


def build_markdown_structure_blocks(normalized_record: dict, normalized_text: str) -> list[dict]:
    source_id = normalized_record["source_id"]
    normalized_path = normalized_record["normalized_path"]
    source_path = normalized_record["source_path"]
    lines = normalized_text.splitlines()
    blocks: list[dict] = []
    heading_stack: list[tuple[int, str, str]] = []
    in_code_fence = False
    current_paragraph: list[tuple[int, str]] = []
    previous_block_id: str | None = None

    def current_heading_parts() -> list[str]:
        return [item[1] for item in heading_stack]

    def append_block(
        block_type: str,
        block_lines: list[tuple[int, str]],
        attributes: dict | None = None,
        *,
        heading_parts: list[str] | None = None,
        parent_block_id: str | None = None,
    ) -> dict | None:
        nonlocal previous_block_id
        if not block_lines:
            return None
        raw_markdown = "\n".join(line for _, line in block_lines).rstrip()
        text = raw_markdown.strip()
        if not text:
            return None
        start_line = block_lines[0][0]
        end_line = block_lines[-1][0]
        block_id = build_structure_block_id(source_id, start_line, end_line, raw_markdown)
        resolved_parent_block_id = parent_block_id
        if resolved_parent_block_id is None and block_type != "heading" and heading_stack:
            resolved_parent_block_id = heading_stack[-1][2] or None
        block = {
            "structure_block_id": block_id,
            "source_id": source_id,
            "source_path": source_path,
            "normalized_path": normalized_path,
            "block_type": block_type,
            "text": text,
            "raw_markdown": raw_markdown,
            "heading_path_parts": list(heading_parts if heading_parts is not None else current_heading_parts()),
            "parent_block_id": resolved_parent_block_id,
            "previous_block_id": previous_block_id,
            "next_block_id": None,
            "children_block_ids": [],
            "start_line": start_line,
            "end_line": end_line,
            "attributes": attributes or {},
            "hash": hashlib.sha256(raw_markdown.encode("utf-8")).hexdigest(),
            "created_at": utc_now_iso(),
        }
        if previous_block_id and blocks:
            blocks[-1]["next_block_id"] = block_id
        blocks.append(block)
        previous_block_id = block_id
        return block

    def flush_paragraph() -> None:
        nonlocal current_paragraph
        if current_paragraph:
            append_block("paragraph", current_paragraph)
            current_paragraph = []

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()

        if in_code_fence:
            current_paragraph.append((line_no, line))
            if stripped.startswith("```"):
                append_block("code_block", current_paragraph, {"fence": "```"})
                current_paragraph = []
                in_code_fence = False
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            current_paragraph = [(line_no, line)]
            in_code_fence = True
            continue

        if not stripped:
            flush_paragraph()
            continue

        block_type, attributes = detect_structure_block_type(line)
        if block_type == "heading":
            flush_paragraph()
            level = attributes["heading_level"]
            title = sanitize_section_label(attributes["heading_text"])
            heading_stack = [item for item in heading_stack if item[0] < level]
            heading_stack.append((level, title, ""))
            heading_parts = [item[1] for item in heading_stack]
            parent_heading_id = next((item[2] for item in reversed(heading_stack[:-1]) if item[2]), None)
            block = append_block(
                "heading",
                [(line_no, line)],
                attributes,
                heading_parts=heading_parts,
                parent_block_id=parent_heading_id,
            )
            if block is not None:
                heading_stack[-1] = (level, title, block["structure_block_id"])
                if parent_heading_id:
                    for existing in blocks:
                        if existing["structure_block_id"] == parent_heading_id:
                            existing["children_block_ids"].append(block["structure_block_id"])
                            break
            continue

        if block_type in {"list_item", "blockquote", "table_row", "table_separator"}:
            flush_paragraph()
            append_block(block_type, [(line_no, line)], attributes)
            continue

        current_paragraph.append((line_no, line))

    flush_paragraph()
    return blocks


def parse_markdown_table_cells(raw_markdown: str) -> list[str]:
    stripped = raw_markdown.strip().strip("|")
    return [strip_markdown_inline_formatting(cell) for cell in stripped.split("|")]


def extract_metadata_from_text(text: str) -> dict:
    cleaned = strip_markdown_inline_formatting(clean_claim_candidate_text(text))
    match = re.match(r"^([^：:]{1,24})[：:]\s*(.+)$", cleaned)
    if not match:
        return {}
    key = match.group(1).strip()
    value = match.group(2).strip()
    if not key or not value:
        return {}
    if key in {"案例", "示例", "例子", "提示", "注意", "说明"}:
        return {}
    if any(token in key.lower() for token in ("http", "https", "file")):
        return {}
    return {key: value}


def build_evidence_block_id(source_id: str, structure_block_ids: list[str], start_line: int, text: str) -> str:
    raw = "|".join([source_id, *structure_block_ids, str(start_line), text])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"ev_{source_id}_{start_line}_{digest}"


def normalize_list_item_text(text: str) -> str:
    cleaned = re.sub(r"^\s*[-*+]\s+", "", text.strip())
    cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned)
    return strip_markdown_inline_formatting(cleaned)


def append_semantic_feature(
    features: list[dict],
    tag: str,
    category: str,
    strength: str,
    evidence: str,
) -> None:
    feature = {
        "tag": tag,
        "category": category,
        "strength": strength,
        "evidence": evidence,
    }
    if feature not in features:
        features.append(feature)


def semantic_features_for_evidence(
    text: str,
    block_kind: str,
    metadata: dict,
    section_path_parts: list[str],
    local_heading: str | None,
) -> list[dict]:
    features: list[dict] = []
    if block_kind in {"table_row", "metadata_line"}:
        append_semantic_feature(features, "rules", "structure", "strong", block_kind)
        append_semantic_feature(features, "reference_structure", "structure", "strong", block_kind)
    if block_kind == "code_example":
        append_semantic_feature(features, "cases", "structure", "strong", block_kind)
        append_semantic_feature(features, "example_structure", "structure", "strong", block_kind)
    if block_kind == "list_item_with_body":
        append_semantic_feature(features, "local_heading_body", "structure", "medium", block_kind)

    cells = metadata.get("cells") if isinstance(metadata, dict) else None
    if isinstance(cells, list) and len([cell for cell in cells if str(cell).strip()]) >= 2:
        append_semantic_feature(features, "reference_structure", "structure", "strong", "table_cells")

    if isinstance(metadata, dict):
        metadata_keys = [str(key).strip() for key in metadata if str(key).strip() and key != "cells"]
        if metadata_keys:
            append_semantic_feature(features, "metadata_fact", "structure", "strong", "metadata_keys")

    return features


def content_tags_from_semantic_features(features: list[dict]) -> list[str]:
    structure_only_tags = {"local_heading_body", "metadata_fact", "reference_structure", "example_structure"}
    tags: list[str] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        tag = str(feature.get("tag", "")).strip()
        category = str(feature.get("category", "")).strip()
        if category == "structure" or tag in structure_only_tags:
            continue
        if tag and tag not in tags:
            tags.append(tag)
    return sorted(tags)


def build_evidence_blocks_from_structure(structure_blocks: list[dict]) -> list[dict]:
    evidence_blocks: list[dict] = []

    index = 0
    while index < len(structure_blocks):
        block = structure_blocks[index]
        block_type = block.get("block_type")
        if block_type in {"table_separator"}:
            index += 1
            continue

        structure_group = [block]
        block_kind = block_type
        text = str(block.get("text", "")).strip()
        local_heading = None
        metadata = dict(block.get("attributes", {}))
        extraction_hint = "single_structure_block"

        if block_type == "heading":
            block_kind = "section_heading"
            local_heading = strip_markdown_inline_formatting(text.lstrip("#").strip())
            metadata["heading_path_parts"] = block.get("heading_path_parts", [])
            extraction_hint = "heading_as_structure_context"

        elif block_type == "list_item":
            local_heading = normalize_list_item_text(text)
            next_block = structure_blocks[index + 1] if index + 1 < len(structure_blocks) else None
            if (
                next_block is not None
                and next_block.get("block_type") == "paragraph"
                and next_block.get("heading_path_parts") == block.get("heading_path_parts")
            ):
                structure_group.append(next_block)
                block_kind = "list_item_with_body"
                text = f"{local_heading}\n{next_block.get('text', '').strip()}"
                extraction_hint = "local_heading_attached_to_body"
                index += 1
            else:
                block_kind = "list_item"
                text = local_heading
                extraction_hint = "list_item_as_evidence"

        elif block_type == "table_row":
            block_kind = "table_row"
            metadata["cells"] = parse_markdown_table_cells(block.get("raw_markdown", text))
            extraction_hint = "table_row_as_evidence"

        elif block_type == "code_block":
            block_kind = "code_example"
            extraction_hint = "code_block_preserved_as_evidence"

        elif block_type == "paragraph":
            metadata.update(extract_metadata_from_text(text))
            block_kind = "metadata_line" if metadata and len(metadata) == 1 else "paragraph"
            extraction_hint = "metadata_extracted_from_paragraph" if block_kind == "metadata_line" else "paragraph_as_evidence"

        start_line = min(item["start_line"] for item in structure_group)
        end_line = max(item["end_line"] for item in structure_group)
        structure_block_ids = [item["structure_block_id"] for item in structure_group]
        evidence_id = build_evidence_block_id(block["source_id"], structure_block_ids, start_line, text)
        heading_path_parts = block.get("heading_path_parts", [])
        semantic_features = semantic_features_for_evidence(
            text=text,
            block_kind=block_kind,
            metadata=metadata,
            section_path_parts=heading_path_parts,
            local_heading=local_heading,
        )
        evidence_blocks.append({
            "evidence_block_id": evidence_id,
            "source_id": block["source_id"],
            "source_path": block["source_path"],
            "normalized_path": block["normalized_path"],
            "structure_block_ids": structure_block_ids,
            "block_kind": block_kind,
            "text": text,
            "local_heading": local_heading,
            "context_before": None,
            "context_after": None,
            "section_path_parts": heading_path_parts,
            "start_line": start_line,
            "end_line": end_line,
            "metadata": metadata,
            "semantic_features": semantic_features,
            "content_tags": content_tags_from_semantic_features(semantic_features),
            "extraction_hint": extraction_hint,
            "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "created_at": utc_now_iso(),
        })
        index += 1

    return evidence_blocks


def build_knowledge_unit_id(source_id: str, evidence_block_ids: list[str], text: str) -> str:
    raw = "|".join([source_id, *evidence_block_ids, normalize_claim_text(text)])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"ku_{source_id}_{digest}"


def knowledge_unit_kind_for_evidence(evidence_block: dict) -> str:
    block_kind = evidence_block.get("block_kind")
    if block_kind == "metadata_line":
        return "metadata_fact"
    if block_kind == "table_row":
        return "table_fact"
    if block_kind in {"section_heading"}:
        return "structural_shell"
    if block_kind == "code_example":
        return "code_example"
    return "statement"


def build_knowledge_units_from_evidence(evidence_blocks: list[dict]) -> list[dict]:
    knowledge_units: list[dict] = []
    for evidence_block in evidence_blocks:
        text = str(evidence_block.get("text", "")).strip()
        if not text:
            continue
        unit_kind = knowledge_unit_kind_for_evidence(evidence_block)
        evidence_block_ids = [evidence_block["evidence_block_id"]]
        knowledge_units.append({
            "knowledge_unit_id": build_knowledge_unit_id(evidence_block["source_id"], evidence_block_ids, text),
            "source_id": evidence_block["source_id"],
            "source_path": evidence_block["source_path"],
            "normalized_path": evidence_block["normalized_path"],
            "text": text,
            "normalized_text": normalize_claim_text(text),
            "unit_kind": unit_kind,
            "local_heading": evidence_block.get("local_heading"),
            "metadata": {
                **evidence_block.get("metadata", {}),
                "section_path_parts": evidence_block.get("section_path_parts", []),
            },
            "evidence_block_ids": evidence_block_ids,
            "source_refs": [
                {
                    "source_id": evidence_block["source_id"],
                    "normalized_path": evidence_block["normalized_path"],
                    "start_line": evidence_block.get("start_line"),
                    "end_line": evidence_block.get("end_line"),
                }
            ],
            "extraction_reason": evidence_block.get("extraction_hint", "evidence_block_compiled"),
            "quality_label": "structural_shell" if unit_kind == "structural_shell" else "standalone",
            "status": "draft",
            "lifecycle_status": "active",
            "semantic_decision_ids": [],
            "semantic_projection": {
                "content_tags": evidence_block.get("content_tags", []),
                "semantic_features": evidence_block.get("semantic_features", []),
            },
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        })
    return knowledge_units


def compile_structure_knowledge_records(normalized_record: dict, normalized_text: str) -> dict:
    structure_blocks = build_markdown_structure_blocks(normalized_record, normalized_text)
    evidence_blocks = build_evidence_blocks_from_structure(structure_blocks)
    knowledge_units = build_knowledge_units_from_evidence(evidence_blocks)
    return {
        "source_id": normalized_record["source_id"],
        "structure_blocks": structure_blocks,
        "evidence_blocks": evidence_blocks,
        "knowledge_units": knowledge_units,
        "updated_at": utc_now_iso(),
    }


def split_markdown_blocks(section_lines: list[tuple[int, str]]) -> list[dict]:
    # 这里把章节文本拆成“块”，优先按空行断开，但尽量不切开 fenced code block。
    blocks: list[dict] = []
    current_lines: list[tuple[int, str]] = []
    in_code_fence = False

    for line_no, line in section_lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence

        if not in_code_fence and stripped == "":
            if current_lines:
                block_text = "\n".join(item[1] for item in current_lines).strip("\n")
                blocks.append({
                    "text": block_text,
                    "start_line": current_lines[0][0],
                    "end_line": current_lines[-1][0],
                })
                current_lines = []
            continue

        current_lines.append((line_no, line))

    if current_lines:
        block_text = "\n".join(item[1] for item in current_lines).strip("\n")
        blocks.append({
            "text": block_text,
            "start_line": current_lines[0][0],
            "end_line": current_lines[-1][0],
        })

    return [block for block in blocks if block["text"].strip()]


def split_normalized_into_sections(normalized_text: str) -> list[dict]:
    # 第一版章节切分只识别 Markdown 标题。
    # 没有标题的文档会落到一个默认章节里，保证任何文本都能继续往下游走。
    sections: list[dict] = []
    lines = normalized_text.splitlines()
    heading_stack: list[str] = []
    current_section = {
        "section_path": ["文档开始"],
        "lines": [],
    }

    for line_no, line in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            if current_section["lines"]:
                sections.append(current_section)

            level = len(match.group(1))
            title = sanitize_section_label(match.group(2))
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            current_section = {
                "section_path": heading_stack.copy(),
                "lines": [(line_no, line)],
            }
            continue

        current_section["lines"].append((line_no, line))

    if current_section["lines"]:
        sections.append(current_section)

    return sections


def split_normalized_into_paragraph_sections(normalized_text: str) -> list[dict]:
    # paragraph_first 用于结构较弱或纯文本型文档：
    # 不依赖标题层级，而是把连续段落作为 section 候选。
    sections: list[dict] = []
    lines = normalized_text.splitlines()
    current_lines: list[tuple[int, str]] = []

    def flush_section() -> None:
        nonlocal current_lines
        if not current_lines:
            return
        preview = next((line.strip() for _, line in current_lines if line.strip()), "文档段落")
        sections.append({
            "section_path": [sanitize_section_label(preview[:24]) or "文档段落"],
            "lines": current_lines,
        })
        current_lines = []

    for line_no, line in enumerate(lines, start=1):
        if re.match(r"^(#{1,6})\s+(.+?)\s*$", line):
            flush_section()
            sections.append({
                "section_path": [sanitize_section_label(re.sub(r"^(#{1,6})\s+", "", line).strip())],
                "lines": [(line_no, line)],
            })
            continue
        if not line.strip():
            flush_section()
            continue
        current_lines.append((line_no, line))

    flush_section()
    return sections


def choose_sections_for_chunking(normalized_record: dict, normalized_text: str) -> list[dict]:
    chunk_strategy_hint = str(normalized_record.get("chunk_strategy_hint", "heading_first")).strip() or "heading_first"
    if chunk_strategy_hint in {"paragraph_first", "chat_turn"}:
        sections = split_normalized_into_paragraph_sections(normalized_text)
        if sections:
            return sections
    return split_normalized_into_sections(normalized_text)


def build_chunk_records_for_section(
    source_id: str,
    source_path: str,
    normalized_rel_path: str,
    section: dict,
    chunk_offset: int,
) -> list[dict]:
    # 这一层把单个 section 继续切成 chunk。
    # 策略先求稳定和可解释：优先按块累积，超过上限就落一个 chunk。
    blocks = split_markdown_blocks(section["lines"])
    if not blocks:
        return []

    max_chars = DEFAULT_CHUNK_MAX_TOKENS * 4
    min_chars = DEFAULT_CHUNK_MIN_TOKENS * 4
    target_chars = DEFAULT_CHUNK_TARGET_TOKENS * 4
    section_path = " > ".join(section["section_path"])

    grouped_blocks: list[list[dict]] = []
    current_group: list[dict] = []
    current_chars = 0

    for block in blocks:
        block_chars = len(block["text"])
        # 如果单块本身就很长，允许它独立成块，避免为了凑阈值把结构切得更碎。
        if current_group and current_chars + block_chars > max_chars:
            grouped_blocks.append(current_group)
            current_group = [block]
            current_chars = block_chars
            continue

        current_group.append(block)
        current_chars += block_chars

        if current_chars >= target_chars:
            grouped_blocks.append(current_group)
            current_group = []
            current_chars = 0

    if current_group:
        if grouped_blocks:
            current_text = "\n\n".join(item["text"] for item in current_group)
            if len(current_text) < min_chars:
                grouped_blocks[-1].extend(current_group)
            else:
                grouped_blocks.append(current_group)
        else:
            grouped_blocks.append(current_group)

    chunk_records: list[dict] = []
    for index, block_group in enumerate(grouped_blocks, start=chunk_offset):
        chunk_text = "\n\n".join(block["text"] for block in block_group).strip() + "\n"
        start_line = block_group[0]["start_line"]
        end_line = block_group[-1]["end_line"]
        chunk_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        section_key = sanitize_source_key(section_path)
        chunk_id = f"chk_{source_id}_{section_key}_{start_line}_{chunk_hash[:10]}"
        section_hierarchy = build_section_hierarchy(section["section_path"])

        chunk_records.append({
            "chunk_id": chunk_id,
            "source_id": source_id,
            "source_path": source_path,
            "normalized_path": normalized_rel_path,
            "section_path": section_path,
            "section_path_parts": section_hierarchy["section_path_parts"],
            "section_title": section_hierarchy["section_title"],
            "parent_section_path": section_hierarchy["parent_section_path"],
            "heading_level": section_hierarchy["heading_level"],
            "chunk_index": index,
            "start_line": start_line,
            "end_line": end_line,
            "page_range": None,
            "char_count": len(chunk_text),
            "token_estimate": estimate_token_count(chunk_text),
            "summary": summarize_chunk_text(chunk_text),
            "text": chunk_text,
            "previous_chunk": None,
            "next_chunk": None,
            "overlap_from_previous": 0,
            "hash": chunk_hash,
            "chunker_version": "chunk_v2",
            "updated_at": utc_now_iso(),
        })

    return chunk_records


def build_chunk_records(normalized_record: dict, normalized_text: str) -> list[dict]:
    # 这里负责文档级切块：先按 section 拆，再给每段 section 分配 chunk 序号。
    sections = choose_sections_for_chunking(normalized_record, normalized_text)
    chunk_records: list[dict] = []
    chunk_index = 0

    for section in sections:
        section_chunks = build_chunk_records_for_section(
            source_id=normalized_record["source_id"],
            source_path=normalized_record["source_path"],
            normalized_rel_path=normalized_record["normalized_path"],
            section=section,
            chunk_offset=chunk_index,
        )
        chunk_records.extend(section_chunks)
        chunk_index += len(section_chunks)

    # previous / next 引用最后再统一回填，避免在切块阶段一边生成一边回看。
        for index, record in enumerate(chunk_records):
            previous_chunk = chunk_records[index - 1]["chunk_id"] if index > 0 else None
            next_chunk = chunk_records[index + 1]["chunk_id"] if index + 1 < len(chunk_records) else None
            record["previous_chunk"] = previous_chunk
            record["next_chunk"] = next_chunk
            record["chunk_kind"] = normalized_record.get("chunk_strategy_hint", "heading_first")
            record["topicworthiness_hint"] = normalized_record.get("document_kind", "note")

    return chunk_records


def write_source_chunks(target: Path, source_id: str, chunk_records: list[dict]) -> str:
    # chunks/ 目录里按 source_id 保存一份局部 JSONL，方便人工单独查看某个来源的切块结果。
    chunk_rel_path = Path("chunks") / f"{source_id}.jsonl"
    chunk_abs_path = target / chunk_rel_path
    write_jsonl(chunk_abs_path, chunk_records)
    return str(chunk_rel_path)


def format_chunk_reference(from_page: Path, source_id: str, chunk_ref: dict) -> str:
    # chunk 目前按 source_id 聚合存成 JSONL，这里把 chunk_id 链到对应文件，并附上段落定位信息。
    chunk_file_link = markdown_link_between_pages(from_page, Path("chunks") / f"{source_id}.jsonl")
    section_path = chunk_ref.get("section_path") or "unknown section"
    start_line = chunk_ref.get("start_line")
    end_line = chunk_ref.get("end_line")
    location = (
        f"{section_path} (lines {start_line}-{end_line})"
        if start_line is not None and end_line is not None
        else section_path
    )
    return f"[`{chunk_ref['chunk_id']}`]({chunk_file_link}) {location}"


def chunk_normalized_record(target: Path, normalized_record: dict) -> dict | None:
    # poor / failed 的文档暂时不进入稳定 chunk 流程，避免把低质量文本继续放大。
    if normalized_record["extraction_quality"] not in {"good", "partial"}:
        return None

    normalized_path = target / normalized_record["normalized_path"]
    normalized_text = normalized_path.read_text(encoding="utf-8")
    chunk_records = build_chunk_records(normalized_record, normalized_text)
    if not chunk_records:
        return None

    chunk_file_path = write_source_chunks(target, normalized_record["source_id"], chunk_records)
    for record in chunk_records:
        record["chunk_file_path"] = chunk_file_path

    return {
        "source_id": normalized_record["source_id"],
        "chunk_file_path": chunk_file_path,
        "chunk_count": len(chunk_records),
        "chunks": chunk_records,
        "updated_at": utc_now_iso(),
    }


def write_json(path: Path, payload: dict) -> None:
    # 单个 claim / review 文件用普通 JSON 保存，人工查看会比 JSONL 更舒服。
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown_to_plain_text(text: str) -> str:
    # Claim 草稿抽取先基于“较干净的正文文本”进行。
    # 这里只做保守清理，不追求完美去 markdown。
    cleaned = text
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"`{1,3}", "", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("*", "").replace("~~", "")
    normalized_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    cleaned = "\n".join(normalized_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def strip_fenced_code_blocks(text: str) -> str:
    # 示例代码块里的 YAML/JSON/命令通常不是正文知识陈述，不应直接进入 claim 抽取。
    lines: list[str] = []
    in_code_fence = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        lines.append(line)

    return "\n".join(lines)


def normalize_heading_plus_body_claim_candidate(text: str) -> str:
    # Markdown 标题和正文在压平成单行后，常变成“Claim 是什么 Claim 是...”这种重复前缀。
    cleaned = clean_concept_title_text(text)
    if not cleaned:
        return ""

    suffix_match = re.match(r"^(.{1,32}?)\s*(?:是|指)?什么\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if suffix_match:
        label = clean_concept_title_text(suffix_match.group(1))
        remainder = clean_concept_title_text(suffix_match.group(2))
        if label and remainder.startswith(label):
            return remainder

    prefix_match = re.match(r"^什么是\s+(.{1,32}?)\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if prefix_match:
        label = clean_concept_title_text(prefix_match.group(1))
        remainder = clean_concept_title_text(prefix_match.group(2))
        if label and remainder.startswith(label):
            return remainder

    return text


def normalize_claim_text(text: str) -> str:
    # Claim 的规范文本用于去重、冲突判断和稳定生成 claim_id。
    cleaned = markdown_to_plain_text(text).lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -:;,.!?。！？；：()[]{}\"'")
    return cleaned


def clean_claim_candidate_text(text: str) -> str:
    # 候选 claim 在进入规则判断前先做一轮轻量清洗：
    # - 去掉 Markdown 标题/引用/列表符号
    # - 去掉常见编号前缀
    # - 压缩多余空白
    cleaned = text.strip()
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^\s*>\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[-*+]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*\d+[.)、:：]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[（(]?\d+[）)]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*(因此|所以|同时|此外|另外|不过|但是|而且|并且|而是)\s*", "", cleaned)
    cleaned = normalize_heading_plus_body_claim_candidate(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -:;,.!?。！？；：，、()[]{}\"'")


def claim_candidate_has_short_gray_zone(text: str) -> bool:
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return False
    natural_chars = [
        char for char in cleaned
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    ]
    if len(natural_chars) >= 10:
        return False
    if claim_candidate_is_noise(cleaned):
        return False
    return True


def text_is_iso_date_label(text: str) -> bool:
    cleaned = clean_claim_candidate_text(text)
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned))


def text_is_question_like(text: str) -> bool:
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return False
    return cleaned.endswith(("？", "?"))


def claim_starts_with_dependent_prefix(text: str) -> bool:
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return False
    return any(cleaned.startswith(prefix) for prefix in CLAIM_DEPENDENT_PREFIXES)


def claim_starts_with_meta_prefix(text: str) -> bool:
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return False
    return any(cleaned.startswith(prefix) for prefix in CLAIM_META_PREFIXES)


def claim_has_standalone_predicate(text: str) -> bool:
    return False


def claim_can_stand_alone(text: str) -> bool:
    cleaned = clean_claim_candidate_text(text)
    if claim_candidate_is_noise(cleaned):
        return False
    if claim_starts_with_dependent_prefix(cleaned):
        return False
    return bool(cleaned)


def claim_is_definition_like_phrase(text: str) -> bool:
    return False


def claim_candidate_is_noise(text: str) -> bool:
    # 这里过滤几类高噪声片段：
    # - 纯链接 / 文件路径味太重
    # - 表格分隔线
    # - 几乎没有自然语言内容的标题或目录碎片
    # 不再单纯因为“长度小于 12”就直接判噪声，避免误杀短而完整的中文陈述。
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return True
    if cleaned.startswith(("http://", "https://", "file://")):
        return True
    if any(marker in cleaned.lower() for marker in ("turn_id", "speaker:", "time:")):
        return True
    if re.match(r"^[A-Za-z][A-Za-z0-9_ -]{0,24}\s*:\s*", cleaned):
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return True
    if re.search(r"\b[A-Za-z][A-Za-z0-9_ -]{0,24}\s*:\s*", cleaned):
        return True
    if re.fullmatch(r"[-|: ]{3,}", cleaned):
        return True
    if cleaned.count("/") >= 3 and len(cleaned) < 48:
        return True
    if cleaned.lower().startswith(("raw/", "../raw/", "wiki/", "claims/", "chunks/", "normalized/")):
        return True

    natural_chars = [
        char for char in cleaned
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    ]
    if len(natural_chars) < 4:
        return True
    if len(natural_chars) < 4:
        return True
    return False


def split_long_claim_candidate(text: str, max_chars: int = 140) -> list[str]:
    # 很长的整段经常会把多个结论糊在一起。
    # 这里优先按中文逗号、顿号、分句连接词再切一次，但只取足够像独立陈述的片段。
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return []

    if len(cleaned) <= max_chars:
        return [cleaned]

    secondary_parts = re.split(r"(?<=[,;。！？!?；])\s*", cleaned)
    refined_parts: list[str] = []
    for raw_part in secondary_parts:
        part = clean_claim_candidate_text(raw_part)
        if claim_candidate_is_noise(part):
            continue
        refined_parts.append(part)

    if len(refined_parts) >= 2:
        return refined_parts
    return [cleaned]


def split_claim_candidates_from_text(text: str) -> list[str]:
    # 这里优先抽取“像一句完整陈述”的片段：
    # 先按句号/分号/换行切，再做一轮候选清洗、去噪和长句拆分。
    # 中文资料里常见“句号后不加空格”的连写，这里也要能正常断句。
    candidates: list[str] = []
    raw_pieces = re.split(r"(?<=[。！？!?；;])\s*|\n{1,}|(?<=\.)\s{2,}", text)

    for raw_piece in raw_pieces:
        if re.match(r"^\s*#{1,6}\s+\S+", raw_piece):
            continue
        piece = clean_claim_candidate_text(raw_piece)
        if claim_candidate_is_noise(piece):
            continue
        sentence_candidates = [piece]
        refined_parts = split_long_claim_candidate(piece)
        if len(refined_parts) >= 2:
            sentence_candidates.extend(
                refined_piece
                for refined_piece in refined_parts
                if refined_piece != piece and claim_can_stand_alone(refined_piece)
            )

        for candidate_text in sentence_candidates:
            normalized_piece = clean_claim_candidate_text(candidate_text)
            if claim_candidate_is_noise(normalized_piece):
                continue
            if normalized_piece in candidates:
                continue
            candidates.append(normalized_piece)

    # 如果按句切之后一个都没留下，至少保留整段，避免 chunk 完全失去 claim 草稿。
    if not candidates and text.strip():
        fallback_piece = clean_claim_candidate_text(text.strip())
        if not claim_candidate_is_noise(fallback_piece):
            return [fallback_piece]
        return []
    return candidates


def classify_claim_type(text: str) -> str:
    # Claim semantics are handled by the semantic passes; this field stays conservative.
    cleaned = clean_claim_candidate_text(text)
    lowered = cleaned.lower()
    if any(keyword in lowered for keyword in ("better", "worse", "useful", "important", "effective")):
        return "evaluation"
    return "fact"


def claim_type_for_knowledge_unit(knowledge_unit: dict, claim_text: str) -> str:
    unit_kind = str(knowledge_unit.get("unit_kind", "")).strip().lower()
    if unit_kind == "metadata_fact":
        return "metadata_fact"
    if unit_kind == "table_fact":
        return "table_fact"
    return classify_claim_type(claim_text)


def contextualize_structural_claim_text(knowledge_unit: dict, claim_text: str) -> str:
    unit_kind = str(knowledge_unit.get("unit_kind", "")).strip().lower()
    cleaned_text = clean_claim_candidate_text(claim_text)
    if unit_kind not in {"metadata_fact", "table_fact"}:
        return cleaned_text

    metadata = knowledge_unit.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    section_path_parts = normalize_string_list(metadata.get("section_path_parts"))
    subject = section_path_parts[-1] if section_path_parts else ""

    if unit_kind == "metadata_fact":
        metadata_items = [
            (str(key).strip(), str(value).strip())
            for key, value in metadata.items()
            if str(key).strip() and str(key).strip() not in {"section_path_parts", "heading_path_parts"} and str(value).strip()
        ]
        if subject and len(metadata_items) == 1:
            key, value = metadata_items[0]
            return f"{subject} {key} 是 {value}"
        return cleaned_text

    cells = metadata.get("cells")
    if subject and isinstance(cells, list) and len(cells) >= 2:
        header = str(cells[0]).strip()
        value = str(cells[1]).strip()
        if header and value and header not in {"字段", "field", "name"}:
            return f"{subject} {header} 是 {value}"
    return cleaned_text


def format_claim_type_label(claim_type: str | None) -> str:
    # 用代码样式展示 claim 类型，避免 Markdown 方括号在部分查看器里被误解成可点击引用。
    return f"`{claim_type or 'unknown'}`"


def format_claim_reference(from_page: Path, claim_record: dict) -> str:
    # 优先把 claim_id 渲染成可跳转到 claims/*.json 的相对链接，方便沿证据链继续下钻。
    claim_id = claim_record["claim_id"]
    claim_file = claim_record.get("claim_file_path")
    if not claim_file:
        return f"`{claim_id}`"
    link = markdown_link_between_pages(from_page, Path(claim_file))
    return f"[`{claim_id}`]({link})"


def format_workspace_file_reference(from_page: Path, path_str: str) -> str:
    # 原始来源、标准化文件、chunk 文件统一渲染成工作区内相对链接，便于直接点开查看。
    link = markdown_link_between_pages(from_page, Path(path_str))
    return f"[`{path_str}`]({link})"


def format_page_label(from_page: Path, page_record: dict) -> str:
    link = markdown_link_between_pages(from_page, Path(page_record["page_path"]))
    return f"[{page_record['title']}]({link})"


def format_source_page_label(from_page: Path, source_page: dict) -> str:
    return format_page_label(from_page, source_page)


def format_source_page_meta(source_page: dict | None, source_ref: dict) -> str:
    # 内部 ID 仍然保留，但放到次级信息里，避免压过真正对人有用的标题和来源路径。
    parts = []
    if source_page is not None:
        parts.append(f"page=`{source_page['page_id']}`")
    parts.append(f"source=`{source_ref['source_id']}`")
    return ", ".join(parts)


def claim_lifecycle_status_for_record(claim_record: dict) -> str:
    # lifecycle_status 负责表达“这条 claim 现在是否仍然活跃可用”，
    # 不与 query 里的 draft / needs_review 混在一起。
    if claim_record.get("lifecycle_status") == "superseded":
        return "superseded"
    if claim_record.get("archived_at"):
        return "archived"
    if not claim_record.get("source_ids") or not claim_record.get("source_refs"):
        return "superseded"
    return "active"


def review_lifecycle_status_for_record(review_record: dict) -> str:
    if review_record.get("lifecycle_status") == "superseded":
        return "superseded"
    if review_record.get("archived_at"):
        return "archived"
    if not review_record.get("candidate_claim_ids") and not review_record.get("candidate_page_ids"):
        return "superseded"
    return "active"


def page_lifecycle_status_for_record(page_record: dict) -> str:
    if page_record.get("removed"):
        return "removed"
    if page_record.get("archived_at"):
        return "archived"
    return "active"


def ensure_claim_lifecycle_defaults(claim_record: dict) -> dict:
    claim_record.setdefault("superseded_by", [])
    claim_record.setdefault("archived_at", None)
    claim_record.setdefault("quality_label", None)
    claim_record.setdefault("quality_reason", None)
    claim_record.setdefault("quality_confidence", None)
    claim_record.setdefault("quality_review_required", False)
    claim_record.setdefault("quality_safe_auto_ready", None)
    claim_record.setdefault("quality_decision_source", None)
    claim_record["lifecycle_status"] = claim_lifecycle_status_for_record(claim_record)
    return sync_claim_semantic_projection(claim_record)


def ensure_review_lifecycle_defaults(review_record: dict) -> dict:
    review_record.setdefault("archived_at", None)
    review_record["lifecycle_status"] = review_lifecycle_status_for_record(review_record)
    return review_record


def ensure_page_lifecycle_defaults(page_record: dict) -> dict:
    # page 这一层和 claim/review 不同：
    # 我们希望在 state/pages.jsonl 里保留“曾经存在过但后来被移除”的自动页面痕迹，
    # 这样后续做页面历史、反向追踪和人工恢复时有抓手。
    page_record.setdefault("removed", False)
    page_record.setdefault("archived_at", None)
    page_record.setdefault("semantic_decision_ids", [])
    page_record.setdefault("page_route", {})
    page_record.setdefault("outgoing_page_ids", [])
    page_record.setdefault("incoming_page_ids", [])
    page_record.setdefault("related_page_ids", [])
    page_record["lifecycle_status"] = page_lifecycle_status_for_record(page_record)
    return page_record


def is_live_page_record(page_record: dict) -> bool:
    # live page 指“当前应参与索引、检索、目录展示”的在线页面。
    # removed / archived 页面仍可保留在 state/pages.jsonl 里，但不进入在线视图。
    lifecycle_status = page_record.get("lifecycle_status")
    if lifecycle_status in {"removed", "archived"}:
        return False
    return not page_record.get("removed", False)


def filter_live_page_records(page_records: list[dict]) -> list[dict]:
    # 统一从完整页面账本中过滤出在线页面，避免 query / index / wiki index
    # 各自手写一遍过滤条件，后续语义更容易保持一致。
    return [record for record in page_records if is_live_page_record(record)]


def is_live_claim_record(claim_record: dict) -> bool:
    # claim 的在线态比 page 更严格：
    # 既要 lifecycle 是 active，也要仍然保有可用的 source/source_ref 追踪链。
    return (
        claim_record.get("lifecycle_status") == "active"
        and bool(claim_record.get("source_ids"))
        and bool(claim_record.get("source_refs"))
    )


def filter_live_claim_records(claim_records: list[dict]) -> list[dict]:
    return [record for record in claim_records if is_live_claim_record(record)]


def filter_live_stable_claim_records(claim_records: list[dict]) -> list[dict]:
    # 可读概念页只消费当前仍活跃、且已经被提升为 stable 的 claim。
    return [
        record for record in claim_records
        if is_live_claim_record(record) and record.get("status") == "stable"
    ]


def is_live_review_record(review_record: dict) -> bool:
    # review 只有在仍然挂着候选 claim、且 lifecycle 为 active 时，
    # 才应继续进入概念页和后续人工处理视图。
    if review_record.get("lifecycle_status") != "active":
        return False
    return bool(review_record.get("candidate_claim_ids") or review_record.get("candidate_page_ids"))


def filter_live_review_records(review_records: list[dict]) -> list[dict]:
    return [record for record in review_records if is_live_review_record(record)]


def build_ordered_claim_state_records(
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
) -> list[dict]:
    # state/claims.jsonl 既保存在线 claim，也保存历史态 claim。
    # 这里统一做一次稳定排序，方便 diff 和排查。
    records = [*live_claims_by_id.values(), *historical_claims_by_id.values()]
    return sorted(
        records,
        key=lambda item: (
            item.get("created_at", ""),
            item.get("updated_at", ""),
            item.get("claim_id", ""),
        ),
    )


def build_ordered_review_state_records(
    live_reviews_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
) -> list[dict]:
    # review 账本里同一个 review_id 不应同时出现 live + historical 两份。
    # 这里优先保留 live 记录，并吞掉重复历史态。
    deduped_records_by_id = dict(historical_reviews_by_id)
    deduped_records_by_id.update(live_reviews_by_id)
    records = list(deduped_records_by_id.values())
    return sorted(
        records,
        key=lambda item: (
            item.get("created_at", ""),
            item.get("resolved_at", "") or "",
            item.get("review_id", ""),
        ),
    )


def load_claim_state_maps(target: Path) -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    # review 命令需要同时看到在线 claim 和历史 claim。
    # 这里统一加载，避免 list/apply 两个命令重复写一遍状态拆分逻辑。
    return repo_load_claim_state_maps(
        target,
        load_jsonl=load_jsonl,
        ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
        filter_live_claim_records=filter_live_claim_records,
        is_live_claim_record=is_live_claim_record,
    )


def load_review_state_maps(target: Path) -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    return repo_load_review_state_maps(
        target,
        load_jsonl=load_jsonl,
        ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
        filter_live_review_records=filter_live_review_records,
        is_live_review_record=is_live_review_record,
    )


def build_claim_lookup_by_any_id(
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
) -> dict[str, dict]:
    # review 历史里经常还保留“原始 claim_id”，
    # 因此这里同时支持按当前主键和 original_claim_id 反查。
    lookup = {}
    for record in [*live_claims_by_id.values(), *historical_claims_by_id.values()]:
        lookup[record["claim_id"]] = record
        original_claim_id = record.get("original_claim_id")
        if original_claim_id:
            lookup.setdefault(original_claim_id, record)
    return lookup


def claim_display_id(claim_record: dict) -> str:
    # 历史态 claim 的主键会加 __hist_ 后缀，展示给用户时优先露出原始 claim_id，
    # 这样 review 操作时不容易看花眼。
    return claim_record.get("original_claim_id") or claim_record["claim_id"]


def review_display_id(review_record: dict) -> str:
    return review_record.get("original_review_id") or review_record["review_id"]


def is_actionable_review_record(review_record: dict) -> bool:
    # 只有仍然 open 的 review 才应该继续影响概念页状态和后续人工待办。
    return is_live_review_record(review_record) and review_record.get("status") == "open"


def build_historical_claim_id(claim_record: dict) -> str:
    # 同一路径 source 原位更新后，新旧 claim 可能共享原始 claim_id。
    # 历史态记录需要搬到单独的命名空间里，避免和新一轮活跃 claim 撞 ID。
    archived_at = claim_record.get("archived_at") or utc_now_iso()
    archived_suffix = re.sub(r"[^0-9]", "", archived_at)[:20] or datetime.now().strftime("%Y%m%d%H%M%S")
    original_claim_id = claim_record.get("original_claim_id") or claim_record["claim_id"]
    return f"{original_claim_id}__hist_{archived_suffix}"


def build_historical_review_id(review_record: dict) -> str:
    archived_at = review_record.get("archived_at") or utc_now_iso()
    archived_suffix = re.sub(r"[^0-9]", "", archived_at)[:20] or datetime.now().strftime("%Y%m%d%H%M%S")
    original_review_id = review_record.get("original_review_id") or review_record["review_id"]
    return f"{original_review_id}__hist_{archived_suffix}"


def convert_claim_record_to_historical(claim_record: dict) -> dict:
    # 历史态 claim 仍保留原始 claim_id 供追踪，但 state/file 主键切换为历史态 ID。
    archived_record = dict(claim_record)
    archived_record["original_claim_id"] = archived_record.get("original_claim_id") or archived_record["claim_id"]
    archived_record["claim_id"] = build_historical_claim_id(archived_record)
    archived_record["claim_file_path"] = str(Path("claims") / f"{archived_record['claim_id']}.json")
    return archived_record


def convert_review_record_to_historical(review_record: dict) -> dict:
    archived_record = dict(review_record)
    archived_record["original_review_id"] = archived_record.get("original_review_id") or archived_record["review_id"]
    archived_record["review_id"] = build_historical_review_id(archived_record)
    archived_record["review_file_path"] = str(Path("reviews") / f"{archived_record['review_id']}.json")
    return archived_record


def has_negation(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in NEGATION_MARKERS)


def normalize_claim_base_for_conflict(text: str) -> str:
    # 冲突判断先用一个粗糙但稳定的“去否定标记”版本做基线。
    normalized = normalize_claim_text(text)
    for marker in NEGATION_MARKERS:
        normalized = normalized.replace(marker.strip(), "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def build_similarity_bucket(text: str) -> str:
    # 这个 bucket 现在主要服务于概念页聚合与缺页补齐。
    # 它仍然保持“稳定、粗粒度、低成本”的特点，不承担最终相似判定责任。
    normalized = normalize_claim_text(text)
    return normalized[:24]


def build_claim_similarity_tokens(text: str) -> list[str]:
    # claim review 的相似检测要比概念页 bucket 更细一点：
    # - 先去掉否定词，让“需要/不需要”这类冲突句仍能进入同一候选池
    # - 再复用 query 的中英混合切词逻辑，保证检索和审核尽量共享一套词法直觉
    base_text = normalize_claim_base_for_conflict(text)
    seen: set[str] = set()
    tokens: list[str] = []

    for token in tokenize_for_search(base_text):
        cleaned_token = token.strip()
        if len(cleaned_token) < 2:
            continue
        if cleaned_token in seen:
            continue
        seen.add(cleaned_token)
        tokens.append(cleaned_token)
    return tokens


def claim_similarity_token_weight(token: str) -> float:
    # 更长的 token 往往语义更具体，给它更高一点的权重。
    # 这里故意保持简单，避免引入太多难以解释的启发式参数。
    latin_or_number = bool(re.fullmatch(r"[a-z0-9_]+", token))
    if latin_or_number:
        return max(1.0, min(len(token), 8) / 2.0)
    return float(min(len(token), 4))


def compute_weighted_token_overlap(left_tokens: list[str], right_tokens: list[str]) -> tuple[float, float, int]:
    # overlap_ratio 看“共享语义片段占较短句子的比例”；
    # jaccard_ratio 看“双方整体重合度”；
    # 两者一起用，能减少“只共享开头几个泛词”导致的误报。
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    if not left_set or not right_set:
        return 0.0, 0.0, 0

    shared_tokens = left_set & right_set
    shared_weight = sum(claim_similarity_token_weight(token) for token in shared_tokens)
    left_weight = sum(claim_similarity_token_weight(token) for token in left_set)
    right_weight = sum(claim_similarity_token_weight(token) for token in right_set)

    overlap_ratio = shared_weight / max(1.0, min(left_weight, right_weight))
    jaccard_ratio = shared_weight / max(1.0, left_weight + right_weight - shared_weight)
    return overlap_ratio, jaccard_ratio, len(shared_tokens)


def measure_claim_text_similarity(left_text: str, right_text: str) -> dict:
    # 这里把“候选召回”和“最终是否足够相似”拆开：
    # 候选召回尽量宽一点，最终判定则结合字符序列和 token 重合度做保守收敛。
    left_base = normalize_claim_base_for_conflict(left_text)
    right_base = normalize_claim_base_for_conflict(right_text)
    left_tokens = build_claim_similarity_tokens(left_text)
    right_tokens = build_claim_similarity_tokens(right_text)
    overlap_ratio, jaccard_ratio, shared_token_count = compute_weighted_token_overlap(left_tokens, right_tokens)
    if left_base and right_base:
        matcher = difflib.SequenceMatcher(None, left_base, right_base)
        sequence_ratio = matcher.ratio()
        longest_common_span = max((block.size for block in matcher.get_matching_blocks()), default=0)
    else:
        sequence_ratio = 0.0
        longest_common_span = 0
    longest_common_span_ratio = longest_common_span / max(1, min(len(left_base), len(right_base)))

    shorter_base, longer_base = sorted([left_base, right_base], key=len)
    containment = bool(shorter_base) and len(shorter_base) >= 12 and shorter_base in longer_base

    return {
        "left_base": left_base,
        "right_base": right_base,
        "left_tokens": left_tokens,
        "right_tokens": right_tokens,
        "overlap_ratio": overlap_ratio,
        "jaccard_ratio": jaccard_ratio,
        "shared_token_count": shared_token_count,
        "sequence_ratio": sequence_ratio,
        "longest_common_span": longest_common_span,
        "longest_common_span_ratio": longest_common_span_ratio,
        "containment": containment,
    }


def claims_are_similar_for_review(left_text: str, right_text: str) -> bool:
    # 这一层不追求“语义理解”，只做 V1 足够稳定的近重复/冲突前置筛选：
    # - 完全同 base：直接视为同主题
    # - 一方基本包含另一方：通常是“扩写版/带前缀版”
    # - 其余情况需要同时满足字符近似 + token 重合，避免误把同领域句子都撞进 review
    metrics = measure_claim_text_similarity(left_text, right_text)
    left_base = metrics["left_base"]
    right_base = metrics["right_base"]
    if not left_base or not right_base:
        return False
    if left_base == right_base:
        return True
    if metrics["containment"]:
        return True
    if metrics["sequence_ratio"] >= 0.90:
        return True
    if (
        metrics["longest_common_span_ratio"] >= 0.62
        and metrics["shared_token_count"] >= 6
    ):
        return True
    if (
        metrics["sequence_ratio"] >= 0.72
        and metrics["overlap_ratio"] >= 0.60
        and metrics["shared_token_count"] >= 4
    ):
        return True
    if (
        metrics["overlap_ratio"] >= 0.82
        and metrics["jaccard_ratio"] >= 0.55
        and metrics["shared_token_count"] >= 5
    ):
        return True
    return False


def index_claim_similarity_tokens(
    similarity_index: dict[str, set[str]],
    claim_record: dict,
) -> None:
    # 这里维护一个很轻量的 token -> claim_id 倒排索引，
    # 让“前缀不同但核心短语相同”的 claim 也能被召回进入后续精判。
    for token in build_claim_similarity_tokens(claim_record.get("text", "")):
        similarity_index.setdefault(token, set()).add(claim_record["claim_id"])


def rebuild_claim_similarity_index(claim_records: list[dict]) -> dict[str, set[str]]:
    similarity_index: dict[str, set[str]] = {}
    for claim_record in claim_records:
        index_claim_similarity_tokens(similarity_index, claim_record)
    return similarity_index


def collect_claim_review_candidate_ids(
    claim_record: dict,
    claims_by_similarity_bucket: dict[str, list[dict]],
    claim_similarity_index: dict[str, set[str]],
) -> set[str]:
    # 候选召回分两路：
    # 1) 老的 bucket，成本低、兼容现有概念页聚合
    # 2) 新的 token 倒排，补足“句首不同但主体相同”的情况
    candidate_claim_ids: set[str] = set()
    similarity_bucket = build_similarity_bucket(claim_record["text"])
    candidate_claim_ids.update(
        item["claim_id"]
        for item in claims_by_similarity_bucket.get(similarity_bucket, [])
    )
    for token in build_claim_similarity_tokens(claim_record.get("text", "")):
        candidate_claim_ids.update(claim_similarity_index.get(token, set()))
    candidate_claim_ids.discard(claim_record["claim_id"])
    return candidate_claim_ids


def append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def sync_claim_semantic_projection(claim_record: dict) -> dict:
    updated = dict(claim_record)
    projection = dict(updated.get("semantic_projection") or {})
    projection["knowledge_role"] = updated.get("knowledge_role")
    projection["page_intent_hints"] = list(updated.get("page_intent_hints", []) or [])
    projection["concept_candidate_score"] = coerce_float(updated.get("concept_candidate_score", 0.0), 0.0)
    if updated.get("quality_label") is not None:
        projection["quality_label"] = updated.get("quality_label")
    if updated.get("quality_reason") is not None:
        projection["quality_reason"] = updated.get("quality_reason")
    if updated.get("quality_confidence") is not None:
        projection["quality_confidence"] = updated.get("quality_confidence")
    if updated.get("quality_safe_auto_ready") is not None:
        projection["quality_safe_auto_ready"] = updated.get("quality_safe_auto_ready")
    if updated.get("quality_review_required") is not None:
        projection["quality_review_required"] = updated.get("quality_review_required")
    updated["semantic_projection"] = projection
    updated.setdefault("semantic_decision_ids", [])
    return updated


def claim_semantic_projection(claim_record: dict) -> dict:
    projection = dict(claim_record.get("semantic_projection") or {})
    if "knowledge_role" not in projection:
        projection["knowledge_role"] = claim_record.get("knowledge_role")
    if "page_intent_hints" not in projection:
        projection["page_intent_hints"] = list(claim_record.get("page_intent_hints", []) or [])
    if "concept_candidate_score" not in projection:
        projection["concept_candidate_score"] = coerce_float(claim_record.get("concept_candidate_score", 0.0), 0.0)
    return projection


def claim_knowledge_role(claim_record: dict) -> str:
    return str(claim_semantic_projection(claim_record).get("knowledge_role") or "").strip().lower()


def claim_page_intent_hints(claim_record: dict) -> list[str]:
    return [
        str(item).strip().lower()
        for item in claim_semantic_projection(claim_record).get("page_intent_hints", []) or []
        if str(item).strip()
    ]


def claim_concept_candidate_score(claim_record: dict) -> float:
    return coerce_float(claim_semantic_projection(claim_record).get("concept_candidate_score", 0.0), 0.0)


def build_claim_record_from_chunk(chunk_record: dict, claim_text: str) -> dict:
    # 单条 Claim 草稿要把溯源线索一开始就带全，后面 page / review 都直接复用。
    normalized_text = normalize_claim_text(claim_text)
    claim_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    claim_id = f"clm_{chunk_record['source_id']}_{claim_hash[:12]}"
    now = utc_now_iso()
    section_path_parts = chunk_record.get("section_path_parts")
    if not section_path_parts:
        section_path_parts = parse_section_path(chunk_record.get("section_path", "")).get("section_path_parts", [])

    return sync_claim_semantic_projection({
        "claim_id": claim_id,
        "text": claim_text.strip(),
        "normalized_text": normalized_text,
        "claim_type": classify_claim_type(claim_text),
        "knowledge_role": None,
        "page_intent_hints": [],
        "concept_candidate_score": 0.0,
        "quality_label": None,
        "quality_reason": None,
        "quality_confidence": None,
        "quality_review_required": False,
        "quality_safe_auto_ready": None,
        "quality_decision_source": None,
        "status": "draft",
        "lifecycle_status": "active",
        "source_ids": [chunk_record["source_id"]],
        "knowledge_unit_ids": [],
        "evidence_block_ids": [],
        "chunk_ids": [chunk_record["chunk_id"]],
        "page_ids": [],
        "conflict_group": None,
        "duplicate_candidates": [],
        "review_reason": None,
        "superseded_by": [],
        "archived_at": None,
        "source_refs": [
            {
                "source_id": chunk_record["source_id"],
                "source_path": chunk_record["source_path"],
                "normalized_path": chunk_record["normalized_path"],
                "chunk_id": chunk_record["chunk_id"],
                "section_path": chunk_record["section_path"],
                "section_path_parts": section_path_parts,
                "section_title": chunk_record.get("section_title") or (section_path_parts[-1] if section_path_parts else ""),
                "parent_section_path": chunk_record.get("parent_section_path") or " > ".join(section_path_parts[:-1]),
                "heading_level": chunk_record.get("heading_level") or len(section_path_parts),
                "start_line": chunk_record["start_line"],
                "end_line": chunk_record["end_line"],
            }
        ],
        "extraction_method": "rule_based_chunk_v2",
        "created_at": now,
        "updated_at": now,
    })


def find_covering_chunk_for_knowledge_unit(knowledge_unit: dict, chunk_records: list[dict]) -> dict | None:
    source_refs = knowledge_unit.get("source_refs", [])
    first_ref = source_refs[0] if source_refs else {}
    start_line = first_ref.get("start_line")
    end_line = first_ref.get("end_line")
    normalized_path = knowledge_unit.get("normalized_path")
    if start_line is None or end_line is None:
        return None

    overlapping_chunks = []
    for chunk_record in chunk_records:
        if chunk_record.get("normalized_path") != normalized_path:
            continue
        chunk_start = chunk_record.get("start_line")
        chunk_end = chunk_record.get("end_line")
        if chunk_start is None or chunk_end is None:
            continue
        if chunk_start <= start_line and chunk_end >= end_line:
            return chunk_record
        if chunk_start <= end_line and chunk_end >= start_line:
            overlapping_chunks.append(chunk_record)
    return overlapping_chunks[0] if overlapping_chunks else None


def build_claim_record_from_knowledge_unit(
    knowledge_unit: dict,
    claim_text: str,
    chunk_record: dict | None = None,
) -> dict:
    claim_text = contextualize_structural_claim_text(knowledge_unit, claim_text)
    normalized_text = normalize_claim_text(claim_text)
    claim_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    claim_id = f"clm_{knowledge_unit['source_id']}_{claim_hash[:12]}"
    now = utc_now_iso()
    chunk_id = chunk_record.get("chunk_id") if chunk_record else None
    chunk_section_parts = chunk_record.get("section_path_parts", []) if chunk_record else []
    if not isinstance(chunk_section_parts, list):
        chunk_section_parts = []
    source_refs = []
    for source_ref in knowledge_unit.get("source_refs", []):
        section_path_parts = knowledge_unit.get("metadata", {}).get("section_path_parts")
        if not section_path_parts:
            section_path_parts = chunk_section_parts
        source_refs.append({
            "source_id": knowledge_unit["source_id"],
            "source_path": knowledge_unit.get("source_path"),
            "normalized_path": knowledge_unit.get("normalized_path"),
            "chunk_id": chunk_id,
            "knowledge_unit_id": knowledge_unit["knowledge_unit_id"],
            "evidence_block_ids": knowledge_unit.get("evidence_block_ids", []),
            "section_path": chunk_record.get("section_path") if chunk_record else " > ".join(section_path_parts),
            "section_path_parts": section_path_parts,
            "section_title": (
                chunk_record.get("section_title")
                if chunk_record
                else section_path_parts[-1] if section_path_parts else ""
            ),
            "parent_section_path": (
                chunk_record.get("parent_section_path")
                if chunk_record
                else " > ".join(section_path_parts[:-1])
            ),
            "heading_level": chunk_record.get("heading_level") if chunk_record else len(section_path_parts),
            "start_line": source_ref.get("start_line"),
            "end_line": source_ref.get("end_line"),
        })
    if not source_refs:
        source_refs.append({
            "source_id": knowledge_unit["source_id"],
            "source_path": knowledge_unit.get("source_path"),
            "normalized_path": knowledge_unit.get("normalized_path"),
            "chunk_id": chunk_id,
            "knowledge_unit_id": knowledge_unit["knowledge_unit_id"],
            "evidence_block_ids": knowledge_unit.get("evidence_block_ids", []),
            "section_path": chunk_record.get("section_path") if chunk_record else "",
            "section_path_parts": chunk_section_parts,
            "section_title": chunk_record.get("section_title") if chunk_record else "",
            "parent_section_path": chunk_record.get("parent_section_path") if chunk_record else "",
            "heading_level": chunk_record.get("heading_level") if chunk_record else 0,
            "start_line": None,
            "end_line": None,
        })

    return sync_claim_semantic_projection({
        "claim_id": claim_id,
        "text": claim_text.strip(),
        "normalized_text": normalized_text,
        "claim_type": claim_type_for_knowledge_unit(knowledge_unit, claim_text),
        "claim_origin_kind": str(knowledge_unit.get("unit_kind", "")).strip().lower() or "statement",
        "knowledge_role": None,
        "page_intent_hints": [],
        "concept_candidate_score": 0.0,
        "quality_label": None,
        "quality_reason": None,
        "quality_confidence": None,
        "quality_review_required": False,
        "quality_safe_auto_ready": None,
        "quality_decision_source": None,
        "status": "draft",
        "lifecycle_status": "active",
        "source_ids": [knowledge_unit["source_id"]],
        "knowledge_unit_ids": [knowledge_unit["knowledge_unit_id"]],
        "evidence_block_ids": list(knowledge_unit.get("evidence_block_ids", [])),
        "chunk_ids": [chunk_id] if chunk_id else [],
        "page_ids": [],
        "conflict_group": None,
        "duplicate_candidates": [],
        "review_reason": None,
        "superseded_by": [],
        "archived_at": None,
        "source_refs": source_refs,
        "extraction_method": "rule_based_knowledge_unit_v1",
        "created_at": now,
        "updated_at": now,
    })


def merge_claim_records(existing_record: dict, incoming_record: dict) -> dict:
    # 如果规范文本完全一致，就把它们视为同一 claim，并合并溯源关系。
    merged = dict(existing_record)
    for source_id in incoming_record["source_ids"]:
        append_unique(merged["source_ids"], source_id)
    for knowledge_unit_id in incoming_record.get("knowledge_unit_ids", []):
        append_unique(merged.setdefault("knowledge_unit_ids", []), knowledge_unit_id)
    for evidence_block_id in incoming_record.get("evidence_block_ids", []):
        append_unique(merged.setdefault("evidence_block_ids", []), evidence_block_id)
    for decision_id in incoming_record.get("semantic_decision_ids", []):
        append_unique(merged.setdefault("semantic_decision_ids", []), decision_id)
    for chunk_id in incoming_record["chunk_ids"]:
        append_unique(merged["chunk_ids"], chunk_id)
    for page_id in incoming_record.get("page_ids", []):
        append_unique(merged["page_ids"], page_id)

    existing_ref_keys = {
        (
            item.get("source_id"),
            item.get("chunk_id"),
            item.get("knowledge_unit_id"),
            tuple(item.get("evidence_block_ids", [])),
            item.get("start_line"),
            item.get("end_line"),
        )
        for item in merged.get("source_refs", [])
    }
    for source_ref in incoming_record.get("source_refs", []):
        ref_key = (
            source_ref.get("source_id"),
            source_ref.get("chunk_id"),
            source_ref.get("knowledge_unit_id"),
            tuple(source_ref.get("evidence_block_ids", [])),
            source_ref.get("start_line"),
            source_ref.get("end_line"),
        )
        if ref_key not in existing_ref_keys:
            merged.setdefault("source_refs", []).append(source_ref)
            existing_ref_keys.add(ref_key)

    if not merged.get("knowledge_role") and incoming_record.get("knowledge_role"):
        merged["knowledge_role"] = incoming_record.get("knowledge_role")
    incoming_intents = incoming_record.get("page_intent_hints", [])
    existing_intents = list(merged.get("page_intent_hints", []))
    for hint in incoming_intents:
        append_unique(existing_intents, hint)
    merged["page_intent_hints"] = existing_intents
    merged["concept_candidate_score"] = max(
        coerce_float(merged.get("concept_candidate_score", 0.0), 0.0),
        coerce_float(incoming_record.get("concept_candidate_score", 0.0), 0.0),
    )
    for field in (
        "quality_label",
        "quality_reason",
        "quality_confidence",
        "quality_review_required",
        "quality_safe_auto_ready",
        "quality_decision_source",
    ):
        incoming_value = incoming_record.get(field)
        if incoming_value is not None:
            merged[field] = incoming_value
    merged["updated_at"] = utc_now_iso()
    merged["lifecycle_status"] = claim_lifecycle_status_for_record(merged)
    return sync_claim_semantic_projection(merged)


def claim_file_path(target: Path, claim_id: str) -> Path:
    return target / "claims" / f"{claim_id}.json"


def write_claim_file(target: Path, claim_record: dict) -> str:
    # claim 文件是权威源；state/claims.jsonl 是便于扫描和索引的派生索引。
    claim_path = claim_file_path(target, claim_record["claim_id"])
    write_json(claim_path, claim_record)
    return str(Path("claims") / claim_path.name)


def review_file_path(target: Path, review_id: str) -> Path:
    return target / "reviews" / f"{review_id}.json"


def build_review_record(
    kind: str,
    candidate_claim_ids: list[str],
    reason: str,
    evidence: list[dict],
    recommended_action: str,
    signature_parts: list[str] | None = None,
) -> dict:
    # review item 尽量自解释：为什么进入审核、建议动作是什么、证据链在哪里。
    if signature_parts:
        signature = "|".join(signature_parts) + "|" + kind
    else:
        signature = "|".join(sorted(candidate_claim_ids)) + "|" + kind
    review_hash = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    review_id = f"rev_{review_hash[:12]}"
    now = utc_now_iso()
    return {
        "review_id": review_id,
        "kind": kind,
        "status": "open",
        "lifecycle_status": "active",
        "candidate_claim_ids": sorted(candidate_claim_ids),
        "candidate_page_ids": [],
        "reason": reason,
        "recommended_action": recommended_action,
        "allowed_actions": ["merge", "keep_both", "archive_one", "edit_then_resume"],
        "resume_from": "claim_review",
        "evidence": evidence,
        "created_at": now,
        "resolved_at": None,
        "archived_at": None,
    }


def write_review_file(target: Path, review_record: dict) -> str:
    review_path = review_file_path(target, review_record["review_id"])
    write_json(review_path, review_record)
    return str(Path("reviews") / review_path.name)


def append_error_record(
    error_log_path: Path,
    task_id: str,
    source_id: str,
    stage: str,
    level: str,
    message: str,
    details: dict | None = None,
) -> dict:
    # 错误日志和 warning 日志统一写这里，后续 review / 报表 / 追查都能复用。
    record = {
        "task_id": task_id,
        "source_id": source_id,
        "stage": stage,
        "level": level,
        "message": message,
        "details": details or {},
        "created_at": utc_now_iso(),
    }
    append_jsonl(error_log_path, record)
    return record


def build_claims_from_chunk(chunk_record: dict) -> list[dict]:
    # 一个 chunk 里可能有多个可提取陈述；这里保留通过规则筛出的全部候选，
    # 避免长段落后半段的独立结论被前几条候选提前截断。
    plain_text = markdown_to_plain_text(strip_fenced_code_blocks(chunk_record["text"]))
    claim_candidates = split_claim_candidates_from_text(plain_text)
    claim_records: list[dict] = []

    for candidate_text in claim_candidates:
        claim_records.append(build_claim_record_from_chunk(chunk_record, candidate_text))

    if claim_records:
        return claim_records

    # 某些时间线型文档正文可能几乎全是对话/元数据噪声，但章节标题本身仍值得沉淀成概念入口。
    section_path = chunk_record.get("section_path", "")
    section_parts = [part.strip() for part in section_path.split(">") if part.strip()]
    if section_parts:
        fallback_label = clean_concept_title_text(section_parts[-1])
        if text_is_iso_date_label(fallback_label):
            return [build_claim_record_from_chunk(chunk_record, fallback_label)]

    return claim_records


def build_claims_from_knowledge_unit(knowledge_unit: dict, chunk_records: list[dict] | None = None) -> list[dict]:
    unit_kind = str(knowledge_unit.get("unit_kind", "")).strip()
    if unit_kind in {"structural_shell", "code_example"}:
        return []

    text = str(knowledge_unit.get("text", "")).strip()
    if not text:
        return []

    local_heading = str(knowledge_unit.get("local_heading") or "").strip()
    if local_heading and text.startswith(local_heading):
        body_text = text[len(local_heading):].strip()
        if body_text:
            text = f"{local_heading}：{body_text}"

    covering_chunk = find_covering_chunk_for_knowledge_unit(knowledge_unit, chunk_records or [])
    plain_text = markdown_to_plain_text(strip_fenced_code_blocks(text))
    claim_candidates = split_claim_candidates_from_text(plain_text)
    claim_records = [
        build_claim_record_from_knowledge_unit(knowledge_unit, candidate_text, covering_chunk)
        for candidate_text in claim_candidates
    ]
    if claim_records:
        return claim_records

    if unit_kind in {"metadata_fact", "table_fact"}:
        metadata = knowledge_unit.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        if unit_kind == "table_fact":
            cells = metadata.get("cells")
            if isinstance(cells, list) and len(cells) >= 2:
                header = str(cells[0]).strip().lower()
                value = str(cells[1]).strip().lower()
                if (header, value) in {
                    ("field", "value"),
                    ("字段", "值"),
                    ("name", "value"),
                    ("key", "value"),
                }:
                    return []
        cleaned_text = clean_claim_candidate_text(text)
        if cleaned_text and not claim_candidate_is_noise(cleaned_text):
            return [build_claim_record_from_knowledge_unit(knowledge_unit, cleaned_text, covering_chunk)]

    return []


def build_claim_candidates_for_source(
    source_id: str,
    knowledge_units_by_source_id: dict[str, list[dict]],
    chunks_by_source_id: dict[str, list[dict]],
) -> list[dict]:
    knowledge_units = knowledge_units_by_source_id.get(source_id, [])
    if knowledge_units:
        claim_records: list[dict] = []
        source_chunks = chunks_by_source_id.get(source_id, [])
        for knowledge_unit in knowledge_units:
            claim_records.extend(build_claims_from_knowledge_unit(knowledge_unit, source_chunks))
        if claim_records:
            return claim_records

    claim_records = []
    for chunk_record in chunks_by_source_id.get(source_id, []):
        claim_records.extend(build_claims_from_chunk(chunk_record))
    return claim_records


def source_claim_stage_completed(source_record: dict) -> bool:
    # 只要来源已经进入 claimed / review_required / generated，
    # 就说明这个 source 的 chunk -> claim 抽取已经跑过一轮了。
    # 在当前“同内容文件不会重复导入为同一 source”的模型下，
    # 后续重复 ingest 不需要再把这个 source 的所有 chunk 全量重抽一遍 claim。
    return source_record.get("status") in {"claimed", "review_required", "generated"}


def workspace_can_skip_page_regeneration(
    sources_by_id: dict[str, dict],
    created_sources: list[dict],
    normalized_sources: list[dict],
    chunked_sources: list[dict],
    claims_created_by_source: dict[str, int],
    review_items: list[dict],
    semantic_claim_updates_applied: bool = False,
) -> bool:
    # 这是一个“无上游变化”的保守短路条件：
    # - 没有新 source
    # - 没有新 normalized/chunk/claim/review
    # - 没有仅由语义账本带来的 claim 角色/页面意图提示变化
    # - 所有来源都已经走到 generated 或 failed
    # 满足这些条件时，source-summary / concept / search index 在语义上都不该变化。
    if (
        created_sources
        or normalized_sources
        or chunked_sources
        or claims_created_by_source
        or review_items
        or semantic_claim_updates_applied
    ):
        return False
    return all(record.get("status") in {"generated", "failed"} for record in sources_by_id.values())


def choose_active_source_ids(sources_by_id: dict[str, dict]) -> set[str]:
    # 同一路径的原始文件在多次 ingest 后，可能会形成多个 source 版本。
    # 页面生成优先围绕“最新且未失败的版本”展开；如果某一路径最新版本失败了，
    # 就暂时回退到该路径最后一个未失败版本，避免因为一次转换失败把现有 wiki 整页抹掉。
    grouped: dict[str, list[dict]] = {}
    for record in sources_by_id.values():
        grouped.setdefault(record["source_path"], []).append(record)

    active_source_ids: set[str] = set()
    for source_path, records in grouped.items():
        sorted_records = sorted(records, key=lambda item: item.get("imported_at", ""))
        non_failed_records = [
            record for record in sorted_records
            if record.get("status") != "failed"
        ]
        chosen_record = non_failed_records[-1] if non_failed_records else sorted_records[-1]
        active_source_ids.add(chosen_record["source_id"])
    return active_source_ids


def expected_source_summary_page_id(source_id: str) -> str:
    return f"page_src_{source_id}"


def build_workspace_overview_page_id() -> str:
    return "page_ovw_workspace"


def workspace_overview_page_path() -> Path:
    return Path("wiki") / "overview" / "index.md"


def collect_missing_source_page_source_ids(
    active_source_ids: set[str],
    sources_by_id: dict[str, dict],
    page_records_by_id: dict[str, dict],
    claims_by_source_id: dict[str, list[dict]],
    chunks_by_source_id: dict[str, list[dict]],
) -> set[str]:
    # 如果某个来源已经有证据层产物，但缺少来源摘要页，就把它视为待补齐页面。
    missing_source_ids: set[str] = set()
    for source_id, source_record in sources_by_id.items():
        if source_id not in active_source_ids:
            continue
        if source_record.get("status") == "failed":
            continue
        if not claims_by_source_id.get(source_id) and not chunks_by_source_id.get(source_id):
            continue
        if expected_source_summary_page_id(source_id) not in page_records_by_id:
            missing_source_ids.add(source_id)
    return missing_source_ids


def collect_missing_concept_bucket_keys(
    claims_by_similarity_bucket: dict[str, list[dict]],
    page_records_by_id: dict[str, dict],
) -> set[str]:
    # 概念页的 page_id 可以由 bucket 稳定推导，因此可以快速补齐缺页。
    missing_bucket_keys: set[str] = set()
    for bucket_key, grouped_claims in claims_by_similarity_bucket.items():
        if not should_generate_concept_page(grouped_claims):
            continue
        if build_concept_page_id(bucket_key) not in page_records_by_id:
            missing_bucket_keys.add(bucket_key)
    return missing_bucket_keys


def expected_workspace_overview_concept_page_ids(
    claims_by_similarity_bucket: dict[str, list[dict]],
) -> set[str]:
    return {
        build_concept_page_id(bucket_key)
        for bucket_key, grouped_claims in claims_by_similarity_bucket.items()
        if should_generate_concept_page(grouped_claims)
    }


def collect_workspace_overview_concept_pages(
    claims_by_similarity_bucket: dict[str, list[dict]],
    page_records_by_id: dict[str, dict],
) -> list[dict]:
    concept_pages: list[dict] = []
    for page_id in sorted(expected_workspace_overview_concept_page_ids(claims_by_similarity_bucket)):
        page_record = page_records_by_id.get(page_id)
        if page_record is None or not is_live_page_record(page_record):
            continue
        if page_record.get("type") != "concept":
            continue
        concept_pages.append(page_record)
    return concept_pages


def should_generate_workspace_overview_page(concept_page_records: list[dict]) -> bool:
    # 综述页先保持保守：至少要有两个可读概念页，才值得给出工作区级总览。
    return len(concept_page_records) >= 2


def workspace_overview_page_missing(
    claims_by_similarity_bucket: dict[str, list[dict]],
    page_records_by_id: dict[str, dict],
) -> bool:
    concept_pages = collect_workspace_overview_concept_pages(
        claims_by_similarity_bucket=claims_by_similarity_bucket,
        page_records_by_id=page_records_by_id,
    )
    return (
        should_generate_workspace_overview_page(concept_pages)
        and build_workspace_overview_page_id() not in page_records_by_id
    )


def regroup_concept_claims_by_canonical_topic(
    concept_claim_groups: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    # 第一层 bucket 主要解决“相似 claim 初步召回”。
    # 但真实页面层还需要再做一次“主题收口”：
    # 如果不同 bucket 最终推导出相同标题/规范键，就应该落到同一概念页，
    # 否则会出现多个 live page 共用同一 canonical_id，进而污染 alias index 和 lint。
    regrouped: dict[str, list[dict]] = {}

    for bucket_key, grouped_claims in concept_claim_groups.items():
        if not grouped_claims:
            continue
        group_topic_label = choose_group_topic_label(grouped_claims)
        canonical_claim = choose_canonical_claim(grouped_claims, group_topic_label)
        title = build_concept_title(canonical_claim, preferred_section_label=group_topic_label)
        canonical_key = build_concept_canonical_key(title)
        # 这里最终只按 canonical_key 收口。
        # 这样同一主题下的多条陈述即使来自不同 bucket，也会落到同一概念页，
        # 避免多个 live page 共享同一 canonical_id。
        regroup_key = canonical_key
        regrouped.setdefault(regroup_key, []).extend(grouped_claims)

    for regroup_key, grouped_claims in list(regrouped.items()):
        deduped_by_claim_id = {claim_record["claim_id"]: claim_record for claim_record in grouped_claims}
        regrouped[regroup_key] = list(deduped_by_claim_id.values())

    return regrouped


def remove_page_id_from_claim_records(claims_by_id: dict[str, dict], page_id: str) -> set[str]:
    dirty_claim_ids: set[str] = set()
    for claim_record in claims_by_id.values():
        page_ids = claim_record.get("page_ids", [])
        if page_id not in page_ids:
            continue
        claim_record["page_ids"] = [item for item in page_ids if item != page_id]
        claim_record["updated_at"] = utc_now_iso()
        dirty_claim_ids.add(claim_record["claim_id"])
    return dirty_claim_ids


def remove_page_id_from_review_records(reviews_by_id: dict[str, dict], page_id: str) -> set[str]:
    dirty_review_ids: set[str] = set()
    for review_record in reviews_by_id.values():
        candidate_page_ids = review_record.get("candidate_page_ids", [])
        if page_id not in candidate_page_ids:
            continue
        review_record["candidate_page_ids"] = [item for item in candidate_page_ids if item != page_id]
        dirty_review_ids.add(review_record["review_id"])
    return dirty_review_ids


def remove_source_refs_from_claim_record(claim_record: dict, source_id: str) -> bool:
    # 同一路径来源更新时，要把旧 source 对应的证据引用从 claim 中剥掉，
    # 这样后续页面聚合和阅读包才会逐步只围绕最新活动版本展开。
    original_source_ids = list(claim_record.get("source_ids", []))
    original_chunk_ids = list(claim_record.get("chunk_ids", []))
    original_source_refs = list(claim_record.get("source_refs", []))

    claim_record["source_ids"] = [
        item for item in claim_record.get("source_ids", [])
        if item != source_id
    ]
    claim_record["source_refs"] = [
        item for item in claim_record.get("source_refs", [])
        if item.get("source_id") != source_id
    ]
    active_chunk_ids = {
        item.get("chunk_id")
        for item in claim_record.get("source_refs", [])
        if item.get("chunk_id")
    }
    claim_record["chunk_ids"] = [
        chunk_id for chunk_id in claim_record.get("chunk_ids", [])
        if chunk_id in active_chunk_ids
    ]
    claim_record["lifecycle_status"] = claim_lifecycle_status_for_record(claim_record)

    return (
        claim_record["source_ids"] != original_source_ids
        or claim_record["chunk_ids"] != original_chunk_ids
        or claim_record["source_refs"] != original_source_refs
    )


def purge_source_from_claims(
    target: Path,
    claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    source_id: str,
) -> tuple[set[str], set[str]]:
    # 返回：
    # 1. 被修改但仍保留的 claim_id
    # 2. 因失去全部 source_ref 而被转入历史态的 claim_id
    dirty_claim_ids: set[str] = set()
    deleted_claim_ids: set[str] = set()

    for claim_id, claim_record in list(claims_by_id.items()):
        if source_id not in claim_record.get("source_ids", []):
            continue
        changed = remove_source_refs_from_claim_record(claim_record, source_id)
        if not changed:
            continue
        if not claim_record.get("source_ids") or not claim_record.get("source_refs"):
            claim_record["lifecycle_status"] = "superseded"
            claim_record["archived_at"] = utc_now_iso()
            claim_record["updated_at"] = utc_now_iso()
            deleted_claim_ids.add(claim_id)
            claims_by_id.pop(claim_id, None)
            historical_claim_record = convert_claim_record_to_historical(claim_record)
            historical_claims_by_id[historical_claim_record["claim_id"]] = historical_claim_record
            write_claim_file(target, historical_claim_record)
            continue
        claim_record["updated_at"] = utc_now_iso()
        dirty_claim_ids.add(claim_id)

    return dirty_claim_ids, deleted_claim_ids


def purge_deleted_claims_from_reviews(
    reviews_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
    deleted_claim_ids: set[str],
) -> tuple[set[str], set[str]]:
    # 被删掉的 claim 不该继续留在 review 候选里。
    # 返回：
    # 1. 仍保留但被修改的 review_id
    # 2. 因失去全部 candidate_claim_ids 而转入历史态的 review_id
    dirty_review_ids: set[str] = set()
    deleted_review_ids: set[str] = set()
    deleted_claim_id_set = set(deleted_claim_ids)

    for review_id, review_record in list(reviews_by_id.items()):
        original_claim_ids = list(review_record.get("candidate_claim_ids", []))
        remaining_claim_ids = [
            claim_id for claim_id in original_claim_ids
            if claim_id not in deleted_claim_id_set
        ]
        if remaining_claim_ids == original_claim_ids:
            continue
        if not remaining_claim_ids:
            review_record["lifecycle_status"] = "superseded"
            review_record["archived_at"] = utc_now_iso()
            reviews_by_id.pop(review_id, None)
            historical_review_record = convert_review_record_to_historical(review_record)
            historical_reviews_by_id[historical_review_record["review_id"]] = historical_review_record
            deleted_review_ids.add(review_id)
            continue
        review_record["candidate_claim_ids"] = remaining_claim_ids
        review_record["lifecycle_status"] = review_lifecycle_status_for_record(review_record)
        dirty_review_ids.add(review_id)

    return dirty_review_ids, deleted_review_ids


def prune_stale_auto_pages(
    target: Path,
    page_records_by_id: dict[str, dict],
    desired_auto_page_ids: set[str],
    claims_by_id: dict[str, dict],
    reviews_by_id: dict[str, dict],
    forced_stale_page_ids: set[str] | None = None,
) -> tuple[list[dict], set[str], set[str]]:
    # 这里负责清理“这轮模型下已经不该存在”的自动页面。
    # 典型场景是：同一路径文档被更新后，过期 source-summary 和概念页应退出主视图。
    removed_pages: list[dict] = []
    dirty_claim_ids: set[str] = set()
    dirty_review_ids: set[str] = set()
    forced_stale_page_ids = forced_stale_page_ids or set()
    auto_page_types = {
        "source-summary",
        "concept",
        "overview",
        "guide",
        "example",
        "topic",
        "reference",
        "timeline",
    }

    stale_page_ids = [
        page_id
        for page_id, page_record in page_records_by_id.items()
        if page_record.get("type") in auto_page_types
        and (
            page_id in forced_stale_page_ids
            or page_id not in desired_auto_page_ids
        )
    ]

    for page_id in stale_page_ids:
        page_record = dict(page_records_by_id[page_id])
        page_record["removed"] = True
        page_record["lifecycle_status"] = "removed"
        page_record["archived_at"] = utc_now_iso()
        page_record["updated"] = utc_now_iso()
        page_records_by_id[page_id] = page_record
        removed_pages.append(page_record)

        page_path = target / page_record["page_path"]
        if page_path.exists():
            page_path.unlink()

        dirty_claim_ids.update(remove_page_id_from_claim_records(claims_by_id, page_id))
        dirty_review_ids.update(remove_page_id_from_review_records(reviews_by_id, page_id))

    return removed_pages, dirty_claim_ids, dirty_review_ids


def sanitize_page_slug(value: str) -> str:
    # wiki 页文件名尽量稳定、可读、跨平台安全。
    slug = sanitize_source_key(value)
    stabilized = stabilize_filename_component(slug, separator="_")
    return stabilized or "page"


def sanitize_page_filename(value: str) -> str:
    # 面向最终导出的页面文件名尽量保留可读性，避免把标题压成一串下划线。
    cleaned = clean_concept_title_text(value)
    cleaned = re.sub(r"[\\/:*?\"<>|#]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    hash_source = re.sub(r"[\\/:*?\"<>|#]+", " ", str(value))
    hash_source = re.sub(r"\s+", " ", hash_source).strip(" .")
    if hash_source and hash_source != cleaned:
        digest = hashlib.sha256(hash_source.encode("utf-8")).hexdigest()[:FILENAME_HASH_LENGTH]
        cleaned = f"{cleaned}__{digest}" if cleaned else digest
    stabilized = stabilize_filename_component(cleaned)
    return stabilized or "page"


def summarize_claims_for_page(claim_records: list[dict], limit: int = 3) -> list[str]:
    # 来源摘要页先挑几条 claim 做“核心观点”。
    ranked = sorted(
        claim_records,
        key=claim_record_rank_key,
        reverse=True,
    )
    return [item["text"] for item in ranked[:limit]]


def source_summary_page_path(source_id: str, title: str) -> Path:
    slug = sanitize_page_slug(title)
    source_key = stabilize_filename_component(sanitize_source_key(source_id), separator="_") or "source"
    filename = stabilize_filename_component(
        f"{slug}__{source_key}",
        max_bytes=MAX_FILENAME_COMPONENT_BYTES - len(".md".encode("utf-8")),
    )
    return Path("wiki") / "sources" / f"{filename or 'page'}.md"


def shorten_title_text(value: str, limit: int = 32) -> str:
    # 页面标题不能无限长，否则文件名、索引页和终端输出都会变得很难读。
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 1)].rstrip() + "..."


def build_concept_page_id(bucket_key: str) -> str:
    # 概念页 ID 基于最终分组键生成。
    # 在 V1 当前实现里，这个键已经包含“可读主题 + 规范概念键”的二次收口结果，
    # 可以避免不同 bucket 最终生成相同 canonical_id 却 page_id 不同的问题。
    bucket_hash = hashlib.sha256(bucket_key.encode("utf-8")).hexdigest()
    return f"page_cpt_{bucket_hash[:12]}"


def build_concept_group_key(claim_record: dict) -> str:
    # 概念页聚合键尽量与 review 检测使用同一套“主题归一化”直觉。
    # 这样 query、review、concept page 三者更容易围绕同一组 claim 收敛。
    section_label = extract_primary_section_label(claim_record)
    if section_label and not is_generic_concept_label(section_label):
        return build_concept_canonical_key(section_label)
    base_text = normalize_claim_base_for_conflict(claim_record.get("text", ""))
    similarity_tokens = build_claim_similarity_tokens(claim_record.get("text", ""))
    token_fingerprint = " ".join(similarity_tokens[:8])
    seed = base_text or claim_record.get("normalized_text", "") or claim_record.get("text", "")
    seed_hash = hashlib.sha256(f"{seed}|{token_fingerprint}".encode("utf-8")).hexdigest()[:12]
    readable_prefix = build_similarity_bucket(claim_record.get("text", ""))
    return f"{readable_prefix}|{seed_hash}"


def claim_role_blocks_concept_path(claim_record: dict) -> bool:
    role = claim_knowledge_role(claim_record)
    if role in {"procedure", "example", "meta", "structural_shell", "opinion"}:
        return True
    page_intent_hints = set(claim_page_intent_hints(claim_record))
    if "reject" in page_intent_hints:
        return True
    return False


def filter_claim_records_for_concept_path(claim_records: list[dict]) -> list[dict]:
    return [record for record in claim_records if not claim_role_blocks_concept_path(record)]


def concept_summary_page_path(page_id: str, title: str) -> Path:
    # 概念页文件名尽量贴近最终展示标题，避免导出到外部工具时把内部 page_id 暴露成主标题。
    filename = sanitize_page_filename(title)
    return Path("wiki") / "concepts" / page_id / f"{filename}.md"


def clean_concept_title_text(value: str) -> str:
    # 概念页标题要尽量像“页面名”，而不是原始 claim 文本残片。
    cleaned = value.replace("|", " ").replace("_", " ")
    # 仅清理“1. 标题”“2) 标题”这类前导编号，不要把 2026-05-24 这类日期误裁成 05-24。
    cleaned = re.sub(r"^\s*\d+\s*[.)、:：]\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;,.!?。！？；：|")
    return cleaned


def normalize_question_style_concept_label(label: str) -> str:
    # FAQ/目录型标题常写成“1. Claim 是什么”或“什么是 Claim”，这里尽量还原成概念名本身。
    cleaned = clean_concept_title_text(label)
    if not cleaned:
        return ""

    suffix_match = re.fullmatch(r"(.+?)\s*(?:是|指)?什么[？?]?", cleaned, flags=re.IGNORECASE)
    if suffix_match:
        candidate = clean_concept_title_text(suffix_match.group(1))
        if candidate:
            return candidate

    prefix_match = re.fullmatch(r"(?:什么是|什么叫|何谓)\s*(.+?)[？?]?", cleaned, flags=re.IGNORECASE)
    if prefix_match:
        candidate = clean_concept_title_text(prefix_match.group(1))
        if candidate:
            return candidate

    return cleaned


def section_path_parts_from_claim_record(claim_record: dict) -> list[str]:
    for source_ref in claim_record.get("source_refs", []):
        parts = source_ref.get("section_path_parts")
        if isinstance(parts, list):
            cleaned_parts = [normalize_question_style_concept_label(str(part)) for part in parts if str(part).strip()]
            cleaned_parts = [part for part in cleaned_parts if part]
            if cleaned_parts:
                return cleaned_parts
        section_path = source_ref.get("section_path", "")
        if not section_path:
            continue
        parsed = parse_section_path(section_path)
        parts = [
            normalize_question_style_concept_label(part)
            for part in parsed.get("section_path_parts", [])
            if part
        ]
        parts = [part for part in parts if part]
        if parts:
            return parts
    return []


def section_label_is_meaningful_context(label: str) -> bool:
    cleaned = normalize_question_style_concept_label(label)
    if not cleaned or is_generic_concept_label(cleaned):
        return False
    if text_is_question_like(cleaned):
        return False
    if len(cleaned) >= 18 and claim_has_standalone_predicate(cleaned):
        return False
    if any(marker in cleaned for marker in ("：", ":", "。", "？", "?")) and len(cleaned) >= 10:
        return False
    return True


def build_hierarchical_section_label(section_parts: list[str], max_parts: int = 3) -> str:
    if not section_parts:
        return ""
    meaningful_parts = [part for part in section_parts if section_label_is_meaningful_context(part)]
    if not meaningful_parts:
        meaningful_parts = [normalize_question_style_concept_label(part) for part in section_parts if part]
        meaningful_parts = [part for part in meaningful_parts if part]
    selected_parts = meaningful_parts[-max_parts:]
    if len(selected_parts) <= 1:
        return selected_parts[0] if selected_parts else ""
    return " / ".join(selected_parts)


def extract_primary_section_label(claim_record: dict) -> str:
    # 对概念页命名来说，section_path 往往比整句 claim 更接近“主题名”。
    parts = section_path_parts_from_claim_record(claim_record)
    if not parts:
        return ""
    return build_hierarchical_section_label(parts)


def choose_group_topic_label(claim_records: list[dict]) -> str:
    # 概念页首先要回答“这一组 claim 到底在讲什么主题”。
    # 这里优先采用来源 section label 的共识，而不是直接相信某一条 claim 的可读性。
    label_scores: dict[str, float] = {}

    for claim_record in claim_records:
        label = extract_primary_section_label(claim_record)
        if not label or is_generic_concept_label(label):
            continue
        label_scores[label] = label_scores.get(label, 0.0) + max(1, len(claim_record.get("source_ids", [])))

    if not label_scores:
        return ""

    ranked = sorted(
        label_scores.items(),
        key=lambda item: (item[1], len(build_claim_similarity_tokens(item[0])), len(item[0])),
        reverse=True,
    )
    return ranked[0][0]


def collect_section_label_aliases(claim_records: list[dict]) -> list[str]:
    aliases: list[str] = []
    for claim_record in claim_records:
        parts = section_path_parts_from_claim_record(claim_record)
        if not parts:
            continue
        candidates = [
            build_hierarchical_section_label(parts),
            normalize_question_style_concept_label(parts[-1]),
            " > ".join(parts),
        ]
        for candidate in candidates:
            cleaned = clean_concept_title_text(candidate)
            if cleaned and cleaned not in aliases:
                aliases.append(cleaned)
    return aliases


def is_generic_concept_label(label: str) -> bool:
    # 有些 section label 太泛，比如“文档开始”“sample”“表格 1”，单独拿来做页面名会很弱。
    normalized = clean_concept_title_text(label).lower()
    if normalized in {"", "文档开始", "sample"}:
        return True
    generic_exact_values = {
        "示例", "总结", "小结", "说明", "原因", "背景", "方法", "流程", "步骤",
        "注意", "补充", "附录", "表格", "代码", "引用", "问题", "状态", "初始化",
        "别名", "为什么", "如何", "怎么做", "做法", "概述", "介绍",
    }
    if normalized in generic_exact_values:
        return True
    if len(normalized) <= 1 and re.search(r"[\u4e00-\u9fff]", normalized):
        return True
    if re.fullmatch(r"(?:问题|示例|总结|步骤|方法)\s*\d*", normalized):
        return True
    if re.fullmatch(r"[一二三四五六七八九十]+[、.]?.{0,2}", normalized):
        return True
    if re.fullmatch(r"表格\s*\d+", normalized):
        return True
    return False


def concept_title_is_whitelisted_short_label(label: str) -> bool:
    normalized = clean_concept_title_text(label)
    if not normalized:
        return False
    if normalized in {"AI", "RAG", "MCP", "CLI", "SDK", "API", "Tauri", "React", "Rust", "BM25"}:
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9._+-]{2,8}", normalized))


def concept_title_quality_details(
    title: str,
    canonical_claim: dict,
    claim_records: list[dict],
    preferred_section_label: str = "",
) -> dict:
    normalized_title = clean_concept_title_text(title)
    normalized_lower = normalized_title.lower()
    section_label = preferred_section_label or extract_primary_section_label(canonical_claim)
    section_label_normalized = clean_concept_title_text(section_label)
    claim_text = clean_claim_candidate_text(canonical_claim.get("text", ""))
    source_ids = {
        source_id
        for claim_record in claim_records
        for source_id in claim_record.get("source_ids", [])
    }
    reasons: list[str] = []
    score = 0

    if not normalized_title:
        reasons.append("empty_title")
        score -= 10

    if is_generic_concept_label(normalized_title):
        reasons.append("generic_title")
        score -= 8
    else:
        score += 3

    if len(normalized_title) <= 1 and not concept_title_is_whitelisted_short_label(normalized_title):
        reasons.append("too_short")
        score -= 10
    elif len(normalized_title) <= 3 and not concept_title_is_whitelisted_short_label(normalized_title):
        reasons.append("very_short")
        score -= 4
    elif len(normalized_title) >= 4:
        score += 1

    if concept_title_is_whitelisted_short_label(normalized_title):
        reasons.append("short_whitelisted")
        score += 4

    if claim_has_standalone_predicate(claim_text):
        score += 2
    else:
        reasons.append("claim_without_predicate")
        score -= 2

    if claim_starts_with_dependent_prefix(claim_text):
        reasons.append("dependent_prefix_claim")
        score -= 3

    if text_is_question_like(claim_text):
        reasons.append("question_like_claim")
        score -= 4

    if claim_is_topic_shell_text(canonical_claim, normalized_title):
        reasons.append("topic_shell_claim")
        score -= 6

    topic_alignment = claim_topic_alignment_score(canonical_claim, normalized_title)
    if topic_alignment >= 8:
        score += 4
    elif topic_alignment >= 4:
        score += 2
    else:
        reasons.append("low_topic_alignment")
        score -= 3

    if section_label_normalized and normalized_lower == section_label_normalized.lower():
        score += 1
    if section_label_normalized and is_generic_concept_label(section_label_normalized):
        reasons.append("generic_section_label")
        score -= 4

    if len(claim_records) >= 2:
        score += 2
    else:
        reasons.append("single_claim_only")
        score -= 1

    if len(source_ids) >= 2:
        reasons.append("cross_source_support")
        score += 4
    else:
        reasons.append("single_source_only")
        score -= 2

    if canonical_claim.get("claim_type") == "definition":
        score += 2

    hard_reject_reasons = {"empty_title", "generic_title", "too_short", "question_like_claim"}
    classification = "strong"
    if any(reason in hard_reject_reasons for reason in reasons):
        classification = "reject"
    elif score < 6:
        classification = "gray"

    return {
        "title": normalized_title,
        "score": score,
        "classification": classification,
        "reasons": reasons,
        "topic_alignment": topic_alignment,
        "section_label": section_label_normalized,
        "source_count": len(source_ids),
        "claim_count": len(claim_records),
    }


def load_concept_quality_review_config(config: dict) -> dict:
    render_config = load_page_render_config(config, "concept_update")
    return {
        "mode": render_config.get("mode"),
        "command": render_config.get("command", []),
        "timeout_seconds": render_config.get("timeout_seconds", 20),
    }


def run_llm_assisted_concept_title_review(
    target: Path,
    review_config: dict,
    title: str,
    canonical_claim: dict,
    claim_records: list[dict],
    preferred_section_label: str = "",
) -> dict | None:
    if review_config.get("mode") != "llm_assisted":
        return None
    command = review_config.get("command", [])
    if not command:
        return None

    payload = {
        "task": "review_concept_candidate",
        "candidate_title": title,
        "preferred_section_label": preferred_section_label,
        "canonical_claim": {
            "claim_id": canonical_claim.get("claim_id"),
            "text": canonical_claim.get("text"),
            "claim_type": canonical_claim.get("claim_type"),
        },
        "supporting_claims": [
            {
                "claim_id": claim_record.get("claim_id"),
                "text": claim_record.get("text"),
                "claim_type": claim_record.get("claim_type"),
                "section_label": extract_primary_section_label(claim_record),
                "source_count": len(claim_record.get("source_ids", [])),
            }
            for claim_record in claim_records[:6]
        ],
        "instructions": (
            "Judge whether this title is a valid reusable concept title or just a structural heading. "
            "If invalid, suggest a better concept title when the evidence clearly supports one. "
            "Return strict JSON only."
        ),
    }

    try:
        completed = subprocess.run(
            command,
            cwd=target,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=review_config.get("timeout_seconds", 20),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    result = parse_hook_process_result(command, completed)
    if not isinstance(result, dict):
        return None

    suggested_title = clean_concept_title_text(result.get("suggested_title", ""))
    decision = str(result.get("decision", "") or "").strip().lower()
    reason = str(result.get("reason", "") or "").strip()
    confidence = result.get("confidence", 0.0)
    if decision not in {"accept", "reject", "rename"}:
        return None
    if suggested_title and is_generic_concept_label(suggested_title):
        suggested_title = ""
    return {
        "decision": decision,
        "suggested_title": suggested_title,
        "reason": reason,
        "confidence": float(confidence) if isinstance(confidence, (int, float)) else 0.0,
    }


def extract_markdown_table_rows(text: str) -> list[list[str]]:
    # 当 claim 来自表格时，原始文本里常带 Markdown 表格；这里抽出单元格以便后续命名。
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if "|" not in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if all(re.fullmatch(r"-+", cell or "") for cell in cells):
            continue
        rows.append([cell for cell in cells if cell])
    return rows


def extract_concept_phrase_from_table_rows(rows: list[list[str]]) -> str:
    # 表格里的“最后一行有效数据”通常最像当前 chunk 的具体陈述。
    if not rows:
        return ""
    data_rows = rows[1:] if len(rows) >= 2 else rows
    if not data_rows:
        data_rows = rows
    last_row = data_rows[-1]
    generic_headers = {"字段", "键", "值", "说明", "项目", "claim"}
    if len(last_row) >= 2:
        head, tail = last_row[0], last_row[1]
        if head in generic_headers:
            return clean_concept_title_text(tail)
        if head.lower().startswith("工作表"):
            return clean_concept_title_text(tail)
        return clean_concept_title_text(f"{head} {tail}")
    return clean_concept_title_text(" ".join(last_row))


def extract_concept_phrase_from_claim(claim_text: str, section_label: str) -> str:
    # 如果 section label 不够具体，就再从 claim 本体里提一段更适合当标题的短语。
    table_rows = extract_markdown_table_rows(claim_text)
    if table_rows:
        phrase = extract_concept_phrase_from_table_rows(table_rows)
        if phrase:
            return phrase

    plain_text = clean_concept_title_text(markdown_to_plain_text(claim_text))
    if section_label and plain_text.lower().startswith(section_label.lower()):
        plain_text = clean_concept_title_text(plain_text[len(section_label):])

    # 句子型 claim 先截到第一个停顿点，避免整句都变成标题。
    pieces = re.split(r"[。！？!?；;:：]", plain_text, maxsplit=1)
    candidate = clean_concept_title_text(pieces[0] if pieces else plain_text)
    return candidate


def build_concept_title(canonical_claim: dict, preferred_section_label: str = "") -> str:
    # 概念页标题优先用 section label，必要时再拼一个来自 claim 的补充短语。
    section_label = preferred_section_label or extract_primary_section_label(canonical_claim)
    claim_phrase = extract_concept_phrase_from_claim(canonical_claim.get("text", ""), section_label)

    if section_label and not is_generic_concept_label(section_label):
        if section_label.startswith("工作表") and claim_phrase and claim_phrase not in section_label:
            return shorten_title_text(clean_concept_title_text(f"{section_label} - {claim_phrase}"), limit=28)
        return shorten_title_text(section_label, limit=28)

    if section_label.startswith("表格") and claim_phrase:
        if claim_phrase.lower().startswith(section_label.lower()):
            claim_phrase = clean_concept_title_text(claim_phrase[len(section_label):])
        if claim_phrase:
            return shorten_title_text(clean_concept_title_text(f"{section_label} - {claim_phrase}"), limit=28)

    if section_label and claim_phrase:
        return shorten_title_text(clean_concept_title_text(f"{section_label} - {claim_phrase}"), limit=28)
    if claim_phrase:
        return shorten_title_text(claim_phrase, limit=28)
    return shorten_title_text(clean_concept_title_text(canonical_claim.get("text", "")), limit=28)


def build_concept_canonical_key(title: str) -> str:
    # canonical key 给后续 alias、redirect、检索归一化用，尽量保持短而稳定。
    cleaned = clean_concept_title_text(title)
    if not cleaned:
        return "concept"
    compact = sanitize_source_key(cleaned)
    return compact or "concept"


def claim_topic_alignment_score(claim_record: dict, group_topic_label: str = "") -> float:
    # 代表陈述首先应和页面主题对齐，其次才是“读起来像一句完整的话”。
    if not group_topic_label:
        return 0.0

    normalized_topic = clean_concept_title_text(group_topic_label).lower()
    if not normalized_topic:
        return 0.0

    claim_text = clean_claim_candidate_text(claim_record.get("text", ""))
    claim_text_lower = claim_text.lower()
    section_label = extract_primary_section_label(claim_record)
    section_label_lower = clean_concept_title_text(section_label).lower()
    topic_tokens = build_claim_similarity_tokens(group_topic_label)
    claim_tokens = build_claim_similarity_tokens(claim_text)
    overlap_ratio, _, shared_token_count = compute_weighted_token_overlap(topic_tokens, claim_tokens)

    score = overlap_ratio * 10.0 + float(shared_token_count)
    if section_label_lower == normalized_topic:
        score += 8.0
    elif section_label_lower and normalized_topic in section_label_lower:
        score += 4.0
    if claim_text_lower.startswith(normalized_topic):
        score += 6.0
    elif normalized_topic in claim_text_lower:
        score += 3.0
    return score


def claim_is_topic_shell_text(claim_record: dict, group_topic_label: str = "") -> bool:
    # 有些 claim 实际上只是 section 标题本身，被抽出来后并没有承载独立结论。
    # 这类“壳句”适合留作 supporting context，但不应抢占代表陈述。
    cleaned = clean_claim_candidate_text(claim_record.get("text", ""))
    if not cleaned:
        return False

    normalized_cleaned = cleaned.lower()
    candidate_labels = []
    section_label = extract_primary_section_label(claim_record)
    if section_label:
        candidate_labels.append(clean_concept_title_text(section_label).lower())
    if group_topic_label:
        candidate_labels.append(clean_concept_title_text(group_topic_label).lower())

    candidate_labels = [label for label in candidate_labels if label]
    if not candidate_labels:
        return False
    if normalized_cleaned not in candidate_labels:
        return False
    return not claim_has_standalone_predicate(cleaned)


def claim_record_readability_score(claim_record: dict, group_topic_label: str = "") -> int:
    text = claim_record.get("text", "")
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return -10

    score = 0
    topic_alignment = claim_topic_alignment_score(claim_record, group_topic_label)
    if topic_alignment >= 12:
        score += 5
    elif topic_alignment >= 8:
        score += 3
    elif topic_alignment >= 4:
        score += 1
    if claim_record.get("claim_type") == "definition":
        score += 2
    if not claim_starts_with_dependent_prefix(cleaned):
        score += 2
    if claim_has_standalone_predicate(cleaned):
        score += 1
    if claim_is_definition_like_phrase(cleaned):
        score += 3

    section_label = extract_primary_section_label(claim_record)
    if section_label and cleaned.lower().startswith(section_label.lower()):
        score += 2

    if 16 <= len(cleaned) <= 72:
        score += 1
    elif len(cleaned) > 120:
        score -= 1

    if claim_starts_with_dependent_prefix(cleaned):
        score -= 3
    if claim_starts_with_meta_prefix(cleaned):
        score -= 3
    if claim_is_topic_shell_text(claim_record, group_topic_label):
        score -= 6
    return score


def claim_record_rank_key(claim_record: dict, group_topic_label: str = "") -> tuple:
    text = claim_record.get("text", "")
    is_topic_shell = claim_is_topic_shell_text(claim_record, group_topic_label)
    return (
        0 if is_topic_shell else 1,
        claim_topic_alignment_score(claim_record, group_topic_label),
        len(claim_record.get("source_ids", [])),
        len(claim_record.get("source_refs", [])),
        claim_record_readability_score(claim_record, group_topic_label),
        -abs(len(text) - 42),
        len(text),
    )


def build_display_claim_text(claim_record: dict, concept_title: str = "") -> str:
    raw_text = markdown_to_plain_text(claim_record.get("text", ""))
    cleaned = clean_claim_candidate_text(raw_text)
    if not cleaned:
        return raw_text.strip()
    return cleaned


def choose_canonical_claim(claim_records: list[dict], group_topic_label: str = "") -> dict:
    # 一组 claim 需要选一个“代表陈述”，后面会用它来命名页面和生成摘要。
    ranked = sorted(
        claim_records,
        key=lambda item: claim_record_rank_key(item, group_topic_label),
        reverse=True,
    )
    return ranked[0]


def should_generate_concept_page(claim_records: list[dict]) -> bool:
    # 概念页不必给每条 claim 都生成一份。
    # V1 先优先保留三类更有价值的候选：
    # 1. 多条相似 claim 汇聚到一起；
    # 2. 单条 claim 但有多个来源支撑；
    # 3. 单条 claim 但表达完整、主题明确，值得先沉淀成主题入口。
    concept_claim_records = filter_claim_records_for_concept_path(claim_records)
    if not concept_claim_records:
        return False

    source_ids = {
        source_id
        for claim_record in concept_claim_records
        for source_id in claim_record.get("source_ids", [])
    }
    if len(concept_claim_records) >= 2:
        return True
    if len(source_ids) >= 2:
        return True
    canonical_claim = choose_canonical_claim(concept_claim_records, choose_group_topic_label(concept_claim_records))
    section_label = choose_group_topic_label(concept_claim_records)
    concept_title = build_concept_title(canonical_claim, preferred_section_label=choose_group_topic_label(concept_claim_records))
    quality = concept_title_quality_details(
        title=concept_title,
        canonical_claim=canonical_claim,
        claim_records=concept_claim_records,
        preferred_section_label=section_label,
    )
    claim_text = canonical_claim.get("text", "")
    cleaned_claim_text = clean_claim_candidate_text(claim_text)
    # 一些明显是“转换占位提示”的文本先不提升成概念页，避免 Wiki 被环境提示刷屏。
    if any(marker in claim_text for marker in ("当前环境缺少", "当前环境未启用", "仅生成占位", "估计页数:")):
        return False
    if text_is_iso_date_label(section_label) or text_is_iso_date_label(cleaned_claim_text):
        return True
    if quality["classification"] == "reject":
        return False
    if text_is_iso_date_label(cleaned_claim_text):
        return True
    if canonical_claim.get("claim_type") == "definition" and len(cleaned_claim_text) >= 14:
        return True
    if section_label and not is_generic_concept_label(section_label) and len(section_label) >= 4:
        return True
    concept_candidate_score = claim_concept_candidate_score(canonical_claim)
    if concept_candidate_score >= 0.75:
        return True
    return len(cleaned_claim_text) >= 18 and concept_candidate_score >= 0.3 and claim_can_stand_alone(cleaned_claim_text)


def resolve_concept_title_candidate(
    target: Path,
    config: dict,
    canonical_claim: dict,
    claim_records: list[dict],
    preferred_section_label: str = "",
) -> tuple[str, dict]:
    title = build_concept_title(canonical_claim, preferred_section_label=preferred_section_label)
    quality = concept_title_quality_details(
        title=title,
        canonical_claim=canonical_claim,
        claim_records=claim_records,
        preferred_section_label=preferred_section_label,
    )

    llm_review: dict | None = None
    if quality["classification"] == "gray":
        llm_review = run_llm_assisted_concept_title_review(
            target=target,
            review_config=load_concept_quality_review_config(config),
            title=title,
            canonical_claim=canonical_claim,
            claim_records=claim_records,
            preferred_section_label=preferred_section_label,
        )
        if llm_review and llm_review.get("decision") == "rename" and llm_review.get("suggested_title"):
            title = llm_review["suggested_title"]
            quality = concept_title_quality_details(
                title=title,
                canonical_claim=canonical_claim,
                claim_records=claim_records,
                preferred_section_label=preferred_section_label,
            )
        elif llm_review and llm_review.get("decision") == "reject":
            quality = dict(quality)
            quality["classification"] = "reject"
            quality["reasons"] = list(quality.get("reasons", [])) + ["llm_rejected_gray_candidate"]
        elif llm_review and llm_review.get("decision") == "accept":
            quality = dict(quality)
            quality["classification"] = "strong"
            quality["reasons"] = list(quality.get("reasons", [])) + ["llm_accepted_gray_candidate"]

    quality = dict(quality)
    quality["llm_review"] = llm_review
    if quality["classification"] == "reject":
        fallback_candidates = [
            extract_concept_phrase_from_claim(canonical_claim.get("text", ""), ""),
            preferred_section_label if text_is_iso_date_label(preferred_section_label) else "",
            clean_concept_title_text(shorten_title_text(markdown_to_plain_text(canonical_claim.get("text", "")), limit=28)),
        ]
        for fallback_title in fallback_candidates:
            fallback_title = clean_concept_title_text(fallback_title)
            if not fallback_title:
                continue
            if is_generic_concept_label(fallback_title) and not text_is_iso_date_label(fallback_title):
                continue
            title = shorten_title_text(fallback_title, limit=28)
            quality = concept_title_quality_details(
                title=title,
                canonical_claim=canonical_claim,
                claim_records=claim_records,
                preferred_section_label=preferred_section_label,
            )
            quality = dict(quality)
            quality["llm_review"] = llm_review
            quality["fallback_title_applied"] = True
            break
    return title, quality


def aggregate_source_refs_for_page(claim_records: list[dict]) -> list[dict]:
    # 页面层只保留“按来源聚合后的证据索引”，正文再去展开更细的 claim / chunk 关系。
    aggregated: dict[str, dict] = {}
    for claim_record in claim_records:
        for source_ref in claim_record.get("source_refs", []):
            source_id = source_ref["source_id"]
            if source_id not in aggregated:
                aggregated[source_id] = {
                    "source_id": source_id,
                    "source_path": source_ref["source_path"],
                    "chunk_ids": [],
                    "claim_ids": [],
                    "chunks": [],
                }
            if source_ref["chunk_id"] not in aggregated[source_id]["chunk_ids"]:
                aggregated[source_id]["chunk_ids"].append(source_ref["chunk_id"])
                aggregated[source_id]["chunks"].append({
                    "chunk_id": source_ref["chunk_id"],
                    "section_path": source_ref.get("section_path"),
                    "start_line": source_ref.get("start_line"),
                    "end_line": source_ref.get("end_line"),
                })
            append_unique(aggregated[source_id]["claim_ids"], claim_record["claim_id"])
    for record in aggregated.values():
        record["chunks"].sort(
            key=lambda item: (
                item.get("start_line") if item.get("start_line") is not None else math.inf,
                item.get("chunk_id", ""),
            )
        )
    return sorted(aggregated.values(), key=lambda item: item["source_id"])


def aggregate_source_refs_for_pages(page_records: list[dict]) -> list[dict]:
    # 更高层页面（如 overview）复用下层页面已经整理过的 source_refs，
    # 避免再次按 claim 全量回扫。
    aggregated: dict[str, dict] = {}
    for page_record in page_records:
        for source_ref in page_record.get("source_refs", []):
            source_id = source_ref["source_id"]
            if source_id not in aggregated:
                aggregated[source_id] = {
                    "source_id": source_id,
                    "source_path": source_ref["source_path"],
                    "chunk_ids": [],
                    "claim_ids": [],
                    "chunks": [],
                }
            for chunk_id in source_ref.get("chunk_ids", []):
                if chunk_id not in aggregated[source_id]["chunk_ids"]:
                    aggregated[source_id]["chunk_ids"].append(chunk_id)
            for claim_id in source_ref.get("claim_ids", []):
                append_unique(aggregated[source_id]["claim_ids"], claim_id)
            for chunk_ref in source_ref.get("chunks", []):
                if any(item.get("chunk_id") == chunk_ref.get("chunk_id") for item in aggregated[source_id]["chunks"]):
                    continue
                aggregated[source_id]["chunks"].append({
                    "chunk_id": chunk_ref.get("chunk_id"),
                    "section_path": chunk_ref.get("section_path"),
                    "start_line": chunk_ref.get("start_line"),
                    "end_line": chunk_ref.get("end_line"),
                })
    for record in aggregated.values():
        record["chunks"].sort(
            key=lambda item: (
                item.get("start_line") if item.get("start_line") is not None else math.inf,
                item.get("chunk_id", ""),
            )
        )
    return sorted(aggregated.values(), key=lambda item: item["source_id"])


def markdown_link_between_pages(from_page: Path, to_page: Path) -> str:
    # 页面正文里尽量使用相对链接，这样整个工作区换目录后链接仍然有效。
    relative = os.path.relpath(to_page, start=from_page.parent)
    return quote(relative.replace(os.sep, "/"), safe="/._-~")


def markdown_link_target(path: str) -> str:
    # 目录页链接也需要对空格等字符做转义，避免某些 Markdown 查看器截断路径。
    return quote(path.replace(os.sep, "/"), safe="/._-~")


def collect_source_summary_pages_for_claims(claim_records: list[dict], page_records_by_id: dict[str, dict]) -> list[dict]:
    # 概念页里最需要引用的是“来源摘要页”，因此这里把相关来源页单独筛出来。
    source_pages: list[dict] = []
    seen_page_ids: set[str] = set()
    for claim_record in claim_records:
        for page_id in claim_record.get("page_ids", []):
            page_record = page_records_by_id.get(page_id)
            if page_record is None or page_record.get("type") != "source-summary":
                continue
            if page_id in seen_page_ids:
                continue
            seen_page_ids.add(page_id)
            source_pages.append(page_record)
    return sorted(source_pages, key=lambda item: item.get("title", "").lower())


def collect_review_ids_for_claims(claim_ids: list[str], review_records: list[dict]) -> list[str]:
    # review 记录本身是“人工裁决入口”，页面记录里也要能反查到它们。
    claim_id_set = set(claim_ids)
    matched: list[str] = []
    for review_record in review_records:
        if not is_actionable_review_record(review_record):
            continue
        candidate_claim_ids = set(review_record.get("candidate_claim_ids", []))
        if claim_id_set & candidate_claim_ids:
            matched.append(review_record["review_id"])
    return sorted(set(matched))


def find_live_page_by_canonical_id_and_type(
    page_records_by_id: dict[str, dict],
    canonical_id: str,
    page_type: str,
) -> dict | None:
    for page_record in page_records_by_id.values():
        if not is_live_page_record(page_record):
            continue
        if page_record.get("canonical_id") != canonical_id:
            continue
        if page_record.get("type") != page_type:
            continue
        return page_record
    return None


def render_claim_as_sentence(claim_record: dict, concept_title: str = "") -> str:
    sentence = build_display_claim_text(claim_record, concept_title).strip()
    if not sentence:
        return ""
    if sentence.endswith(("。", "！", "？", ".", "!", "?")):
        return sentence
    return f"{sentence}。"


def extract_first_sentence(text: str) -> str:
    cleaned = markdown_to_plain_text(text).strip()
    if not cleaned:
        return ""
    match = re.split(r"(?<=[。！？.!?])\s+", cleaned, maxsplit=1)
    return match[0].strip() if match else cleaned


def split_text_into_sentences(text: str) -> list[str]:
    cleaned = markdown_to_plain_text(text).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[。！？.!?])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def collect_page_claim_records(page_record: dict, claim_records_by_id: dict[str, dict]) -> list[dict]:
    return [
        claim_records_by_id[claim_id]
        for claim_id in page_record.get("claim_ids", [])
        if claim_id in claim_records_by_id
    ]


def count_claim_types(claim_records: list[dict]) -> Counter:
    return Counter(
        claim_record.get("claim_type", "unknown")
        for claim_record in claim_records
    )


def concept_page_overview_rank_key(page_record: dict, claim_records_by_id: dict[str, dict]) -> tuple[int, int, int, str]:
    claim_records = collect_page_claim_records(page_record, claim_records_by_id)
    claim_type_counts = count_claim_types(claim_records)
    operational_signal = sum(
        claim_type_counts.get(claim_type, 0)
        for claim_type in {"procedure", "warning", "comparison", "causal", "evaluation"}
    )
    return (
        len(page_record.get("source_refs", [])),
        len(page_record.get("claim_ids", [])),
        operational_signal,
        page_record.get("title", "").lower(),
    )


def overview_title_parts(page_record: dict) -> list[str]:
    title = str(page_record.get("title", "")).strip()
    if not title:
        return []
    return [part.strip() for part in title.split("/") if part.strip()]


def overview_theme_family_key(page_record: dict) -> str:
    parts = overview_title_parts(page_record)
    if len(parts) >= 2:
        return " / ".join(parts[:2]).lower()
    if parts:
        return parts[0].lower()
    return str(page_record.get("page_id", "")).strip().lower()


def overview_theme_representativeness_score(
    page_record: dict,
    claim_records_by_id: dict[str, dict],
) -> tuple[int, int, int, int, str]:
    claim_records = collect_page_claim_records(page_record, claim_records_by_id)
    claim_type_counts = count_claim_types(claim_records)
    foundational_signal = sum(
        claim_type_counts.get(claim_type, 0)
        for claim_type in {"definition", "fact"}
    )
    operational_signal = sum(
        claim_type_counts.get(claim_type, 0)
        for claim_type in {"procedure", "warning", "comparison", "causal", "evaluation"}
    )
    title_parts = overview_title_parts(page_record)
    source_ref_count = len(page_record.get("source_refs", []))
    claim_count = len(page_record.get("claim_ids", []))
    # 更少的标题层级更像工作区入口主题；coverage 仍然保留为强信号。
    hierarchy_breadth = -len(title_parts) if title_parts else 0
    semantic_breadth = max(foundational_signal, operational_signal)
    return (
        hierarchy_breadth,
        source_ref_count,
        semantic_breadth,
        claim_count,
        page_record.get("title", "").lower(),
    )


def format_overview_title_phrase(titles: list[str]) -> str:
    cleaned_titles = [str(title).strip() for title in titles if str(title).strip()]
    if not cleaned_titles:
        return ""
    if len(cleaned_titles) == 1:
        return cleaned_titles[0]
    if len(cleaned_titles) == 2:
        return f"{cleaned_titles[0]} 和 {cleaned_titles[1]}"
    return "、".join(cleaned_titles[:-1]) + f" 和 {cleaned_titles[-1]}"


def format_overview_theme_count_phrase(count: int) -> str:
    small_count_labels = {
        1: "一个",
        2: "两个",
        3: "三个",
        4: "四个",
        5: "五个",
        6: "六个",
    }
    return small_count_labels.get(count, f"{count} 个")


def summarize_concept_page_for_overview(page_record: dict) -> str:
    return summarize_concept_page_for_overview_helper(
        page_record=page_record,
        extract_first_sentence=extract_first_sentence,
    )


def build_workspace_overview_key_theme_rows(
    concept_pages: list[dict],
    claim_records_by_id: dict[str, dict],
    limit: int = 10,
) -> list[dict]:
    return build_workspace_overview_key_theme_rows_helper(
        concept_pages=concept_pages,
        claim_records_by_id=claim_records_by_id,
        extract_first_sentence=extract_first_sentence,
        limit=limit,
    )


def build_workspace_source_coverage_rows(
    concept_pages: list[dict],
    source_pages_by_id: dict[str, dict],
    limit: int = 8,
) -> list[dict]:
    return build_workspace_source_coverage_rows_helper(
        concept_pages=concept_pages,
        source_pages_by_id=source_pages_by_id,
        expected_source_summary_page_id=expected_source_summary_page_id,
        append_unique=append_unique,
        limit=limit,
    )


def build_workspace_overview_summary_text(
    concept_pages: list[dict],
    source_refs: list[dict],
    claim_records_by_id: dict[str, dict],
) -> str:
    key_theme_rows = build_workspace_overview_key_theme_rows(
        concept_pages=concept_pages,
        claim_records_by_id=claim_records_by_id,
        limit=3,
    )
    return build_workspace_overview_summary_text_helper(
        concept_pages=concept_pages,
        source_refs=source_refs,
        key_theme_rows=key_theme_rows,
    )


def build_workspace_overview_summary_grounding_references(
    concept_pages: list[dict],
    source_refs: list[dict],
    claim_records_by_id: dict[str, dict],
) -> list[str]:
    claim_ids = {
        claim_id
        for page_record in concept_pages
        for claim_id in page_record.get("claim_ids", [])
    }
    key_theme_rows = build_workspace_overview_key_theme_rows(
        concept_pages=concept_pages,
        claim_records_by_id=claim_records_by_id,
        limit=3,
    )
    key_theme_titles = [
        item["page_record"].get("title", "")
        for item in key_theme_rows
        if item["page_record"].get("title")
    ]
    operational_theme_count = sum(
        1 for item in key_theme_rows if item["theme_kind"] == "operational"
    )
    references = [
        build_workspace_overview_summary_text(
            concept_pages=concept_pages,
            source_refs=source_refs,
            claim_records_by_id=claim_records_by_id,
        ),
        f"这些主题当前覆盖 {len(claim_ids)} 条稳定 Claim 和 {len(source_refs)} 个来源。",
    ]
    if key_theme_titles:
        key_theme_text = "、".join(key_theme_titles[:3])
        references.append(f"{key_theme_text} 是当前工作区里已经沉淀出的稳定主题。")
        readable_title_text = format_overview_title_phrase(key_theme_titles[:3])
        if len(key_theme_titles) == 1:
            references.append(f"这个工作区主要围绕 {readable_title_text} 这个稳定主题展开。")
        else:
            references.append(
                f"这个工作区主要围绕 {readable_title_text} "
                f"{format_overview_theme_count_phrase(len(key_theme_titles))}稳定主题展开。"
            )
            references.append(f"工作区当前沉淀出的稳定主题包括 {readable_title_text}。")
    if operational_theme_count:
        references.append(f"其中有 {operational_theme_count} 个主题带有更强的操作或判断信号。")
    else:
        references.append("这些主题目前以基础概念和事实定义为主。")
    for page_record in concept_pages:
        references.append(page_record.get("title", ""))
        references.append(page_record.get("summary", ""))
    return [reference for reference in references if str(reference).strip()]


def text_is_grounded_in_reference(
    text: str,
    reference_text: str,
    *,
    min_overlap: int = 2,
    min_ratio: float = 0.35,
) -> bool:
    cleaned = markdown_to_plain_text(str(text)).strip()
    reference_cleaned = markdown_to_plain_text(str(reference_text)).strip()
    if not cleaned or not reference_cleaned:
        return False
    normalized = normalize_claim_text(cleaned)
    reference_normalized = normalize_claim_text(reference_cleaned)
    if reference_normalized and (reference_normalized in normalized or normalized in reference_normalized):
        return True

    grounded_tokens = set(tokenize_for_search(reference_cleaned))
    candidate_tokens = set(tokenize_for_search(cleaned))
    if not candidate_tokens or not grounded_tokens:
        return False

    overlap = grounded_tokens.intersection(candidate_tokens)
    if len(overlap) < min_overlap:
        return False
    return (len(overlap) / len(candidate_tokens)) >= min_ratio


def strip_overview_rewrite_framing(text: str) -> str:
    cleaned = markdown_to_plain_text(text).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s*\(claims=\d+\s*,\s*sources=\d+\)\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("|", " ")
    cleaned = re.sub(
        r"^如果你[^，。；:：]{0,32}[，,:：]\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"[。.!?]+$", "", cleaned)
    cleaned = re.sub(
        r"^这个主题(?:会|将)?(?:解释|说明|介绍|展示|聚焦|围绕|讨论|主要讲)(?:了)?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"^如果你(?:更)?想[^，。；:：]{0,24}?(?:先读|先看|再看|接着读|优先从)\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"^(?:建议|可以|可先|优先)?\s*(?:先读|先看|再看|接着读|优先从|从)\s*", "", cleaned)
    cleaned = re.sub(
        r"(?:\s*(?:主题|页面|页))?(?:\s*(?:往下钻|继续往下钻|开始|入手|了解))?\s*$",
        "",
        cleaned,
    )
    return cleaned.strip(" -:;,.!?。！？；：，、()[]{}\"'")


def llm_assisted_rewrite_text_is_grounded(text: str, claim_record: dict, title: str) -> bool:
    cleaned = markdown_to_plain_text(str(text)).strip()
    if not cleaned:
        return False
    normalized = normalize_claim_text(cleaned)
    claim_text = claim_record.get("text", "")
    claim_normalized = normalize_claim_text(claim_text)
    if not claim_normalized:
        return False
    if claim_normalized in normalized or normalized in claim_normalized:
        return True

    grounded_tokens = set(tokenize_for_search(claim_text))
    grounded_tokens.update(tokenize_for_search(title))
    candidate_tokens = set(tokenize_for_search(cleaned))
    if not candidate_tokens or not grounded_tokens:
        return False

    overlap = grounded_tokens.intersection(candidate_tokens)
    if len(overlap) < 2:
        return False
    return (len(overlap) / len(candidate_tokens)) >= 0.35


def llm_assisted_rewrite_text_is_grounded_in_page(text: str, page_record: dict) -> bool:
    cleaned = markdown_to_plain_text(str(text)).strip()
    if not cleaned:
        return False
    page_summary = markdown_to_plain_text(page_record.get("summary", "")).strip()
    title = page_record.get("title", "")
    allowed_text = " ".join(part for part in [title, page_summary] if part).strip()
    if text_is_grounded_in_reference(cleaned, allowed_text):
        return True

    stripped = strip_overview_rewrite_framing(cleaned)
    normalized_title = normalize_claim_text(title)
    stripped_normalized = normalize_claim_text(stripped)
    if normalized_title and stripped_normalized in {
        normalized_title,
        normalize_claim_text(f"{title} 主题"),
        normalize_claim_text(f"{title} 页面"),
    }:
        return True
    if stripped and stripped != cleaned and text_is_grounded_in_reference(stripped, allowed_text):
        return True
    return False


def llm_assisted_rewrite_text_is_grounded_in_pages(text: str, page_records: list[dict]) -> bool:
    return any(
        llm_assisted_rewrite_text_is_grounded_in_page(text, page_record)
        for page_record in page_records
    )


def llm_assisted_overview_summary_is_grounded(
    text: str,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
) -> bool:
    sentences = split_text_into_sentences(text)
    if not sentences:
        return False
    source_refs = aggregate_source_refs_for_pages(page_records)
    reference_texts = build_workspace_overview_summary_grounding_references(
        concept_pages=page_records,
        source_refs=source_refs,
        claim_records_by_id=claim_records_by_id,
    )
    if not reference_texts:
        return False
    for sentence in sentences:
        if any(
            text_is_grounded_in_reference(sentence, reference_text, min_overlap=2, min_ratio=0.25)
            for reference_text in reference_texts
        ):
            continue
        if not llm_assisted_rewrite_text_is_grounded_in_pages(sentence, page_records):
            return False
    return True


def normalize_llm_assisted_rewrite_items(
    raw_items,
    allowed_claims_by_id: dict[str, dict],
    title: str,
    limit: int,
) -> list[dict]:
    normalized_items: list[dict] = []
    if not isinstance(raw_items, list):
        return normalized_items

    for raw_item in raw_items:
        if len(normalized_items) >= limit:
            break
        if not isinstance(raw_item, dict):
            continue
        claim_id = str(raw_item.get("claim_id", "")).strip()
        text = str(raw_item.get("text", "")).strip()
        claim_record = allowed_claims_by_id.get(claim_id)
        if claim_record is None:
            continue
        if not llm_assisted_rewrite_text_is_grounded(text, claim_record, title):
            continue
        normalized_items.append({
            "claim_record": claim_record,
            "text": markdown_to_plain_text(text).strip(),
        })
    return normalized_items


def normalize_llm_assisted_page_items(
    raw_items,
    allowed_pages_by_id: dict[str, dict],
    limit: int,
) -> list[dict]:
    normalized_items: list[dict] = []
    if not isinstance(raw_items, list):
        return normalized_items

    for raw_item in raw_items:
        if len(normalized_items) >= limit:
            break
        if not isinstance(raw_item, dict):
            continue
        page_id = str(raw_item.get("page_id", "")).strip()
        text = str(raw_item.get("text", "")).strip()
        page_record = allowed_pages_by_id.get(page_id)
        if page_record is None:
            continue
        if not llm_assisted_rewrite_text_is_grounded_in_page(text, page_record):
            continue
        normalized_items.append({
            "page_record": page_record,
            "text": markdown_to_plain_text(text).strip(),
        })
    return normalized_items


def extract_markdown_section_text(page_text: str, heading: str) -> str:
    lines = page_text.splitlines()
    collecting = False
    collected: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            collecting = True
            continue
        if collecting and stripped.startswith("## "):
            break
        if collecting:
            collected.append(line)
    return "\n".join(collected).strip()


def extract_markdown_bullet_lines(section_text: str) -> list[str]:
    bullet_lines: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullet_lines.append(stripped)
    return bullet_lines


def parse_claim_id_from_markdown_reference(text: str) -> str | None:
    match = re.search(r"\[`([^`]+)`\]\([^)]+\)", text)
    if match:
        return match.group(1)
    return None


def parse_page_id_from_markdown_page_link(text: str) -> str | None:
    match = re.search(r"\]\([^)]+/([^/]+)/[^/)]+\.md\)", text)
    if match:
        return match.group(1)
    return None


def strip_claim_reference_from_bullet(text: str) -> str:
    cleaned = re.sub(r"\s*\(\[`[^`]+`\]\([^)]+\)\)\s*$", "", text).strip()
    return cleaned


def readable_concept_page_grounding_issues(
    target: Path,
    page_record: dict,
    claim_records_by_id: dict[str, dict],
) -> list[str]:
    if page_record.get("type") != "concept":
        return []

    page_path = page_record.get("page_path")
    if not page_path:
        return ["missing_page_path"]
    page_file = target / page_path
    if not page_file.exists():
        return ["missing_page_file"]

    stable_claim_records = [
        claim_records_by_id[claim_id]
        for claim_id in page_record.get("claim_ids", [])
        if claim_id in claim_records_by_id
    ]
    if not stable_claim_records:
        return ["missing_live_claims"]

    title = page_record.get("title", "")
    canonical_claim = choose_canonical_claim(stable_claim_records, title)
    page_text = page_file.read_text(encoding="utf-8")

    summary_text = extract_markdown_section_text(page_text, "## 摘要 / Summary")
    if summary_text:
        summary_ok = any(
            llm_assisted_rewrite_text_is_grounded(summary_text, claim_record, title)
            for claim_record in stable_claim_records
        )
        if not summary_ok:
            return ["summary_not_grounded"]

    core_definition_text = extract_markdown_section_text(page_text, "## 核心定义 / Core Definition")
    if core_definition_text and not llm_assisted_rewrite_text_is_grounded(core_definition_text, canonical_claim, title):
        return ["core_definition_not_grounded"]

    key_points_text = extract_markdown_section_text(page_text, "## 关键要点 / Key Points")
    for bullet in extract_markdown_bullet_lines(key_points_text):
        claim_id = parse_claim_id_from_markdown_reference(bullet)
        if not claim_id:
            return [f"key_point_missing_claim_ref:{bullet}"]
        claim_record = claim_records_by_id.get(claim_id)
        if claim_record is None:
            return [f"key_point_unknown_claim_ref:{claim_id}"]
        bullet_text = strip_claim_reference_from_bullet(bullet[2:])
        if not llm_assisted_rewrite_text_is_grounded(bullet_text, claim_record, title):
            return [f"key_point_not_grounded:{claim_id}"]

    practical_text = extract_markdown_section_text(page_text, "## 使用提示 / Practical Notes")
    for bullet in extract_markdown_bullet_lines(practical_text):
        fallback_text = "- 当前稳定结论以概念定义和基础事实为主，尚未整理出更多操作性提示。"
        if bullet == fallback_text:
            continue
        claim_id = parse_claim_id_from_markdown_reference(bullet)
        if not claim_id:
            return [f"practical_note_missing_claim_ref:{bullet}"]
        claim_record = claim_records_by_id.get(claim_id)
        if claim_record is None:
            return [f"practical_note_unknown_claim_ref:{claim_id}"]
        bullet_text = strip_claim_reference_from_bullet(bullet[2:])
        if not llm_assisted_rewrite_text_is_grounded(bullet_text, claim_record, title):
            return [f"practical_note_not_grounded:{claim_id}"]

    return []


def overview_page_grounding_issues(
    target: Path,
    page_record: dict,
    page_records_by_id: dict[str, dict],
    claim_records_by_id: dict[str, dict],
) -> list[str]:
    if page_record.get("type") != "overview":
        return []

    page_path = page_record.get("page_path")
    if not page_path:
        return ["missing_page_path"]
    page_file = target / page_path
    if not page_file.exists():
        return ["missing_page_file"]

    concept_pages = {
        record["page_id"]: record
        for record in page_records_by_id.values()
        if is_live_page_record(record) and record.get("type") == "concept"
    }
    if not concept_pages:
        return ["missing_concept_pages"]

    page_text = page_file.read_text(encoding="utf-8")
    summary_text = extract_markdown_section_text(page_text, "## 工作区综述 / Workspace Overview")
    if summary_text:
        summary_ok = llm_assisted_overview_summary_is_grounded(
            summary_text,
            list(concept_pages.values()),
            claim_records_by_id=claim_records_by_id,
        )
        if not summary_ok:
            return ["overview_summary_not_grounded"]

    theme_map_text = extract_markdown_section_text(page_text, "## 主题导览 / Theme Map")
    theme_map_bullets = extract_markdown_bullet_lines(theme_map_text)
    for bullet in theme_map_bullets:
        if bullet == "- 先读这些基础主题：" or bullet == "- 再看这些更偏操作或判断的主题：" or bullet == "- 当前还没有足够的稳定主题可用于生成综述。":
            continue
        page_id = parse_page_id_from_markdown_page_link(bullet)
        if not page_id:
            return [f"theme_map_missing_page_ref:{bullet}"]
        concept_page = concept_pages.get(page_id)
        if concept_page is None:
            return [f"theme_map_unknown_page_ref:{page_id}"]
        bullet_text = strip_claim_reference_from_bullet(bullet[2:])
        if not llm_assisted_rewrite_text_is_grounded_in_page(bullet_text, concept_page):
            return [f"theme_map_not_grounded:{page_id}"]

    reading_path_text = extract_markdown_section_text(page_text, "## 推荐阅读路径 / Suggested Reading Path")
    for bullet in extract_markdown_bullet_lines(reading_path_text):
        page_id = parse_page_id_from_markdown_page_link(bullet)
        if not page_id:
            return [f"reading_path_missing_page_ref:{bullet}"]
        concept_page = concept_pages.get(page_id)
        if concept_page is None:
            return [f"reading_path_unknown_page_ref:{page_id}"]
        bullet_text = strip_claim_reference_from_bullet(bullet[2:])
        if not llm_assisted_rewrite_text_is_grounded_in_page(bullet_text, concept_page):
            return [f"reading_path_not_grounded:{page_id}"]

    return []


def rendered_page_grounding_issues(
    target: Path,
    page_record: dict,
    claim_records_by_id: dict[str, dict],
    page_records_by_id: dict[str, dict] | None = None,
) -> list[str]:
    render_target = page_record_render_target(page_record)
    if render_target == "readable_concept":
        return readable_concept_page_grounding_issues(
            target=target,
            page_record=page_record,
            claim_records_by_id=claim_records_by_id,
        )
    if render_target == "overview" and page_records_by_id is not None:
        return overview_page_grounding_issues(
            target=target,
            page_record=page_record,
            page_records_by_id=page_records_by_id,
            claim_records_by_id=claim_records_by_id,
        )
    return []


def concept_page_quality_issues(page_record: dict, claim_records_by_id: dict[str, dict]) -> list[str]:
    if page_record.get("type") != "concept":
        return []
    title = page_record.get("title", "") or ""
    claim_ids = page_record.get("claim_ids", []) or []
    claim_records = [
        claim_records_by_id[claim_id]
        for claim_id in claim_ids
        if claim_id in claim_records_by_id
    ]
    if not claim_records:
        return ["missing_claim_records"]
    canonical_claim = claim_records[0]
    quality = concept_title_quality_details(
        title=title,
        canonical_claim=canonical_claim,
        claim_records=claim_records,
    )
    issues: list[str] = []
    if quality["classification"] == "reject":
        issues.append(f"rejected_title:{title}")
    if "generic_title" in quality["reasons"]:
        issues.append("generic_title")
    if "too_short" in quality["reasons"] or "very_short" in quality["reasons"]:
        issues.append("too_short")
    if "question_like_claim" in quality["reasons"]:
        issues.append("question_like_claim")
    return issues


def page_semantic_consistency_issues(page_record: dict, claim_records_by_id: dict[str, dict]) -> list[str]:
    page_type = str(page_record.get("type", "")).strip().lower()
    if page_type not in {"concept", "guide", "duty", "example", "topic", "reference", "timeline"}:
        return []

    page_intent = str(page_record.get("page_intent", "")).strip().lower()
    page_route = page_record.get("page_route", {}) if isinstance(page_record.get("page_route"), dict) else {}
    route_target = str(page_route.get("route_target", "")).strip().lower()
    route_decision_id = str(page_route.get("semantic_decision_id", "") or "").strip()
    semantic_decision_ids = set(page_record.get("semantic_decision_ids", []) or [])
    claim_ids = page_record.get("claim_ids", []) or []
    claim_records = [
        claim_records_by_id[claim_id]
        for claim_id in claim_ids
        if claim_id in claim_records_by_id
    ]
    if not claim_records:
        return []

    roles = {
        claim_knowledge_role(record)
        for record in claim_records
        if claim_knowledge_role(record)
    }
    intent_hints = {
        hint
        for record in claim_records
        for hint in claim_page_intent_hints(record)
    }
    issues: list[str] = []

    expected_intent_by_type = {
        "concept": "concept",
        "guide": "guide",
        "duty": "duty",
        "example": "example",
        "topic": "topic",
        "reference": "reference",
        "timeline": "timeline",
    }
    expected_intent = expected_intent_by_type.get(page_type)
    if page_intent and expected_intent and page_intent != expected_intent:
        issues.append(f"page_type_intent_mismatch:{page_type}!={page_intent}")
    if route_target and expected_intent and route_target != expected_intent:
        issues.append(f"page_route_target_mismatch:{page_type}!={route_target}")
    if not route_decision_id:
        issues.append("page_route_decision_missing")
    elif route_decision_id not in semantic_decision_ids:
        issues.append("page_route_decision_not_linked")

    if page_type == "concept":
        blocked_roles = sorted(role for role in roles if role in {"procedure", "example", "meta", "structural_shell", "opinion"})
        if blocked_roles:
            issues.append(f"concept_page_blocked_roles:{','.join(blocked_roles)}")
        if "reject" in intent_hints:
            issues.append("concept_page_reject_intent_hint")
    elif page_type == "guide":
        if roles and "procedure" not in roles:
            issues.append(f"guide_page_missing_procedure_role:{','.join(sorted(roles))}")
    elif page_type == "duty":
        if roles and roles.issubset({"procedure", "example", "meta", "opinion"}):
            issues.append(f"duty_page_missing_fact_like_role:{','.join(sorted(roles))}")
    elif page_type == "example":
        if roles and "example" not in roles:
            issues.append(f"example_page_missing_example_role:{','.join(sorted(roles))}")
    elif page_type == "topic":
        if roles and roles.issubset({"procedure", "example", "meta", "structural_shell"}):
            issues.append(f"topic_page_semantically_thin:{','.join(sorted(roles))}")
    elif page_type == "reference":
        if roles and roles.issubset({"procedure", "example", "meta"}):
            issues.append(f"reference_page_semantically_thin:{','.join(sorted(roles))}")
    elif page_type == "timeline":
        if roles and roles.issubset({"meta", "structural_shell"}):
            issues.append(f"timeline_page_semantically_thin:{','.join(sorted(roles))}")

    return issues


def page_intent_brake_issues(page_record: dict) -> list[str]:
    page_route = page_record.get("page_route", {}) if isinstance(page_record.get("page_route"), dict) else {}
    route_reason = str(page_route.get("route_reason", "")).strip()
    if route_reason.startswith("page_intent_validation_downgraded_"):
        return [route_reason]
    return []


def claim_semantic_risk_issues(
    claim_record: dict,
    semantic_decisions_by_id: dict[str, dict],
) -> list[str]:
    issues: list[str] = []
    if not is_live_claim_record(claim_record):
        return issues
    if claim_record.get("status") == "needs_review" or claim_record.get("review_reason"):
        return issues
    for decision_id in claim_record.get("semantic_decision_ids", []) or []:
        decision_record = semantic_decisions_by_id.get(str(decision_id))
        if not decision_record or decision_record.get("task_type") != "claim_role":
            continue
        risk_flags = normalize_string_list(decision_record.get("risk_flags"))
        ambiguous_flags = sorted(flag for flag in risk_flags if "ambiguous" in flag)
        if ambiguous_flags:
            issues.append(f"{claim_record.get('claim_id')}:{','.join(ambiguous_flags)}")
            break
    return issues


def run_llm_assisted_readable_concept_render(
    target: Path,
    render_config: dict,
    title: str,
    canonical_claim: dict,
    stable_claim_records: list[dict],
    key_point_claims: list[dict],
    practical_claims: list[dict],
    summary_text: str,
) -> dict | None:
    if render_config.get("mode") != "llm_assisted":
        return None
    command = render_config.get("command", [])
    if not command:
        return None

    payload = {
        "task": "render_readable_concept_page",
        "title": title,
        "canonical_claim": {
            "claim_id": canonical_claim["claim_id"],
            "text": canonical_claim["text"],
            "claim_type": canonical_claim.get("claim_type"),
        },
        "stable_claims": [
            {
                "claim_id": claim_record["claim_id"],
                "text": claim_record["text"],
                "claim_type": claim_record.get("claim_type"),
                "status": claim_record.get("status"),
            }
            for claim_record in stable_claim_records
        ],
        "default_summary": summary_text,
        "default_key_points": [
            {
                "claim_id": claim_record["claim_id"],
                "text": render_claim_as_sentence(claim_record, title),
            }
            for claim_record in key_point_claims
        ],
        "default_practical_notes": [
            {
                "claim_id": claim_record["claim_id"],
                "text": render_claim_as_sentence(claim_record, title),
            }
            for claim_record in practical_claims
        ],
        "instructions": (
            "Only rewrite for readability. Do not add new facts. "
            "Every rewritten bullet must stay grounded in the referenced claim."
        ),
    }

    try:
        completed = subprocess.run(
            command,
            cwd=target,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=render_config.get("timeout_seconds", 20),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw_result = parse_hook_process_result(command, completed)
    if not isinstance(raw_result, dict):
        return None

    allowed_claims_by_id = {
        claim_record["claim_id"]: claim_record
        for claim_record in stable_claim_records
    }
    assisted_summary = str(raw_result.get("summary", "")).strip()
    if not llm_assisted_rewrite_text_is_grounded(assisted_summary, canonical_claim, title):
        assisted_summary = ""

    key_points = normalize_llm_assisted_rewrite_items(
        raw_result.get("key_points", []),
        allowed_claims_by_id=allowed_claims_by_id,
        title=title,
        limit=max(len(key_point_claims), 1),
    )
    practical_notes = normalize_llm_assisted_rewrite_items(
        raw_result.get("practical_notes", []),
        allowed_claims_by_id=allowed_claims_by_id,
        title=title,
        limit=max(len(practical_claims), 1),
    )

    if not assisted_summary and not key_points and not practical_notes:
        return None
    return {
        "summary": assisted_summary,
        "key_points": key_points,
        "practical_notes": practical_notes,
    }


def run_llm_assisted_overview_render(
    target: Path,
    render_config: dict,
    title: str,
    summary_text: str,
    theme_rows: list[dict],
    reading_path_rows: list[dict],
    claim_records_by_id: dict[str, dict],
) -> dict | None:
    if render_config.get("mode") != "llm_assisted":
        return None
    command = render_config.get("command", [])
    if not command:
        return None

    payload = {
        "task": "render_workspace_overview_page",
        "title": title,
        "default_summary": summary_text,
        "theme_rows": [
            {
                "page_id": item["page_record"]["page_id"],
                "title": item["page_record"].get("title", ""),
                "summary": item["summary"],
                "theme_kind": item["theme_kind"],
                "claim_count": item["claim_count"],
                "source_count": item["source_count"],
                "review_count": item["review_count"],
            }
            for item in theme_rows
        ],
        "reading_path_rows": [
            {
                "page_id": item["page_record"]["page_id"],
                "title": item["page_record"].get("title", ""),
                "summary": summarize_concept_page_for_overview_helper(
                    page_record=item["page_record"],
                    extract_first_sentence=extract_first_sentence,
                ),
            }
            for item in reading_path_rows
        ],
        "instructions": (
            "Only rewrite for readability. Do not add new facts. "
            "Every rewritten theme summary and reading-path bullet must stay grounded in the referenced concept page."
        ),
    }

    try:
        completed = subprocess.run(
            command,
            cwd=target,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=render_config.get("timeout_seconds", 20),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw_result = parse_hook_process_result(command, completed)
    if not isinstance(raw_result, dict):
        return None

    allowed_pages_by_id = {
        item["page_record"]["page_id"]: item["page_record"]
        for item in theme_rows
    }
    allowed_pages_by_id.update({
        item["page_record"]["page_id"]: item["page_record"]
        for item in reading_path_rows
    })

    assisted_summary = str(raw_result.get("summary", "")).strip()
    if not llm_assisted_overview_summary_is_grounded(
        assisted_summary,
        list(allowed_pages_by_id.values()),
        claim_records_by_id=claim_records_by_id,
    ):
        assisted_summary = ""

    theme_rows_rewrite = normalize_llm_assisted_page_items(
        raw_result.get("theme_rows", []),
        allowed_pages_by_id=allowed_pages_by_id,
        limit=max(len(theme_rows), 1),
    )
    reading_path_rewrite = normalize_llm_assisted_page_items(
        raw_result.get("reading_path", []),
        allowed_pages_by_id=allowed_pages_by_id,
        limit=max(len(reading_path_rows), 1),
    )

    if not assisted_summary and not theme_rows_rewrite and not reading_path_rewrite:
        return None
    return {
        "summary": assisted_summary,
        "theme_rows": theme_rows_rewrite,
        "reading_path": reading_path_rewrite,
    }


def build_source_summary_page(
    target: Path,
    source_record: dict,
    page_rel_path: Path,
    normalized_record: dict | None,
    claim_records: list[dict],
    chunk_records: list[dict],
) -> tuple[str, dict]:
    # source-summary 现在明确承担“来源入口视图”角色：
    # 先给出来源与转换状态，再暴露 claim / chunk / 结构信号入口，
    # 而不是兜底承载各种杂项内容。
    page_id = f"page_src_{source_record['source_id']}"
    title = normalized_record["title"] if normalized_record else Path(source_record["source_path"]).stem
    summary_claims = summarize_claims_for_page(claim_records)
    summary_text = summary_claims[0] if summary_claims else f"Source summary for {title}"
    semantic_context = prepare_page_semantic_context(
        target,
        claim_records,
    )
    semantic_frontmatter = semantic_context["semantic_frontmatter"]
    structure_projection = semantic_context["structure_projection"]
    metadata_key_counts = dict(structure_projection.get("metadata_key_counts", {}) or {})
    evidence_block_kind_counts = dict(structure_projection.get("evidence_block_kind_counts", {}) or {})
    section_path_counts = dict(structure_projection.get("section_path_counts", {}) or {})
    source_view_label = "source_view"

    lines = [
        "---",
        f'page_id: "{page_id}"',
        f'title: "{title}"',
        'type: "source-summary"',
        f'canonical_id: "{page_id}"',
        'status: "draft"',
        'automation_level: "auto_with_log"',
        f'render_target: "{source_view_label}"',
        f'source_id: "{source_record["source_id"]}"',
        f'claim_count: {len(claim_records)}',
        f'chunk_count: {len(chunk_records)}',
    ]
    append_frontmatter_list(lines, "content_tags", semantic_frontmatter["content_tags"])
    append_frontmatter_list(lines, "semantic_feature_tags", semantic_frontmatter["semantic_feature_tags"])
    lines.extend([
        "---",
        "",
        f"# {title}",
        "",
        "## 来源入口视图 / Source Entry View",
        "",
        f"- 来源路径: `{source_record['source_path']}`",
        f"- 来源类型: `{source_record['source_type']}`",
        f"- 当前状态: `{source_record.get('status', 'unknown')}`",
    ])

    if normalized_record is not None:
        lines.extend([
            f"- 标准化文件: `{normalized_record['normalized_path']}`",
            f"- 提取方式: `{normalized_record['extraction_method']}`",
            f"- 提取质量: `{normalized_record['extraction_quality']}`",
        ])
        if normalized_record.get("warnings"):
            lines.append(f"- 标准化警告: `{', '.join(normalized_record['warnings'])}`")

    lines.extend([
        "",
        "## 来源摘要 / Source Summary",
        "",
    ])
    if summary_claims:
        for claim_text in summary_claims:
            lines.append(f"- {claim_text}")
    else:
        lines.append("- 当前尚未生成可用 claim。")

    lines.extend([
        "",
        "## 结构与证据入口 / Structure And Evidence Entry",
        "",
        f"- 章节路径覆盖数: `{len(section_path_counts)}`",
        f"- 结构元信息字段数: `{sum(metadata_key_counts.values())}`",
        f"- 证据块类型数: `{len(evidence_block_kind_counts)}`",
    ])
    if section_path_counts:
        lines.append(f"- 代表性章节: `{next(iter(section_path_counts.keys()))}`")
    if metadata_key_counts:
        lines.append(
            "- 元信息字段: "
            + ", ".join(f"`{key}` x{count}" for key, count in list(metadata_key_counts.items())[:6])
        )
    if evidence_block_kind_counts:
        lines.append(
            "- 证据块类型: "
            + ", ".join(f"`{key}` x{count}" for key, count in list(evidence_block_kind_counts.items())[:6])
        )

    lines.extend([
        "",
        "## 可追踪 Claims / Traceable Claims",
        "",
    ])
    if claim_records:
        for claim_record in claim_records:
            lines.append(
                f"- {format_claim_reference(page_rel_path, claim_record)} {format_claim_type_label(claim_record.get('claim_type'))} "
                f"{claim_record['text']}"
            )
    else:
        lines.append("- 暂无 claims。")

    lines.extend([
        "",
        "## 上下文切块 / Context Chunks",
        "",
    ])
    if chunk_records:
        for chunk_record in chunk_records[:10]:
            lines.append(
                f"- {format_chunk_reference(page_rel_path, source_record['source_id'], chunk_record)}"
            )
        if len(chunk_records) > 10:
            lines.append(f"- ... 其余 {len(chunk_records) - 10} 个 chunk 省略")
    else:
        lines.append("- 暂无 chunks。")

    lines.extend([
        "",
        "## 读取建议 / Reading Path",
        "",
        "- 先看本页的来源状态、元信息字段和代表性 Claims，再决定是否继续跳到正式页面。",
        "- 如果问题偏证据核对，优先沿 claim -> evidence_block -> source 回链继续阅读。",
        "- 如果问题偏主题理解，再跳转到概念页、职责页、参考页或综述页。",
    ])

    page_text = "\n".join(lines).strip() + "\n"
    page_record = {
        "page_id": page_id,
        "title": title,
        "type": "source-summary",
        "render_target": source_view_label,
        "canonical_id": page_id,
        "status": "draft",
        "lifecycle_status": "active",
        "automation_level": "auto_with_log",
        "review_reason": None,
        "summary": summary_text,
        "aliases": [],
        "redirect_to": None,
        "claim_ids": [item["claim_id"] for item in claim_records],
        "content_tags": semantic_frontmatter["content_tags"],
        "semantic_feature_tags": semantic_frontmatter["semantic_feature_tags"],
        "structure_projection": structure_projection,
        "source_refs": [
            {
                "source_id": source_record["source_id"],
                "source_path": source_record["source_path"],
                "chunk_ids": [item["chunk_id"] for item in chunk_records],
            }
        ],
        "created": utc_now_iso(),
        "updated": utc_now_iso(),
        "archived_at": None,
    }
    return page_text, page_record


def build_concept_page(
    target: Path,
    bucket_key: str,
    page_rel_path: Path,
    claim_records: list[dict],
    page_records_by_id: dict[str, dict],
    review_records: list[dict],
    render_config: dict | None = None,
) -> tuple[str, dict]:
    render_target = page_record_render_target({"type": "concept"}) or "readable_concept"
    config = load_workspace_config(target)
    concept_claim_selection = prepare_concept_claim_selection_helper(
        target=target,
        claim_records=claim_records,
        prepare_page_semantic_context=prepare_page_semantic_context,
        filter_claim_records_for_concept_path=filter_claim_records_for_concept_path,
        filter_live_stable_claim_records=filter_live_stable_claim_records,
        choose_group_topic_label=choose_group_topic_label,
        choose_canonical_claim=choose_canonical_claim,
    )
    stable_claim_records = concept_claim_selection["stable_claim_records"]
    render_claim_records = concept_claim_selection["render_claim_records"]
    group_topic_label = concept_claim_selection["group_topic_label"]
    canonical_claim = concept_claim_selection["canonical_claim"]
    page_id = build_concept_page_id(bucket_key)
    concept_page_title = prepare_concept_page_title_helper(
        target=target,
        config=config,
        canonical_claim=canonical_claim,
        render_claim_records=render_claim_records,
        group_topic_label=group_topic_label,
        resolve_concept_title_candidate=resolve_concept_title_candidate,
        build_concept_canonical_key=build_concept_canonical_key,
    )
    title = concept_page_title["title"]
    title_quality = concept_page_title["title_quality"]
    concept_page_context = prepare_concept_page_context_helper(
        target=target,
        title=title,
        canonical_claim=canonical_claim,
        render_claim_records=render_claim_records,
        review_records=review_records,
        page_records_by_id=page_records_by_id,
        prepare_page_semantic_context=prepare_page_semantic_context,
        render_claim_as_sentence=render_claim_as_sentence,
        collect_review_ids_for_claims=collect_review_ids_for_claims,
        collect_source_summary_pages_for_claims=collect_source_summary_pages_for_claims,
        aggregate_source_refs_for_page=aggregate_source_refs_for_page,
        build_concept_canonical_key=build_concept_canonical_key,
    )
    render_claim_records = concept_page_context["render_claim_records"]
    review_ids = concept_page_context["review_ids"]
    source_pages = concept_page_context["source_pages"]
    source_refs = concept_page_context["source_refs"]
    semantic_frontmatter = concept_page_context["semantic_frontmatter"]
    canonical_display_text = concept_page_context["canonical_display_text"]
    canonical_key = concept_page_title["canonical_key"]
    canonical_id = concept_page_title["canonical_id"]

    concept_render_inputs = prepare_concept_render_inputs_helper(
        render_claim_records=render_claim_records,
        canonical_claim=canonical_claim,
        group_topic_label=group_topic_label,
        title=title,
        claim_record_rank_key=claim_record_rank_key,
        claim_is_topic_shell_text=claim_is_topic_shell_text,
        clean_concept_title_text=clean_concept_title_text,
        shorten_title_text=shorten_title_text,
        extract_primary_section_label=extract_primary_section_label,
        collect_section_label_aliases=collect_section_label_aliases,
    )
    sorted_claims = concept_render_inputs["sorted_claims"]
    key_point_claims = concept_render_inputs["key_point_claims"]
    practical_claims = concept_render_inputs["practical_claims"]
    aliases = concept_render_inputs["aliases"]

    summary_text = build_readable_concept_summary_text_helper(
        title=title,
        canonical_claim=canonical_claim,
        stable_claim_records=render_claim_records,
        source_refs=source_refs,
        render_claim_as_sentence=render_claim_as_sentence,
    )
    assisted_render = run_llm_assisted_readable_concept_render(
        target=target,
        render_config=render_config or {"mode": "deterministic", "command": [], "timeout_seconds": 20},
        title=title,
        canonical_claim=canonical_claim,
        stable_claim_records=render_claim_records,
        key_point_claims=key_point_claims,
        practical_claims=practical_claims,
        summary_text=summary_text,
    )
    requested_render_mode = (render_config or {}).get("mode", "deterministic")
    render_result = finalize_concept_render_result_helper(
        assisted_render=assisted_render,
        requested_render_mode=requested_render_mode,
        summary_text=summary_text,
    )
    rendered_summary_text = render_result["rendered_summary_text"]
    rendered_key_points = render_result["rendered_key_points"]
    rendered_practical_notes = render_result["rendered_practical_notes"]
    render_status = render_result["render_status"]

    return build_concept_page_output_helper(
        page_id=page_id,
        title=title,
        render_target=render_target,
        canonical_id=canonical_id,
        review_ids=review_ids,
        requested_render_mode=requested_render_mode,
        render_status=render_status,
        stable_claim_count=len(stable_claim_records),
        source_refs=source_refs,
        semantic_frontmatter=semantic_frontmatter,
        bucket_key=bucket_key,
        canonical_key=canonical_key,
        canonical_display_text=canonical_display_text,
        render_claim_records=render_claim_records,
        rendered_summary_text=rendered_summary_text,
        canonical_claim=canonical_claim,
        rendered_key_points=rendered_key_points,
        key_point_claims=key_point_claims,
        rendered_practical_notes=rendered_practical_notes,
        practical_claims=practical_claims,
        sorted_claims=sorted_claims,
        source_pages=source_pages,
        page_rel_path=page_rel_path,
        format_claim_reference=format_claim_reference,
        format_claim_type_label=format_claim_type_label,
        render_claim_as_sentence=render_claim_as_sentence,
        format_source_page_label=format_source_page_label,
        format_workspace_file_reference=format_workspace_file_reference,
        format_source_page_meta=format_source_page_meta,
        format_chunk_reference=format_chunk_reference,
        append_frontmatter_list=append_frontmatter_list,
        utc_now_iso=utc_now_iso,
        title_quality=title_quality,
        aliases=aliases,
    )


def build_workspace_overview_page(
    target: Path,
    page_rel_path: Path,
    concept_pages: list[dict],
    page_records_by_id: dict[str, dict],
    claim_records_by_id: dict[str, dict],
    render_config: dict | None = None,
) -> tuple[str, dict]:
    render_target = "overview"
    config = load_workspace_config(target)
    project_name = (
        str(config.get("project", {}).get("name", "")).strip()
        if isinstance(config.get("project"), dict)
        else ""
    ) or target.name
    page_id = build_workspace_overview_page_id()
    title = f"{project_name} 综述"
    canonical_id = "overview:workspace"
    overview_context = prepare_workspace_overview_context_helper(
        concept_pages=concept_pages,
        page_records_by_id=page_records_by_id,
        claim_records_by_id=claim_records_by_id,
        aggregate_source_refs_for_pages=aggregate_source_refs_for_pages,
        is_live_page_record=is_live_page_record,
        expected_source_summary_page_id=expected_source_summary_page_id,
        append_unique=append_unique,
        extract_first_sentence=extract_first_sentence,
    )
    source_refs = overview_context["source_refs"]
    claim_ids = overview_context["claim_ids"]
    review_ids = overview_context["review_ids"]
    key_theme_rows = overview_context["key_theme_rows"]
    source_coverage_rows = overview_context["source_coverage_rows"]
    summary_text = overview_context["summary_text"]
    overview_claim_records = [
        claim_records_by_id[claim_id]
        for claim_id in claim_ids
        if isinstance(claim_records_by_id.get(claim_id), dict)
    ]
    semantic_frontmatter = prepare_page_semantic_context(
        target,
        overview_claim_records,
    )["semantic_frontmatter"]
    overview_render_inputs = prepare_workspace_overview_render_inputs_helper(
        key_theme_rows=key_theme_rows,
    )
    operational_rows = overview_render_inputs["operational_rows"]
    foundational_rows = overview_render_inputs["foundational_rows"]
    requested_render_mode = (render_config or {}).get("mode", "deterministic")
    deterministic_reading_path_rows = overview_render_inputs["deterministic_reading_path_rows"]

    assisted_render = run_llm_assisted_overview_render(
        target=target,
        render_config=render_config or {"mode": "deterministic", "command": [], "timeout_seconds": 20},
        title=title,
        summary_text=summary_text,
        theme_rows=key_theme_rows,
        reading_path_rows=deterministic_reading_path_rows,
        claim_records_by_id=claim_records_by_id,
    )
    render_result = finalize_workspace_overview_render_result_helper(
        assisted_render=assisted_render,
        requested_render_mode=requested_render_mode,
        summary_text=summary_text,
    )
    rendered_summary_text = render_result["rendered_summary_text"]
    rendered_theme_rows = render_result["rendered_theme_rows"]
    rendered_reading_path = render_result["rendered_reading_path"]
    render_status = render_result["render_status"]

    return build_workspace_overview_page_output_helper(
        page_id=page_id,
        title=title,
        render_target=render_target,
        canonical_id=canonical_id,
        review_ids=review_ids,
        requested_render_mode=requested_render_mode,
        render_status=render_status,
        claim_ids=claim_ids,
        source_refs=source_refs,
        rendered_summary_text=rendered_summary_text,
        rendered_theme_rows=rendered_theme_rows,
        foundational_rows=foundational_rows,
        operational_rows=operational_rows,
        key_theme_rows=key_theme_rows,
        rendered_reading_path=rendered_reading_path,
        source_coverage_rows=source_coverage_rows,
        concept_pages=concept_pages,
        semantic_frontmatter=semantic_frontmatter,
        page_rel_path=page_rel_path,
        format_page_label=format_page_label,
        summarize_concept_page_for_overview=lambda page_record: summarize_concept_page_for_overview_helper(
            page_record=page_record,
            extract_first_sentence=extract_first_sentence,
        ),
        format_source_page_label=format_source_page_label,
        format_workspace_file_reference=format_workspace_file_reference,
        append_frontmatter_list=append_frontmatter_list,
        utc_now_iso=utc_now_iso,
    )


def page_intent_page_id(bucket_key: str, page_intent: str) -> str:
    bucket_hash = hashlib.sha256(f"{page_intent}|{bucket_key}".encode("utf-8")).hexdigest()
    return f"page_{page_intent[:3]}_{bucket_hash[:12]}"


def page_intent_page_path(page_intent: str, page_id: str, title: str) -> Path:
    filename = sanitize_page_filename(title)
    folder = {
        "guide": "guides",
        "duty": "duties",
        "example": "examples",
        "topic": "topics",
        "reference": "references",
        "timeline": "timelines",
    }.get(page_intent, "topics")
    return Path("wiki") / folder / page_id / f"{filename}.md"


def build_intent_routed_page(
    target: Path,
    config: dict,
    bucket_key: str,
    page_intent: str,
    page_rel_path: Path,
    claim_records: list[dict],
    page_records_by_id: dict[str, dict],
    review_records: list[dict],
) -> tuple[str, dict]:
    semantic_context = prepare_page_semantic_context(target, claim_records)
    claim_records = semantic_context["claim_records"]
    group_topic_label = choose_group_topic_label(claim_records)
    canonical_claim = choose_canonical_claim(claim_records, group_topic_label)
    descriptor = build_intent_page_descriptor_helper(
        page_intent=page_intent,
        group_topic_label=group_topic_label or "",
        canonical_claim_text=canonical_claim.get("text", ""),
        clean_concept_title_text=clean_concept_title_text,
        build_concept_canonical_key=build_concept_canonical_key,
    )
    title = descriptor["title"]
    canonical_id = descriptor["canonical_id"]
    summary = descriptor["summary"]
    section_title = descriptor["section_title"]

    page_id = page_intent_page_id(bucket_key, page_intent)
    review_ids = collect_review_ids_for_claims(
        [claim_record["claim_id"] for claim_record in claim_records],
        review_records,
    )
    source_refs = aggregate_source_refs_for_page(claim_records)
    source_pages = collect_source_summary_pages_for_claims(claim_records, page_records_by_id)
    semantic_frontmatter = semantic_context["semantic_frontmatter"]

    return build_intent_routed_page_output_helper(
        page_id=page_id,
        title=title,
        page_intent=page_intent,
        canonical_id=canonical_id,
        review_ids=review_ids,
        claim_records=claim_records,
        source_refs=source_refs,
        source_pages=source_pages,
        semantic_frontmatter=semantic_frontmatter,
        summary=summary,
        section_title=section_title,
        page_rel_path=page_rel_path,
        format_source_page_label=format_source_page_label,
        format_workspace_file_reference=format_workspace_file_reference,
        render_claim_as_sentence=render_claim_as_sentence,
        format_claim_reference=format_claim_reference,
        append_frontmatter_list=append_frontmatter_list,
        utc_now_iso=utc_now_iso,
    )


def write_wiki_page(target: Path, relative_path: Path, page_text: str) -> None:
    # Wiki 页面属于最终产物，改写时也尽量走原子写，避免意外中断留下半截 Markdown。
    page_path = target / relative_path
    page_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(page_path, page_text, encoding="utf-8")


def remove_stale_page_file(target: Path, previous_path: str, current_path: str) -> None:
    # 页面改名后，把旧文件清掉，避免 wiki 目录里残留同一 page_id 的历史壳文件。
    if not previous_path or previous_path == current_path:
        return
    previous_page_path = target / previous_path
    if previous_page_path.exists():
        previous_page_path.unlink()

    stop_dirs = {
        (target / "wiki").resolve(),
        (target / "wiki" / "concepts").resolve(),
        (target / "wiki" / "sources").resolve(),
    }
    parent = previous_page_path.parent
    while parent.exists() and parent.resolve() not in stop_dirs:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def build_page_signature(page_record: dict, page_text: str) -> str:
    # 页面签名用于判断“这页内容是否真的变了”。
    # 如果签名不变，就没必要重写页面文件、日志和页面索引记录。
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
        "page_text": page_text,
    }
    return hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def upsert_wiki_page(
    target: Path,
    page_records_by_id: dict[str, dict],
    page_record: dict,
    page_text: str,
) -> tuple[dict, bool]:
    # 统一处理页面落盘、页面索引更新和“是否真的发生变化”的判断。
    page_record = dict(page_record)
    page_record["lifecycle_status"] = page_lifecycle_status_for_record(page_record)
    page_record["page_signature"] = build_page_signature(page_record, page_text)

    previous_record = page_records_by_id.get(page_record["page_id"])
    if previous_record is not None and previous_record.get("page_signature") == page_record["page_signature"]:
        # 内容没变时，保留旧 created / updated / signature，避免制造无意义噪声。
        return previous_record, False

    if previous_record is not None:
        remove_stale_page_file(
            target=target,
            previous_path=previous_record.get("page_path", ""),
            current_path=page_record.get("page_path", ""),
        )
        page_record["created"] = previous_record.get("created", page_record.get("created"))
    page_record["updated"] = utc_now_iso()

    write_wiki_page(target, Path(page_record["page_path"]), page_text)
    page_records_by_id[page_record["page_id"]] = page_record
    return page_record, True


def rebuild_wiki_index(target: Path, page_records: list[dict]) -> None:
    # index 先作为“wiki 总目录”存在，按页面类型分组后会比单一长列表更容易读。
    page_records = filter_live_page_records(page_records)
    lines = [
        "# Wiki 索引 / Wiki Index",
        "",
        "## 阅读页 / Readable Pages",
        "",
    ]

    concept_pages = [
        record for record in page_records
        if record.get("type") == "concept"
    ]
    overview_pages = [
        record for record in page_records
        if record.get("type") == "overview"
    ]
    source_pages = [
        record for record in page_records
        if record.get("type") == "source-summary"
    ]
    other_pages = [
        record for record in page_records
        if record.get("type") not in {"overview", "concept", "source-summary"}
    ]

    if overview_pages or concept_pages:
        for record in sorted(overview_pages, key=lambda item: item["title"].lower()):
            page_path = markdown_link_target(record.get("page_path", ""))
            lines.append(
                f"- [{record['title']}]({page_path}) "
                f"({record['type']}, claims={len(record.get('claim_ids', []))}, reviews={len(record.get('review_ids', []))}) "
                f"- {record['summary']}"
            )
        for record in sorted(concept_pages, key=lambda item: item["title"].lower()):
            page_path = markdown_link_target(record.get("page_path", ""))
            lines.append(
                f"- [{record['title']}]({page_path}) "
                f"({record['type']}, claims={len(record.get('claim_ids', []))}, reviews={len(record.get('review_ids', []))}) "
                f"- {record['summary']}"
            )
    else:
        lines.append("- 暂无可读概念页。")

    lines.extend([
        "",
        "## 来源页 / Source Pages",
        "",
    ])
    if source_pages:
        for record in sorted(source_pages, key=lambda item: item["title"].lower()):
            page_path = markdown_link_target(record.get("page_path", ""))
            lines.append(
                f"- [{record['title']}]({page_path}) "
                f"({record['type']}, claims={len(record.get('claim_ids', []))}) - {record['summary']}"
            )
    else:
        lines.append("- 暂无来源页。")

    if other_pages:
        lines.extend([
            "",
            "## 其他页面 / Other Pages",
            "",
        ])
        for record in sorted(other_pages, key=lambda item: item["title"].lower()):
            page_path = markdown_link_target(record.get("page_path", ""))
            lines.append(
                f"- [{record['title']}]({page_path}) "
                f"({record['type']}, claims={len(record.get('claim_ids', []))}) - {record['summary']}"
            )

    # index.md 每次 ingest 都会整体重建，因此也适合直接走原子覆盖写。
    atomic_write_text(target / "wiki" / "index.md", "\n".join(lines).strip() + "\n", encoding="utf-8")


def append_wiki_log(target: Path, task_id: str, changed_pages: list[dict]) -> None:
    # log 先走 append-only，记录每次 ingest 真实写入、更新或清理了哪些页面。
    log_path = target / "wiki" / "log.md"
    lines = [f"## [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ingest | {task_id}"]
    if changed_pages:
        for page in changed_pages:
            action = "removed" if page.get("removed") else "generated"
            lines.append(f"- {action} {page['type']} page: `{page['page_id']}` -> `{page['page_path']}`")
    else:
        lines.append("- no wiki pages generated in this run")
    lines.append("")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def link_claims_to_page_in_memory(
    claim_records: list[dict],
    page_id: str,
    claims_by_id: dict[str, dict],
) -> set[str]:
    # 页面生成后，把 claim -> page 的反向关系先写进内存。
    # 这样一轮 ingest 内如果有很多页面命中同一批 claims，就不会每条 claim 都去重写一遍 claims.jsonl。
    dirty_claim_ids: set[str] = set()
    for claim_record in claim_records:
        if page_id in claim_record.get("page_ids", []):
            continue
        claim_record.setdefault("page_ids", []).append(page_id)
        claim_record["updated_at"] = utc_now_iso()
        claim_record["lifecycle_status"] = claim_lifecycle_status_for_record(claim_record)
        claims_by_id[claim_record["claim_id"]] = claim_record
        dirty_claim_ids.add(claim_record["claim_id"])
    return dirty_claim_ids


def link_reviews_to_page_in_memory(
    review_records: list[dict],
    page_id: str,
    claim_ids: list[str],
    reviews_by_id: dict[str, dict],
) -> set[str]:
    # review 记录也先在内存里补 page 反链，最后统一写回 reviews.jsonl 和 review 文件。
    claim_id_set = set(claim_ids)
    dirty_review_ids: set[str] = set()
    for review_record in review_records:
        if not claim_id_set.intersection(review_record.get("candidate_claim_ids", [])):
            continue
        if page_id in review_record.get("candidate_page_ids", []):
            continue
        review_record.setdefault("candidate_page_ids", []).append(page_id)
        review_record["lifecycle_status"] = review_lifecycle_status_for_record(review_record)
        reviews_by_id[review_record["review_id"]] = review_record
        dirty_review_ids.add(review_record["review_id"])
    return dirty_review_ids


def extract_markdown_headings(text: str) -> list[str]:
    # query 阶段会单独给 headings 打分，因此这里把 Markdown 标题抽出来。
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        heading_text = re.sub(r"^#{1,6}\s*", "", stripped).strip()
        if heading_text and heading_text.lower() not in QUERY_HEADING_BLACKLIST:
            headings.append(heading_text)
    return headings


def strip_frontmatter(text: str) -> str:
    # wiki 页面大多带 frontmatter，query 做正文检索时应当把这层元数据先剥掉。
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[index + 1:])
    return text


def build_searchable_body_text(page_text: str) -> str:
    # body 字段不应该把“每页都重复的模板栏目标题”当成正文。
    # 这里先做一个保守清洗：去 frontmatter、去公共标题行，保留其余正文和列表内容。
    cleaned_lines: list[str] = []
    for line in strip_frontmatter(page_text).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading_text = re.sub(r"^#{1,6}\s*", "", stripped).strip().lower()
            if heading_text in QUERY_HEADING_BLACKLIST:
                continue
        cleaned_lines.append(line)
    return markdown_to_plain_text("\n".join(cleaned_lines))


def tokenize_for_search(text: str) -> list[str]:
    # V1 先用一个非常保守、纯 Python 的中英混合切词器：
    # - 英文/数字连续串作为一个 token
    # - 中文按双字/三字滑窗补一层召回
    # 这样虽然不如专业中文分词细，但不引入额外依赖也能先把检索跑起来。
    normalized = normalize_claim_text(text)
    latin_tokens = re.findall(r"[a-z0-9_]+", normalized)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized)

    tokens = [token for token in latin_tokens if len(token) >= 2]
    if chinese_chars:
        joined = "".join(chinese_chars)
        # 单个中文字符召回虽然高，但噪声也很大；V1 默认从双字开始。
        for width in (2, 3):
            if len(joined) >= width:
                for index in range(len(joined) - width + 1):
                    tokens.append(joined[index:index + width])

    # 最后再补一层原始空格切分，给中英混排句子多一些命中机会。
    for part in normalized.split():
        if len(part) >= 2 and part not in tokens:
            tokens.append(part)
    return tokens


def normalize_query_text(text: str) -> str:
    return normalize_query_text_helper(
        text,
        normalize_claim_text=normalize_claim_text,
    )


def detect_query_intent(query_text: str, normalized_query: str) -> str:
    return detect_query_intent_helper(
        query_text,
        normalized_query,
        query_intent_markers=QUERY_INTENT_MARKERS,
    )


def alias_match_boost(page_record: dict, normalized_query: str, alias_hits: list[dict]) -> tuple[float, list[str]]:
    return alias_match_boost_helper(
        page_record,
        normalized_query,
        alias_hits,
        normalize_query_text=normalize_query_text,
        query_exact_match_max_boost=QUERY_EXACT_MATCH_MAX_BOOST,
    )


def query_intent_page_type_boost(intent: str, page_record: dict) -> tuple[float, str | None]:
    return query_intent_page_type_boost_helper(intent, page_record)


def query_intent_field_multiplier(intent: str, field_name: str) -> float:
    return query_intent_field_multiplier_helper(
        intent,
        field_name,
        query_intent_field_multipliers=QUERY_INTENT_FIELD_MULTIPLIERS,
    )


def expand_query_with_alias_registry(
    query_text: str,
    alias_index: dict,
) -> dict:
    return expand_query_with_alias_registry_helper(
        query_text,
        alias_index,
        normalize_query_text=normalize_query_text,
        tokenize_for_search=tokenize_for_search,
        detect_query_intent=detect_query_intent,
    )


def build_page_field_texts(page_record: dict, page_text: str, claim_records_by_id: dict[str, dict]) -> dict[str, str]:
    return repo_build_page_field_texts(
        page_record,
        page_text,
        claim_records_by_id,
        parse_section_path=parse_section_path,
        extract_markdown_headings=extract_markdown_headings,
        build_searchable_body_text=build_searchable_body_text,
    )


def compute_document_frequency(documents: list[dict[str, list[str]]], field_name: str) -> dict[str, int]:
    # BM25 需要知道“某个 token 出现在多少文档里”，这里按字段分别统计。
    frequency: dict[str, int] = {}
    for document in documents:
        unique_tokens = set(document.get(field_name, []))
        for token in unique_tokens:
            frequency[token] = frequency.get(token, 0) + 1
    return frequency


def bm25_score(
    query_tokens: list[str],
    document_tokens: list[str],
    document_frequency: dict[str, int],
    total_documents: int,
    average_length: float,
    k1: float = QUERY_BM25_K1,
    b: float = QUERY_BM25_B,
) -> float:
    # 这里实现标准 BM25 基线公式，不做额外花活，方便后面替换成索引引擎时对齐行为。
    if not query_tokens or not document_tokens or total_documents == 0:
        return 0.0

    token_counts = Counter(document_tokens)
    document_length = len(document_tokens)
    score = 0.0

    for token in query_tokens:
        term_frequency = token_counts.get(token, 0)
        if term_frequency == 0:
            continue

        doc_freq = document_frequency.get(token, 0)
        inverse_document_frequency = math.log(1 + (total_documents - doc_freq + 0.5) / (doc_freq + 0.5))
        numerator = term_frequency * (k1 + 1)
        denominator = term_frequency + k1 * (1 - b + b * (document_length / max(average_length, 1e-9)))
        score += inverse_document_frequency * (numerator / denominator)

    return score


def query_page_type_weight(page_record: dict) -> float:
    page_type = page_record.get("type", "source-summary")
    return QUERY_PAGE_TYPE_WEIGHTS.get(page_type, QUERY_PAGE_TYPE_WEIGHTS.get("draft", 0.70))


def query_page_status_weight(page_record: dict) -> float:
    status = page_record.get("status", "draft")
    return QUERY_PAGE_STATUS_WEIGHTS.get(status, QUERY_PAGE_STATUS_WEIGHTS["draft"])


def page_type_profile(page_type: str) -> str:
    normalized = str(page_type or "").strip().lower()
    if normalized == "guide":
        return "guide"
    if normalized == "example":
        return "example"
    if normalized == "topic":
        return "topic"
    if normalized == "reference":
        return "reference"
    if normalized == "timeline":
        return "timeline"
    if normalized == "concept":
        return "concept"
    if normalized == "source-summary":
        return "source"
    if normalized == "overview":
        return "overview"
    return "generic"


def build_query_documents(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
) -> list[dict]:
    return repo_build_query_documents(
        target,
        page_records,
        claim_records_by_id,
        filter_live_page_records=filter_live_page_records,
        build_page_field_texts=build_page_field_texts,
        tokenize_for_search=tokenize_for_search,
    )


def build_search_index_record(document: dict) -> dict:
    return repo_build_search_index_record(
        document,
        utc_now_iso=utc_now_iso,
        search_pages_index_version=SEARCH_PAGES_INDEX_VERSION,
    )


def write_search_pages_index(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
    previous_records: list[dict] | None = None,
) -> dict:
    return repo_write_search_pages_index(
        target,
        page_records,
        claim_records_by_id,
        previous_records,
        search_pages_index_rel_path=str(SEARCH_PAGES_INDEX_REL_PATH),
        search_pages_index_version=SEARCH_PAGES_INDEX_VERSION,
        filter_live_page_records=filter_live_page_records,
        build_page_field_texts=build_page_field_texts,
        tokenize_for_search=tokenize_for_search,
        write_jsonl=write_jsonl,
        utc_now_iso=utc_now_iso,
    )


def load_search_pages_index(target: Path) -> list[dict]:
    return repo_load_search_pages_index(
        target,
        search_pages_index_rel_path=SEARCH_PAGES_INDEX_REL_PATH,
        load_jsonl=load_jsonl,
    )


def index_records_to_query_documents(index_records: list[dict]) -> list[dict]:
    return repo_load_query_documents_from_search_index(index_records)


def ensure_query_documents(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
) -> tuple[list[dict], str]:
    return repo_ensure_query_documents(
        target,
        page_records,
        claim_records_by_id,
        load_search_pages_index=load_search_pages_index,
        load_query_documents_from_search_index=index_records_to_query_documents,
        build_query_documents=build_query_documents,
    )


def load_chunks_by_id(target: Path) -> dict[str, dict]:
    # chunk 阅读包要频繁按 chunk_id 回查，因此这里先建一个内存映射。
    chunks_path = target / "state" / "chunks.jsonl"
    if not chunks_path.exists():
        return {}
    chunk_records = load_jsonl(chunks_path)
    return {record["chunk_id"]: record for record in chunk_records}


def score_claim_for_query(query_tokens: list[str], claim_record: dict) -> tuple[float, list[str]]:
    return score_claim_for_query_helper(
        query_tokens,
        claim_record,
        tokenize_for_search=tokenize_for_search,
        select_top_matches=select_top_matches,
    )


def score_chunk_for_query(query_tokens: list[str], chunk_record: dict) -> tuple[float, list[str]]:
    return score_chunk_for_query_helper(
        query_tokens,
        chunk_record,
        tokenize_for_search=tokenize_for_search,
        select_top_matches=select_top_matches,
    )


def build_source_brief(source_ref: dict) -> dict:
    return build_source_brief_helper(source_ref)


def build_chunk_reading_brief(chunk_record: dict) -> dict:
    return build_chunk_reading_brief_helper(chunk_record)


def build_timeline_sources(chunk_matches: list[dict]) -> list[dict]:
    return build_timeline_sources_helper(chunk_matches)


def build_source_trail(claim_matches: list[dict], chunk_matches: list[dict]) -> list[dict]:
    return build_source_trail_helper(claim_matches, chunk_matches)


def build_hierarchy_match_explanation(result: dict, matched_chunks: list[dict]) -> dict:
    return build_hierarchy_match_explanation_helper(
        result,
        matched_chunks,
        parse_section_path=parse_section_path,
        tokenize_for_search=tokenize_for_search,
    )


def query_reading_focus(query_intent: str, page_type: str = "") -> str:
    return query_reading_focus_helper(query_intent, page_type=page_type)


def build_answer_guardrails(
    query_intent: str,
    page_status: str,
    page_type: str,
    review_ids: list[str],
    matched_claims: list[dict],
    matched_chunks: list[dict],
    timeline_sources: list[dict],
    source_trail: list[dict],
) -> dict:
    return build_answer_guardrails_helper(
        query_intent,
        page_status,
        page_type,
        review_ids,
        matched_claims,
        matched_chunks,
        timeline_sources,
        source_trail,
    )


def build_answer_handoff(query_intent: str, answer_guardrails: dict, page_type: str) -> dict:
    return build_answer_handoff_helper(query_intent, answer_guardrails, page_type)


def summarize_linked_page(page_record: dict, reason: str) -> dict:
    return {
        "page_id": page_record.get("page_id"),
        "title": page_record.get("title", ""),
        "page_path": page_record.get("page_path", ""),
        "type": page_record.get("type", ""),
        "status": page_record.get("status", ""),
        "canonical_id": page_record.get("canonical_id"),
        "summary": page_record.get("summary", ""),
        "reason": reason,
    }


def expand_related_pages_for_query_result(
    result: dict,
    page_records_by_id: dict[str, dict],
    page_links_index: dict,
    link_expansion: str,
) -> tuple[list[dict], dict]:
    return expand_related_pages_for_query_result_helper(
        result,
        page_records_by_id,
        page_links_index,
        link_expansion,
        is_live_page_record=is_live_page_record,
    )


def build_result_reading_pack(
    result: dict,
    query_text: str,
    normalized_query: str,
    query_tokens: list[str],
    claim_records_by_id: dict[str, dict],
    chunk_records_by_id: dict[str, dict],
    page_records_by_id: dict[str, dict],
    page_links_index: dict,
    claim_limit: int,
    chunk_limit: int,
    query_intent: str,
    link_expansion: str,
) -> dict:
    return build_result_reading_pack_helper(
        result,
        query_text,
        normalized_query,
        query_tokens,
        claim_records_by_id,
        chunk_records_by_id,
        page_records_by_id,
        page_links_index,
        claim_limit,
        chunk_limit,
        query_intent,
        link_expansion,
        score_claim_for_query=score_claim_for_query,
        build_source_brief=build_source_brief,
        score_chunk_for_query=score_chunk_for_query,
        build_chunk_reading_brief=build_chunk_reading_brief,
        build_source_trail=build_source_trail,
        build_timeline_sources=build_timeline_sources,
        query_reading_focus=query_reading_focus,
        build_hierarchy_match_explanation=build_hierarchy_match_explanation,
        expand_related_pages_for_query_result=expand_related_pages_for_query_result,
        build_answer_guardrails=build_answer_guardrails,
        build_answer_handoff=build_answer_handoff,
        query_answer_handoff_contract_version=QUERY_ANSWER_HANDOFF_CONTRACT_VERSION,
        page_type_profile=page_type_profile,
    )


def build_answer_ready_payload(query_payload: dict) -> dict:
    return build_answer_ready_payload_helper(
        query_payload,
        answer_ready_output_version=ANSWER_READY_OUTPUT_VERSION,
        page_type_profile=page_type_profile,
    )


def render_answer_ready_message(answer_ready_payload: dict) -> str:
    return render_answer_ready_message_helper(answer_ready_payload)


def render_answer_ready_prompt(answer_ready_payload: dict) -> str:
    return render_answer_ready_prompt_helper(answer_ready_payload)


def build_answer_ready_messages(answer_ready_payload: dict) -> list[dict]:
    return build_answer_ready_messages_helper(answer_ready_payload)


def render_answer_ready_chatml(answer_ready_payload: dict) -> str:
    return render_answer_ready_chatml_helper(answer_ready_payload)


def select_top_matches(query_tokens: list[str], field_tokens: list[str], limit: int = 5) -> list[str]:
    return select_top_matches_helper(query_tokens, field_tokens, limit=limit)


def build_query_payload(
    target: Path,
    query_text: str,
    limit: int,
    claim_limit: int,
    chunk_limit: int,
    reading_depth: str = "standard",
    intent: str | None = None,
    link_expansion: str = "auto",
) -> dict:
    return query_cli_component.build_query_payload(
        build_query_cli_deps(),
        target=target,
        query_text=query_text,
        limit=limit,
        claim_limit=claim_limit,
        chunk_limit=chunk_limit,
        reading_depth=reading_depth,
        intent=intent,
        link_expansion=link_expansion,
    )


def command_query(args: argparse.Namespace) -> CommandResult:
    return query_cli_component.command_query(build_query_cli_deps(), args)


def command_answer_query(args: argparse.Namespace) -> CommandResult:
    return query_cli_component.command_answer_query(build_query_cli_deps(), args)


def build_query_cli_deps() -> QueryCliDeps:
    return QueryCliDeps(
        provider=sys.modules[__name__],
        ensure_workspace_schema_supported=ensure_workspace_schema_supported,
        render_workspace_summary_message=render_workspace_summary_message,
        render_answer_ready_message=render_answer_ready_message,
        format_claim_type_label=format_claim_type_label,
        reading_depth_limits=QUERY_READING_DEPTH_LIMITS,
        link_expansion_choices=QUERY_LINK_EXPANSION_CHOICES,
        build_query_payload=build_query_payload,
        build_answer_ready_payload=build_answer_ready_payload,
        render_answer_ready_prompt=render_answer_ready_prompt,
        build_answer_ready_messages=build_answer_ready_messages,
        render_answer_ready_chatml=render_answer_ready_chatml,
    )


def build_review_cli_deps() -> ReviewCliDeps:
    return ReviewCliDeps(
        ensure_workspace_schema_supported=ensure_workspace_schema_supported,
        load_claim_state_maps=load_claim_state_maps,
        load_review_state_maps=load_review_state_maps,
        build_claim_lookup_by_any_id=build_claim_lookup_by_any_id,
        refresh_alias_conflict_reviews=refresh_alias_conflict_reviews,
        persist_ordered_review_state=lambda workspace_target, live_reviews_by_id, historical_reviews_by_id: repo_persist_ordered_review_state(
            workspace_target,
            live_reviews_by_id=live_reviews_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
            build_ordered_review_state_records=build_ordered_review_state_records,
            persist_review_records=lambda target_for_repo, review_records: repo_persist_review_records(
                target_for_repo,
                review_records=review_records,
                write_jsonl=write_jsonl,
                write_review_file=write_review_file,
            ),
        ),
        persist_ordered_claim_state=lambda workspace_target, live_claims_by_id, historical_claims_by_id: repo_persist_ordered_claim_state(
            workspace_target,
            live_claims_by_id=live_claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
            build_ordered_claim_state_records=build_ordered_claim_state_records,
            persist_claim_records=lambda target_for_repo, claim_records: repo_persist_claim_records(
                target_for_repo,
                claim_records=claim_records,
                write_jsonl=write_jsonl,
                write_claim_file=write_claim_file,
            ),
        ),
        cleanup_review_related_record_files=lambda workspace_target, historical_claims_by_id, historical_reviews_by_id: repo_cleanup_review_related_record_files(
            workspace_target,
            historical_claims_by_id=historical_claims_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
            cleanup_superseded_record_files=cleanup_superseded_record_files,
        ),
        review_display_id=review_display_id,
        claim_display_id=claim_display_id,
        apply_review_action=apply_review_action,
        build_ordered_claim_state_records=build_ordered_claim_state_records,
        rebuild_review_affected_pages=rebuild_review_affected_pages,
        build_workspace_summary=build_workspace_summary,
        render_workspace_summary_message=render_workspace_summary_message,
        load_workspace_config=load_workspace_config,
        load_automation_target_config=load_automation_target_config,
        propose_review_auto_action=propose_review_auto_action,
        is_actionable_review_record=is_actionable_review_record,
        claim_record_is_safe_auto_stable_candidate=claim_record_is_safe_auto_stable_candidate,
        maybe_get_agent_assisted_stable_promotion=maybe_get_agent_assisted_stable_promotion,
        utc_now_iso=utc_now_iso,
        build_review_auto_escalation_entry=build_review_auto_escalation_entry,
        build_review_auto_agent_handoff=build_review_auto_agent_handoff,
        review_auto_handoff_contract_version=REVIEW_AUTO_HANDOFF_CONTRACT_VERSION,
        render_review_auto_prompt=render_review_auto_prompt,
        build_review_auto_messages=build_review_auto_messages,
        render_review_auto_chatml=render_review_auto_chatml,
        render_review_auto_message=render_review_auto_message,
    )


def command_review_list(args: argparse.Namespace) -> CommandResult:
    return review_cli_component.command_review_list(build_review_cli_deps(), args)


def choose_auto_merge_primary_claim_id(candidate_claim_ids: list[str], live_claims_by_id: dict[str, dict]) -> str | None:
    live_candidates = [live_claims_by_id[claim_id] for claim_id in candidate_claim_ids if claim_id in live_claims_by_id]
    if len(live_candidates) != len(candidate_claim_ids):
        return None
    if len(live_candidates) != 2:
        return None
    ranked = sorted(
        live_candidates,
        key=lambda item: (
            len(item.get("source_ids", [])),
            len(clean_claim_candidate_text(item.get("text", ""))),
            item.get("created_at", ""),
            item["claim_id"],
        ),
        reverse=True,
    )
    return ranked[0]["claim_id"] if ranked else None


def build_review_auto_decision_payload(
    review_record: dict,
    live_claims_by_id: dict[str, dict],
    target: Path,
) -> dict:
    return build_review_auto_decision_payload_helper(
        review_record,
        live_claims_by_id,
        target,
        ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
        load_jsonl=load_jsonl,
        load_alias_index=load_alias_index,
        alias_index_matches_for_value=alias_index_matches_for_value,
    )


def normalize_review_auto_hook_plan(
    hook_result: dict,
    review_record: dict,
    base_plan: dict,
    live_claims_by_id: dict[str, dict],
    min_confidence: float,
) -> dict | None:
    return normalize_review_auto_hook_plan_helper(
        hook_result,
        review_record,
        base_plan,
        live_claims_by_id,
        min_confidence,
        coerce_float=coerce_float,
        choose_auto_merge_primary_claim_id=choose_auto_merge_primary_claim_id,
    )


def maybe_get_agent_assisted_review_plan(
    target: Path,
    review_record: dict,
    live_claims_by_id: dict[str, dict],
    automation_config: dict,
    base_plan: dict,
) -> dict | None:
    return maybe_get_agent_assisted_review_plan_helper(
        target,
        review_record,
        live_claims_by_id,
        automation_config,
        base_plan,
        build_review_auto_decision_payload=build_review_auto_decision_payload,
        run_json_automation_command=run_json_automation_command,
        normalize_review_auto_hook_plan=normalize_review_auto_hook_plan,
    )


def review_action_plain_label(action: str) -> str:
    return review_action_plain_label_helper(action)


def claim_record_is_safe_auto_stable_candidate(
    claim_record: dict,
    live_reviews_by_id: dict[str, dict],
) -> tuple[bool, str | None]:
    return claim_record_is_safe_auto_stable_candidate_helper(
        claim_record,
        live_reviews_by_id,
        is_actionable_review_record=is_actionable_review_record,
        clean_claim_candidate_text=clean_claim_candidate_text,
        claim_candidate_is_noise=claim_candidate_is_noise,
        claim_starts_with_dependent_prefix=claim_starts_with_dependent_prefix,
        text_is_question_like=text_is_question_like,
        claim_candidate_has_short_gray_zone=claim_candidate_has_short_gray_zone,
        claim_can_stand_alone=claim_can_stand_alone,
    )


def build_stable_promotion_payload(claim_record: dict) -> dict:
    return build_stable_promotion_payload_helper(claim_record)


def maybe_get_agent_assisted_stable_promotion(
    target: Path,
    claim_record: dict,
    automation_config: dict,
) -> tuple[bool, str | None]:
    return maybe_get_agent_assisted_stable_promotion_helper(
        target,
        claim_record,
        automation_config,
        run_json_automation_command=run_json_automation_command,
        build_stable_promotion_payload=build_stable_promotion_payload,
        coerce_float=coerce_float,
    )


def build_review_auto_escalation_entry(
    review_record: dict,
    plan: dict,
    live_claims_by_id: dict[str, dict],
) -> dict:
    return build_review_auto_escalation_entry_helper(
        review_record,
        plan,
        live_claims_by_id,
        review_display_id=review_display_id,
    )


def build_review_auto_agent_handoff(
    auto_apply_plans: list[dict],
    escalated_entries: list[dict],
    promoted_claims: list[dict],
    review_automation_config: dict,
    stable_automation_config: dict,
) -> tuple[dict, str]:
    return build_review_auto_agent_handoff_helper(
        auto_apply_plans,
        escalated_entries,
        promoted_claims,
        review_automation_config,
        stable_automation_config,
    )


def render_review_auto_message(review_auto_payload: dict) -> str:
    return render_review_auto_message_helper(review_auto_payload)


def render_review_auto_prompt(review_auto_payload: dict) -> str:
    return render_review_auto_prompt_helper(review_auto_payload)


def build_review_auto_messages(review_auto_payload: dict) -> list[dict]:
    return build_review_auto_messages_helper(review_auto_payload)


def render_review_auto_chatml(review_auto_payload: dict) -> str:
    return render_review_auto_chatml_helper(review_auto_payload)


def run_post_ingest_review_auto(target: Path) -> dict:
    return review_cli_component.run_post_ingest_review_auto(build_review_cli_deps(), target)


def render_post_ingest_review_auto_summary(review_auto_payload: dict | None) -> str | None:
    if not review_auto_payload:
        return None
    summary = review_auto_payload.get("summary", {})
    agent_brief = review_auto_payload.get("agent_brief", {})
    return (
        "Auto review: "
        f"applied={summary.get('applied_count', 0)}, "
        f"escalated={summary.get('escalated_count', 0)}, "
        f"promoted_claims={summary.get('promoted_claim_count', 0)}, "
        f"next_action={agent_brief.get('next_action', 'continue_with_normal_workflow')}"
    )


def propose_review_auto_action(
    target: Path,
    review_record: dict,
    live_claims_by_id: dict[str, dict],
    automation_config: dict,
) -> dict:
    return propose_review_auto_action_helper(
        target,
        review_record,
        live_claims_by_id,
        automation_config,
        review_display_id=review_display_id,
        is_actionable_review_record=is_actionable_review_record,
        maybe_get_agent_assisted_review_plan=maybe_get_agent_assisted_review_plan,
        choose_auto_merge_primary_claim_id=choose_auto_merge_primary_claim_id,
    )


def command_review_auto(args: argparse.Namespace) -> CommandResult:
    return review_cli_component.command_review_auto(build_review_cli_deps(), args)


def rebuild_review_affected_pages(
    target: Path,
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
) -> None:
    # review 动作完成后，如果不刷新页面，wiki 页面与 query 索引会滞后。
    # 这里走一个“小范围账本重建”：
    # 1. 重新根据 live claims / live reviews 计算 source-summary / concept
    # 2. 移除不再需要的自动页
    # 3. 重建 pages.jsonl / wiki/index.md / search index
    config = load_workspace_config(target)
    readable_concept_render_config = load_readable_concept_render_config(config)
    overview_render_config = load_page_render_config(config, "overview")
    page_intent_config = load_semantic_task_config(config, "page_intent")
    sources_path = target / "state" / "sources.jsonl"
    normalized_path = target / "state" / "normalized.jsonl"
    pages_path = target / "state" / "pages.jsonl"
    chunks_path = target / "state" / "chunks.jsonl"

    sources_by_id = {
        record["source_id"]: record
        for record in load_jsonl(sources_path)
    }
    normalized_records_by_source = {
        record["source_id"]: record
        for record in load_jsonl(normalized_path)
    }
    chunk_records = load_jsonl(chunks_path)
    chunks_by_source_id: dict[str, list[dict]] = {}
    for chunk_record in chunk_records:
        chunks_by_source_id.setdefault(chunk_record["source_id"], []).append(chunk_record)

    page_records = [ensure_page_lifecycle_defaults(record) for record in load_jsonl(pages_path)]
    page_records_by_id = {record["page_id"]: record for record in page_records}
    active_source_ids = choose_active_source_ids(sources_by_id)
    run_review_rebuild_page_regeneration(
        ReviewRebuildPageContext(
            target=target,
            config=config,
            readable_concept_render_config=readable_concept_render_config,
            overview_render_config=overview_render_config,
            page_intent_config=page_intent_config,
            sources_by_id=sources_by_id,
            normalized_records_by_source=normalized_records_by_source,
            chunks_by_source_id=chunks_by_source_id,
            page_records_by_id=page_records_by_id,
            active_source_ids=active_source_ids,
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
        ),
        deps=ReviewRebuildPageDeps(
            is_actionable_review_record=is_actionable_review_record,
            utc_now_iso=utc_now_iso,
            source_summary_page_path=source_summary_page_path,
            build_source_summary_page=build_source_summary_page,
            apply_page_alias_overrides=apply_page_alias_overrides,
            upsert_wiki_page=upsert_wiki_page,
            link_claims_to_page_in_memory=link_claims_to_page_in_memory,
            build_concept_group_key=build_concept_group_key,
            regroup_concept_claims_by_canonical_topic=regroup_concept_claims_by_canonical_topic,
            apply_page_intent_decisions_to_claim_groups=apply_page_intent_decisions_to_claim_groups,
            page_route_for_bucket=page_route_for_bucket,
            preferred_page_intent_for_claim_group=preferred_page_intent_for_claim_group,
            should_generate_concept_page=should_generate_concept_page,
            choose_group_topic_label=choose_group_topic_label,
            choose_canonical_claim=choose_canonical_claim,
            resolve_concept_title_candidate=resolve_concept_title_candidate,
            build_concept_page_id=build_concept_page_id,
            concept_summary_page_path=concept_summary_page_path,
            build_concept_page=build_concept_page,
            apply_page_route_to_page_record=apply_page_route_to_page_record,
            link_reviews_to_page_in_memory=link_reviews_to_page_in_memory,
            page_intent_page_id=page_intent_page_id,
            page_intent_page_path=page_intent_page_path,
            build_intent_routed_page=build_intent_routed_page,
            collect_workspace_overview_concept_pages=collect_workspace_overview_concept_pages,
            should_generate_workspace_overview_page=should_generate_workspace_overview_page,
            workspace_overview_page_path=workspace_overview_page_path,
            build_workspace_overview_page=build_workspace_overview_page,
            build_workspace_overview_page_id=build_workspace_overview_page_id,
            expected_source_summary_page_id=expected_source_summary_page_id,
            prune_stale_auto_pages=prune_stale_auto_pages,
        ),
    )
    run_review_rebuild_persistence(
        ReviewRebuildPersistContext(
            target=target,
            page_records_by_id=page_records_by_id,
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
        ),
        deps=ReviewRebuildPersistDeps(
            load_claim_state_records=lambda workspace_target: load_jsonl(workspace_target / "state" / "claims.jsonl"),
            ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
            build_ordered_claim_state_records=build_ordered_claim_state_records,
            write_jsonl=write_jsonl,
            write_claim_file=write_claim_file,
            load_review_state_records=lambda workspace_target: load_jsonl(workspace_target / "state" / "reviews.jsonl"),
            ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
            is_live_review_record=is_live_review_record,
            build_ordered_review_state_records=build_ordered_review_state_records,
            write_review_file=write_review_file,
            write_page_links_index=write_page_links_index,
            rebuild_wiki_index=rebuild_wiki_index,
            write_alias_index=write_alias_index,
            refresh_alias_conflict_reviews=refresh_alias_conflict_reviews,
            cleanup_superseded_record_files=cleanup_superseded_record_files,
            load_search_pages_index=load_search_pages_index,
            write_search_pages_index=write_search_pages_index,
        ),
    )

def resolve_claim_record_for_action(
    claim_id: str,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
) -> dict:
    return resolve_claim_record_for_action_helper(
        claim_id,
        live_claims_by_id,
        historical_claims_by_id,
        build_claim_lookup_by_any_id=build_claim_lookup_by_any_id,
    )


def archive_live_claim(
    claim_record: dict,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    archived_by_claim_id: str | None = None,
) -> dict:
    return archive_live_claim_helper(
        claim_record,
        live_claims_by_id,
        historical_claims_by_id,
        utc_now_iso=utc_now_iso,
        append_unique=append_unique,
        convert_claim_record_to_historical=convert_claim_record_to_historical,
        archived_by_claim_id=archived_by_claim_id,
    )


def normalize_claim_review_flags(claim_record: dict) -> None:
    normalize_claim_review_flags_helper(
        claim_record,
        utc_now_iso=utc_now_iso,
    )


def sync_claim_review_state_from_open_reviews(
    claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
) -> set[str]:
    return sync_claim_review_state_from_open_reviews_helper(
        claim_ids,
        live_claims_by_id,
        live_reviews_by_id,
        is_actionable_review_record=is_actionable_review_record,
        normalize_claim_review_flags=normalize_claim_review_flags,
    )


def rewrite_open_reviews_for_claim_change(
    changed_review_id: str,
    removed_claim_id: str,
    replacement_claim_id: str | None,
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
) -> tuple[set[str], set[str]]:
    return rewrite_open_reviews_for_claim_change_helper(
        changed_review_id,
        removed_claim_id,
        replacement_claim_id,
        live_claims_by_id,
        live_reviews_by_id,
        utc_now_iso=utc_now_iso,
        review_lifecycle_status_for_record=review_lifecycle_status_for_record,
        sync_claim_review_state_from_open_reviews=sync_claim_review_state_from_open_reviews,
    )


def cleanup_superseded_record_files(
    target: Path,
    historical_claims_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
) -> None:
    cleanup_superseded_record_files_helper(
        target,
        historical_claims_by_id,
        historical_reviews_by_id,
        claim_file_path=claim_file_path,
        review_file_path=review_file_path,
    )


def reload_claims_from_disk_for_review(
    target: Path,
    claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
) -> set[str]:
    return reload_claims_from_disk_for_review_helper(
        target,
        claim_ids,
        live_claims_by_id,
        claim_file_path=claim_file_path,
        ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
        load_json=load_json,
    )


def apply_review_action(
    target: Path,
    review_record: dict,
    action: str,
    primary_claim_id: str | None,
    secondary_claim_id: str | None,
    primary_page_id: str | None,
    alias_value: str | None,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
) -> dict:
    return apply_review_action_via_helpers(
        target=target,
        review_record=review_record,
        action=action,
        primary_claim_id=primary_claim_id,
        secondary_claim_id=secondary_claim_id,
        primary_page_id=primary_page_id,
        alias_value=alias_value,
        live_claims_by_id=live_claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
        deps=ReviewActionDeps(
            review_display_id=review_display_id,
            utc_now_iso=utc_now_iso,
            load_live_page_aliases_by_id=load_live_page_aliases_by_id,
            load_page_state_records=lambda workspace_target: repo_load_page_state_records(
                workspace_target,
                load_jsonl=load_jsonl,
                ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
            ),
            apply_alias_override_action=apply_alias_override_action,
            apply_page_alias_overrides_payload=apply_page_alias_overrides_payload,
            build_alias_index=build_alias_index,
            alias_index_matches_for_value=alias_index_matches_for_value,
            clear_accepted_alias_conflict=clear_accepted_alias_conflict,
            update_page_alias_overrides_with_lock=update_page_alias_overrides_with_lock,
            persist_accepted_alias_conflict=persist_accepted_alias_conflict,
            sync_claim_review_state_from_open_reviews=sync_claim_review_state_from_open_reviews,
            reload_claims_from_disk_for_review=reload_claims_from_disk_for_review,
            resolve_claim_record_for_action=resolve_claim_record_for_action,
            archive_live_claim=archive_live_claim,
            rewrite_open_reviews_for_claim_change=rewrite_open_reviews_for_claim_change,
            merge_claim_records=merge_claim_records,
            normalize_claim_review_flags=normalize_claim_review_flags,
        ),
    )


def command_review_apply(args: argparse.Namespace) -> CommandResult:
    return review_cli_component.command_review_apply(build_review_cli_deps(), args)


def command_init(args: argparse.Namespace) -> CommandResult:
    return init_cli_component.command_init(
        build_init_cli_component_deps(
            find_project_root=find_project_root,
            structure_blocks_rel_path=STRUCTURE_BLOCKS_REL_PATH,
            evidence_blocks_rel_path=EVIDENCE_BLOCKS_REL_PATH,
            knowledge_units_rel_path=KNOWLEDGE_UNITS_REL_PATH,
            semantic_decisions_rel_path=SEMANTIC_DECISIONS_REL_PATH,
            search_pages_index_rel_path=SEARCH_PAGES_INDEX_REL_PATH,
            render_template=render_template,
            ensure_clean_target=ensure_clean_target,
            ensure_directory=ensure_directory,
            write_jsonl=write_jsonl,
            write_alias_index=write_alias_index,
            git_init_and_commit=git_init_and_commit,
            build_workspace_summary=build_workspace_summary,
            render_workspace_summary_message=render_workspace_summary_message,
        ),
        args,
    )


def build_misc_cli_deps(
    *,
    load_page_state_records: object,
    load_claim_state_maps_override: object | None = None,
    load_review_state_maps_override: object | None = None,
) -> MiscCliDeps:
    return build_misc_cli_component_deps(
        find_project_root=find_project_root,
        workspace_schema_guard_payload=workspace_schema_guard_payload,
        load_simple_yaml=load_simple_yaml,
        resolve_workspace_path=resolve_workspace_path,
        load_jsonl=load_jsonl,
        load_semantic_decisions=load_semantic_decisions,
        ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
        filter_live_claim_records=filter_live_claim_records,
        is_live_claim_record=is_live_claim_record,
        ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
        filter_live_review_records=filter_live_review_records,
        is_live_review_record=is_live_review_record,
        load_page_state_records=load_page_state_records,
        ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
        filter_live_page_records=filter_live_page_records,
        is_live_page_record=is_live_page_record,
        claim_semantic_risk_issues=claim_semantic_risk_issues,
        rendered_page_grounding_issues=rendered_page_grounding_issues,
        concept_page_quality_issues=concept_page_quality_issues,
        page_semantic_consistency_issues=page_semantic_consistency_issues,
        page_intent_brake_issues=page_intent_brake_issues,
        load_alias_index=load_alias_index,
        alias_index_path=alias_index_path,
        unresolved_alias_conflicts=unresolved_alias_conflicts,
        load_search_pages_index=load_search_pages_index,
        atomic_write_text=atomic_write_text,
        build_workspace_summary=build_workspace_summary,
        render_workspace_summary_message=render_workspace_summary_message,
        alias_index_rel_path=str(ALIAS_INDEX_REL_PATH),
        search_pages_index_rel_path=str(SEARCH_PAGES_INDEX_REL_PATH),
        structure_blocks_rel_path=str(STRUCTURE_BLOCKS_REL_PATH),
        evidence_blocks_rel_path=str(EVIDENCE_BLOCKS_REL_PATH),
        knowledge_units_rel_path=str(KNOWLEDGE_UNITS_REL_PATH),
        semantic_decisions_rel_path=str(SEMANTIC_DECISIONS_REL_PATH),
        ensure_workspace_schema_supported=ensure_workspace_schema_supported,
        page_render_targets=PAGE_RENDER_TARGETS,
        load_claim_state_maps=load_claim_state_maps_override or load_claim_state_maps,
        load_review_state_maps=load_review_state_maps_override or load_review_state_maps,
        rebuild_review_affected_pages=rebuild_review_affected_pages,
        live_pages_for_render_target=live_pages_for_render_target,
        page_record_render_target=page_record_render_target,
        run_semantic_batch_task=run_semantic_batch_task,
        is_actionable_review_record=is_actionable_review_record,
        utc_now_iso=utc_now_iso,
    )


def command_lint(args: argparse.Namespace) -> CommandResult:
    return misc_cli_component.command_lint(
        build_misc_cli_deps(
            load_page_state_records=repo_build_page_state_records_loader(
                load_jsonl=load_jsonl,
                ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
            ),
            load_claim_state_maps_override=repo_build_claim_state_maps_loader(
                load_jsonl=load_jsonl,
                ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
                filter_live_claim_records=filter_live_claim_records,
                is_live_claim_record=is_live_claim_record,
            ),
            load_review_state_maps_override=repo_build_review_state_maps_loader(
                load_jsonl=load_jsonl,
                ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
                filter_live_review_records=filter_live_review_records,
                is_live_review_record=is_live_review_record,
            ),
        ),
        args,
    )


def command_render_page(args: argparse.Namespace) -> CommandResult:
    return misc_cli_component.command_render_page(
        build_misc_cli_deps(
            load_page_state_records=repo_build_page_state_records_loader(
                load_jsonl=load_jsonl,
                ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
            ),
            load_claim_state_maps_override=repo_build_claim_state_maps_loader(
                load_jsonl=load_jsonl,
                ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
                filter_live_claim_records=filter_live_claim_records,
                is_live_claim_record=is_live_claim_record,
            ),
            load_review_state_maps_override=repo_build_review_state_maps_loader(
                load_jsonl=load_jsonl,
                ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
                filter_live_review_records=filter_live_review_records,
                is_live_review_record=is_live_review_record,
            ),
        ),
        args,
    )


def command_semantic_batch(args: argparse.Namespace) -> CommandResult:
    return misc_cli_component.command_semantic_batch(
        build_misc_cli_deps(
            load_page_state_records=repo_build_page_state_records_loader(
                load_jsonl=load_jsonl,
                ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
            ),
        ),
        args,
    )


def command_claim_set_status(args: argparse.Namespace) -> CommandResult:
    return misc_cli_component.command_claim_set_status(
        build_misc_cli_deps(
            load_page_state_records=repo_build_page_state_records_loader(
                load_jsonl=load_jsonl,
                ensure_page_lifecycle_defaults=ensure_page_lifecycle_defaults,
            ),
            load_claim_state_maps_override=repo_build_claim_state_maps_loader(
                load_jsonl=load_jsonl,
                ensure_claim_lifecycle_defaults=ensure_claim_lifecycle_defaults,
                filter_live_claim_records=filter_live_claim_records,
                is_live_claim_record=is_live_claim_record,
            ),
            load_review_state_maps_override=repo_build_review_state_maps_loader(
                load_jsonl=load_jsonl,
                ensure_review_lifecycle_defaults=ensure_review_lifecycle_defaults,
                filter_live_review_records=filter_live_review_records,
                is_live_review_record=is_live_review_record,
            ),
        ),
        args,
    )


def build_ingest_cli_deps() -> IngestCliDeps:
    return ingest_cli_component.build_ingest_cli_deps(sys.modules[__name__])


def command_ingest(args: argparse.Namespace) -> CommandResult:
    return ingest_cli_component.command_ingest(build_ingest_cli_deps(), args)


def build_parser() -> argparse.ArgumentParser:
    return build_cli_parser(
        command_init=command_init,
        command_ingest=command_ingest,
        command_lint=command_lint,
        command_query=command_query,
        command_answer_query=command_answer_query,
        command_render_page=command_render_page,
        command_semantic_batch=command_semantic_batch,
        command_claim_set_status=command_claim_set_status,
        command_review_list=command_review_list,
        command_review_auto=command_review_auto,
        command_review_apply=command_review_apply,
        query_reading_depth_limits=QUERY_READING_DEPTH_LIMITS,
        query_link_expansion_choices=QUERY_LINK_EXPANSION_CHOICES,
        semantic_task_names=SEMANTIC_TASK_NAMES,
        supported_page_render_targets=supported_page_render_targets,
    )


def main() -> int:
    # main 保持很薄，只负责“解析参数 -> 调用命令 -> 输出结果”这条主线。
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except HookExecutionError as exc:
        result = CommandResult(exit_code=1, payload=exc.payload, message=exc.message)
    return print_result(result, as_json=getattr(args, "json", False))


if __name__ == "__main__":
    raise SystemExit(main())
