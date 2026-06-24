from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from ..app_services.init_service import InitRequest, InitServiceDeps, run_init_service
from .result import CommandResult


@dataclass(frozen=True)
class InitCliDeps:
    find_project_root: object
    structure_blocks_rel_path: Path
    evidence_blocks_rel_path: Path
    knowledge_units_rel_path: Path
    semantic_decisions_rel_path: Path
    search_pages_index_rel_path: Path
    render_template: object
    ensure_clean_target: object
    ensure_directory: object
    write_jsonl: object
    write_alias_index: object
    git_init_and_commit: object
    build_workspace_summary: object
    render_workspace_summary_message: object


def build_init_cli_deps(
    *,
    find_project_root: object,
    structure_blocks_rel_path: Path,
    evidence_blocks_rel_path: Path,
    knowledge_units_rel_path: Path,
    semantic_decisions_rel_path: Path,
    search_pages_index_rel_path: Path,
    render_template: object,
    ensure_clean_target: object,
    ensure_directory: object,
    write_jsonl: object,
    write_alias_index: object,
    git_init_and_commit: object,
    build_workspace_summary: object,
    render_workspace_summary_message: object,
) -> InitCliDeps:
    return InitCliDeps(
        find_project_root=find_project_root,
        structure_blocks_rel_path=structure_blocks_rel_path,
        evidence_blocks_rel_path=evidence_blocks_rel_path,
        knowledge_units_rel_path=knowledge_units_rel_path,
        semantic_decisions_rel_path=semantic_decisions_rel_path,
        search_pages_index_rel_path=search_pages_index_rel_path,
        render_template=render_template,
        ensure_clean_target=ensure_clean_target,
        ensure_directory=ensure_directory,
        write_jsonl=write_jsonl,
        write_alias_index=write_alias_index,
        git_init_and_commit=git_init_and_commit,
        build_workspace_summary=build_workspace_summary,
        render_workspace_summary_message=render_workspace_summary_message,
    )


def command_init(deps: InitCliDeps, args: argparse.Namespace) -> CommandResult:
    payload = run_init_service(
        InitRequest(
            project_name=args.project_name,
            source_dir=args.source_dir,
            target_dir=args.target_dir,
        ),
        InitServiceDeps(
            repo_root=deps.find_project_root(),
            python_executable=sys.executable,
            structure_blocks_rel_path=deps.structure_blocks_rel_path,
            evidence_blocks_rel_path=deps.evidence_blocks_rel_path,
            knowledge_units_rel_path=deps.knowledge_units_rel_path,
            semantic_decisions_rel_path=deps.semantic_decisions_rel_path,
            search_pages_index_rel_path=deps.search_pages_index_rel_path,
            render_template=deps.render_template,
            ensure_clean_target=deps.ensure_clean_target,
            ensure_directory=deps.ensure_directory,
            write_jsonl=deps.write_jsonl,
            write_alias_index=deps.write_alias_index,
            git_init_and_commit=deps.git_init_and_commit,
            build_workspace_summary=deps.build_workspace_summary,
        ),
    )
    target_dir = Path(payload["target_dir"])
    raw_dir = Path(payload["raw_dir"])
    raw_dir_preexisting = bool(payload["raw_dir_preexisting"])
    return CommandResult(
        payload=payload,
        message=deps.render_workspace_summary_message(
            "Workspace initialized.",
            target_dir=target_dir,
            raw_dir=raw_dir,
            extra_lines=[
                f"Project name: {args.project_name}",
                f"Raw directory existed before init: {'yes' if raw_dir_preexisting else 'no'}",
            ],
        ),
    )
