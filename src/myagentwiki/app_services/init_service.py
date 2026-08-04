from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class InitRequest:
    project_name: str
    source_dir: str | None
    target_dir: str | None


@dataclass(frozen=True)
class InitServiceDeps:
    repo_root: Path
    python_executable: str
    structure_blocks_rel_path: Path
    evidence_blocks_rel_path: Path
    knowledge_units_rel_path: Path
    semantic_decisions_rel_path: Path
    search_pages_index_rel_path: Path
    render_template: Callable[[Path, dict[str, str]], str]
    ensure_clean_target: Callable[[Path], None]
    ensure_directory: Callable[[Path], None]
    write_jsonl: Callable[[Path, list[dict]], None]
    write_alias_index: Callable[[Path, list[dict]], dict]
    git_init_and_commit: Callable[[Path], list[str]]
    build_workspace_summary: Callable[[Path, Path | None], dict]


def run_init_service(request: InitRequest, deps: InitServiceDeps) -> dict:
    raw_dir = Path(request.source_dir).expanduser().resolve() if request.source_dir else None
    target_dir = Path(request.target_dir).expanduser().resolve() if request.target_dir else None

    if raw_dir is None and target_dir is None:
        target_dir = (Path.cwd() / request.project_name).resolve()
        raw_dir = (target_dir.parent / "raw").resolve()
    elif raw_dir is not None and target_dir is None:
        target_dir = (raw_dir.parent / request.project_name).resolve()
    elif raw_dir is None and target_dir is not None:
        raw_dir = (target_dir.parent / "raw").resolve()

    assert raw_dir is not None
    assert target_dir is not None
    if raw_dir.name != "raw":
        raise ValueError(f"Raw directory must be named 'raw': {raw_dir}")
    if raw_dir.parent != target_dir.parent:
        raise ValueError(
            f"Raw directory must be a sibling of the workspace: raw={raw_dir} target={target_dir}"
        )
    if raw_dir.exists() and not raw_dir.is_dir():
        raise FileExistsError(f"Raw path exists but is not a directory: {raw_dir}")

    deps.ensure_clean_target(target_dir)
    deps.ensure_directory(target_dir)
    raw_dir_preexisting = raw_dir.exists()
    assets_dir = (raw_dir.parent / "assets").resolve()
    assets_dir_preexisting = assets_dir.exists()
    deps.ensure_directory(raw_dir)
    deps.ensure_directory(assets_dir)
    raw_dir_relative_path = os.path.relpath(raw_dir, start=target_dir).replace(os.sep, "/")
    assets_dir_relative_path = os.path.relpath(assets_dir, start=target_dir).replace(os.sep, "/")

    context = {
        "project_name": request.project_name,
        "source_dir_name": raw_dir.name,
        "source_dir_path": str(raw_dir),
        "raw_dir_name": raw_dir.name,
        "raw_dir_path": str(raw_dir),
        "raw_dir_relative_path": raw_dir_relative_path,
        "assets_dir_name": assets_dir.name,
        "assets_dir_path": str(assets_dir),
        "assets_dir_relative_path": assets_dir_relative_path,
        "python_executable": deps.python_executable,
    }

    workspace_directories = (
        "normalized",
        "chunks",
        "claims",
        "semantic",
        "semantic/batches",
        "wiki",
        "indexes",
        "state",
        "reviews",
        "logs",
        "outputs",
        "config",
        "reports/lint",
    )
    for directory in workspace_directories:
        deps.ensure_directory(target_dir / directory)

    template_root = deps.repo_root / "templates" / "project"
    template_files = {
        "AGENTS.md.tmpl": target_dir / "AGENTS.md",
        "gitignore.tmpl": target_dir / ".gitignore",
        "wiki/index.md.tmpl": target_dir / "wiki" / "index.md",
        "wiki/log.md.tmpl": target_dir / "wiki" / "log.md",
        "config/project.yml.tmpl": target_dir / "config" / "project.yml",
        ".env.example.tmpl": target_dir / ".env.example",
        "config/runtime_manifest.yml.tmpl": target_dir / "config" / "runtime_manifest.yml",
    }

    for template_name, output_path in template_files.items():
        rendered = deps.render_template(template_root / template_name, context)
        output_path.write_text(rendered, encoding="utf-8")

    metadata_files = {
        target_dir / "state" / "sources.jsonl": [],
        target_dir / "state" / "ingest_state.jsonl": [],
        target_dir / "state" / "error_log.jsonl": [],
        target_dir / "state" / "normalized.jsonl": [],
        target_dir / deps.structure_blocks_rel_path: [],
        target_dir / deps.evidence_blocks_rel_path: [],
        target_dir / deps.knowledge_units_rel_path: [],
        target_dir / "state" / "chunks.jsonl": [],
        target_dir / "state" / "claims.jsonl": [],
        target_dir / "state" / "reviews.jsonl": [],
        target_dir / "state" / "pages.jsonl": [],
        target_dir / deps.semantic_decisions_rel_path: [],
        target_dir / deps.search_pages_index_rel_path: [],
    }
    for path, records in metadata_files.items():
        deps.write_jsonl(path, records)

    deps.write_alias_index(target_dir, [])

    git_steps: list[str] = []
    if not (target_dir / ".git").exists():
        git_steps = deps.git_init_and_commit(target_dir)

    return {
        "project_name": request.project_name,
        "source_dir": str(raw_dir),
        "raw_dir": str(raw_dir),
        "assets_dir": str(assets_dir),
        "target_dir": str(target_dir),
        "workspace_summary": deps.build_workspace_summary(target_dir, raw_dir),
        "created_directories": [
            str(raw_dir),
            str(assets_dir),
            *[str(target_dir / path) for path in workspace_directories],
        ],
        "raw_dir_relative_path": raw_dir_relative_path,
        "raw_dir_preexisting": raw_dir_preexisting,
        "assets_dir_relative_path": assets_dir_relative_path,
        "assets_dir_preexisting": assets_dir_preexisting,
        "metadata_files": [str(path) for path in metadata_files],
        "git_steps": git_steps,
    }
