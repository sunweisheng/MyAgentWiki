from __future__ import annotations

import argparse
import json
import importlib.util
import os
import shutil
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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Template
import ast
import tomllib
import tempfile
from urllib.parse import quote
from xml.etree import ElementTree as ET

try:
    import docx
except ImportError:  # pragma: no cover - 依赖缺失时走降级逻辑
    docx = None

try:
    import openpyxl
except ImportError:  # pragma: no cover - 依赖缺失时走降级逻辑
    openpyxl = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - 依赖缺失时走降级逻辑
    PdfReader = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - 依赖缺失时走降级逻辑
    Image = None


ROOT_MARKERS = ("pyproject.toml", ".git")
DEFAULT_CHUNK_TARGET_TOKENS = 1000
DEFAULT_CHUNK_MAX_TOKENS = 1600
DEFAULT_CHUNK_MIN_TOKENS = 200
DEFAULT_MAX_CLAIMS_PER_CHUNK = 3
ALIAS_INDEX_REL_PATH = Path("indexes") / "aliases.json"
PAGE_ALIAS_OVERRIDES_REL_PATH = Path("state") / "page_alias_overrides.json"
NEGATION_MARKERS = ("不", "不是", "没有", "无法", "不能", "未", "无", "禁止", "不要", "not ", "no ", "never ", "cannot ")
PACKAGE_IMPORT_ALIASES = {
    "python-docx": "docx",
    "pillow": "PIL",
}
QUERY_FIELD_WEIGHTS = {
    "title": 5.0,
    "aliases": 4.0,
    "summary": 3.0,
    "headings": 2.5,
    "body": 1.0,
    "claim_text": 2.0,
    "source_refs": 0.5,
}
QUERY_PAGE_TYPE_WEIGHTS = {
    "overview": 1.25,
    "concept": 1.15,
    "concept-summary": 1.15,
    "entity": 1.10,
    "source-summary": 1.00,
    "qa": 0.95,
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
}
SEARCH_PAGES_INDEX_REL_PATH = Path("indexes") / "search_pages.jsonl"
SEARCH_PAGES_INDEX_VERSION = "search_pages_v1"
ALIAS_INDEX_VERSION = "aliases_v1"
QUERY_INTENT_MARKERS = {
    "definition": (
        "是什么", "什么是", "定义", "是指", "指什么", "介绍一下", "what is", "define",
    ),
    "compare": (
        "区别", "对比", "比较", "差异", "vs", "versus", "compare",
    ),
    "timeline": (
        "时间线", "演变", "历史", "历程", "timeline",
    ),
    "how_to": (
        "如何", "怎么", "步骤", "做法", "实践", "how to", "tutorial",
    ),
    "evidence": (
        "来源", "证据", "出处", "引用", "依据", "为什么", "source", "evidence", "trace",
    ),
}
QUERY_INTENT_FIELD_MULTIPLIERS = {
    "lookup": {},
    "definition": {
        "title": 1.15,
        "summary": 1.15,
        "aliases": 1.10,
    },
    "compare": {
        "claim_text": 1.15,
        "body": 1.10,
        "headings": 1.05,
    },
    "timeline": {
        "body": 1.10,
        "summary": 1.05,
        "source_refs": 1.10,
    },
    "how_to": {
        "headings": 1.15,
        "body": 1.15,
        "claim_text": 1.10,
    },
    "evidence": {
        "source_refs": 1.80,
        "claim_text": 1.20,
        "body": 1.05,
    },
}


@dataclass
class CommandResult:
    # 所有命令统一返回这一层结构，方便后面既能打印给人看，也能转成 JSON 给 Agent 消费。
    exit_code: int = 0
    payload: dict | None = None
    message: str | None = None


def find_project_root(start: Path | None = None) -> Path:
    # 从当前文件或给定路径一路向上找项目根目录。
    # 这里优先依赖 pyproject.toml 和 .git 这样的标记文件，避免把临时目录误判成项目根。
    current = (start or Path(__file__)).resolve()
    for path in [current, *current.parents]:
        if all((path / marker).exists() or marker == ".git" and (path / marker).exists() for marker in ROOT_MARKERS):
            return path
    for path in [current, *current.parents]:
        if (path / "pyproject.toml").exists():
            return path
    raise FileNotFoundError("Could not locate project root from current path.")


def parse_yaml_scalar(raw: str):
    # 当前项目里的 YAML 结构比较简单，这里做一个轻量标量解析器就够用了。
    # 目标不是支持完整 YAML 语法，而是稳定读取我们自己维护的配置文件。
    value = raw.strip()
    if value == "":
        return {}
    if value in {"true", "false"}:
        return value == "true"
    if value in {"[]", "{}"}:
        return ast.literal_eval(value)
    if value.startswith(("[", "{", "'", '"')):
        return ast.literal_eval(value)
    return value


def load_simple_yaml(path: Path) -> dict:
    # 这里实现的是“够用版 YAML 读取器”：
    # 只处理字典嵌套、简单标量、缩进列表，不引入额外依赖。
    root: dict = {}
    stack: list[tuple[int, object, dict | None, str | None]] = [(-1, root, None, None)]

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        # 通过缩进层级维护一个栈，逐步构造嵌套字典结构。
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        stripped = raw_line.strip()
        current_indent, parent, owner, owner_key = stack[-1]

        if stripped.startswith("- "):
            if isinstance(parent, dict):
                # 空字典节点如果下一层第一条就是 "- item"，就把它视为列表容器。
                if parent == {} and owner is not None and owner_key is not None:
                    parent = []
                    owner[owner_key] = parent
                    stack[-1] = (current_indent, parent, owner, owner_key)
                else:
                    raise ValueError(f"Invalid YAML list item placement in {path}: {raw_line}")
            if not isinstance(parent, list):
                raise ValueError(f"Invalid YAML list item placement in {path}: {raw_line}")
            parent.append(parse_yaml_scalar(stripped[2:]))
            continue

        key, sep, rest = stripped.partition(":")
        if not sep:
            continue

        if rest.strip() == "":
            node: dict | list = {}
            parent[key] = node
            stack.append((indent, node, parent, key))
        else:
            parent[key] = parse_yaml_scalar(rest)

    return root


def load_runtime_manifest(root: Path) -> dict:
    # runtime_manifest 是运行环境的统一来源，doctor/bootstrap 都会依赖它。
    manifest_path = root / "config" / "runtime_manifest.yml"
    return load_simple_yaml(manifest_path)


def load_project_metadata(root: Path) -> dict:
    # pyproject.toml 负责项目名、版本、依赖和 CLI 入口等元信息。
    with (root / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def print_result(result: CommandResult, as_json: bool = False) -> int:
    # 所有命令统一走这里输出，避免每个命令自己决定打印格式。
    if as_json:
        print(json.dumps(result.payload or {}, ensure_ascii=False, indent=2))
        return result.exit_code

    if result.message:
        print(result.message)
    elif result.payload is not None:
        print(json.dumps(result.payload, ensure_ascii=False, indent=2))
    return result.exit_code


def compare_python_version(spec: str) -> bool:
    # 目前只需要支持 >= 这种最常见的版本约束，先不把比较器做复杂。
    if not spec.startswith(">="):
        return True
    required = tuple(int(part) for part in spec[2:].split("."))
    current = sys.version_info[: len(required)]
    return current >= required


def run_check_command(command: list[str]) -> tuple[bool, str]:
    # doctor 检查系统工具时统一走这个函数。
    # 成功时返回命令输出，失败时返回异常信息，尽量保留可诊断线索。
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        output = (completed.stdout or completed.stderr).strip()
        return True, output
    except (OSError, subprocess.CalledProcessError) as exc:
        return False, str(exc)


def command_exists(name: str) -> bool:
    # 有些增强能力只需要知道系统命令是否在 PATH 中，不必真的跑一遍。
    return shutil.which(name) is not None


def normalize_package_name(name: str) -> str:
    # Python 包名和 import 名有时会用 - / _ 混用，这里先做最常见的归一化。
    if name in PACKAGE_IMPORT_ALIASES:
        return PACKAGE_IMPORT_ALIASES[name]
    return name.replace("-", "_")


def check_python_package_installed(name: str) -> bool:
    # 通过 importlib 检测包是否可导入，避免直接 import 触发副作用。
    return importlib.util.find_spec(normalize_package_name(name)) is not None


def collect_python_package_report(manifest: dict) -> dict:
    # 把 Python 包依赖拆成 required / optional 两层，doctor 输出时会更容易读。
    required_packages = manifest.get("python_packages", {}).get("required", [])
    optional_groups = manifest.get("python_packages", {}).get("optional", {})

    required_report = {
        package: {"ok": check_python_package_installed(package)}
        for package in required_packages
    }
    optional_report = {
        group: {
            package: {"ok": check_python_package_installed(package)}
            for package in packages
        }
        for group, packages in optional_groups.items()
    }
    return {
        "required": required_report,
        "optional": optional_report,
    }


def build_doctor_payload(root: Path) -> dict:
    # doctor 的核心逻辑集中在这里：
    # 读取项目元信息、读取运行时清单、检查 Python / git / 可选系统工具 / Python 包。
    manifest = load_runtime_manifest(root)
    project_meta = load_project_metadata(root)

    python_spec = manifest["runtime"]["python"]["version"]
    python_ok = compare_python_version(python_spec)
    git_command = manifest["runtime"]["git"]["check"]["command"]
    git_ok, git_output = run_check_command(git_command)

    required = {
        "python": {
            "required_version": python_spec,
            "current_version": ".".join(map(str, sys.version_info[:3])),
            "ok": python_ok,
        },
        "git": {
            "ok": git_ok,
            "details": git_output,
        },
    }

    optional_tools: dict[str, dict] = {}
    current_platform = sys.platform
    platform_label = (
        "windows" if current_platform.startswith("win")
        else "macos" if current_platform == "darwin"
        else "linux"
    )
    # 平台标签单独算出来，后面 Windows/macOS/Linux 的提示逻辑都会复用。
    for tool_name, tool_data in manifest.get("system_tools", {}).get("optional", {}).items():
        ok, details = run_check_command(tool_data["check"]["command"])
        optional_tools[tool_name] = {
            "ok": ok,
            "purpose": tool_data["purpose"],
            "fallback": tool_data["fallback"],
            "supported_platforms": tool_data["supported_platforms"],
            "supported_on_current_platform": platform_label in tool_data["supported_platforms"],
            "details": details,
        }

    python_packages = collect_python_package_report(manifest)
    required_python_packages_ok = all(
        item["ok"] for item in python_packages["required"].values()
    )
    bootstrap_examples = {
        "windows": [
            r"py -3.12 -m venv .venv",
            r".venv\Scripts\python -m pip install -U pip",
            r".venv\Scripts\python -m myagentwiki bootstrap --extra dev",
        ],
        "macos": [
            "python3.12 -m venv .venv",
            ".venv/bin/python -m pip install -U pip",
            ".venv/bin/python -m myagentwiki bootstrap --extra dev",
        ],
        "linux": [
            "python3.12 -m venv .venv",
            ".venv/bin/python -m pip install -U pip",
            ".venv/bin/python -m myagentwiki bootstrap --extra dev",
        ],
    }
    return {
        "project": {
            "name": project_meta["project"]["name"],
            "version": project_meta["project"]["version"],
            "root": str(root),
        },
        "platform": {
            "os_name": os.name,
            "sys_platform": sys.platform,
            "platform_label": platform_label,
        },
        "required": required,
        "python_packages": python_packages,
        "optional": optional_tools,
        "summary": {
            "required_ok": all(item["ok"] for item in required.values()) and required_python_packages_ok,
            "missing_required_python_packages": [
                name for name, item in python_packages["required"].items() if not item["ok"]
            ],
            "optional_missing": [name for name, item in optional_tools.items() if not item["ok"]],
        },
        "bootstrap_guidance": {
            "recommended_shell_examples": bootstrap_examples.get(platform_label, bootstrap_examples["linux"]),
            "notes": [
                "核心流程不依赖 shell 专属语法，Windows / macOS / Linux 都应可执行。",
                "可选系统工具缺失时，优先走 Python 降级路径，再视需要交给 Agent 补强。",
            ],
        },
    }


def command_doctor(args: argparse.Namespace) -> CommandResult:
    # command_* 函数负责组装业务结果；真正的公共逻辑尽量往辅助函数里收。
    root = find_project_root()
    payload = build_doctor_payload(root)
    return CommandResult(payload=payload, message="MyAgentWiki doctor report ready.")


def command_bootstrap(args: argparse.Namespace) -> CommandResult:
    # bootstrap 当前先聚焦 Python 依赖安装，不擅自处理系统级软件。
    # 命令本身保持跨平台：直接调用当前 Python 解释器，不依赖 bash/zsh 专属语法。
    root = find_project_root()
    install_command = [sys.executable, "-m", "pip", "install", "-e"]
    if args.extras:
        # extras 允许用户按需装增强能力，比如 pdf / dev。
        install_command.append(f"{str(root)}[{','.join(args.extras)}]")
    else:
        install_command.append(str(root))

    doctor_payload = build_doctor_payload(root)

    if args.dry_run:
        # dry-run 先把“将做什么”讲清楚，避免一上来就改环境。
        payload = {
            "action": "dry_run",
            "install_command": install_command,
            "project_root": str(root),
            "requested_extras": args.extras,
            "doctor_summary": doctor_payload["summary"],
        }
        return CommandResult(payload=payload, message="Bootstrap dry run complete.")

    completed = subprocess.run(
        install_command,
        check=False,
        capture_output=True,
        text=True,
    )
    # pip 的 stdout / stderr 原样带回去，方便排查安装失败的真实原因。
    payload = {
        "action": "install",
        "install_command": install_command,
        "requested_extras": args.extras,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "doctor_summary": doctor_payload["summary"],
    }
    return CommandResult(
        exit_code=completed.returncode,
        payload=payload,
        message="Bootstrap finished." if completed.returncode == 0 else "Bootstrap finished with errors.",
    )


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
        "config/project.yml",
        "config/runtime_manifest.yml",
        "indexes/aliases.json",
        str(SEARCH_PAGES_INDEX_REL_PATH),
        "reports/lint/lint_latest.md",
        "state/claims.jsonl",
        "state/chunks.jsonl",
        "state/error_log.jsonl",
        "state/ingest_state.jsonl",
        "state/normalized.jsonl",
        "state/pages.jsonl",
        "state/reviews.jsonl",
        "state/sources.jsonl",
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
    # 同一路径可能因为旧版本实现留下多条 source 记录，这里统一选“最近导入”的那条。
    latest_by_path: dict[str, dict] = {}
    for record in records:
        source_path = record.get("source_path")
        if not source_path:
            continue
        current = latest_by_path.get(source_path)
        if current is None or record.get("imported_at", "") >= current.get("imported_at", ""):
            latest_by_path[source_path] = record
    return latest_by_path


def collect_files(root: Path) -> list[Path]:
    # 递归遍历 raw 下所有文件，允许用户按主题、来源、年份自由分子目录管理原始资料。
    return sorted(path for path in root.rglob("*") if path.is_file())


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


def resolve_workspace_path(target: Path, configured_path: str) -> Path:
    # config 里的路径既可能是相对工作区，也可能是绝对路径。
    path = Path(configured_path).expanduser()
    if path.is_absolute():
        return path
    return (target / path).resolve()


def resolve_source_record_path(target: Path, source_path: str) -> Path:
    # source_path 默认按“相对工作区可访问路径”解释，这样 ../raw/... 也能稳定解析。
    path = Path(source_path).expanduser()
    if path.is_absolute():
        return path
    return (target / path).resolve()


def alias_index_path(target: Path) -> Path:
    # alias registry 是工作区级派生索引，和 search index 一样放在 indexes/ 下。
    return target / ALIAS_INDEX_REL_PATH


def page_alias_overrides_path(target: Path) -> Path:
    # 人工对页面 alias 的修订单独存一层覆盖，避免被后续自动页面重建直接抹掉。
    return target / PAGE_ALIAS_OVERRIDES_REL_PATH


def normalize_alias_value(text: str) -> str:
    # alias / canonical 查询归一化尽量沿用 claim 文本清洗逻辑，
    # 这样页面标题、别名、查询词之间更容易对齐。
    return normalize_claim_text(text)


def load_alias_index(target: Path) -> dict:
    path = alias_index_path(target)
    if not path.exists():
        return {
            "index_version": ALIAS_INDEX_VERSION,
            "updated_at": None,
            "canonical_map": {},
            "alias_map": {},
            "conflicts": [],
        }
    return load_json(path)


def load_page_alias_overrides(target: Path) -> dict:
    path = page_alias_overrides_path(target)
    if not path.exists():
        return {"page_aliases": {}}
    return load_json(path)


def write_page_alias_overrides(target: Path, payload: dict) -> None:
    write_json(page_alias_overrides_path(target), payload)


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


def build_alias_index(page_records: list[dict]) -> dict:
    # alias registry 统一记录 canonical_id、title、aliases 的双向映射关系。
    # query、lint、Agent 约定都依赖它，避免各自维护一份别名世界观。
    canonical_map: dict[str, dict] = {}
    alias_map: dict[str, list[dict]] = {}

    for page_record in filter_live_page_records(page_records):
        page_id = page_record.get("page_id")
        canonical_id = page_record.get("canonical_id") or page_id
        title = page_record.get("title", "")
        page_path = page_record.get("page_path", "")
        page_type = page_record.get("type", "")
        page_status = page_record.get("status", "")

        canonical_map[canonical_id] = {
            "canonical_id": canonical_id,
            "page_id": page_id,
            "title": title,
            "page_path": page_path,
            "type": page_type,
            "status": page_status,
            "aliases": sorted(set(page_record.get("aliases", []))),
        }

        candidates = [title, canonical_id, *page_record.get("aliases", [])]
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
        conflicts.append({
            "alias": alias_key,
            "canonical_ids": canonical_ids,
            "page_ids": sorted({item["page_id"] for item in matches}),
        })

    return {
        "index_version": ALIAS_INDEX_VERSION,
        "updated_at": utc_now_iso(),
        "canonical_map": canonical_map,
        "alias_map": alias_map,
        "conflicts": conflicts,
    }


def write_alias_index(target: Path, page_records: list[dict]) -> dict:
    alias_index = build_alias_index(page_records)
    write_json(alias_index_path(target), alias_index)
    return alias_index


def apply_page_alias_overrides(target: Path, page_record: dict) -> dict:
    # 自动页面重建前先叠加人工 alias 覆盖层。
    overrides = load_page_alias_overrides(target)
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


def build_alias_conflict_reviews(
    alias_index: dict,
    existing_reviews: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    # alias registry 里一旦出现“一词多义”的冲突，就应进入 review 队列而不是只留在 lint 里。
    created_reviews: list[dict] = []
    touched_review_ids: list[str] = []

    for conflict in alias_index.get("conflicts", []):
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
                *page_ids,
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


def normalize_text_content(source_type: str, raw_text: str) -> str:
    # 第一版先做最保守的规范化：统一换行、去掉尾部多余空白，并确保纯文本也能落成 Markdown。
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    # 行尾空白通常没有信息价值，反而会让 hash 和 diff 变得不稳定。
    lines = [line.rstrip() for line in normalized.split("\n")]
    normalized = "\n".join(lines).strip()
    if source_type == "plain_text":
        # 纯文本在 V1 里先直接当成 Markdown 文本存储，简化后续统一处理。
        return normalized + "\n"
    return normalized + "\n"


def normalize_markdown_or_text_record(target: Path, source_record: dict) -> dict:
    # Markdown 和纯文本是当前最稳定的一类输入，直接按文本规范化处理。
    source_type = source_record["source_type"]
    raw_path = resolve_source_record_path(target, source_record["source_path"])
    raw_text = raw_path.read_text(encoding="utf-8")
    normalized_text = normalize_text_content(source_type, raw_text)
    normalized_rel_path = Path("normalized") / f"{source_record['source_id']}.md"
    normalized_abs_path = target / normalized_rel_path
    normalized_abs_path.write_text(normalized_text, encoding="utf-8")

    normalized_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    line_count = len(normalized_text.splitlines()) or 1
    title = raw_path.stem

    return {
        "source_id": source_record["source_id"],
        "source_type": source_type,
        "source_path": source_record["source_path"],
        "normalized_path": str(normalized_rel_path),
        "title": title,
        "language": "unknown",
        "content_format": "markdown",
        "raw_hash": source_record["source_hash"],
        "normalized_hash": normalized_hash,
        "normalizer_version": "normalize_v1",
        "extraction_method": "python_only",
        "extraction_quality": "good",
        "warnings": [],
        "location_map": {
            "type": "line_map",
            "normalized_line_range": f"1-{line_count}",
            "source_path": source_record["source_path"],
        },
        "updated_at": utc_now_iso(),
    }


def convert_pdf_to_markdown(raw_path: Path) -> tuple[str, dict]:
    # PDF 先走纯 Python 文本提取，按页组织成 Markdown。
    if PdfReader is None:
        return convert_pdf_to_markdown_fallback(raw_path)

    try:
        reader = PdfReader(str(raw_path))
        parts: list[str] = [f"# {raw_path.stem}"]
        page_map: list[dict] = []
        warnings: list[str] = []

        for page_index, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text() or ""
            cleaned = extracted.strip()
            parts.append(f"\n## 第 {page_index} 页\n")
            if cleaned:
                parts.append(cleaned)
            else:
                parts.append("_本页未提取到文本_")
                warnings.append(f"page_{page_index}_empty_text")
            page_map.append({
                "page": page_index,
                "char_count": len(cleaned),
            })

        markdown = "\n\n".join(parts).strip() + "\n"
        metadata = {
            "content_format": "markdown",
            "extraction_method": "python_only",
            "extraction_quality": "partial" if warnings else "good",
            "warnings": warnings,
            "location_map": {
                "type": "pdf_page_map",
                "pages": page_map,
                "source_path": str(raw_path),
            },
        }
        return markdown, metadata
    except Exception:
        # 主路径失败时退回低依赖 fallback，尽量别让 PDF 直接中断整批 ingest。
        return convert_pdf_to_markdown_fallback(raw_path)


def pdf_count_pages_from_bytes(pdf_bytes: bytes) -> int:
    # 这是一个很保守的页数估计：匹配 /Type /Page，避开 /Pages。
    matches = re.findall(rb"/Type\s*/Page\b", pdf_bytes)
    return max(len(matches), 0)


def pdf_try_inflate_stream(stream_bytes: bytes) -> bytes:
    try:
        return zlib.decompress(stream_bytes)
    except Exception:
        return stream_bytes


def decode_pdf_literal_string(raw: bytes) -> str:
    # PDF 文本操作符中的字符串常常放在 (...) 里，这里做一层轻量解码。
    text = raw.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
    try:
        return text.decode("utf-8")
    except UnicodeDecodeError:
        return text.decode("latin-1", errors="ignore")


def pdf_extract_text_snippets_from_bytes(pdf_bytes: bytes) -> list[str]:
    # fallback 只求“尽量提取一点正文”，不追求完整版面恢复。
    snippets: list[str] = []

    object_matches = re.finditer(rb"(\d+\s+\d+\s+obj.*?endobj)", pdf_bytes, flags=re.DOTALL)
    for match in object_matches:
        object_bytes = match.group(1)
        stream_match = re.search(rb"stream\r?\n(.*?)\r?\nendstream", object_bytes, flags=re.DOTALL)
        if not stream_match:
            continue
        stream_bytes = stream_match.group(1)
        if b"/FlateDecode" in object_bytes:
            stream_bytes = pdf_try_inflate_stream(stream_bytes)

        for block in re.findall(rb"BT(.*?)ET", stream_bytes, flags=re.DOTALL):
            pieces = re.findall(rb"\(([^()]*)\)", block)
            if not pieces:
                continue
            combined = "".join(decode_pdf_literal_string(piece) for piece in pieces).strip()
            combined = re.sub(r"\s+", " ", combined)
            if len(combined) >= 4 and combined not in snippets:
                snippets.append(combined)

    return snippets[:20]


def convert_pdf_to_markdown_fallback(raw_path: Path) -> tuple[str, dict]:
    # 没有 pypdf 时，至少给 PDF 生成页数、可提取文本片段和占位信息。
    pdf_bytes = raw_path.read_bytes()
    page_count = pdf_count_pages_from_bytes(pdf_bytes)
    snippets = pdf_extract_text_snippets_from_bytes(pdf_bytes)
    warnings: list[str] = []

    parts = [f"# {raw_path.stem}", "", f"- 估计页数: {page_count or 'unknown'}"]
    if snippets:
        parts.extend(["", "## 提取文本片段"])
        for index, snippet in enumerate(snippets, start=1):
            parts.append(f"{index}. {snippet}")
    else:
        warnings.append("pdf_fallback_no_text")
        parts.extend([
            "",
            "> 当前环境未启用 `pypdf`，且标准库 fallback 未提取到正文文本。",
        ])

    markdown = "\n".join(parts).strip() + "\n"
    pages = [{"page": index + 1, "char_count": None} for index in range(page_count)] if page_count else []
    return markdown, {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "partial",
        "warnings": warnings if warnings else ["pdf_fallback_used"],
        "location_map": {
            "type": "pdf_page_map",
            "pages": pages,
            "source_path": str(raw_path),
        },
    }


def iter_docx_blocks(document) -> list[tuple[str, str]]:
    # python-docx 的段落和表格分散在不同结构里。
    # V1 先分别收集，再按各自顺序做一个保守输出。
    blocks: list[tuple[str, str]] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name.lower() if paragraph.style and paragraph.style.name else ""
        if "heading" in style_name:
            digits = "".join(ch for ch in style_name if ch.isdigit())
            level = int(digits) if digits else 1
            level = min(max(level, 1), 6)
            blocks.append(("heading", "#" * level + " " + text))
        else:
            blocks.append(("paragraph", text))

    for table_index, table in enumerate(document.tables, start=1):
        rows = []
        for row in table.rows:
            values = [cell.text.strip().replace("\n", " ") or " " for cell in row.cells]
            rows.append(values)
        if not rows:
            continue
        blocks.append(("table_title", f"## 表格 {table_index}"))
        header = rows[0]
        divider = ["---"] * len(header)
        table_lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(divider) + " |",
        ]
        for row in rows[1:]:
            padded = row + [" "] * (len(header) - len(row))
            table_lines.append("| " + " | ".join(padded[: len(header)]) + " |")
        blocks.append(("table", "\n".join(table_lines)))

    return blocks


DOCX_NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}

XLSX_NAMESPACES = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

OLE_HEADER_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def docx_style_map_from_archive(archive: zipfile.ZipFile) -> dict[str, str]:
    # 纯 Python 兜底解析 docx 时，需要先把 styleId 映射到更容易理解的样式名。
    try:
        styles_xml = archive.read("word/styles.xml")
    except KeyError:
        return {}

    root = ET.fromstring(styles_xml)
    style_map: dict[str, str] = {}
    for style in root.findall("w:style", DOCX_NAMESPACES):
        style_id = style.get(f"{{{DOCX_NAMESPACES['w']}}}styleId")
        name_node = style.find("w:name", DOCX_NAMESPACES)
        if not style_id:
            continue
        style_map[style_id] = name_node.get(f"{{{DOCX_NAMESPACES['w']}}}val", style_id) if name_node is not None else style_id
    return style_map


def docx_paragraph_text(node: ET.Element) -> str:
    # Word 段落里的文本经常被拆到多个 run / text 节点里，这里把它们拼回去。
    texts = [item.text or "" for item in node.findall(".//w:t", DOCX_NAMESPACES)]
    return "".join(texts).strip()


def docx_heading_level_from_style(style_name: str, style_id: str) -> int | None:
    # heading 样式名和 styleId 在不同文档里可能略有不同，这里做保守识别。
    candidates = f"{style_name} {style_id}".lower()
    if "heading" not in candidates:
        return None
    digits = "".join(ch for ch in candidates if ch.isdigit())
    if not digits:
        return 1
    return min(max(int(digits[0]), 1), 6)


def docx_table_to_markdown(node: ET.Element) -> str:
    # 纯 XML 路径下把 Word 表格转成 Markdown 表格。
    rows: list[list[str]] = []
    for row in node.findall("w:tr", DOCX_NAMESPACES):
        values = []
        for cell in row.findall("w:tc", DOCX_NAMESPACES):
            cell_texts = []
            for paragraph in cell.findall(".//w:p", DOCX_NAMESPACES):
                text = docx_paragraph_text(paragraph)
                if text:
                    cell_texts.append(text)
            values.append(" ".join(cell_texts).strip() or " ")
        if rows or any(value.strip() for value in values):
            rows.append(values)

    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized_rows = [row + [" "] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    divider = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(divider) + " |",
    ]
    for row in normalized_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def convert_docx_to_markdown_fallback(raw_path: Path) -> tuple[str, dict]:
    # 这个 fallback 完全走标准库，避免因为 lxml / 二进制依赖不兼容把整条 docx 路堵死。
    parts = [f"# {raw_path.stem}"]
    warnings: list[str] = []

    with zipfile.ZipFile(raw_path) as archive:
        style_map = docx_style_map_from_archive(archive)
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    body = root.find("w:body", DOCX_NAMESPACES)
    if body is None:
        warnings.append("docx_missing_body")
        markdown = "\n".join(parts).strip() + "\n"
        return markdown, {
            "content_format": "markdown",
            "extraction_method": "python_only",
            "extraction_quality": "partial",
            "warnings": warnings,
            "location_map": {
                "type": "line_map",
                "normalized_line_range": "1-1",
                "source_path": str(raw_path),
            },
        }

    table_index = 0
    for child in list(body):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = docx_paragraph_text(child)
            if not text:
                continue
            style_node = child.find("w:pPr/w:pStyle", DOCX_NAMESPACES)
            style_id = style_node.get(f"{{{DOCX_NAMESPACES['w']}}}val", "") if style_node is not None else ""
            style_name = style_map.get(style_id, style_id)
            heading_level = docx_heading_level_from_style(style_name, style_id)
            if heading_level is not None:
                parts.append("#" * heading_level + " " + text)
            else:
                parts.append(text)
        elif tag == "tbl":
            table_index += 1
            table_markdown = docx_table_to_markdown(child)
            if table_markdown:
                parts.append(f"## 表格 {table_index}")
                parts.append(table_markdown)

    markdown = "\n\n".join(part for part in parts if part.strip()).strip() + "\n"
    line_count = len(markdown.splitlines()) or 1
    metadata = {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "good" if len(parts) > 1 else "partial",
        "warnings": warnings if warnings else [],
        "location_map": {
            "type": "line_map",
            "normalized_line_range": f"1-{line_count}",
            "source_path": str(raw_path),
        },
    }
    return markdown, metadata


def convert_docx_to_markdown(raw_path: Path) -> tuple[str, dict]:
    # Word 文档优先保留“标题 + 段落 + 表格”的主结构。
    if docx is not None:
        document = docx.Document(str(raw_path))
        blocks = iter_docx_blocks(document)
        parts = [f"# {raw_path.stem}"]
        parts.extend(block for _, block in blocks)
        markdown = "\n\n".join(part for part in parts if part.strip()).strip() + "\n"
        line_count = len(markdown.splitlines()) or 1

        metadata = {
            "content_format": "markdown",
            "extraction_method": "python_only",
            "extraction_quality": "good" if blocks else "partial",
            "warnings": [] if blocks else ["docx_no_visible_blocks"],
            "location_map": {
                "type": "line_map",
                "normalized_line_range": f"1-{line_count}",
                "source_path": str(raw_path),
            },
        }
        return markdown, metadata

    # 如果 python-docx 不可用，就退回到 zip+xml 路径。
    return convert_docx_to_markdown_fallback(raw_path)


def is_probably_ole_document(raw_path: Path) -> bool:
    # 老 Office 二进制格式通常基于 OLE Compound File。
    # 这里先做魔数级判断，用于给 fallback metadata 增加一点上下文。
    with raw_path.open("rb") as fh:
        return fh.read(len(OLE_HEADER_MAGIC)) == OLE_HEADER_MAGIC


def normalize_binary_snippet_text(text: str) -> str:
    # 二进制兜底抽出来的文本会混杂很多控制字符和奇怪空白，这里尽量压平。
    cleaned = []
    for char in text:
        if char in {"\n", "\r", "\t"}:
            cleaned.append(" ")
            continue
        category = ord(char)
        if char.isprintable() or 0x4E00 <= category <= 0x9FFF:
            cleaned.append(char)
    normalized = "".join(cleaned)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def binary_text_candidate_is_meaningful(text: str, min_length: int = 8) -> bool:
    # 兜底提取不要求完美，但至少要像“人会读的片段”，尽量别把纯噪声放进去。
    if len(text) < min_length:
        return False
    interesting_chars = [
        char for char in text
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    ]
    if len(interesting_chars) < max(4, min_length // 2):
        return False
    return True


def extract_printable_ascii_snippets(binary_bytes: bytes, min_length: int = 8) -> list[str]:
    snippets: list[str] = []
    for match in re.finditer(rb"[\x20-\x7e]{8,}", binary_bytes):
        text = normalize_binary_snippet_text(match.group(0).decode("utf-8", errors="ignore"))
        if binary_text_candidate_is_meaningful(text, min_length=min_length):
            snippets.append(text)
    return snippets


def extract_utf16_text_snippets(binary_bytes: bytes, min_length: int = 8) -> list[str]:
    # 老 Office 二进制里经常能捞到 UTF-16LE 文本。
    # 为了适应可能的字节对齐偏移，这里从 0/1 两个 offset 都扫一遍。
    snippets: list[str] = []
    pattern = re.compile(r"[0-9A-Za-z\u4e00-\u9fff][0-9A-Za-z\u4e00-\u9fff\s，。、“”‘’；：？！,.!?:;()（）\-_/]{7,}")
    for offset in (0, 1):
        if len(binary_bytes) <= offset + 2:
            continue
        decoded = binary_bytes[offset:].decode("utf-16le", errors="ignore")
        for match in pattern.finditer(decoded):
            text = normalize_binary_snippet_text(match.group(0))
            if binary_text_candidate_is_meaningful(text, min_length=min_length):
                snippets.append(text)
    return snippets


def extract_text_snippets_from_binary_document(
    binary_bytes: bytes,
    limit: int = 20,
    min_length: int = 8,
) -> list[str]:
    # 这是老格式 Office 的兜底文本提取：
    # - 先扫 ASCII/UTF-8 可见串
    # - 再扫 UTF-16LE 候选串
    # 目标是尽量拿到“能提示内容主题”的片段，而不是高保真还原。
    ordered_candidates = [
        *extract_printable_ascii_snippets(binary_bytes, min_length=min_length),
        *extract_utf16_text_snippets(binary_bytes, min_length=min_length),
    ]

    snippets: list[str] = []
    seen: set[str] = set()
    for candidate in ordered_candidates:
        dedupe_key = candidate.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        snippets.append(candidate)
        if len(snippets) >= limit:
            break
    return snippets


def convert_legacy_doc_to_markdown(raw_path: Path) -> tuple[str, dict]:
    # `.doc` 在 V1 先不上复杂二进制解析器。
    # 先尽量给出“文件身份 + 可见文本片段 + 明确告警”，保证能进入后续链路。
    binary_bytes = raw_path.read_bytes()
    snippets = extract_text_snippets_from_binary_document(binary_bytes)
    is_ole = is_probably_ole_document(raw_path)

    parts = [
        f"# {raw_path.stem}",
        "",
        "## 文档信息 / Document Info",
        "",
        f"- 原始格式: `.doc`",
        f"- 文件大小: {len(binary_bytes)} bytes",
        f"- OLE 容器: `{is_ole}`",
    ]

    if snippets:
        parts.extend([
            "",
            "## 提取文本片段 / Extracted Snippets",
            "",
        ])
        for index, snippet in enumerate(snippets, start=1):
            parts.append(f"{index}. {snippet}")
    else:
        parts.extend([
            "",
            "## 提取文本片段 / Extracted Snippets",
            "",
            "> 当前纯 Python fallback 未提取到可读正文片段。",
        ])

    markdown = "\n".join(parts).strip() + "\n"
    return markdown, {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "partial" if snippets else "poor",
        "warnings": ["legacy_doc_binary_fallback"] if snippets else ["legacy_doc_no_text_snippets"],
        "location_map": {
            "type": "binary_snippet_map",
            "source_path": str(raw_path),
            "snippet_count": len(snippets),
            "is_ole_container": is_ole,
        },
    }


def image_size_from_binary(raw_path: Path) -> tuple[int | None, int | None, str | None]:
    # 在 Pillow 不可用时，用文件头做一层轻量尺寸识别。
    with raw_path.open("rb") as fh:
        header = fh.read(64)

    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
        width, height = struct.unpack(">II", header[16:24])
        return width, height, "PNG"

    if header.startswith(b"\xff\xd8"):
        with raw_path.open("rb") as fh:
            fh.read(2)
            while True:
                marker_start = fh.read(1)
                if not marker_start:
                    break
                if marker_start != b"\xff":
                    continue
                marker = fh.read(1)
                while marker == b"\xff":
                    marker = fh.read(1)
                if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                    segment_length = struct.unpack(">H", fh.read(2))[0]
                    _precision = fh.read(1)
                    height, width = struct.unpack(">HH", fh.read(4))
                    return width, height, "JPEG"
                if marker in {b"\xd8", b"\xd9"}:
                    continue
                segment_length_data = fh.read(2)
                if len(segment_length_data) < 2:
                    break
                segment_length = struct.unpack(">H", segment_length_data)[0]
                fh.seek(segment_length - 2, 1)

    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        if header[12:16] == b"VP8X" and len(header) >= 30:
            width = 1 + int.from_bytes(header[24:27], "little")
            height = 1 + int.from_bytes(header[27:30], "little")
            return width, height, "WEBP"

    return None, None, None


def worksheet_to_markdown(sheet) -> str:
    # Excel 每个 sheet 先保守转成一个 Markdown 表格。
    rows = []
    for row in sheet.iter_rows(values_only=True):
        values = ["" if value is None else str(value).replace("\n", " ") for value in row]
        if any(value != "" for value in values):
            rows.append(values)

    if not rows:
        return "_此工作表无可见数据_"

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    divider = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(divider) + " |",
    ]
    for row in normalized_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def xlsx_shared_strings_from_archive(archive: zipfile.ZipFile) -> list[str]:
    # xlsx 里的字符串常常集中存在 sharedStrings.xml，需要先整体解开。
    try:
        xml_data = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml_data)
    values: list[str] = []
    for item in root.findall("main:si", XLSX_NAMESPACES):
        texts = [node.text or "" for node in item.findall(".//main:t", XLSX_NAMESPACES)]
        values.append("".join(texts))
    return values


def xlsx_sheet_names_from_workbook(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    # 从 workbook 和关系文件里拿到 sheet 名和对应的 sheet xml 路径。
    workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))

    rel_map = {}
    for rel in rel_root.findall("rel:Relationship", XLSX_NAMESPACES):
        rel_id = rel.get("Id")
        target = rel.get("Target")
        if rel_id and target:
            rel_map[rel_id] = target

    sheets: list[tuple[str, str]] = []
    for sheet in workbook_root.findall("main:sheets/main:sheet", XLSX_NAMESPACES):
        name = sheet.get("name", "Sheet")
        rel_id = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_map.get(rel_id, "")
        if target:
            normalized_target = target.lstrip("/")
            if normalized_target.startswith("xl/"):
                sheet_path = normalized_target
            else:
                sheet_path = f"xl/{normalized_target}"
            sheets.append((name, sheet_path))
    return sheets


def column_letters_to_index(value: str) -> int:
    index = 0
    for char in value:
        if not char.isalpha():
            break
        index = index * 26 + (ord(char.upper()) - ord("A") + 1)
    return max(index - 1, 0)


def xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.get("t")
    value_node = cell.find("main:v", XLSX_NAMESPACES)
    inline_node = cell.find("main:is", XLSX_NAMESPACES)

    if inline_node is not None:
        texts = [node.text or "" for node in inline_node.findall(".//main:t", XLSX_NAMESPACES)]
        return "".join(texts).strip()
    if value_node is None or value_node.text is None:
        return ""
    raw_value = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (ValueError, IndexError):
            return raw_value
    return raw_value


def xlsx_rows_from_sheet_xml(archive: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows: list[list[str]] = []

    for row in root.findall("main:sheetData/main:row", XLSX_NAMESPACES):
        row_values: list[str] = []
        last_index = -1
        for cell in row.findall("main:c", XLSX_NAMESPACES):
            ref = cell.get("r", "")
            col_index = column_letters_to_index(ref)
            while len(row_values) < col_index:
                row_values.append("")
            value = xlsx_cell_value(cell, shared_strings).replace("\n", " ").strip()
            row_values.append(value)
            last_index = col_index
        if row_values and any(value != "" for value in row_values):
            rows.append(row_values)

    return rows


def rows_to_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return "_此工作表无可见数据_"

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    divider = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(divider) + " |",
    ]
    for row in normalized_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def convert_xlsx_to_markdown_fallback(raw_path: Path) -> tuple[str, dict]:
    # 没有 openpyxl 时，xlsx 仍然可以作为 zip+xml 做保守解析。
    with zipfile.ZipFile(raw_path) as archive:
        shared_strings = xlsx_shared_strings_from_archive(archive)
        sheets = xlsx_sheet_names_from_workbook(archive)

        parts = [f"# {raw_path.stem}"]
        sheet_map: list[dict] = []

        for sheet_name, sheet_path in sheets:
            rows = xlsx_rows_from_sheet_xml(archive, sheet_path, shared_strings)
            parts.append(f"## 工作表: {sheet_name}")
            parts.append(rows_to_markdown_table(rows))
            sheet_map.append({
                "sheet_name": sheet_name,
                "row_count": len(rows),
                "sheet_path": sheet_path,
            })

    markdown = "\n\n".join(part for part in parts if part.strip()).strip() + "\n"
    return markdown, {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "good" if sheet_map else "partial",
        "warnings": [] if sheet_map else ["xlsx_no_visible_sheets"],
        "location_map": {
            "type": "sheet_map",
            "sheets": sheet_map,
            "source_path": str(raw_path),
        },
    }


def convert_legacy_xls_to_markdown(raw_path: Path) -> tuple[str, dict]:
    # `.xls` 也先走“可见文本片段 + 明确警告”的保守路径。
    # 这样至少能把工作表名、列名、公式痕迹或可读单元格内容捞出一部分。
    binary_bytes = raw_path.read_bytes()
    snippets = extract_text_snippets_from_binary_document(binary_bytes)
    is_ole = is_probably_ole_document(raw_path)

    parts = [
        f"# {raw_path.stem}",
        "",
        "## 工作簿信息 / Workbook Info",
        "",
        f"- 原始格式: `.xls`",
        f"- 文件大小: {len(binary_bytes)} bytes",
        f"- OLE 容器: `{is_ole}`",
    ]

    if snippets:
        parts.extend([
            "",
            "## 可见文本片段 / Visible Text Snippets",
            "",
        ])
        for index, snippet in enumerate(snippets, start=1):
            parts.append(f"{index}. {snippet}")
    else:
        parts.extend([
            "",
            "## 可见文本片段 / Visible Text Snippets",
            "",
            "> 当前纯 Python fallback 未提取到可读工作簿文本。",
        ])

    markdown = "\n".join(parts).strip() + "\n"
    return markdown, {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "partial" if snippets else "poor",
        "warnings": ["legacy_xls_binary_fallback"] if snippets else ["legacy_xls_no_text_snippets"],
        "location_map": {
            "type": "binary_snippet_map",
            "source_path": str(raw_path),
            "snippet_count": len(snippets),
            "is_ole_container": is_ole,
        },
    }


def convert_spreadsheet_to_markdown(raw_path: Path) -> tuple[str, dict]:
    # 电子表格优先保留 sheet 结构、表头和主要单元格内容。
    if raw_path.suffix.lower() == ".csv":
        return convert_csv_to_markdown(raw_path)
    if raw_path.suffix.lower() == ".xls":
        return convert_legacy_xls_to_markdown(raw_path)
    if openpyxl is None:
        return convert_xlsx_to_markdown_fallback(raw_path)

    workbook = openpyxl.load_workbook(str(raw_path), data_only=False)
    parts = [f"# {raw_path.stem}"]
    sheet_map: list[dict] = []

    for sheet in workbook.worksheets:
        parts.append(f"\n## 工作表: {sheet.title}\n")
        parts.append(worksheet_to_markdown(sheet))
        sheet_map.append({
            "sheet_name": sheet.title,
            "max_row": sheet.max_row,
            "max_column": sheet.max_column,
        })

    markdown = "\n\n".join(parts).strip() + "\n"
    metadata = {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "good" if workbook.worksheets else "partial",
        "warnings": [] if workbook.worksheets else ["spreadsheet_no_worksheets"],
        "location_map": {
            "type": "sheet_map",
            "sheets": sheet_map,
            "source_path": str(raw_path),
        },
    }
    return markdown, metadata


def convert_csv_to_markdown(raw_path: Path) -> tuple[str, dict]:
    # CSV 不依赖 openpyxl，直接走标准库就够了。
    rows: list[list[str]] = []
    with raw_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if any(cell.strip() for cell in row):
                rows.append([cell.strip() for cell in row])

    parts = [f"# {raw_path.stem}", "", "## 工作表: CSV", ""]
    if rows:
        width = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (width - len(row)) for row in rows]
        header = normalized_rows[0]
        divider = ["---"] * width
        parts.append("| " + " | ".join(header) + " |")
        parts.append("| " + " | ".join(divider) + " |")
        for row in normalized_rows[1:]:
            parts.append("| " + " | ".join(row) + " |")
    else:
        parts.append("_CSV 文件没有可见数据_")

    markdown = "\n".join(parts).strip() + "\n"
    return markdown, {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "good" if rows else "partial",
        "warnings": [] if rows else ["csv_no_visible_rows"],
        "location_map": {
            "type": "sheet_map",
            "sheets": [{"sheet_name": "CSV", "row_count": len(rows)}],
            "source_path": str(raw_path),
        },
    }


def ocr_text_is_meaningful(text: str, min_length: int = 12) -> bool:
    normalized = normalize_binary_snippet_text(text)
    if len(normalized) < min_length:
        return False
    interesting_chars = [
        char for char in normalized
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    ]
    return len(interesting_chars) >= max(6, min_length // 2)


def run_tesseract_ocr(raw_path: Path) -> tuple[str, dict]:
    # 图片 OCR 作为增强路径存在：
    # - 有 tesseract：尽量提取正文
    # - 无 tesseract：走元数据占位
    # 这里统一返回结构化结果，方便 normalized / 日志 / 测试共用。
    if not command_exists("tesseract"):
        return "", {
            "used": False,
            "ok": False,
            "quality": "missing",
            "warnings": ["tesseract_missing"],
            "details": "tesseract command not found in PATH",
        }

    completed = subprocess.run(
        ["tesseract", str(raw_path), "stdout", "--psm", "3"],
        check=False,
        capture_output=True,
        text=True,
    )
    raw_text = (completed.stdout or "").strip()
    normalized_text = normalize_binary_snippet_text(raw_text)

    if completed.returncode != 0:
        stderr_text = (completed.stderr or "").strip() or "unknown_tesseract_error"
        return "", {
            "used": True,
            "ok": False,
            "quality": "failed",
            "warnings": ["tesseract_ocr_failed"],
            "details": stderr_text,
        }

    if not normalized_text:
        return "", {
            "used": True,
            "ok": True,
            "quality": "empty",
            "warnings": ["tesseract_ocr_no_text"],
            "details": (completed.stderr or "").strip(),
        }

    quality = "good" if ocr_text_is_meaningful(normalized_text) else "partial"
    warnings: list[str] = []
    if quality == "partial":
        warnings.append("tesseract_ocr_low_signal")
    return normalized_text, {
        "used": True,
        "ok": True,
        "quality": quality,
        "warnings": warnings,
        "details": (completed.stderr or "").strip(),
    }


def convert_image_to_markdown(raw_path: Path) -> tuple[str, dict]:
    # 图片标准化采用“元数据始终保底，OCR 视环境增强”的策略。
    warnings: list[str] = []
    stat = raw_path.stat()
    metadata_lines = [
        f"# {raw_path.stem}",
        "",
        f"- 文件名: {raw_path.name}",
        f"- 文件大小: {stat.st_size} bytes",
    ]
    location_map = {
        "type": "image_metadata",
        "source_path": str(raw_path),
    }

    width = None
    height = None
    image_format = None
    image_mode = "unknown"
    exif = {}

    if Image is None:
        warnings.append("pillow_missing")
        width, height, image_format = image_size_from_binary(raw_path)
    else:
        try:
            with Image.open(raw_path) as image:
                width = image.width
                height = image.height
                image_mode = image.mode
                image_format = image.format or "unknown"
                if hasattr(image, "getexif"):
                    exif_data = image.getexif()
                    if exif_data:
                        exif = {str(key): str(value) for key, value in exif_data.items()}
        except Exception as exc:
            warnings.append("pillow_image_open_failed")
            width, height, image_format = image_size_from_binary(raw_path)
            image_mode = "unknown"

    metadata_lines.extend([
        f"- 尺寸: {width}x{height}" if width and height else "- 尺寸: unknown",
        f"- 模式: {image_mode}",
        f"- 格式: {image_format}" if image_format else "- 格式: unknown",
    ])

    if exif:
        metadata_lines.append("")
        metadata_lines.append("## EXIF")
        for key, value in sorted(exif.items()):
            metadata_lines.append(f"- {key}: {value}")

    ocr_text, ocr_result = run_tesseract_ocr(raw_path)
    warnings.extend(ocr_result.get("warnings", []))

    extraction_quality = "partial"
    if ocr_text:
        metadata_lines.extend([
            "",
            "## OCR 文本 / OCR Text",
            "",
            ocr_text,
        ])
        extraction_quality = "good" if ocr_result.get("quality") == "good" else "partial"
    else:
        if ocr_result.get("quality") == "failed":
            metadata_lines.extend([
                "",
                "> tesseract 已安装，但本次 OCR 执行失败，当前仅保留图片元数据。",
            ])
        elif ocr_result.get("quality") == "missing":
            metadata_lines.extend([
                "",
                "> 当前环境未检测到 tesseract，图片仅生成元数据级 normalized 文档。",
            ])
        else:
            metadata_lines.extend([
                "",
                "> 本次 OCR 未提取到稳定正文，当前保留图片元数据供后续人工或 Agent 处理。",
            ])

    markdown = "\n".join(metadata_lines).strip() + "\n"
    location_map["image"] = {
        "has_exif": bool(exif),
        "width": width,
        "height": height,
        "mode": image_mode,
        "format": image_format,
    }
    location_map["ocr"] = {
        "used": ocr_result.get("used", False),
        "ok": ocr_result.get("ok", False),
        "quality": ocr_result.get("quality"),
        "char_count": len(ocr_text),
    }
    return markdown, {
        "content_format": "markdown",
        "extraction_method": "python_only+tesseract" if ocr_result.get("used") else "python_only",
        "extraction_quality": extraction_quality,
        "warnings": warnings if warnings else ([] if ocr_text else ["image_metadata_only"]),
        "location_map": location_map,
    }


def convert_unknown_source_to_placeholder(raw_path: Path, source_type: str) -> tuple[str, dict]:
    # 对暂不支持的格式，至少生成一个可追踪占位文档，而不是静默丢掉。
    markdown = (
        f"# {raw_path.stem}\n\n"
        f"- source_type: {source_type}\n"
        f"- source_path: {raw_path}\n\n"
        "> 当前版本暂不支持该格式的自动标准化，请等待后续转换器或使用 Agent 辅助处理。\n"
    )
    return markdown, {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "poor",
        "warnings": [f"unsupported_source_type:{source_type}"],
        "location_map": {
            "type": "placeholder",
            "source_path": str(raw_path),
        },
    }


def convert_source_to_normalized_markdown(raw_path: Path, source_type: str) -> tuple[str, dict]:
    # 多格式标准化统一从这里分派，后续新增格式时只需要扩展这一层。
    if source_type in {"markdown", "plain_text"}:
        raw_text = raw_path.read_text(encoding="utf-8")
        return normalize_text_content(source_type, raw_text), {
            "content_format": "markdown",
            "extraction_method": "python_only",
            "extraction_quality": "good",
            "warnings": [],
        }
    if source_type == "pdf":
        return convert_pdf_to_markdown(raw_path)
    if source_type == "docx":
        return convert_docx_to_markdown(raw_path)
    if source_type == "doc":
        return convert_legacy_doc_to_markdown(raw_path)
    if source_type == "spreadsheet":
        return convert_spreadsheet_to_markdown(raw_path)
    if source_type == "image":
        return convert_image_to_markdown(raw_path)
    return convert_unknown_source_to_placeholder(raw_path, source_type)


def build_failed_conversion_placeholder(raw_path: Path, source_type: str, exc: Exception) -> tuple[str, dict]:
    # 某个转换器失败时，不让整次 ingest 中断，而是生成一个可追踪的失败占位文档。
    markdown = (
        f"# {raw_path.stem}\n\n"
        f"- source_type: {source_type}\n"
        f"- source_path: {raw_path}\n"
        f"- converter_error: {type(exc).__name__}: {exc}\n\n"
        "> 当前版本在标准化该文件时失败，已生成占位文档等待后续修复或 Agent 辅助处理。\n"
    )
    return markdown, {
        "content_format": "markdown",
        "extraction_method": "python_only",
        "extraction_quality": "failed",
        "warnings": [f"converter_error:{type(exc).__name__}", str(exc)],
        "location_map": {
            "type": "conversion_error",
            "source_path": str(raw_path),
        },
    }


def normalize_source_record(target: Path, source_record: dict) -> dict | None:
    # 这一层负责把“来源登记记录”转成“标准化记录”。
    # 这里是 normalized 层的统一入口：不同类型都尽量产出 Markdown 形态的标准文本。
    source_type = source_record["source_type"]
    if source_type in {"markdown", "plain_text"}:
        return normalize_markdown_or_text_record(target, source_record)

    raw_path = resolve_source_record_path(target, source_record["source_path"])
    try:
        normalized_text, metadata = convert_source_to_normalized_markdown(raw_path, source_type)
    except Exception as exc:
        # 多格式转换器允许单文件失败，但不应该拖垮整个 ingest 批次。
        normalized_text, metadata = build_failed_conversion_placeholder(raw_path, source_type, exc)
    normalized_text = normalize_text_content("markdown", normalized_text)
    normalized_rel_path = Path("normalized") / f"{source_record['source_id']}.md"
    normalized_abs_path = target / normalized_rel_path
    normalized_abs_path.write_text(normalized_text, encoding="utf-8")

    # 标准化后的 hash 要单独记录，因为后面 chunk/claim 更关心“规范化后的稳定文本”。
    normalized_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    title = raw_path.stem
    location_map = dict(metadata.get("location_map", {}))
    location_map["source_path"] = source_record["source_path"]

    if location_map.get("type") == "line_map" and "normalized_line_range" not in location_map:
        line_count = len(normalized_text.splitlines()) or 1
        location_map["normalized_line_range"] = f"1-{line_count}"

    return {
        "source_id": source_record["source_id"],
        "source_type": source_type,
        "source_path": source_record["source_path"],
        "normalized_path": str(normalized_rel_path),
        "title": title,
        "language": "unknown",
        "content_format": metadata.get("content_format", "markdown"),
        "raw_hash": source_record["source_hash"],
        "normalized_hash": normalized_hash,
        "normalizer_version": "normalize_v1",
        "extraction_method": metadata.get("extraction_method", "python_only"),
        "extraction_quality": metadata.get("extraction_quality", "partial"),
        "warnings": metadata.get("warnings", []),
        "location_map": location_map,
        "updated_at": utc_now_iso(),
    }


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

        chunk_records.append({
            "chunk_id": chunk_id,
            "source_id": source_id,
            "source_path": source_path,
            "normalized_path": normalized_rel_path,
            "section_path": section_path,
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
            "chunker_version": "chunk_v1",
            "updated_at": utc_now_iso(),
        })

    return chunk_records


def build_chunk_records(normalized_record: dict, normalized_text: str) -> list[dict]:
    # 这里负责文档级切块：先按 section 拆，再给每段 section 分配 chunk 序号。
    sections = split_normalized_into_sections(normalized_text)
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

    return chunk_records


def write_source_chunks(target: Path, source_id: str, chunk_records: list[dict]) -> str:
    # chunks/ 目录里按 source_id 保存一份局部 JSONL，方便人工单独查看某个来源的切块结果。
    chunk_rel_path = Path("chunks") / f"{source_id}.jsonl"
    chunk_abs_path = target / chunk_rel_path
    write_jsonl(chunk_abs_path, chunk_records)
    return str(chunk_rel_path)


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
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"`{1,3}", "", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
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
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^\s*>\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[-*+]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*\d+[.)、:：]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[（(]?\d+[）)]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*(因此|所以|同时|此外|另外|不过|但是|而且|并且|而是)\s*", "", cleaned)
    cleaned = normalize_heading_plus_body_claim_candidate(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -:;,.!?。！？；：，、()[]{}\"'")


def claim_candidate_is_noise(text: str) -> bool:
    # 这里过滤几类高噪声片段：
    # - 纯链接 / 文件路径味太重
    # - 表格分隔线
    # - 几乎没有自然语言内容的标题或目录碎片
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return True
    if cleaned.startswith(("http://", "https://", "file://")):
        return True
    if re.fullmatch(r"[-|: ]{3,}", cleaned):
        return True
    if cleaned.count("/") >= 3 and len(cleaned) < 48:
        return True
    if cleaned.lower().startswith(("raw/", "../raw/", "wiki/", "claims/", "chunks/", "normalized/")):
        return True
    if len(cleaned) < 12:
        return True

    natural_chars = [
        char for char in cleaned
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    ]
    if len(natural_chars) < 8:
        return True
    return False


def split_long_claim_candidate(text: str, max_chars: int = 140) -> list[str]:
    # 很长的整段经常会把多个结论糊在一起。
    # 这里优先按中文逗号、顿号、分句连接词再切一次，但只取足够像独立陈述的片段。
    cleaned = clean_claim_candidate_text(text)
    if not cleaned:
        return []

    has_multi_clause_signal = any(
        marker in cleaned
        for marker in ("因此", "所以", "同时", "此外", "另外", "但是", "不过", "而且", "并且")
    ) and any(marker in cleaned for marker in ("，", ",", "；", ";"))
    if len(cleaned) <= max_chars and not has_multi_clause_signal:
        return [cleaned]

    secondary_parts = re.split(r"(?<=[，,；;。！？!?])\s*|(?=(?:但是|不过|因此|所以|同时|此外|另外|而且|并且|而是))", cleaned)
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
    candidates: list[str] = []
    raw_pieces = re.split(r"(?<=[。！？!?；;])\s+|\n{1,}|(?<=\.)\s{2,}", text)

    for raw_piece in raw_pieces:
        piece = clean_claim_candidate_text(raw_piece)
        if claim_candidate_is_noise(piece):
            continue
        for refined_piece in split_long_claim_candidate(piece):
            normalized_piece = clean_claim_candidate_text(refined_piece)
            if claim_candidate_is_noise(normalized_piece):
                continue
            if normalized_piece in candidates:
                continue
            candidates.append(normalized_piece)
            if len(candidates) >= DEFAULT_MAX_CLAIMS_PER_CHUNK:
                return candidates

    # 如果按句切之后一个都没留下，至少保留整段，避免 chunk 完全失去 claim 草稿。
    if not candidates and text.strip():
        fallback_piece = clean_claim_candidate_text(text.strip())
        if not claim_candidate_is_noise(fallback_piece):
            return [fallback_piece]
        return [text.strip()]
    return candidates[:DEFAULT_MAX_CLAIMS_PER_CHUNK]


def classify_claim_type(text: str) -> str:
    # 先给 Claim 一个启发式类型，后面接入 Agent 时可以被重写或提升。
    lowered = text.lower()
    if any(keyword in text for keyword in ("注意", "警告", "风险", "不要", "禁止")):
        return "warning"
    if any(keyword in text for keyword in ("步骤", "做法", "如何", "怎么", "先", "然后")):
        return "procedure"
    if any(keyword in text for keyword in ("因为", "因此", "导致", "使得", "原因")):
        return "causal"
    if any(keyword in text for keyword in ("相比", "对比", "区别", "优于", "弱于")):
        return "comparison"
    if any(keyword in text for keyword in ("是", "是指", "定义", "叫做")):
        return "definition"
    if any(keyword in lowered for keyword in ("better", "worse", "useful", "important", "effective")):
        return "evaluation"
    return "fact"


def estimate_claim_confidence(text: str) -> float:
    # 规则抽取得到的 claim 先统一低置信度起步，避免后续页面把它当成“已确认事实”。
    base = 0.35
    if len(text) >= 40:
        base += 0.05
    if len(text) >= 80:
        base += 0.05
    return min(base, 0.5)


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
    claim_record["lifecycle_status"] = claim_lifecycle_status_for_record(claim_record)
    return claim_record


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


def is_live_review_record(review_record: dict) -> bool:
    # review 只有在仍然挂着候选 claim、且 lifecycle 为 active 时，
    # 才应继续进入概念页和后续人工处理视图。
    return (
        review_record.get("lifecycle_status") == "active"
        and bool(review_record.get("candidate_claim_ids") or review_record.get("candidate_page_ids"))
    )


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
    records = [*live_reviews_by_id.values(), *historical_reviews_by_id.values()]
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
    claim_records = [
        ensure_claim_lifecycle_defaults(record)
        for record in load_jsonl(target / "state" / "claims.jsonl")
    ]
    live_claims = {record["claim_id"]: record for record in filter_live_claim_records(claim_records)}
    historical_claims = {
        record["claim_id"]: record
        for record in claim_records
        if not is_live_claim_record(record)
    }
    return live_claims, historical_claims, claim_records


def load_review_state_maps(target: Path) -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    review_records = [
        ensure_review_lifecycle_defaults(record)
        for record in load_jsonl(target / "state" / "reviews.jsonl")
    ]
    live_reviews = {record["review_id"]: record for record in filter_live_review_records(review_records)}
    historical_reviews = {
        record["review_id"]: record
        for record in review_records
        if not is_live_review_record(record)
    }
    return live_reviews, historical_reviews, review_records


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


def build_claim_record_from_chunk(chunk_record: dict, claim_text: str) -> dict:
    # 单条 Claim 草稿要把溯源线索一开始就带全，后面 page / review 都直接复用。
    normalized_text = normalize_claim_text(claim_text)
    claim_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    claim_id = f"clm_{chunk_record['source_id']}_{claim_hash[:12]}"
    now = utc_now_iso()

    return {
        "claim_id": claim_id,
        "text": claim_text.strip(),
        "normalized_text": normalized_text,
        "claim_type": classify_claim_type(claim_text),
        "status": "draft",
        "lifecycle_status": "active",
        "confidence": estimate_claim_confidence(claim_text),
        "source_ids": [chunk_record["source_id"]],
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
                "start_line": chunk_record["start_line"],
                "end_line": chunk_record["end_line"],
            }
        ],
        "extraction_method": "rule_based_chunk_v1",
        "created_at": now,
        "updated_at": now,
    }


def merge_claim_records(existing_record: dict, incoming_record: dict) -> dict:
    # 如果规范文本完全一致，就把它们视为同一 claim，并合并溯源关系。
    merged = dict(existing_record)
    for source_id in incoming_record["source_ids"]:
        append_unique(merged["source_ids"], source_id)
    for chunk_id in incoming_record["chunk_ids"]:
        append_unique(merged["chunk_ids"], chunk_id)
    for page_id in incoming_record.get("page_ids", []):
        append_unique(merged["page_ids"], page_id)

    existing_ref_keys = {
        (item["source_id"], item["chunk_id"])
        for item in merged.get("source_refs", [])
    }
    for source_ref in incoming_record.get("source_refs", []):
        ref_key = (source_ref["source_id"], source_ref["chunk_id"])
        if ref_key not in existing_ref_keys:
            merged.setdefault("source_refs", []).append(source_ref)
            existing_ref_keys.add(ref_key)

    merged["confidence"] = max(merged.get("confidence", 0.0), incoming_record.get("confidence", 0.0))
    merged["updated_at"] = utc_now_iso()
    merged["lifecycle_status"] = claim_lifecycle_status_for_record(merged)
    return merged


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
    # 一个 chunk 里可能有多个可提取陈述，但 V1 先控制上限，避免 claim 过碎。
    plain_text = markdown_to_plain_text(strip_fenced_code_blocks(chunk_record["text"]))
    claim_candidates = split_claim_candidates_from_text(plain_text)
    claim_records: list[dict] = []

    for candidate_text in claim_candidates:
        normalized_text = normalize_claim_text(candidate_text)
        if len(normalized_text) < 12:
            continue
        claim_records.append(build_claim_record_from_chunk(chunk_record, candidate_text))

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
) -> bool:
    # 这是一个“无上游变化”的保守短路条件：
    # - 没有新 source
    # - 没有新 normalized/chunk/claim/review
    # - 所有来源都已经走到 generated 或 failed
    # 满足这些条件时，source-summary / concept-summary / search index 在语义上都不该变化。
    if created_sources or normalized_sources or chunked_sources or claims_created_by_source or review_items:
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
        canonical_claim = choose_canonical_claim(grouped_claims)
        title = build_concept_title(canonical_claim)
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
) -> tuple[list[dict], set[str], set[str]]:
    # 这里负责清理“这轮模型下已经不该存在”的自动页面。
    # 典型场景是：同一路径文档被更新后，旧版本 source-summary 和旧概念页应退出主视图。
    removed_pages: list[dict] = []
    dirty_claim_ids: set[str] = set()
    dirty_review_ids: set[str] = set()

    stale_page_ids = [
        page_id
        for page_id, page_record in page_records_by_id.items()
        if page_record.get("type") in {"source-summary", "concept-summary"}
        and page_id not in desired_auto_page_ids
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
    return slug or "page"


def sanitize_page_filename(value: str) -> str:
    # 面向最终导出的页面文件名尽量保留可读性，避免把标题压成一串下划线。
    cleaned = clean_concept_title_text(value)
    cleaned = re.sub(r"[\\/:*?\"<>|#]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "page"


def summarize_claims_for_page(claim_records: list[dict], limit: int = 3) -> list[str]:
    # 来源摘要页先挑几条 claim 做“核心观点”。
    ranked = sorted(
        claim_records,
        key=lambda item: (item.get("confidence", 0.0), len(item.get("text", ""))),
        reverse=True,
    )
    return [item["text"] for item in ranked[:limit]]


def source_summary_page_path(source_id: str, title: str) -> Path:
    slug = sanitize_page_slug(title)
    return Path("wiki") / "sources" / f"{slug}__{source_id}.md"


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
    base_text = normalize_claim_base_for_conflict(claim_record.get("text", ""))
    similarity_tokens = build_claim_similarity_tokens(claim_record.get("text", ""))
    token_fingerprint = " ".join(similarity_tokens[:8])
    seed = base_text or claim_record.get("normalized_text", "") or claim_record.get("text", "")
    seed_hash = hashlib.sha256(f"{seed}|{token_fingerprint}".encode("utf-8")).hexdigest()[:12]
    readable_prefix = build_similarity_bucket(claim_record.get("text", ""))
    return f"{readable_prefix}|{seed_hash}"


def concept_summary_page_path(page_id: str, title: str) -> Path:
    # 概念页文件名尽量贴近最终展示标题，避免导出到外部工具时把内部 page_id 暴露成主标题。
    filename = sanitize_page_filename(title)
    return Path("wiki") / "concepts" / page_id / f"{filename}.md"


def clean_concept_title_text(value: str) -> str:
    # 概念页标题要尽量像“页面名”，而不是原始 claim 文本残片。
    cleaned = value.replace("|", " ").replace("_", " ")
    cleaned = re.sub(r"^\s*\d+\s*[.)、:：-]?\s*", "", cleaned)
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


def extract_primary_section_label(claim_record: dict) -> str:
    # 对概念页命名来说，section_path 往往比整句 claim 更接近“主题名”。
    for source_ref in claim_record.get("source_refs", []):
        section_path = source_ref.get("section_path", "")
        if not section_path:
            continue
        parts = [part.strip() for part in section_path.split(">") if part.strip()]
        if parts:
            return normalize_question_style_concept_label(parts[-1])
    return ""


def is_generic_concept_label(label: str) -> bool:
    # 有些 section label 太泛，比如“文档开始”“sample”“表格 1”，单独拿来做页面名会很弱。
    normalized = clean_concept_title_text(label).lower()
    if normalized in {"", "文档开始", "sample"}:
        return True
    if re.fullmatch(r"表格\s*\d+", normalized):
        return True
    return False


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


def build_concept_title(canonical_claim: dict) -> str:
    # 概念页标题优先用 section label，必要时再拼一个来自 claim 的补充短语。
    section_label = extract_primary_section_label(canonical_claim)
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


def choose_canonical_claim(claim_records: list[dict]) -> dict:
    # 一组 claim 需要选一个“代表陈述”，后面会用它来命名页面和生成摘要。
    ranked = sorted(
        claim_records,
        key=lambda item: (
            len(item.get("source_ids", [])),
            len(item.get("source_refs", [])),
            item.get("confidence", 0.0),
            len(item.get("text", "")),
        ),
        reverse=True,
    )
    return ranked[0]


def should_generate_concept_page(claim_records: list[dict]) -> bool:
    # 概念页不必给每条 claim 都生成一份。
    # V1 先优先保留三类更有价值的候选：
    # 1. 多条相似 claim 汇聚到一起；
    # 2. 单条 claim 但有多个来源支撑；
    # 3. 单条 claim 但置信度较高，值得先沉淀成主题入口。
    source_ids = {
        source_id
        for claim_record in claim_records
        for source_id in claim_record.get("source_ids", [])
    }
    if len(claim_records) >= 2:
        return True
    if len(source_ids) >= 2:
        return True
    if not claim_records:
        return False
    canonical_claim = choose_canonical_claim(claim_records)
    claim_text = canonical_claim.get("text", "")
    # 一些明显是“转换占位提示”的文本先不提升成概念页，避免 Wiki 被环境提示刷屏。
    if any(marker in claim_text for marker in ("当前环境缺少", "当前环境未启用", "仅生成占位", "估计页数:")):
        return False
    return canonical_claim.get("confidence", 0.0) >= 0.35 and len(claim_text) >= 18


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
                }
            append_unique(aggregated[source_id]["chunk_ids"], source_ref["chunk_id"])
            append_unique(aggregated[source_id]["claim_ids"], claim_record["claim_id"])
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


def build_source_summary_page(
    source_record: dict,
    normalized_record: dict | None,
    claim_records: list[dict],
    chunk_records: list[dict],
) -> tuple[str, dict]:
    # 第一版 wiki 页面先从“来源摘要页”做起，稳定承载这一份资料的处理结果。
    page_id = f"page_src_{source_record['source_id']}"
    title = normalized_record["title"] if normalized_record else Path(source_record["source_path"]).stem
    summary_claims = summarize_claims_for_page(claim_records)
    summary_text = summary_claims[0] if summary_claims else f"Source summary for {title}"

    lines = [
        "---",
        f'page_id: "{page_id}"',
        f'title: "{title}"',
        'type: "source-summary"',
        f'canonical_id: "{page_id}"',
        'status: "draft"',
        'automation_level: "auto_with_log"',
        f'source_id: "{source_record["source_id"]}"',
        f'claim_count: {len(claim_records)}',
        f'chunk_count: {len(chunk_records)}',
        "---",
        "",
        f"# {title}",
        "",
        "## 原文概览 / Source Overview",
        "",
        f"- 来源路径: `{source_record['source_path']}`",
        f"- 来源类型: `{source_record['source_type']}`",
        f"- 当前状态: `{source_record.get('status', 'unknown')}`",
    ]

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
        "## 核心观点 / Key Points",
        "",
    ])
    if summary_claims:
        for claim_text in summary_claims:
            lines.append(f"- {claim_text}")
    else:
        lines.append("- 当前尚未生成可用 claim。")

    lines.extend([
        "",
        "## 知识声明 / Claims",
        "",
    ])
    if claim_records:
        for claim_record in claim_records:
            lines.append(
                f"- `{claim_record['claim_id']}` [{claim_record['claim_type']}] "
                f"{claim_record['text']} (confidence={claim_record['confidence']:.2f})"
            )
    else:
        lines.append("- 暂无 claims。")

    lines.extend([
        "",
        "## 证据切块 / Chunks",
        "",
    ])
    if chunk_records:
        for chunk_record in chunk_records[:10]:
            lines.append(
                f"- `{chunk_record['chunk_id']}` {chunk_record['section_path']} "
                f"(lines {chunk_record['start_line']}-{chunk_record['end_line']})"
            )
        if len(chunk_records) > 10:
            lines.append(f"- ... 其余 {len(chunk_records) - 10} 个 chunk 省略")
    else:
        lines.append("- 暂无 chunks。")

    lines.extend([
        "",
        "## 后续建议 / Next Steps",
        "",
        "- 检查是否需要将高价值 claim 提升为概念页或综述页。",
        "- 若存在 partial / failed 提取，优先补强转换路径或人工审核。",
    ])

    page_text = "\n".join(lines).strip() + "\n"
    page_record = {
        "page_id": page_id,
        "title": title,
        "type": "source-summary",
        "canonical_id": page_id,
        "status": "draft",
        "lifecycle_status": "active",
        "automation_level": "auto_with_log",
        "review_reason": None,
        "summary": summary_text,
        "aliases": [],
        "redirect_to": None,
        "claim_ids": [item["claim_id"] for item in claim_records],
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


def build_concept_summary_page(
    bucket_key: str,
    page_rel_path: Path,
    claim_records: list[dict],
    page_records_by_id: dict[str, dict],
    review_records: list[dict],
) -> tuple[str, dict]:
    # 概念页的目标不是重复原文，而是把多条 claim 聚合成一个可继续编辑的主题入口。
    canonical_claim = choose_canonical_claim(claim_records)
    page_id = build_concept_page_id(bucket_key)
    title = build_concept_title(canonical_claim)
    canonical_key = build_concept_canonical_key(title)
    review_ids = collect_review_ids_for_claims(
        [claim_record["claim_id"] for claim_record in claim_records],
        review_records,
    )
    source_pages = collect_source_summary_pages_for_claims(claim_records, page_records_by_id)
    source_refs = aggregate_source_refs_for_page(claim_records)
    aliases = [
        alias
        for alias in {
            clean_concept_title_text(shorten_title_text(claim_record["text"], limit=36))
            for claim_record in claim_records
            if claim_record["text"] != canonical_claim["text"]
        }
        if alias
    ]
    section_alias = extract_primary_section_label(canonical_claim)
    if section_alias and section_alias != title:
        aliases.append(section_alias)
    claim_phrase_alias = extract_concept_phrase_from_claim(canonical_claim.get("text", ""), section_alias)
    if claim_phrase_alias and claim_phrase_alias != title:
        aliases.append(claim_phrase_alias)

    lines = [
        "---",
        f'page_id: "{page_id}"',
        f'title: "{title}"',
        'type: "concept-summary"',
        f'canonical_id: "concept:{canonical_key}"',
        f'status: "{"needs_review" if review_ids else "draft"}"',
        'automation_level: "auto_with_log"',
        f'claim_count: {len(claim_records)}',
        f'source_count: {len(source_refs)}',
        "---",
        "",
        f"# {title}",
        "",
        "## 概念摘要 / Concept Summary",
        "",
        f"- 规范概念键: `{canonical_key}`",
        f"- 聚类键: `{bucket_key}`",
        f"- 代表陈述: {canonical_claim['text']}",
        f"- 关联 Claim 数量: `{len(claim_records)}`",
        f"- 关联来源数量: `{len(source_refs)}`",
        f"- 关联审核项数量: `{len(review_ids)}`",
        "",
        "## 核心陈述 / Canonical Claim",
        "",
        f"- `{canonical_claim['claim_id']}` [{canonical_claim['claim_type']}] {canonical_claim['text']} "
        f"(confidence={canonical_claim['confidence']:.2f})",
        "",
        "## 支撑声明 / Supporting Claims",
        "",
    ]

    for claim_record in sorted(
        claim_records,
        key=lambda item: (
            len(item.get("source_ids", [])),
            item.get("confidence", 0.0),
            len(item.get("text", "")),
        ),
        reverse=True,
    ):
        lines.append(
            f"- `{claim_record['claim_id']}` [{claim_record['claim_type']}] {claim_record['text']} "
            f"(sources={len(claim_record.get('source_ids', []))}, "
            f"chunks={len(claim_record.get('chunk_ids', []))}, "
            f"confidence={claim_record['confidence']:.2f})"
        )

    lines.extend([
        "",
        "## 来源页面 / Source Pages",
        "",
    ])
    if source_pages:
        for source_page in source_pages:
            link = markdown_link_between_pages(page_rel_path, Path(source_page["page_path"]))
            lines.append(
                f"- [{source_page['title']}]({link}) "
                f"`{source_page['page_id']}`"
            )
    else:
        lines.append("- 当前还没有可链接的来源摘要页。")

    lines.extend([
        "",
        "## 来源证据 / Source Evidence",
        "",
    ])
    for source_ref in source_refs:
        lines.append(
            f"- `{source_ref['source_id']}` `{source_ref['source_path']}` "
            f"(claims={len(source_ref['claim_ids'])}, chunks={len(source_ref['chunk_ids'])})"
        )

    lines.extend([
        "",
        "## 审核提示 / Review Notes",
        "",
    ])
    if review_ids:
        for review_id in review_ids:
            lines.append(f"- 关联审核项: `{review_id}`")
    else:
        lines.append("- 当前没有命中的冲突或重复审核项。")

    lines.extend([
        "",
        "## 后续建议 / Next Steps",
        "",
        "- 若该概念跨多个来源重复出现，可继续沉淀为综述页或主题页。",
        "- 若该页命中审核项，优先处理 review 后再决定是否保留、合并或拆分概念。",
    ])

    page_text = "\n".join(lines).strip() + "\n"
    page_record = {
        "page_id": page_id,
        "title": title,
        "type": "concept-summary",
        "canonical_id": f"concept:{canonical_key}",
        "status": "needs_review" if review_ids else "draft",
        "lifecycle_status": "active",
        "automation_level": "auto_with_log",
        "review_reason": "claim_reviews_attached" if review_ids else None,
        "summary": canonical_claim["text"],
        "aliases": sorted(set(alias for alias in aliases if alias and alias != title))[:8],
        "redirect_to": None,
        "claim_ids": [claim_record["claim_id"] for claim_record in claim_records],
        "review_ids": review_ids,
        "source_refs": source_refs,
        "created": utc_now_iso(),
        "updated": utc_now_iso(),
        "archived_at": None,
    }
    return page_text, page_record


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
        "## 概念页 / Concept Pages",
        "",
    ]

    concept_pages = [
        record for record in page_records
        if record.get("type") == "concept-summary"
    ]
    source_pages = [
        record for record in page_records
        if record.get("type") == "source-summary"
    ]
    other_pages = [
        record for record in page_records
        if record.get("type") not in {"concept-summary", "source-summary"}
    ]

    if concept_pages:
        for record in sorted(concept_pages, key=lambda item: item["title"].lower()):
            page_path = markdown_link_target(record.get("page_path", ""))
            lines.append(
                f"- [{record['title']}]({page_path}) "
                f"({record['type']}, claims={len(record.get('claim_ids', []))}, reviews={len(record.get('review_ids', []))}) "
                f"- {record['summary']}"
            )
    else:
        lines.append("- 暂无概念页。")

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
    # query normalization 先保持轻量：
    # 统一空白、大小写和常见标点，得到一个稳定查询串。
    return normalize_claim_text(text)


def detect_query_intent(query_text: str, normalized_query: str) -> str:
    # V1 的意图识别先保持可解释：
    # 只看一些高频提示词，不做复杂分类模型。
    combined_text = f"{query_text.lower()} {normalized_query}"
    # 某些意图比 definition 更具体，例如“如何建立来源追踪”“来源证据是什么”。
    # 这里先把 how_to / evidence 提到前面，避免被“是什么”或“来源”误吞。
    if any(marker in combined_text for marker in QUERY_INTENT_MARKERS["how_to"]):
        return "how_to"
    if any(marker in combined_text for marker in QUERY_INTENT_MARKERS["evidence"]):
        return "evidence"
    for intent, markers in QUERY_INTENT_MARKERS.items():
        if intent in {"how_to", "evidence"}:
            continue
        if any(marker in combined_text for marker in markers):
            return intent
    return "lookup"


def alias_match_boost(page_record: dict, normalized_query: str, alias_hits: list[dict]) -> tuple[float, list[str]]:
    # alias/canonical 命中如果只回传不参与排序，用户感受会很奇怪。
    # 这里给精确命中一个温和加权，不会压过真正强相关的正文命中。
    boost_reasons: list[str] = []
    title_norm = normalize_query_text(page_record.get("title", ""))
    aliases_norm = [normalize_query_text(alias) for alias in page_record.get("aliases", [])]
    canonical_norm = normalize_query_text(page_record.get("canonical_id", "") or "")

    boost = 1.0
    if normalized_query and title_norm == normalized_query:
        boost = max(boost, QUERY_EXACT_MATCH_MAX_BOOST)
        boost_reasons.append("title_exact")
    if normalized_query and canonical_norm == normalized_query:
        boost = max(boost, 1.30)
        boost_reasons.append("canonical_exact")
    if normalized_query and normalized_query in aliases_norm:
        boost = max(boost, 1.25)
        boost_reasons.append("alias_exact")

    alias_hit_page_ids = {item.get("page_id") for item in alias_hits}
    if page_record.get("page_id") in alias_hit_page_ids:
        boost = max(boost, 1.20)
        boost_reasons.append("alias_registry_hit")

    return boost, boost_reasons


def query_intent_page_type_boost(intent: str, page_record: dict) -> tuple[float, str | None]:
    # query intent 只做一层轻微调权，用来把“看定义”和“看证据”这类问题往更合适的页型推一点。
    page_type = page_record.get("type", "")
    page_status = page_record.get("status", "")

    if intent == "definition" and page_type == "concept-summary":
        return 1.12, "intent_definition_prefers_concept"
    if intent == "compare" and page_type == "concept-summary":
        return 1.08, "intent_compare_prefers_concept"
    if intent == "how_to" and page_type == "source-summary":
        return 1.05, "intent_how_to_prefers_source"
    if intent == "evidence" and page_type == "source-summary":
        return 2.6, "intent_evidence_prefers_source"
    if intent == "evidence" and page_type == "concept-summary":
        return 0.35, "intent_evidence_deprioritizes_concept"
    if intent == "timeline" and page_status == "stable":
        return 1.05, "intent_timeline_prefers_stable"
    return 1.0, None


def query_intent_field_multiplier(intent: str, field_name: str) -> float:
    # 字段乘子只做轻量调权，尽量不破坏 BM25 的主体排序逻辑。
    return QUERY_INTENT_FIELD_MULTIPLIERS.get(intent, {}).get(field_name, 1.0)


def expand_query_with_alias_registry(
    query_text: str,
    alias_index: dict,
) -> dict:
    # 这一步负责把用户输入变成“可检索对象”：
    # - 原始查询
    # - 规范化查询
    # - alias 命中的扩展词
    # - 如果 alias 唯一映射到某个 canonical_id，就一并记录规范目标
    normalized_query = normalize_query_text(query_text)
    alias_map = alias_index.get("alias_map", {})
    canonical_map = alias_index.get("canonical_map", {})
    matched_alias_entries = alias_map.get(normalized_query, [])

    alias_expansions: list[str] = []
    canonical_targets: list[dict] = []
    for entry in matched_alias_entries:
        canonical_id = entry.get("canonical_id")
        canonical_record = canonical_map.get(canonical_id, {})
        for candidate in [
            entry.get("title", ""),
            canonical_id or "",
            *canonical_record.get("aliases", []),
        ]:
            normalized_candidate = normalize_query_text(candidate)
            if normalized_candidate and normalized_candidate not in alias_expansions:
                alias_expansions.append(normalized_candidate)
        if canonical_record and canonical_record not in canonical_targets:
            canonical_targets.append(canonical_record)

    expanded_parts = [normalized_query, *alias_expansions]
    expanded_query = " ".join(part for part in expanded_parts if part).strip()
    expanded_tokens = tokenize_for_search(expanded_query)
    detected_intent = detect_query_intent(query_text, normalized_query)

    return {
        "raw_query": query_text,
        "normalized_query": normalized_query,
        "expanded_query": expanded_query or normalized_query,
        "query_tokens": expanded_tokens,
        "alias_hits": matched_alias_entries,
        "canonical_targets": canonical_targets,
        "intent": detected_intent,
    }


def build_page_field_texts(page_record: dict, page_text: str, claim_records_by_id: dict[str, dict]) -> dict[str, str]:
    # query 读的是“页面视角”，但 claim/source 相关内容也要折叠进字段里参与排序。
    claim_texts = []
    for claim_id in page_record.get("claim_ids", []):
        claim_record = claim_records_by_id.get(claim_id)
        if claim_record is None:
            continue
        claim_texts.append(claim_record.get("text", ""))

    source_ref_parts = []
    for source_ref in page_record.get("source_refs", []):
        source_ref_parts.append(source_ref.get("source_id", ""))
        source_ref_parts.append(source_ref.get("source_path", ""))

    return {
        "title": page_record.get("title", ""),
        "aliases": "\n".join(page_record.get("aliases", [])),
        "summary": page_record.get("summary", ""),
        "headings": "\n".join(extract_markdown_headings(page_text)),
        "body": build_searchable_body_text(page_text),
        "claim_text": "\n".join(claim_texts),
        "source_refs": "\n".join(source_ref_parts),
    }


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
    # 设计文档里的类型名和当前实现的页面类型不完全一样，这里做一层兼容映射。
    page_type = page_record.get("type", "source-summary")
    return QUERY_PAGE_TYPE_WEIGHTS.get(page_type, QUERY_PAGE_TYPE_WEIGHTS.get("draft", 0.70))


def query_page_status_weight(page_record: dict) -> float:
    status = page_record.get("status", "draft")
    return QUERY_PAGE_STATUS_WEIGHTS.get(status, QUERY_PAGE_STATUS_WEIGHTS["draft"])


def build_query_documents(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
) -> list[dict]:
    # 页面记录是 query 的主入口；正文和 claim 文本会在这里汇总成待检索文档。
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


def build_search_index_record(document: dict) -> dict:
    # 持久化索引只保存 query 真正需要的字段，避免把整页正文重复存得过重。
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
        "field_texts": field_texts,
        "field_tokens": field_tokens,
        # 把页面签名一并写进索引，后续 ingest 就可以先看页面有没有变，
        # 没变时直接复用整条索引记录，连页面文件都不用再读。
        "page_signature": page_record.get("page_signature"),
        "document_signature": document_signature,
        "indexed_at": utc_now_iso(),
        "index_version": SEARCH_PAGES_INDEX_VERSION,
    }


def write_search_pages_index(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
    previous_records: list[dict] | None = None,
) -> dict:
    # search_pages.jsonl 是 query 的派生索引：
    # 页面权威内容仍然在 wiki/*.md 和 state/pages.jsonl，索引只负责加速读取。
    index_path = target / SEARCH_PAGES_INDEX_REL_PATH
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
            and previous_record.get("index_version") == SEARCH_PAGES_INDEX_VERSION
        ):
            reused_record = dict(previous_record)
            # 索引命中完全相同内容时，保留旧 indexed_at，便于观察哪些记录真的被重建过。
            records.append(reused_record)
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
        record = build_search_index_record({
            "page_record": page_record,
            "page_text": page_text,
            "field_texts": field_texts,
            "field_tokens": field_tokens,
        })

        records.append(record)
        rebuilt_count += 1

    write_jsonl(index_path, records)
    return {
        "index_path": str(SEARCH_PAGES_INDEX_REL_PATH),
        "record_count": len(records),
        "rebuilt_count": rebuilt_count,
        "reused_count": reused_count,
        "index_version": SEARCH_PAGES_INDEX_VERSION,
        "updated_at": utc_now_iso(),
    }


def load_search_pages_index(target: Path) -> list[dict]:
    index_path = target / SEARCH_PAGES_INDEX_REL_PATH
    if not index_path.exists():
        return []
    return load_jsonl(index_path)


def index_records_to_query_documents(index_records: list[dict]) -> list[dict]:
    # query 从索引恢复时，拼回与“现算文档”一致的形状，这样评分逻辑就可以复用。
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
        }
        documents.append({
            "page_record": page_record,
            "page_text": None,
            "field_texts": record.get("field_texts", {}),
            "field_tokens": record.get("field_tokens", {}),
        })
    return documents


def ensure_query_documents(
    target: Path,
    page_records: list[dict],
    claim_records_by_id: dict[str, dict],
) -> tuple[list[dict], str]:
    # query 优先读持久化索引；索引缺失时再降级现场构建，保证功能永远可用。
    index_records = load_search_pages_index(target)
    if index_records:
        return index_records_to_query_documents(index_records), "search_pages_index"
    return build_query_documents(target, page_records, claim_records_by_id), "live_scan"


def load_chunks_by_id(target: Path) -> dict[str, dict]:
    # chunk 阅读包要频繁按 chunk_id 回查，因此这里先建一个内存映射。
    chunks_path = target / "state" / "chunks.jsonl"
    if not chunks_path.exists():
        return {}
    chunk_records = load_jsonl(chunks_path)
    return {record["chunk_id"]: record for record in chunk_records}


def score_claim_for_query(query_tokens: list[str], claim_record: dict) -> tuple[float, list[str]]:
    # claim 排序先用一个轻量相关度：命中 token 越多、claim 自身越短小直接，越优先展示。
    claim_tokens = tokenize_for_search(claim_record.get("text", ""))
    matched_tokens = select_top_matches(query_tokens, claim_tokens, limit=8)
    if not matched_tokens:
        return 0.0, []
    score = float(len(matched_tokens)) + min(claim_record.get("confidence", 0.0), 1.0)
    return score, matched_tokens


def score_chunk_for_query(query_tokens: list[str], chunk_record: dict) -> tuple[float, list[str]]:
    # chunk 相关度同样保持简单：看 chunk 文本与摘要里实际命中的 token。
    chunk_text = "\n".join([chunk_record.get("summary", ""), chunk_record.get("text", "")])
    chunk_tokens = tokenize_for_search(chunk_text)
    matched_tokens = select_top_matches(query_tokens, chunk_tokens, limit=8)
    if not matched_tokens:
        return 0.0, []
    score = float(len(matched_tokens))
    # 更短的 chunk 往往更聚焦，给一个很轻的偏好。
    score += 0.25 if chunk_record.get("char_count", 0) <= 600 else 0.0
    return score, matched_tokens


def build_source_brief(source_ref: dict) -> dict:
    # 阅读包里不需要把 source 全量展开，先给一个短摘要，保持结果紧凑。
    return {
        "source_id": source_ref.get("source_id"),
        "source_path": source_ref.get("source_path"),
        "normalized_path": source_ref.get("normalized_path"),
        "start_line": source_ref.get("start_line"),
        "end_line": source_ref.get("end_line"),
        "section_path": source_ref.get("section_path"),
        "chunk_id": source_ref.get("chunk_id"),
    }


def build_chunk_reading_brief(chunk_record: dict) -> dict:
    # 设计文档要求命中 chunk 时附带 section_path / previous / next，这里固定打包出来。
    return {
        "chunk_id": chunk_record.get("chunk_id"),
        "section_path": chunk_record.get("section_path"),
        "start_line": chunk_record.get("start_line"),
        "end_line": chunk_record.get("end_line"),
        "summary": chunk_record.get("summary"),
        "text": chunk_record.get("text"),
        "previous_chunk": chunk_record.get("previous_chunk"),
        "next_chunk": chunk_record.get("next_chunk"),
        "source_id": chunk_record.get("source_id"),
        "source_path": chunk_record.get("source_path"),
        "normalized_path": chunk_record.get("normalized_path"),
    }


def build_timeline_sources(chunk_matches: list[dict]) -> list[dict]:
    # timeline query 需要的不是“更多 chunk”，而是“按来源组织的时序证据入口”。
    grouped: dict[str, dict] = {}
    for chunk in chunk_matches:
        source_id = chunk.get("source_id")
        if not source_id:
            continue
        if source_id not in grouped:
            grouped[source_id] = {
                "source_id": source_id,
                "source_path": chunk.get("source_path"),
                "normalized_path": chunk.get("normalized_path"),
                "chunk_ids": [],
                "section_paths": [],
            }
        if chunk.get("chunk_id") and chunk["chunk_id"] not in grouped[source_id]["chunk_ids"]:
            grouped[source_id]["chunk_ids"].append(chunk["chunk_id"])
        if chunk.get("section_path") and chunk["section_path"] not in grouped[source_id]["section_paths"]:
            grouped[source_id]["section_paths"].append(chunk["section_path"])
    return sorted(grouped.values(), key=lambda item: item["source_id"])


def build_result_reading_pack(
    result: dict,
    query_tokens: list[str],
    claim_records_by_id: dict[str, dict],
    chunk_records_by_id: dict[str, dict],
    claim_limit: int,
    chunk_limit: int,
    query_intent: str,
) -> dict:
    # 阅读包是 query V1 的关键补强：
    # 先返回“为什么命中这页”，再给最相关的 claims/chunks/sources，方便 Agent 继续读。
    claim_matches: list[dict] = []
    chunk_matches: list[dict] = []
    seen_chunk_ids: set[str] = set()

    for claim_id in result.get("claim_ids", []):
        claim_record = claim_records_by_id.get(claim_id)
        if claim_record is None:
            continue
        claim_score, claim_hits = score_claim_for_query(query_tokens, claim_record)
        if claim_score <= 0:
            continue

        claim_matches.append({
            "claim_id": claim_record["claim_id"],
            "text": claim_record.get("text", ""),
            "claim_type": claim_record.get("claim_type"),
            "status": claim_record.get("status"),
            "confidence": claim_record.get("confidence"),
            "matched_tokens": claim_hits,
            "source_refs": [build_source_brief(item) for item in claim_record.get("source_refs", [])],
            "_score": (
                claim_score + (len(claim_record.get("source_refs", [])) * 0.25)
                if query_intent == "evidence"
                else claim_score + 0.4
                if query_intent == "compare" and claim_record.get("claim_type") in {"comparison", "evaluation", "causal"}
                else claim_score + 0.2
                if query_intent == "timeline" and claim_record.get("source_refs")
                else claim_score
            ),
        })

        for chunk_id in claim_record.get("chunk_ids", []):
            if chunk_id in seen_chunk_ids:
                continue
            chunk_record = chunk_records_by_id.get(chunk_id)
            if chunk_record is None:
                continue
            chunk_score, chunk_hits = score_chunk_for_query(query_tokens, chunk_record)
            if chunk_score <= 0:
                continue
            seen_chunk_ids.add(chunk_id)
            chunk_matches.append({
                "matched_tokens": chunk_hits,
                "_score": (
                    chunk_score + 0.5
                    if query_intent == "evidence" and chunk_record.get("source_id")
                    else chunk_score + 0.45
                    if query_intent == "how_to" and any(
                        marker in (chunk_record.get("text", "") + chunk_record.get("summary", ""))
                        for marker in ("步骤", "首先", "然后", "最后", "如何", "怎么")
                    )
                    else chunk_score + 0.25
                    if query_intent == "timeline" and chunk_record.get("source_id")
                    else chunk_score
                ),
                **build_chunk_reading_brief(chunk_record),
            })

    claim_matches.sort(key=lambda item: item["_score"], reverse=True)
    chunk_matches.sort(key=lambda item: item["_score"], reverse=True)

    trimmed_claims = []
    for item in claim_matches[:claim_limit]:
        cleaned = dict(item)
        cleaned.pop("_score", None)
        trimmed_claims.append(cleaned)

    trimmed_chunks = []
    for item in chunk_matches[:chunk_limit]:
        cleaned = dict(item)
        cleaned.pop("_score", None)
        trimmed_chunks.append(cleaned)

    return {
        "page_summary": result.get("summary", ""),
        "query_intent": query_intent,
        "matched_claims": trimmed_claims,
        "matched_chunks": trimmed_chunks,
        "timeline_sources": build_timeline_sources(trimmed_chunks) if query_intent == "timeline" else [],
        "review_ids": result.get("review_ids", []),
        "focus": (
            "compare_claims" if query_intent == "compare"
            else "timeline_evidence" if query_intent == "timeline"
            else "procedural_chunks" if query_intent == "how_to"
            else "source_evidence" if query_intent == "evidence"
            else "general_lookup"
        ),
    }


def select_top_matches(query_tokens: list[str], field_tokens: list[str], limit: int = 5) -> list[str]:
    # 返回具体命中的 token，方便 CLI 输出“为什么这条结果排这么前面”。
    if not query_tokens or not field_tokens:
        return []
    field_counter = Counter(field_tokens)
    matches = []
    for token in query_tokens:
        if field_counter.get(token, 0) > 0 and token not in matches:
            matches.append(token)
    return matches[:limit]


def build_query_payload(
    target: Path,
    query_text: str,
    limit: int,
    claim_limit: int,
    chunk_limit: int,
) -> dict:
    # query 当前走“现算现查”策略：
    # 直接读取 state/pages.jsonl + claims + wiki 页面，避免先做一层复杂索引器。
    pages_path = target / "state" / "pages.jsonl"
    claims_path = target / "state" / "claims.jsonl"
    if not pages_path.exists():
        raise FileNotFoundError(f"Missing pages index: {pages_path}")

    page_records = [ensure_page_lifecycle_defaults(record) for record in load_jsonl(pages_path)]
    claim_records = [ensure_claim_lifecycle_defaults(record) for record in (load_jsonl(claims_path) if claims_path.exists() else [])]
    live_claim_records = filter_live_claim_records(claim_records)
    claim_records_by_id = {record["claim_id"]: record for record in live_claim_records}
    chunk_records_by_id = load_chunks_by_id(target)
    alias_index = load_alias_index(target)
    normalized_query_payload = expand_query_with_alias_registry(query_text, alias_index)

    normalized_query = normalized_query_payload["normalized_query"]
    query_tokens = normalized_query_payload["query_tokens"]
    query_intent = normalized_query_payload["intent"]
    documents, document_source = ensure_query_documents(target, page_records, claim_records_by_id)

    field_document_frequencies = {
        field_name: compute_document_frequency(
            [document["field_tokens"] for document in documents],
            field_name,
        )
        for field_name in QUERY_FIELD_WEIGHTS
    }
    field_average_lengths = {
        field_name: (
            sum(len(document["field_tokens"].get(field_name, [])) for document in documents) / len(documents)
            if documents else 0.0
        )
        for field_name in QUERY_FIELD_WEIGHTS
    }

    scored_results = []
    for document in documents:
        page_record = document["page_record"]
        field_scores: dict[str, float] = {}
        weighted_field_sum = 0.0
        field_hits: dict[str, list[str]] = {}

        for field_name, field_weight in QUERY_FIELD_WEIGHTS.items():
            document_tokens = document["field_tokens"].get(field_name, [])
            raw_score = bm25_score(
                query_tokens=query_tokens,
                document_tokens=document_tokens,
                document_frequency=field_document_frequencies[field_name],
                total_documents=len(documents),
                average_length=field_average_lengths[field_name],
            )
            if raw_score <= 0:
                continue
            intent_field_multiplier = query_intent_field_multiplier(query_intent, field_name)
            weighted_score = raw_score * field_weight * intent_field_multiplier
            field_scores[field_name] = round(weighted_score, 6)
            weighted_field_sum += weighted_score
            field_hits[field_name] = select_top_matches(query_tokens, document_tokens)

        if weighted_field_sum <= 0:
            continue

        page_type_weight = query_page_type_weight(page_record)
        page_status_weight = query_page_status_weight(page_record)
        exact_match_boost, exact_match_reasons = alias_match_boost(
            page_record=page_record,
            normalized_query=normalized_query,
            alias_hits=normalized_query_payload["alias_hits"],
        )
        intent_boost, intent_boost_reason = query_intent_page_type_boost(query_intent, page_record)
        final_score = weighted_field_sum * page_type_weight * page_status_weight * exact_match_boost * intent_boost
        result_record = {
            "page_id": page_record["page_id"],
            "title": page_record.get("title", ""),
            "page_path": page_record.get("page_path", ""),
            "type": page_record.get("type", ""),
            "status": page_record.get("status", ""),
            "summary": page_record.get("summary", ""),
            "claim_ids": page_record.get("claim_ids", []),
            "review_ids": page_record.get("review_ids", []),
            "score": round(final_score, 6),
            "field_scores": field_scores,
            "field_hits": field_hits,
            "page_type_weight": page_type_weight,
            "page_status_weight": page_status_weight,
            "exact_match_boost": round(exact_match_boost, 4),
            "exact_match_reasons": exact_match_reasons,
            "intent": query_intent,
            "intent_boost": round(intent_boost, 4),
            "intent_boost_reason": intent_boost_reason,
        }
        result_record["reading_pack"] = build_result_reading_pack(
            result=result_record,
            query_tokens=query_tokens,
            claim_records_by_id=claim_records_by_id,
            chunk_records_by_id=chunk_records_by_id,
            claim_limit=claim_limit,
            chunk_limit=chunk_limit,
            query_intent=query_intent,
        )
        scored_results.append(result_record)

    scored_results.sort(key=lambda item: (item["score"], item["title"]), reverse=True)
    return {
        "workspace": str(target),
        "query": query_text,
        "normalized_query": normalized_query,
        "expanded_query": normalized_query_payload["expanded_query"],
        "query_tokens": query_tokens,
        "intent": query_intent,
        "alias_hits": normalized_query_payload["alias_hits"],
        "canonical_targets": normalized_query_payload["canonical_targets"],
        "weights": {
            "fields": QUERY_FIELD_WEIGHTS,
            "intent_field_multipliers": QUERY_INTENT_FIELD_MULTIPLIERS,
            "page_types": QUERY_PAGE_TYPE_WEIGHTS,
            "page_status": QUERY_PAGE_STATUS_WEIGHTS,
            "exact_match_max_boost": QUERY_EXACT_MATCH_MAX_BOOST,
        },
        "document_source": document_source,
        "results": scored_results[:limit],
        "summary": {
            "candidate_page_count": len(documents),
            "matched_page_count": len(scored_results),
            "returned_page_count": min(limit, len(scored_results)),
        },
    }


def command_query(args: argparse.Namespace) -> CommandResult:
    # query 的 V1 目标是“先给出靠谱候选页 + 可解释排序原因”，而不是直接替用户写答案。
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    payload = build_query_payload(
        target=target,
        query_text=args.text,
        limit=args.limit,
        claim_limit=args.claim_limit,
        chunk_limit=args.chunk_limit,
    )

    if args.json:
        return CommandResult(payload=payload, message="Query completed.")

    if not payload["results"]:
        return CommandResult(
            payload=payload,
            message=f"No wiki results matched query: {args.text}",
        )

    lines = [
        f'Query: {payload["query"]}',
        f'Normalized: {payload["normalized_query"]}',
        f'Expanded: {payload["expanded_query"]}',
        f'Intent: {payload["intent"]}',
        "",
        "Top Results:",
    ]
    for index, result in enumerate(payload["results"], start=1):
        lines.append(
            f"{index}. {result['title']} [{result['type']}, status={result['status']}, score={result['score']:.4f}]"
        )
        lines.append(f"   path: {result['page_path']}")
        lines.append(f"   summary: {result['summary']}")
        if result["field_scores"]:
            explanation = ", ".join(
                f"{field}={score:.3f}"
                for field, score in sorted(result["field_scores"].items(), key=lambda item: item[1], reverse=True)
            )
            lines.append(f"   field_scores: {explanation}")
        if result.get("exact_match_reasons"):
            lines.append(
                f"   exact_match_boost: {result['exact_match_boost']:.3f} ({'/'.join(result['exact_match_reasons'])})"
            )
        if result.get("intent_boost_reason"):
            lines.append(
                f"   intent_boost: {result['intent_boost']:.3f} ({result['intent_boost_reason']})"
            )
        if result["field_hits"]:
            hit_explanation = ", ".join(
                f"{field}:{'/'.join(tokens)}"
                for field, tokens in result["field_hits"].items()
                if tokens
            )
            if hit_explanation:
                lines.append(f"   hits: {hit_explanation}")
        reading_pack = result.get("reading_pack", {})
        matched_claims = reading_pack.get("matched_claims", [])
        matched_chunks = reading_pack.get("matched_chunks", [])
        if matched_claims:
            lines.append("   matched_claims:")
            for claim in matched_claims:
                lines.append(
                    f"     - {claim['claim_id']} [{claim.get('claim_type')}] "
                    f"{claim['text']} (hits={'/'.join(claim.get('matched_tokens', []))})"
                )
        if matched_chunks:
            lines.append("   matched_chunks:")
            for chunk in matched_chunks:
                lines.append(
                    f"     - {chunk['chunk_id']} {chunk['section_path']} "
                    f"(lines {chunk['start_line']}-{chunk['end_line']}, hits={'/'.join(chunk.get('matched_tokens', []))})"
                )
                lines.append(
                    f"       prev={chunk.get('previous_chunk')} next={chunk.get('next_chunk')}"
                )
    return CommandResult(payload=payload, message="\n".join(lines))


def build_review_list_payload(target: Path, status_filter: str | None = None) -> dict:
    live_reviews_by_id, historical_reviews_by_id, all_review_records = load_review_state_maps(target)
    live_claims_by_id, historical_claims_by_id, _ = load_claim_state_maps(target)
    claim_lookup = build_claim_lookup_by_any_id(live_claims_by_id, historical_claims_by_id)

    review_records = all_review_records
    if status_filter:
        review_records = [
            record for record in review_records
            if record.get("status") == status_filter
        ]

    items = []
    for review_record in sorted(
        review_records,
        key=lambda item: (item.get("created_at", ""), review_display_id(item)),
        reverse=True,
    ):
        candidate_claims = []
        for claim_id in review_record.get("candidate_claim_ids", []):
            claim_record = claim_lookup.get(claim_id)
            if claim_record is None:
                continue
            candidate_claims.append({
                "claim_id": claim_id,
                "display_id": claim_display_id(claim_record),
                "lifecycle_status": claim_record.get("lifecycle_status"),
                "status": claim_record.get("status"),
                "text": claim_record.get("text", ""),
                "source_count": len(claim_record.get("source_ids", [])),
                "page_count": len(claim_record.get("page_ids", [])),
            })

        items.append({
            "review_id": review_record["review_id"],
            "display_id": review_display_id(review_record),
            "kind": review_record.get("kind"),
            "status": review_record.get("status"),
            "lifecycle_status": review_record.get("lifecycle_status"),
            "reason": review_record.get("reason"),
            "recommended_action": review_record.get("recommended_action"),
            "allowed_actions": review_record.get("allowed_actions", []),
            "candidate_page_ids": review_record.get("candidate_page_ids", []),
            "candidate_claims": candidate_claims,
            "created_at": review_record.get("created_at"),
            "resolved_at": review_record.get("resolved_at"),
            "archived_at": review_record.get("archived_at"),
        })

    return {
        "workspace": str(target),
        "items": items,
        "summary": {
            "review_count": len(items),
            "live_review_count": len(live_reviews_by_id),
            "historical_review_count": len(historical_reviews_by_id),
        },
    }


def command_review_list(args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    payload = build_review_list_payload(target, status_filter=args.status)
    if args.json:
        return CommandResult(payload=payload, message="Review list completed.")

    lines = ["Review Items:"]
    for index, item in enumerate(payload["items"], start=1):
        lines.append(
            f"{index}. {item['display_id']} [{item['kind']}, status={item['status']}, lifecycle={item['lifecycle_status']}]"
        )
        lines.append(f"   reason: {item['reason']}")
        lines.append(f"   recommended: {item['recommended_action']}")
        lines.append(f"   allowed: {', '.join(item['allowed_actions'])}")
        for claim in item["candidate_claims"][:4]:
            lines.append(
                f"   - {claim['display_id']} [{claim['lifecycle_status']}/{claim['status']}] {claim['text']}"
            )
    if len(lines) == 1:
        lines.append("No review items found.")
    return CommandResult(payload=payload, message="\n".join(lines))


def rebuild_review_affected_pages(
    target: Path,
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
) -> None:
    # review 动作完成后，如果不刷新页面，wiki 页面与 query 索引会滞后。
    # 这里走一个“小范围账本重建”：
    # 1. 重新根据 live claims / live reviews 计算 source-summary / concept-summary
    # 2. 移除不再需要的自动页
    # 3. 重建 pages.jsonl / wiki/index.md / search index
    config = load_workspace_config(target)
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
    live_claim_records = list(live_claims_by_id.values())
    live_review_records = [
        record for record in live_reviews_by_id.values()
        if is_actionable_review_record(record)
    ]

    # 先把旧的自动页反链从 live claim / review 中清掉，再按当前 live 集合重建。
    for page_record in list(page_records_by_id.values()):
        if page_record.get("type") not in {"source-summary", "concept-summary"}:
            continue
        page_id = page_record["page_id"]
        for claim_record in live_claim_records:
            if page_id in claim_record.get("page_ids", []):
                claim_record["page_ids"] = [item for item in claim_record["page_ids"] if item != page_id]
                claim_record["updated_at"] = utc_now_iso()
        for review_record in live_review_records:
            if page_id in review_record.get("candidate_page_ids", []):
                review_record["candidate_page_ids"] = [
                    item for item in review_record["candidate_page_ids"] if item != page_id
                ]

    claims_by_source_id: dict[str, list[dict]] = {}
    for claim_record in live_claim_records:
        for source_id in claim_record.get("source_ids", []):
            if source_id in active_source_ids:
                claims_by_source_id.setdefault(source_id, []).append(claim_record)

    for source_id in sorted(active_source_ids):
        source_record = sources_by_id.get(source_id)
        if source_record is None or source_record.get("status") == "failed":
            continue
        source_claims = claims_by_source_id.get(source_id, [])
        source_chunks = chunks_by_source_id.get(source_id, [])
        if not source_claims and not source_chunks:
            continue
        source_record_for_page = dict(source_record)
        source_record_for_page["status"] = "generated"
        normalized_record = normalized_records_by_source.get(source_id)
        page_text, page_record = build_source_summary_page(
            source_record=source_record_for_page,
            normalized_record=normalized_record,
            claim_records=source_claims,
            chunk_records=source_chunks,
        )
        page_record = apply_page_alias_overrides(target, page_record)
        page_record["page_path"] = str(source_summary_page_path(source_id, page_record["title"]))
        stored_page_record, _ = upsert_wiki_page(
            target=target,
            page_records_by_id=page_records_by_id,
            page_record=page_record,
            page_text=page_text,
        )
        link_claims_to_page_in_memory(source_claims, stored_page_record["page_id"], live_claims_by_id)

    concept_claim_groups: dict[str, list[dict]] = {}
    for claim_record in live_claim_records:
        active_claim_source_ids = [
            source_id for source_id in claim_record.get("source_ids", [])
            if source_id in active_source_ids
        ]
        if not active_claim_source_ids:
            continue
        bucket_key = build_concept_group_key(claim_record)
        concept_claim_groups.setdefault(bucket_key, []).append(claim_record)
    concept_claim_groups = regroup_concept_claims_by_canonical_topic(concept_claim_groups)

    for bucket_key, grouped_claims in sorted(concept_claim_groups.items()):
        if not should_generate_concept_page(grouped_claims):
            continue
        canonical_claim = choose_canonical_claim(grouped_claims)
        concept_page_id = build_concept_page_id(bucket_key)
        page_rel_path = concept_summary_page_path(concept_page_id, build_concept_title(canonical_claim))
        page_text, page_record = build_concept_summary_page(
            bucket_key=bucket_key,
            page_rel_path=page_rel_path,
            claim_records=grouped_claims,
            page_records_by_id=page_records_by_id,
            review_records=live_review_records,
        )
        page_record = apply_page_alias_overrides(target, page_record)
        page_record["page_path"] = str(page_rel_path)
        stored_page_record, _ = upsert_wiki_page(
            target=target,
            page_records_by_id=page_records_by_id,
            page_record=page_record,
            page_text=page_text,
        )
        link_claims_to_page_in_memory(grouped_claims, stored_page_record["page_id"], live_claims_by_id)
        link_reviews_to_page_in_memory(
            review_records=live_review_records,
            page_id=stored_page_record["page_id"],
            claim_ids=stored_page_record["claim_ids"],
            reviews_by_id=live_reviews_by_id,
        )

    desired_auto_page_ids = {
        expected_source_summary_page_id(source_id)
        for source_id in active_source_ids
        if claims_by_source_id.get(source_id) or chunks_by_source_id.get(source_id)
    }
    for bucket_key, grouped_claims in concept_claim_groups.items():
        if should_generate_concept_page(grouped_claims):
            desired_auto_page_ids.add(build_concept_page_id(bucket_key))

    prune_stale_auto_pages(
        target=target,
        page_records_by_id=page_records_by_id,
        desired_auto_page_ids=desired_auto_page_ids,
        claims_by_id=live_claims_by_id,
        reviews_by_id=live_reviews_by_id,
    )

    write_jsonl(
        target / "state" / "claims.jsonl",
        build_ordered_claim_state_records(
            live_claims_by_id=live_claims_by_id,
            historical_claims_by_id={
                record["claim_id"]: record
                for record in load_jsonl(target / "state" / "claims.jsonl")
                if ensure_claim_lifecycle_defaults(record).get("lifecycle_status") != "active"
            },
        ),
    )
    for claim_record in load_jsonl(target / "state" / "claims.jsonl"):
        write_claim_file(target, claim_record)

    write_jsonl(
        target / "state" / "reviews.jsonl",
        build_ordered_review_state_records(
            live_reviews_by_id=live_reviews_by_id,
            historical_reviews_by_id={
                record["review_id"]: record
                for record in load_jsonl(target / "state" / "reviews.jsonl")
                if not is_live_review_record(ensure_review_lifecycle_defaults(record))
            },
        ),
    )
    for review_record in load_jsonl(target / "state" / "reviews.jsonl"):
        write_review_file(target, review_record)

    write_jsonl(pages_path, list(page_records_by_id.values()))
    rebuild_wiki_index(target, list(page_records_by_id.values()))
    alias_index = write_alias_index(target, list(page_records_by_id.values()))
    alias_conflict_reviews, _ = build_alias_conflict_reviews(alias_index, live_reviews_by_id)
    if alias_conflict_reviews:
        for review_record in alias_conflict_reviews:
            live_reviews_by_id[review_record["review_id"]] = review_record
            review_record["review_file_path"] = write_review_file(target, review_record)
        write_jsonl(
            target / "state" / "reviews.jsonl",
            build_ordered_review_state_records(
                live_reviews_by_id=live_reviews_by_id,
                historical_reviews_by_id={
                    record["review_id"]: record
                    for record in load_jsonl(target / "state" / "reviews.jsonl")
                    if not is_live_review_record(ensure_review_lifecycle_defaults(record))
                },
            ),
        )
    previous_search_index_records = load_search_pages_index(target)
    write_search_pages_index(
        target=target,
        page_records=list(page_records_by_id.values()),
        claim_records_by_id=live_claims_by_id,
        previous_records=previous_search_index_records,
    )

def resolve_claim_record_for_action(
    claim_id: str,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
) -> dict:
    claim_record = build_claim_lookup_by_any_id(live_claims_by_id, historical_claims_by_id).get(claim_id)
    if claim_record is None:
        raise KeyError(f"Unknown claim_id: {claim_id}")
    return claim_record


def archive_live_claim(
    claim_record: dict,
    live_claims_by_id: dict[str, dict],
    historical_claims_by_id: dict[str, dict],
    archived_by_claim_id: str | None = None,
) -> dict:
    # archive_one / merge 都会复用这段逻辑：
    # 把在线 claim 迁到历史态，并保留被谁替代的线索。
    live_claims_by_id.pop(claim_record["claim_id"], None)
    claim_record = dict(claim_record)
    claim_record["lifecycle_status"] = "superseded"
    claim_record["archived_at"] = utc_now_iso()
    claim_record["updated_at"] = utc_now_iso()
    if archived_by_claim_id:
        append_unique(claim_record.setdefault("superseded_by", []), archived_by_claim_id)
    historical_claim_record = convert_claim_record_to_historical(claim_record)
    historical_claims_by_id[historical_claim_record["claim_id"]] = historical_claim_record
    return historical_claim_record


def normalize_claim_review_flags(claim_record: dict) -> None:
    # claim 上的 review 标志位要和当前人工状态同步。
    # 如果重复候选、冲突组都已经不再存在，就把它还原成普通 draft。
    duplicate_candidates = [
        item for item in claim_record.get("duplicate_candidates", [])
        if item != claim_record["claim_id"]
    ]
    claim_record["duplicate_candidates"] = sorted(set(duplicate_candidates))
    if claim_record.get("status") == "needs_review":
        has_duplicate_signal = bool(claim_record.get("duplicate_candidates"))
        has_conflict_signal = bool(claim_record.get("conflict_group"))
        if not has_duplicate_signal and not has_conflict_signal:
            claim_record["status"] = "draft"
            claim_record["review_reason"] = None
    claim_record["updated_at"] = utc_now_iso()


def sync_claim_review_state_from_open_reviews(
    claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
) -> set[str]:
    # 某条 review 被处理后，相关 claim 的“待审状态”不能只看旧标记，
    # 要重新基于当前仍然 open 的 review 集合计算一次。
    dirty_claim_ids: set[str] = set()
    target_claim_ids = {claim_id for claim_id in claim_ids if claim_id in live_claims_by_id}

    for claim_id in sorted(target_claim_ids):
        claim_record = live_claims_by_id.get(claim_id)
        if claim_record is None:
            continue

        duplicate_candidates: set[str] = set()
        conflict_group = claim_record.get("conflict_group")
        review_reason = None

        for review_record in live_reviews_by_id.values():
            if not is_actionable_review_record(review_record):
                continue
            candidate_claim_ids = set(review_record.get("candidate_claim_ids", []))
            if claim_id not in candidate_claim_ids:
                continue

            if review_record.get("kind") == "claim_duplicate":
                duplicate_candidates.update(candidate_claim_ids - {claim_id})
                review_reason = "possible_duplicate_claim"
            elif review_record.get("kind") == "claim_conflict":
                if not conflict_group:
                    conflict_group = claim_record.get("conflict_group")
                review_reason = "conflicting_claims_detected"

        claim_record["duplicate_candidates"] = sorted(duplicate_candidates)
        claim_record["conflict_group"] = conflict_group if review_reason == "conflicting_claims_detected" else None
        if review_reason:
            claim_record["status"] = "needs_review"
            claim_record["review_reason"] = review_reason
        else:
            claim_record["review_reason"] = None
        normalize_claim_review_flags(claim_record)
        dirty_claim_ids.add(claim_id)

    return dirty_claim_ids


def rewrite_open_reviews_for_claim_change(
    changed_review_id: str,
    removed_claim_id: str,
    replacement_claim_id: str | None,
    live_claims_by_id: dict[str, dict],
    live_reviews_by_id: dict[str, dict],
) -> tuple[set[str], set[str]]:
    # review 动作会改变候选 claim 集合：
    # - archive_one: 某个候选 claim 彻底退出
    # - merge: 某个候选 claim 被并入另一个仍存活的 claim
    # 这里把其他 open review 里对旧 claim 的引用一并修正，
    # 避免 review 队列继续挂着已经失效的候选项。
    dirty_review_ids: set[str] = set()
    touched_live_claim_ids: set[str] = set()

    for review_id, candidate_review in live_reviews_by_id.items():
        if review_id == changed_review_id:
            continue
        if candidate_review.get("status") != "open":
            continue

        original_claim_ids = list(candidate_review.get("candidate_claim_ids", []))
        if removed_claim_id not in original_claim_ids:
            continue

        rewritten_claim_ids: list[str] = []
        for claim_id in original_claim_ids:
            if claim_id != removed_claim_id:
                if claim_id not in rewritten_claim_ids:
                    rewritten_claim_ids.append(claim_id)
                continue
            if replacement_claim_id and replacement_claim_id not in rewritten_claim_ids:
                rewritten_claim_ids.append(replacement_claim_id)

        if rewritten_claim_ids == original_claim_ids:
            continue

        candidate_review["candidate_claim_ids"] = rewritten_claim_ids
        candidate_review["candidate_page_ids"] = []

        if len(rewritten_claim_ids) < 2:
            candidate_review["status"] = "resolved"
            candidate_review["resolved_at"] = utc_now_iso()
        candidate_review["lifecycle_status"] = review_lifecycle_status_for_record(candidate_review)
        dirty_review_ids.add(review_id)

        touched_live_claim_ids.update(set(original_claim_ids) | set(rewritten_claim_ids))

    sync_claim_review_state_from_open_reviews(
        claim_ids=sorted(touched_live_claim_ids),
        live_claims_by_id=live_claims_by_id,
        live_reviews_by_id=live_reviews_by_id,
    )

    return dirty_review_ids, touched_live_claim_ids


def cleanup_superseded_record_files(
    target: Path,
    historical_claims_by_id: dict[str, dict],
    historical_reviews_by_id: dict[str, dict],
) -> None:
    # state/*.jsonl 才是账本真相，但磁盘上的旧文件也要跟着收口。
    # 否则同一个 claim/review 在进入历史态后，会同时留下“旧活跃文件 + 新历史文件”两份。
    for claim_record in historical_claims_by_id.values():
        original_claim_id = claim_record.get("original_claim_id")
        if not original_claim_id or original_claim_id == claim_record["claim_id"]:
            continue
        stale_claim_path = claim_file_path(target, original_claim_id)
        if stale_claim_path.exists():
            stale_claim_path.unlink()

    for review_record in historical_reviews_by_id.values():
        original_review_id = review_record.get("original_review_id")
        if not original_review_id or original_review_id == review_record["review_id"]:
            continue
        stale_review_path = review_file_path(target, original_review_id)
        if stale_review_path.exists():
            stale_review_path.unlink()


def reload_claims_from_disk_for_review(
    target: Path,
    claim_ids: list[str],
    live_claims_by_id: dict[str, dict],
) -> set[str]:
    # edit_then_resume 的前提是“人已经先改了 claim 文件”。
    # 这里把指定 claim 的磁盘内容重新加载回内存账本。
    reloaded_claim_ids: set[str] = set()

    for claim_id in claim_ids:
        claim_path = claim_file_path(target, claim_id)
        if not claim_path.exists():
            raise FileNotFoundError(
                f"Claim file does not exist for edit_then_resume: {claim_path}"
            )
        disk_record = ensure_claim_lifecycle_defaults(load_json(claim_path))
        disk_record["claim_id"] = claim_id
        disk_record["claim_file_path"] = str(Path("claims") / claim_path.name)
        disk_record.setdefault("page_ids", live_claims_by_id.get(claim_id, {}).get("page_ids", []))
        live_claims_by_id[claim_id] = disk_record
        reloaded_claim_ids.add(claim_id)

    return reloaded_claim_ids


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
    allowed_actions = set(review_record.get("allowed_actions", []))
    if action not in allowed_actions:
        raise ValueError(f"Action `{action}` is not allowed for review `{review_display_id(review_record)}`.")

    candidate_claim_ids = list(review_record.get("candidate_claim_ids", []))
    candidate_page_ids = list(review_record.get("candidate_page_ids", []))

    if review_record.get("kind") == "alias_conflict" and action in {"assign_alias", "remove_alias"}:
        if not primary_page_id:
            raise ValueError(f"{action} requires --primary-page-id.")
        if primary_page_id not in candidate_page_ids:
            raise ValueError("primary page must belong to candidate_page_ids.")

        evidence = review_record.get("evidence", [])
        alias_from_review = evidence[0].get("alias") if evidence else None
        alias_to_assign = alias_value or alias_from_review
        if not alias_to_assign:
            raise ValueError(f"{action} requires alias value from review evidence or --alias-value.")

        if action == "assign_alias":
            overrides = load_page_alias_overrides(target)
            page_aliases = overrides.setdefault("page_aliases", {})
            live_aliases_by_page_id = load_live_page_aliases_by_id(target)
            normalized_alias = normalize_alias_value(alias_to_assign)

            for page_id in candidate_page_ids:
                page_override = page_aliases.setdefault(page_id, {})
                aliases = sorted(set(page_override.get("aliases", live_aliases_by_page_id.get(page_id, []))))
                aliases = [alias for alias in aliases if normalize_alias_value(alias) != normalized_alias]
                if page_id == primary_page_id and alias_to_assign not in aliases:
                    aliases.append(alias_to_assign)
                page_override["aliases"] = sorted(set(aliases))

            write_page_alias_overrides(target, overrides)
        else:
            remove_alias_from_overrides(target, candidate_page_ids, alias_to_assign)

        review_record["status"] = "resolved"
        review_record["resolved_at"] = utc_now_iso()
        review_record["lifecycle_status"] = "active"
        return {
            "action": action,
            "changed_page_ids": candidate_page_ids,
            "resolved_review_id": review_record["review_id"],
            "alias_value": alias_to_assign,
            "primary_page_id": primary_page_id,
        }

    if action == "keep_both":
        review_record["status"] = "resolved"
        review_record["resolved_at"] = utc_now_iso()
        review_record["lifecycle_status"] = "active"
        sync_claim_review_state_from_open_reviews(
            claim_ids=candidate_claim_ids,
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
        )
        return {
            "action": action,
            "changed_claim_ids": candidate_claim_ids,
            "resolved_review_id": review_record["review_id"],
        }

    if action == "edit_then_resume":
        reloaded_claim_ids = reload_claims_from_disk_for_review(
            target=target,
            claim_ids=candidate_claim_ids,
            live_claims_by_id=live_claims_by_id,
        )
        review_record["status"] = "resolved"
        review_record["resolved_at"] = utc_now_iso()
        review_record["lifecycle_status"] = "active"
        sync_claim_review_state_from_open_reviews(
            claim_ids=sorted(reloaded_claim_ids),
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
        )
        return {
            "action": action,
            "changed_claim_ids": sorted(reloaded_claim_ids),
            "resolved_review_id": review_record["review_id"],
        }

    if action == "archive_one":
        if not primary_claim_id:
            raise ValueError("archive_one requires --primary-claim-id.")
        if primary_claim_id not in candidate_claim_ids:
            raise ValueError("primary claim must belong to candidate_claim_ids.")
        claim_record = resolve_claim_record_for_action(primary_claim_id, live_claims_by_id, historical_claims_by_id)
        if claim_record["claim_id"] not in live_claims_by_id:
            raise ValueError("archive_one currently only supports active claims.")
        historical_claim_record = archive_live_claim(
            claim_record=claim_record,
            live_claims_by_id=live_claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
        )
        review_record["status"] = "resolved"
        review_record["resolved_at"] = utc_now_iso()
        review_record["lifecycle_status"] = "active"
        rewrite_open_reviews_for_claim_change(
            changed_review_id=review_record["review_id"],
            removed_claim_id=primary_claim_id,
            replacement_claim_id=None,
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
        )
        return {
            "action": action,
            "changed_claim_ids": [historical_claim_record["claim_id"]],
            "resolved_review_id": review_record["review_id"],
        }

    if action == "merge":
        if not primary_claim_id or not secondary_claim_id:
            raise ValueError("merge requires --primary-claim-id and --secondary-claim-id.")
        if primary_claim_id == secondary_claim_id:
            raise ValueError("primary and secondary claim ids must be different.")
        if primary_claim_id not in candidate_claim_ids or secondary_claim_id not in candidate_claim_ids:
            raise ValueError("Both primary and secondary claims must belong to candidate_claim_ids.")

        primary_record = resolve_claim_record_for_action(primary_claim_id, live_claims_by_id, historical_claims_by_id)
        secondary_record = resolve_claim_record_for_action(secondary_claim_id, live_claims_by_id, historical_claims_by_id)
        if primary_record["claim_id"] not in live_claims_by_id or secondary_record["claim_id"] not in live_claims_by_id:
            raise ValueError("merge currently only supports active claims.")

        merged_record = merge_claim_records(primary_record, secondary_record)
        merged_record["duplicate_candidates"] = [
            item for item in merged_record.get("duplicate_candidates", [])
            if item not in {merged_record["claim_id"], secondary_record["claim_id"]}
        ]
        merged_record["conflict_group"] = None
        merged_record["review_reason"] = None
        merged_record["status"] = "draft"
        merged_record["updated_at"] = utc_now_iso()
        live_claims_by_id[merged_record["claim_id"]] = merged_record

        historical_secondary = archive_live_claim(
            claim_record=secondary_record,
            live_claims_by_id=live_claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
            archived_by_claim_id=merged_record["claim_id"],
        )
        review_record["status"] = "resolved"
        review_record["resolved_at"] = utc_now_iso()
        review_record["lifecycle_status"] = "active"
        rewrite_open_reviews_for_claim_change(
            changed_review_id=review_record["review_id"],
            removed_claim_id=secondary_claim_id,
            replacement_claim_id=merged_record["claim_id"],
            live_claims_by_id=live_claims_by_id,
            live_reviews_by_id=live_reviews_by_id,
        )
        normalize_claim_review_flags(merged_record)
        return {
            "action": action,
            "changed_claim_ids": [merged_record["claim_id"], historical_secondary["claim_id"]],
            "resolved_review_id": review_record["review_id"],
        }

    raise NotImplementedError(f"Action `{action}` is not implemented yet.")


def command_review_apply(args: argparse.Namespace) -> CommandResult:
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    claims_path = target / "state" / "claims.jsonl"
    reviews_path = target / "state" / "reviews.jsonl"

    live_claims_by_id, historical_claims_by_id, _ = load_claim_state_maps(target)
    live_reviews_by_id, historical_reviews_by_id, _ = load_review_state_maps(target)

    review_record = live_reviews_by_id.get(args.review_id) or historical_reviews_by_id.get(args.review_id)
    if review_record is None:
        raise KeyError(f"Unknown review_id: {args.review_id}")
    if review_record["review_id"] not in live_reviews_by_id:
        raise ValueError("review_apply currently only supports active review items.")

    result = apply_review_action(
        target=target,
        review_record=review_record,
        action=args.action,
        primary_claim_id=args.primary_claim_id,
        secondary_claim_id=args.secondary_claim_id,
        primary_page_id=args.primary_page_id,
        alias_value=args.alias_value,
        live_claims_by_id=live_claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
        live_reviews_by_id=live_reviews_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )
    live_reviews_by_id[review_record["review_id"]] = review_record

    write_jsonl(
        claims_path,
        build_ordered_claim_state_records(
            live_claims_by_id=live_claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
        ),
    )
    for claim_record in [*live_claims_by_id.values(), *historical_claims_by_id.values()]:
        write_claim_file(target, claim_record)

    write_jsonl(
        reviews_path,
        build_ordered_review_state_records(
            live_reviews_by_id=live_reviews_by_id,
            historical_reviews_by_id=historical_reviews_by_id,
        ),
    )
    for review_state_record in [*live_reviews_by_id.values(), *historical_reviews_by_id.values()]:
        write_review_file(target, review_state_record)
    cleanup_superseded_record_files(
        target=target,
        historical_claims_by_id=historical_claims_by_id,
        historical_reviews_by_id=historical_reviews_by_id,
    )

    rebuild_review_affected_pages(
        target=target,
        live_claims_by_id=live_claims_by_id,
        live_reviews_by_id=live_reviews_by_id,
    )

    payload = {
        "workspace": str(target),
        "review_id": review_record["review_id"],
        "display_id": review_display_id(review_record),
        **result,
    }
    return CommandResult(payload=payload, message="Review action applied.")


def command_init(args: argparse.Namespace) -> CommandResult:
    # init 负责把“普通资料目录”初始化成“可被 Agent 驱动的 MyAgentWiki 工作区”。
    root = find_project_root()
    raw_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else None
    target_dir = Path(args.target_dir).expanduser().resolve() if args.target_dir else None

    if raw_dir is None and target_dir is None:
        target_dir = (Path.cwd() / args.project_name).resolve()
        raw_dir = (target_dir.parent / "raw").resolve()
    elif raw_dir is not None and target_dir is None:
        target_dir = (raw_dir.parent / args.project_name).resolve()
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

    ensure_clean_target(target_dir)
    # 这里即使目录不存在也没关系，mkdir 会顺手把父目录一起建出来。
    ensure_directory(target_dir)
    raw_dir_preexisting = raw_dir.exists()
    ensure_directory(raw_dir)
    raw_dir_relative_path = os.path.relpath(raw_dir, start=target_dir).replace(os.sep, "/")

    context = {
        "project_name": args.project_name,
        "source_dir_name": raw_dir.name,
        "source_dir_path": str(raw_dir),
        "raw_dir_name": raw_dir.name,
        "raw_dir_path": str(raw_dir),
        "raw_dir_relative_path": raw_dir_relative_path,
    }

    for directory in (
        "normalized",
        "chunks",
        "claims",
        "wiki",
        "indexes",
        "state",
        "reviews",
        "logs",
        "outputs",
        "config",
        "reports/lint",
    ):
        # 工作区目录先一次性建齐，后面各阶段脚本就可以假定这些路径始终存在。
        ensure_directory(target_dir / directory)

    template_root = root / "templates" / "project"
    # 模板文件保存的是“用户工作区初始化时需要复制的骨架文件”。
    template_files = {
        "AGENTS.md.tmpl": target_dir / "AGENTS.md",
        "CLAUDE.md.tmpl": target_dir / "CLAUDE.md",
        "gitignore.tmpl": target_dir / ".gitignore",
        "wiki/index.md.tmpl": target_dir / "wiki" / "index.md",
        "wiki/log.md.tmpl": target_dir / "wiki" / "log.md",
        "config/project.yml.tmpl": target_dir / "config" / "project.yml",
        "config/runtime_manifest.yml.tmpl": target_dir / "config" / "runtime_manifest.yml",
    }

    for template_name, output_path in template_files.items():
        # 用同一份 context 渲染，能保证 README、配置、Agent 说明里的项目名一致。
        rendered = render_template(template_root / template_name, context)
        output_path.write_text(rendered, encoding="utf-8")

    metadata_files = {
        target_dir / "state" / "sources.jsonl": [],
        target_dir / "state" / "ingest_state.jsonl": [],
        target_dir / "state" / "error_log.jsonl": [],
        target_dir / "state" / "normalized.jsonl": [],
        target_dir / "state" / "chunks.jsonl": [],
        target_dir / "state" / "claims.jsonl": [],
        target_dir / "state" / "reviews.jsonl": [],
        target_dir / "state" / "pages.jsonl": [],
        target_dir / SEARCH_PAGES_INDEX_REL_PATH: [],
    }
    for path, records in metadata_files.items():
        # 这些状态文件先创建成空 JSONL，后面脚本就不用额外判“文件是否存在”。
        write_jsonl(path, records)

    (target_dir / "reports" / "lint" / "lint_latest.md").write_text(
        "# Lint Report\n\nNo lint runs yet.\n",
        encoding="utf-8",
    )
    write_alias_index(target_dir, [])

    git_steps: list[str] = []
    if not (target_dir / ".git").exists():
        git_steps = git_init_and_commit(target_dir)

    payload = {
        "project_name": args.project_name,
        "source_dir": str(raw_dir),
        "raw_dir": str(raw_dir),
        "target_dir": str(target_dir),
        "created_directories": [
            str(raw_dir),
            *[
                str(target_dir / path)
                for path in (
                    "normalized",
                    "chunks",
                    "claims",
                    "wiki",
                    "indexes",
                    "state",
                    "reviews",
                    "logs",
                    "outputs",
                    "config",
                    "reports/lint",
                )
            ],
        ],
        "raw_dir_relative_path": raw_dir_relative_path,
        "raw_dir_preexisting": raw_dir_preexisting,
        "metadata_files": [str(path) for path in metadata_files],
        "git_steps": git_steps,
    }
    return CommandResult(payload=payload, message="Workspace initialized.")


def command_ingest(args: argparse.Namespace) -> CommandResult:
    # ingest 是第一条真正处理用户资料的流水线命令。
    # 它现在包含五步：来源登记、标准化、切块、Claim 草稿抽取、Wiki 页面生成。
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    config = load_workspace_config(target)
    raw_dir = resolve_workspace_path(target, config["paths"]["raw"])
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw directory does not exist: {raw_dir}")

    sources_path = target / "state" / "sources.jsonl"
    ingest_state_path = target / "state" / "ingest_state.jsonl"
    normalized_path = target / "state" / "normalized.jsonl"
    chunks_path = target / "state" / "chunks.jsonl"
    claims_path = target / "state" / "claims.jsonl"
    reviews_path = target / "state" / "reviews.jsonl"
    error_log_path = target / "state" / "error_log.jsonl"
    pages_path = target / "state" / "pages.jsonl"

    existing_sources = load_jsonl(sources_path)
    existing_by_hash = {record["source_hash"]: record for record in existing_sources}
    sources_by_id = {record["source_id"]: record for record in existing_sources}
    latest_source_by_path = build_latest_source_record_by_path(existing_sources)
    existing_normalized = {record["source_id"]: record for record in load_jsonl(normalized_path)}
    existing_chunked = {record["source_id"]: record for record in load_jsonl(chunks_path)}
    existing_claim_records = [ensure_claim_lifecycle_defaults(record) for record in load_jsonl(claims_path)]
    live_existing_claims = filter_live_claim_records(existing_claim_records)
    historical_existing_claims = [
        record for record in existing_claim_records
        if not is_live_claim_record(record)
    ]
    claims_by_id = {record["claim_id"]: record for record in live_existing_claims}
    historical_claims_by_id = {record["claim_id"]: record for record in historical_existing_claims}
    claims_by_normalized_text = {record["normalized_text"]: record for record in live_existing_claims}
    claims_by_similarity_bucket: dict[str, list[dict]] = {}
    for record in live_existing_claims:
        claims_by_similarity_bucket.setdefault(build_similarity_bucket(record["text"]), []).append(record)
    claim_similarity_index = rebuild_claim_similarity_index(live_existing_claims)
    existing_review_records = [
        ensure_review_lifecycle_defaults(record)
        for record in (load_jsonl(reviews_path) if reviews_path.exists() else [])
    ]
    live_existing_reviews = filter_live_review_records(existing_review_records)
    historical_existing_reviews = [
        record for record in existing_review_records
        if not is_live_review_record(record)
    ]
    existing_reviews = {
        record["review_id"]: record for record in live_existing_reviews
    }
    historical_reviews_by_id = {
        record["review_id"]: ensure_review_lifecycle_defaults(record)
        for record in historical_existing_reviews
    }
    # 这里按 hash 做首轮去重，意味着内容完全一样的文件只会登记一次。
    # 后面如果要支持“同内容不同来源”的更细建模，可以再加来源关系表。

    created_sources: list[dict] = []
    skipped_sources: list[dict] = []
    normalized_sources: list[dict] = []
    chunked_sources: list[dict] = []
    claimed_sources: list[dict] = []
    review_items: list[dict] = []
    error_items: list[dict] = []
    generated_pages: list[dict] = []
    task_id = f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    reingested_source_ids: set[str] = set()
    purged_claim_ids: set[str] = set()
    purged_review_ids: set[str] = set()

    # ingest 第一阶段只做来源登记：扫描 raw、生成 source_id、写 sources/state。
    for file_path in collect_files(raw_dir):
        source_hash = file_sha256(file_path)
        relative_path = os.path.relpath(file_path, start=target).replace(os.sep, "/")
        if source_hash in existing_by_hash:
            # 已有相同内容时跳过，避免反复导入导致 state 膨胀。
            skipped_sources.append({
                "path": str(file_path),
                "source_hash": source_hash,
                "reason": "duplicate_hash",
                "source_id": existing_by_hash[source_hash]["source_id"],
            })
            continue

        previous_path_record = latest_source_by_path.get(relative_path)
        if previous_path_record is not None:
            # 同一路径但内容哈希变化时，按“路径级版本更新”处理：
            # 复用原 source_id，清理旧证据链，再让后续 normalized/chunk/claim/wiki
            # 围绕同一个 source_id 重算，而不是无止境地产生平行来源版本。
            source_id = previous_path_record["source_id"]
            version_group = previous_path_record.get("version_group") or build_source_version_group_from_source_path(relative_path)
            previous_source_hash = previous_path_record.get("source_hash")
            previous_normalized_path = previous_path_record.get("normalized_path")

            existing_normalized.pop(source_id, None)
            existing_chunked.pop(source_id, None)

            if previous_normalized_path:
                normalized_file_path = target / previous_normalized_path
                if normalized_file_path.exists():
                    normalized_file_path.unlink()

            chunk_file_path = target / "chunks" / f"{source_id}.jsonl"
            if chunk_file_path.exists():
                chunk_file_path.unlink()

            dirty_claim_ids, deleted_claim_ids = purge_source_from_claims(
                target=target,
                claims_by_id=claims_by_id,
                historical_claims_by_id=historical_claims_by_id,
                source_id=source_id,
            )
            purged_claim_ids.update(deleted_claim_ids)

            dirty_review_ids, deleted_review_ids = purge_deleted_claims_from_reviews(
                reviews_by_id=existing_reviews,
                historical_reviews_by_id=historical_reviews_by_id,
                deleted_claim_ids=deleted_claim_ids,
            )
            purged_review_ids.update(deleted_review_ids)

            claims_by_normalized_text = {
                record["normalized_text"]: record for record in claims_by_id.values()
            }
            claims_by_similarity_bucket = {}
            for record in claims_by_id.values():
                claims_by_similarity_bucket.setdefault(build_similarity_bucket(record["text"]), []).append(record)
            claim_similarity_index = rebuild_claim_similarity_index(list(claims_by_id.values()))

            updated_record = dict(previous_path_record)
            updated_record.update({
                "source_path": relative_path,
                "source_type": infer_source_type(file_path),
                "source_hash": source_hash,
                "dedupe_key": source_hash,
                "version_group": version_group,
                "imported_at": utc_now_iso(),
                "status": "new",
                "normalized_path": None,
                "warnings": [],
            })
            replace_jsonl_record(sources_path, "source_id", source_id, updated_record)
            replace_jsonl_record(
                ingest_state_path,
                "source_id",
                source_id,
                {
                    "task_id": task_id,
                    "source_id": source_id,
                    "state": "new",
                    "last_successful_stage": None,
                    "failed_stage": None,
                    "retry_count": 0,
                    "updated_at": utc_now_iso(),
                },
            )

            sources_by_id[source_id] = updated_record
            latest_source_by_path[relative_path] = updated_record
            existing_by_hash[source_hash] = updated_record
            created_sources.append(updated_record)
            reingested_source_ids.add(source_id)
            continue

        source_id = build_source_id(raw_dir, file_path, source_hash)
        version_group = build_source_version_group(raw_dir, file_path)
        record = {
            "source_id": source_id,
            "source_path": relative_path,
            "source_type": infer_source_type(file_path),
            "source_uri": None,
            "source_hash": source_hash,
            "dedupe_key": source_hash,
            "version_group": version_group,
            "imported_at": utc_now_iso(),
            "status": "new",
            "normalized_path": None,
            "warnings": [],
        }
        append_jsonl(sources_path, record)
        append_jsonl(
            ingest_state_path,
            {
                "task_id": task_id,
                "source_id": source_id,
                "state": "new",
                "last_successful_stage": None,
                "failed_stage": None,
                "retry_count": 0,
                "updated_at": utc_now_iso(),
            },
        )
        created_sources.append(record)
        existing_sources.append(record)
        sources_by_id[source_id] = record
        latest_source_by_path[relative_path] = record

    # 来源登记完成后，第一版先支持 markdown/plain_text 的最小标准化。
    for source_record in load_jsonl(sources_path):
        if source_record["source_id"] in existing_normalized:
            # 已标准化过的记录直接跳过，保证 ingest 可以重复执行而不反复写文件。
            continue
        normalized_record = normalize_source_record(target, source_record)
        if normalized_record is None:
            # 暂不支持的文件类型先保留在 sources.jsonl，等待后续转换器接手。
            continue

        append_jsonl(normalized_path, normalized_record)
        normalized_sources.append(normalized_record)

        if normalized_record["extraction_quality"] in {"failed", "poor", "partial"}:
            level = "error" if normalized_record["extraction_quality"] == "failed" else "warning"
            error_items.append(
                append_error_record(
                    error_log_path=error_log_path,
                    task_id=task_id,
                    source_id=normalized_record["source_id"],
                    stage="normalized",
                    level=level,
                    message=f"Normalization finished with quality={normalized_record['extraction_quality']}",
                    details={
                        "warnings": normalized_record.get("warnings", []),
                        "normalized_path": normalized_record["normalized_path"],
                        "source_type": normalized_record["source_type"],
                    },
                )
            )

        updated_source = dict(source_record)
        updated_source["status"] = (
            "failed"
            if normalized_record["extraction_quality"] == "failed"
            else "review_required"
            if normalized_record["extraction_quality"] == "poor"
            else "normalized"
        )
        updated_source["normalized_path"] = normalized_record["normalized_path"]
        # sources.jsonl 记录的是“来源主档案”，状态变化后要同步更新。
        replace_jsonl_record(sources_path, "source_id", source_record["source_id"], updated_source)
        sources_by_id[source_record["source_id"]] = updated_source

        replace_jsonl_record(
            ingest_state_path,
            "source_id",
            source_record["source_id"],
            {
                "task_id": task_id,
                "source_id": source_record["source_id"],
                "state": (
                    "failed"
                    if normalized_record["extraction_quality"] == "failed"
                    else "review_required"
                    if normalized_record["extraction_quality"] == "poor"
                    else "normalized"
                ),
                "last_successful_stage": None if normalized_record["extraction_quality"] == "failed" else "normalized",
                "failed_stage": "normalized" if normalized_record["extraction_quality"] == "failed" else None,
                "retry_count": 0,
                "updated_at": utc_now_iso(),
            },
        )

    # 标准化完成后，继续把合格文档切成 chunk，作为 claim / query 的基础证据单元。
    for normalized_record in load_jsonl(normalized_path):
        if normalized_record["source_id"] in existing_chunked:
            continue

        chunk_result = chunk_normalized_record(target, normalized_record)
        if chunk_result is None:
            continue

        # 同一 source_id 的 chunk 在原位更新场景下应该整体替换，而不是继续 append。
        replace_jsonl_records_by_filter(
            chunks_path,
            keep_predicate=lambda record, source_id=chunk_result["source_id"]: record.get("source_id") != source_id,
            replacement_records=chunk_result["chunks"],
        )
        chunked_sources.append({
            "source_id": chunk_result["source_id"],
            "chunk_file_path": chunk_result["chunk_file_path"],
            "chunk_count": chunk_result["chunk_count"],
            "updated_at": chunk_result["updated_at"],
        })
        existing_chunked[chunk_result["source_id"]] = {
            "source_id": chunk_result["source_id"],
            "chunk_count": chunk_result["chunk_count"],
        }

        source_record = sources_by_id.get(normalized_record["source_id"])
        if source_record is not None:
            updated_source = dict(source_record)
            updated_source["status"] = "chunked"
            replace_jsonl_record(sources_path, "source_id", source_record["source_id"], updated_source)
            sources_by_id[source_record["source_id"]] = updated_source

        replace_jsonl_record(
            ingest_state_path,
            "source_id",
            normalized_record["source_id"],
            {
                "task_id": task_id,
                "source_id": normalized_record["source_id"],
                "state": "chunked",
                "last_successful_stage": "chunked",
                "failed_stage": None,
                "retry_count": 0,
                "updated_at": utc_now_iso(),
            },
        )

    # Claim 草稿层先做“保守抽取”：
    # 从 chunk 文本里提几条可能的陈述，把追踪链和审核机制先立起来。
    chunk_records = load_jsonl(chunks_path)
    claims_created_by_source: dict[str, int] = {}
    completed_claim_source_ids = {
        source_id
        for source_id, source_record in sources_by_id.items()
        if source_claim_stage_completed(source_record)
    }
    active_source_ids = choose_active_source_ids(sources_by_id)

    for chunk_record in chunk_records:
        if chunk_record["source_id"] in completed_claim_source_ids:
            continue
        chunk_claims = build_claims_from_chunk(chunk_record)
        for claim_record in chunk_claims:
            existing_claim = claims_by_normalized_text.get(claim_record["normalized_text"])
            if existing_claim is not None:
                merged_claim = merge_claim_records(existing_claim, claim_record)
                write_claim_file(target, merged_claim)
                replace_jsonl_record(claims_path, "claim_id", merged_claim["claim_id"], merged_claim)
                claims_by_id[merged_claim["claim_id"]] = merged_claim
                claims_by_normalized_text[merged_claim["normalized_text"]] = merged_claim
                continue

            similarity_bucket = build_similarity_bucket(claim_record["text"])
            candidate_claim_ids = collect_claim_review_candidate_ids(
                claim_record=claim_record,
                claims_by_similarity_bucket=claims_by_similarity_bucket,
                claim_similarity_index=claim_similarity_index,
            )
            conflicting_candidates = []
            duplicate_candidates = []
            incoming_has_negation = has_negation(claim_record["text"])

            for candidate_claim_id in sorted(candidate_claim_ids):
                similar_claim = claims_by_id.get(candidate_claim_id)
                if similar_claim is None:
                    continue
                if not claims_are_similar_for_review(claim_record["text"], similar_claim["text"]):
                    continue
                if has_negation(similar_claim["text"]) != incoming_has_negation:
                    conflicting_candidates.append(similar_claim)
                else:
                    duplicate_candidates.append(similar_claim)

            if duplicate_candidates:
                claim_record["duplicate_candidates"] = [item["claim_id"] for item in duplicate_candidates]
                claim_record["review_reason"] = "possible_duplicate_claim"
                claim_record["status"] = "needs_review"

                review_record = build_review_record(
                    kind="claim_duplicate",
                    candidate_claim_ids=sorted([claim_record["claim_id"], *[item["claim_id"] for item in duplicate_candidates]]),
                    reason="Detected highly similar claims that may need merge or archive decisions.",
                    evidence=[
                        {
                            "claim_id": claim_record["claim_id"],
                            "text": claim_record["text"],
                            "source_refs": claim_record["source_refs"],
                        },
                        *[
                            {
                                "claim_id": item["claim_id"],
                                "text": item["text"],
                                "source_refs": item.get("source_refs", []),
                            }
                            for item in duplicate_candidates
                        ],
                    ],
                    recommended_action="merge",
                    signature_parts=[
                        claim_record["normalized_text"],
                        *sorted(item["claim_id"] for item in duplicate_candidates),
                    ],
                )
                if review_record["review_id"] not in existing_reviews:
                    review_file_path = write_review_file(target, review_record)
                    review_record["review_file_path"] = review_file_path
                    append_jsonl(reviews_path, review_record)
                    existing_reviews[review_record["review_id"]] = review_record
                    review_items.append(review_record)

                error_items.append(
                    append_error_record(
                        error_log_path=error_log_path,
                        task_id=task_id,
                        source_id=claim_record["source_ids"][0],
                        stage="claim",
                        level="warning",
                        message="Possible duplicate claims detected",
                        details={
                            "claim_id": claim_record["claim_id"],
                            "duplicate_candidates": claim_record["duplicate_candidates"],
                        },
                    )
                )

            if conflicting_candidates:
                conflict_claim_ids = sorted([claim_record["claim_id"], *[item["claim_id"] for item in conflicting_candidates]])
                conflict_group = hashlib.sha256("|".join(conflict_claim_ids).encode("utf-8")).hexdigest()[:12]
                claim_record["conflict_group"] = f"cfg_{conflict_group}"
                claim_record["review_reason"] = "conflicting_claims_detected"
                claim_record["status"] = "needs_review"

                evidence = [
                    {
                        "claim_id": claim_record["claim_id"],
                        "text": claim_record["text"],
                        "source_refs": claim_record["source_refs"],
                    }
                ]
                evidence.extend({
                    "claim_id": item["claim_id"],
                    "text": item["text"],
                    "source_refs": item.get("source_refs", []),
                } for item in conflicting_candidates)

                review_record = build_review_record(
                    kind="claim_conflict",
                    candidate_claim_ids=conflict_claim_ids,
                    reason="Detected claims with opposite negation pattern but very similar normalized content.",
                    evidence=evidence,
                    recommended_action="keep_both",
                )
                if review_record["review_id"] not in existing_reviews:
                    review_file_path = write_review_file(target, review_record)
                    review_record["review_file_path"] = review_file_path
                    append_jsonl(reviews_path, review_record)
                    existing_reviews[review_record["review_id"]] = review_record
                    review_items.append(review_record)

                error_items.append(
                    append_error_record(
                        error_log_path=error_log_path,
                        task_id=task_id,
                        source_id=claim_record["source_ids"][0],
                        stage="claim",
                        level="warning",
                        message="Conflicting claims detected",
                        details={
                            "claim_id": claim_record["claim_id"],
                            "conflict_group": claim_record["conflict_group"],
                            "candidate_claim_ids": conflict_claim_ids,
                        },
                    )
                )

            claim_file_rel_path = write_claim_file(target, claim_record)
            claim_record["claim_file_path"] = claim_file_rel_path
            append_jsonl(claims_path, claim_record)
            claims_by_id[claim_record["claim_id"]] = claim_record
            claims_by_normalized_text[claim_record["normalized_text"]] = claim_record
            claims_by_similarity_bucket.setdefault(similarity_bucket, []).append(claim_record)
            index_claim_similarity_tokens(claim_similarity_index, claim_record)
            source_id = claim_record["source_ids"][0]
            claims_created_by_source[source_id] = claims_created_by_source.get(source_id, 0) + 1

    for source_id, claim_count in sorted(claims_created_by_source.items()):
        source_claims = [
            record for record in claims_by_id.values()
            if source_id in record.get("source_ids", [])
        ]
        has_review_claim = any(record.get("status") == "needs_review" for record in source_claims)

        claimed_sources.append({
            "source_id": source_id,
            "claim_count": claim_count,
            "needs_review": has_review_claim,
        })

        source_record = sources_by_id.get(source_id)
        if source_record is not None:
            updated_source = dict(source_record)
            updated_source["status"] = "review_required" if has_review_claim else "claimed"
            replace_jsonl_record(sources_path, "source_id", source_id, updated_source)
            sources_by_id[source_id] = updated_source

        replace_jsonl_record(
            ingest_state_path,
            "source_id",
            source_id,
            {
                "task_id": task_id,
                "source_id": source_id,
                "state": "review_required" if has_review_claim else "claimed",
                "last_successful_stage": "claimed",
                "failed_stage": None,
                "retry_count": 0,
                "updated_at": utc_now_iso(),
            },
        )

    # 如果来源被原位重算过，claims/reviews 的内存状态可能已经发生清理或删除，
    # 这里先统一刷回 state 文件，确保后续页面生成和 lint 看到的是同一套事实。
    if reingested_source_ids or purged_claim_ids:
        claim_state_records = build_ordered_claim_state_records(
            live_claims_by_id=claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
        )
        write_jsonl(claims_path, claim_state_records)
        for claim_record in claim_state_records:
            write_claim_file(target, claim_record)

    if reingested_source_ids or purged_review_ids:
        review_state_records = build_ordered_review_state_records(
            live_reviews_by_id=existing_reviews,
            historical_reviews_by_id=historical_reviews_by_id,
        )
        write_jsonl(reviews_path, review_state_records)
        for review_record in review_state_records:
            write_review_file(target, review_record)

    # 如果这次 ingest 没有引入任何上游变化，就不必再完整重跑页面生成与索引更新。
    # 这样重复执行 ingest 时，系统会更像“增量编译”而不是“全量重编”。
    can_skip_page_regeneration = workspace_can_skip_page_regeneration(
        sources_by_id=sources_by_id,
        created_sources=created_sources,
        normalized_sources=normalized_sources,
        chunked_sources=chunked_sources,
        claims_created_by_source=claims_created_by_source,
        review_items=review_items,
    )

    if can_skip_page_regeneration:
        existing_pages = [ensure_page_lifecycle_defaults(record) for record in load_jsonl(pages_path)] if pages_path.exists() else []
        live_existing_pages = filter_live_page_records(existing_pages)
        page_records_by_id = {record["page_id"]: record for record in existing_pages}
        all_chunk_records = load_jsonl(chunks_path)
        claims_by_source_id: dict[str, list[dict]] = {}
        for claim_record in claims_by_id.values():
            for source_id in claim_record.get("source_ids", []):
                claims_by_source_id.setdefault(source_id, []).append(claim_record)
        chunks_by_source_id: dict[str, list[dict]] = {}
        for chunk_record in all_chunk_records:
            chunks_by_source_id.setdefault(chunk_record["source_id"], []).append(chunk_record)
        missing_source_page_source_ids = collect_missing_source_page_source_ids(
            active_source_ids=active_source_ids,
            sources_by_id=sources_by_id,
            page_records_by_id=page_records_by_id,
            claims_by_source_id=claims_by_source_id,
            chunks_by_source_id=chunks_by_source_id,
        )
        missing_concept_bucket_keys = collect_missing_concept_bucket_keys(
            claims_by_similarity_bucket=claims_by_similarity_bucket,
            page_records_by_id=page_records_by_id,
        )
        if missing_source_page_source_ids or missing_concept_bucket_keys:
            can_skip_page_regeneration = False

    if can_skip_page_regeneration:
        previous_search_index_records = load_search_pages_index(target)
        search_index = {
            "index_path": str(SEARCH_PAGES_INDEX_REL_PATH),
            "record_count": len(previous_search_index_records),
            "rebuilt_count": 0,
            "reused_count": len(previous_search_index_records),
            "index_version": SEARCH_PAGES_INDEX_VERSION,
            "updated_at": utc_now_iso(),
        }
        append_wiki_log(target, task_id, generated_pages)
        payload = {
            "task_id": task_id,
            "workspace": str(target),
            "raw_dir": str(raw_dir),
            "created_sources": created_sources,
            "skipped_sources": skipped_sources,
            "normalized_sources": normalized_sources,
            "chunked_sources": chunked_sources,
            "claimed_sources": claimed_sources,
            "generated_pages": generated_pages,
            "search_index": search_index,
            "review_items": review_items,
            "error_items": error_items,
            "summary": {
                "created_count": len(created_sources),
                "skipped_count": len(skipped_sources),
                "normalized_count": len(normalized_sources),
                "chunked_count": len(chunked_sources),
                "claimed_count": len(claimed_sources),
                "changed_page_count": 0,
                "review_count": len(review_items),
                "error_count": len([item for item in error_items if item["level"] == "error"]),
                "warning_count": len([item for item in error_items if item["level"] == "warning"]),
                "existing_page_count": len(live_existing_pages),
                "tracked_page_count": len(existing_pages),
            },
        }
        return CommandResult(
            payload=payload,
            message="Ingest completed with no upstream changes; wiki regeneration was skipped.",
        )

    # 先生成来源摘要页，形成 source -> claim -> page 的第一层闭环。
    page_records = [ensure_page_lifecycle_defaults(record) for record in load_jsonl(pages_path)] if pages_path.exists() else []
    page_records_by_id = {record["page_id"]: record for record in page_records}
    all_claim_records = build_ordered_claim_state_records(
        live_claims_by_id=claims_by_id,
        historical_claims_by_id=historical_claims_by_id,
    )
    all_chunk_records = load_jsonl(chunks_path)
    dirty_claim_ids: set[str] = set()
    dirty_review_ids: set[str] = set()
    changed_source_ids = {record["source_id"] for record in created_sources}
    changed_source_ids.update(record["source_id"] for record in normalized_sources)
    changed_source_ids.update(record["source_id"] for record in chunked_sources)
    changed_source_ids.update(claims_created_by_source.keys())
    normalized_records_by_source = {
        record["source_id"]: record for record in load_jsonl(normalized_path)
    }
    claims_by_source_id: dict[str, list[dict]] = {}
    for claim_record in filter_live_claim_records(all_claim_records):
        for source_id in claim_record.get("source_ids", []):
            claims_by_source_id.setdefault(source_id, []).append(claim_record)
    chunks_by_source_id: dict[str, list[dict]] = {}
    for chunk_record in all_chunk_records:
        chunks_by_source_id.setdefault(chunk_record["source_id"], []).append(chunk_record)

    changed_source_ids.update(
        collect_missing_source_page_source_ids(
            active_source_ids=active_source_ids,
            sources_by_id=sources_by_id,
            page_records_by_id=page_records_by_id,
            claims_by_source_id=claims_by_source_id,
            chunks_by_source_id=chunks_by_source_id,
        )
    )

    for source_record in load_jsonl(sources_path):
        source_id = source_record["source_id"]
        if source_id not in changed_source_ids:
            continue
        if source_id not in active_source_ids:
            continue
        source_claims = claims_by_source_id.get(source_id, [])
        source_chunks = chunks_by_source_id.get(source_id, [])
        if not source_claims and not source_chunks:
            continue

        # 来源摘要页正文里会展示当前来源状态。
        # 如果这里仍然沿用上一阶段的 claimed/chunked 状态，第一页生成出来的正文
        # 就会和后面真正写回 sources.jsonl 的 generated 状态不一致，导致下一次 ingest
        # 平白再改一遍来源页。这里先在内存里把“即将生成页面”的来源状态提升到 generated，
        # 再用于页面渲染和状态落盘，保证第一次与后续重复运行的页面签名一致。
        source_record_for_page = dict(sources_by_id.get(source_id, source_record))
        source_record_for_page["status"] = "generated"

        normalized_record = normalized_records_by_source.get(source_id)
        page_text, page_record = build_source_summary_page(
            source_record=source_record_for_page,
            normalized_record=normalized_record,
            claim_records=source_claims,
            chunk_records=source_chunks,
        )
        page_record = apply_page_alias_overrides(target, page_record)
        page_rel_path = source_summary_page_path(source_id, page_record["title"])
        page_record["page_path"] = str(page_rel_path)
        stored_page_record, page_changed = upsert_wiki_page(
            target=target,
            page_records_by_id=page_records_by_id,
            page_record=page_record,
            page_text=page_text,
        )
        if page_changed:
            generated_pages.append(stored_page_record)
            dirty_claim_ids.update(
                link_claims_to_page_in_memory(
                    source_claims,
                    stored_page_record["page_id"],
                    claims_by_id,
                )
            )

        replace_jsonl_record(
            ingest_state_path,
            "source_id",
            source_id,
            {
                "task_id": task_id,
                "source_id": source_id,
                "state": "generated",
                "last_successful_stage": "generated",
                "failed_stage": None,
                "retry_count": 0,
                "updated_at": utc_now_iso(),
            },
        )

        replace_jsonl_record(sources_path, "source_id", source_id, source_record_for_page)
        sources_by_id[source_id] = source_record_for_page

    # 再生成概念候选页，让多来源、多 claim 的主题可以在 Wiki 层聚合起来。
    # 这里直接沿用内存中的 claims 映射，保证前面给来源页补上的 page 反链
    # 在概念页生成阶段立刻可见，不必依赖中途先刷回磁盘。
    all_claim_records = list(claims_by_id.values())
    review_records = list(existing_reviews.values())
    concept_claim_groups: dict[str, list[dict]] = {}
    for claim_record in all_claim_records:
        active_claim_source_ids = [
            source_id for source_id in claim_record.get("source_ids", [])
            if source_id in active_source_ids
        ]
        if not active_claim_source_ids:
            continue
        # 概念页聚合与 review 检测共享更稳的 group key，减少“同主题分裂成多页”。
        bucket_key = build_concept_group_key(claim_record)
        concept_claim_groups.setdefault(bucket_key, []).append(claim_record)
    concept_claim_groups = regroup_concept_claims_by_canonical_topic(concept_claim_groups)

    changed_bucket_keys = set()
    for claim_record in all_claim_records:
        if any(source_id in changed_source_ids for source_id in claim_record.get("source_ids", [])):
            original_bucket_key = build_concept_group_key(claim_record)
            matching_bucket_key = next(
                (
                    bucket_key
                    for bucket_key, grouped_claims in concept_claim_groups.items()
                    if any(item["claim_id"] == claim_record["claim_id"] for item in grouped_claims)
                ),
                original_bucket_key,
            )
            changed_bucket_keys.add(matching_bucket_key)
    changed_bucket_keys.update(
        collect_missing_concept_bucket_keys(
            claims_by_similarity_bucket=concept_claim_groups,
            page_records_by_id=page_records_by_id,
        )
    )

    for bucket_key, grouped_claims in sorted(concept_claim_groups.items()):
        if bucket_key not in changed_bucket_keys:
            continue
        if not should_generate_concept_page(grouped_claims):
            continue

        canonical_claim = choose_canonical_claim(grouped_claims)
        concept_page_id = build_concept_page_id(bucket_key)
        concept_title = build_concept_title(canonical_claim)
        page_rel_path = concept_summary_page_path(
            concept_page_id,
            concept_title,
        )
        page_text, page_record = build_concept_summary_page(
            bucket_key=bucket_key,
            page_rel_path=page_rel_path,
            claim_records=grouped_claims,
            page_records_by_id=page_records_by_id,
            review_records=review_records,
        )
        page_record = apply_page_alias_overrides(target, page_record)
        page_record["page_path"] = str(page_rel_path)
        stored_page_record, page_changed = upsert_wiki_page(
            target=target,
            page_records_by_id=page_records_by_id,
            page_record=page_record,
            page_text=page_text,
        )
        if page_changed:
            generated_pages.append(stored_page_record)
            dirty_claim_ids.update(
                link_claims_to_page_in_memory(
                    grouped_claims,
                    stored_page_record["page_id"],
                    claims_by_id,
                )
            )
            dirty_review_ids.update(
                link_reviews_to_page_in_memory(
                    review_records=review_records,
                    page_id=stored_page_record["page_id"],
                    claim_ids=stored_page_record["claim_ids"],
                    reviews_by_id=existing_reviews,
                )
            )

    desired_auto_page_ids = {
        expected_source_summary_page_id(source_id)
        for source_id in active_source_ids
        if claims_by_source_id.get(source_id) or chunks_by_source_id.get(source_id)
    }
    for bucket_key, grouped_claims in concept_claim_groups.items():
        if should_generate_concept_page(grouped_claims):
            desired_auto_page_ids.add(build_concept_page_id(bucket_key))

    removed_pages, pruned_claim_ids, pruned_review_ids = prune_stale_auto_pages(
        target=target,
        page_records_by_id=page_records_by_id,
        desired_auto_page_ids=desired_auto_page_ids,
        claims_by_id=claims_by_id,
        reviews_by_id=existing_reviews,
    )
    if removed_pages:
        generated_pages.extend(removed_pages)
    dirty_claim_ids.update(pruned_claim_ids)
    dirty_review_ids.update(pruned_review_ids)

    # 页面阶段结束后再统一把内存中的 claims / reviews / pages 落盘，
    # 避免生成大量概念页时频繁整文件重写，明显降低大资料集下的 ingest 耗时。
    if dirty_claim_ids:
        claim_state_records = build_ordered_claim_state_records(
            live_claims_by_id=claims_by_id,
            historical_claims_by_id=historical_claims_by_id,
        )
        write_jsonl(claims_path, claim_state_records)
        for claim_id in dirty_claim_ids:
            write_claim_file(target, claims_by_id[claim_id])

    if dirty_review_ids:
        review_state_records = build_ordered_review_state_records(
            live_reviews_by_id=existing_reviews,
            historical_reviews_by_id=historical_reviews_by_id,
        )
        write_jsonl(reviews_path, review_state_records)
        for review_id in dirty_review_ids:
            write_review_file(target, existing_reviews[review_id])

    # pages.jsonl 这里保留完整页面账本：
    # 在线页面继续参与 query/index，removed 页面则作为历史痕迹留存。
    write_jsonl(pages_path, list(page_records_by_id.values()))

    all_claim_records = list(claims_by_id.values())
    page_records_for_index = list(page_records_by_id.values())
    claim_records_by_id = {record["claim_id"]: record for record in all_claim_records}
    previous_search_index_records = load_search_pages_index(target)
    search_index = write_search_pages_index(
        target=target,
        page_records=page_records_for_index,
        claim_records_by_id=claim_records_by_id,
        previous_records=previous_search_index_records,
    )

    alias_index = write_alias_index(target, page_records_for_index)
    alias_conflict_reviews, _ = build_alias_conflict_reviews(alias_index, existing_reviews)
    for review_record in alias_conflict_reviews:
        review_file_path = write_review_file(target, review_record)
        review_record["review_file_path"] = review_file_path
        append_jsonl(reviews_path, review_record)
        existing_reviews[review_record["review_id"]] = review_record
        review_items.append(review_record)
    rebuild_wiki_index(target, list(page_records_by_id.values()))
    append_wiki_log(target, task_id, generated_pages)

    payload = {
        "task_id": task_id,
        "workspace": str(target),
        "raw_dir": str(raw_dir),
        "created_sources": created_sources,
        "skipped_sources": skipped_sources,
        "normalized_sources": normalized_sources,
        "chunked_sources": chunked_sources,
        "claimed_sources": claimed_sources,
        "generated_pages": generated_pages,
        "search_index": search_index,
        "alias_index": {
            "index_path": str(ALIAS_INDEX_REL_PATH),
            "canonical_count": len(alias_index.get("canonical_map", {})),
            "alias_key_count": len(alias_index.get("alias_map", {})),
            "conflict_count": len(alias_index.get("conflicts", [])),
            "index_version": alias_index.get("index_version"),
        },
        "review_items": review_items,
        "error_items": error_items,
        "summary": {
            "created_count": len(created_sources),
            "skipped_count": len(skipped_sources),
            "normalized_count": len(normalized_sources),
            "chunked_count": len(chunked_sources),
            "claimed_count": len(claimed_sources),
            "changed_page_count": len(generated_pages),
            "review_count": len(review_items),
            "error_count": len([item for item in error_items if item["level"] == "error"]),
            "warning_count": len([item for item in error_items if item["level"] == "warning"]),
        },
    }
    return CommandResult(payload=payload, message="Ingest registration, normalization, chunking, claim drafting, and wiki generation completed.")


def command_stub(args: argparse.Namespace) -> CommandResult:
    # 预留命令占位，方便先把 CLI 骨架搭起来，再逐步补真实能力。
    return CommandResult(message=f"MyAgentWiki command scaffold: {args.command}")


def command_lint(args: argparse.Namespace) -> CommandResult:
    # lint 在 V1 里承担“结构 + 基础质量巡检”双重职责：
    # - 目录与状态文件是否完整
    # - page / claim / review / alias index 是否彼此对齐
    root = find_project_root()
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else root

    checks = []

    def add_check(name: str, ok: bool, details: str, severity: str = "error") -> None:
        # 统一收集检查项，后面既能给人看，也方便做 JSON 输出。
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
            "docs/MyAgentWiki系统详细设计-V1.md",
            "pyproject.toml",
            "config/runtime_manifest.yml",
            "src/myagentwiki/cli.py",
            "templates/project/config/project.yml.tmpl",
        ]
    else:
        add_check("workspace_target", True, f"Linting initialized workspace: {target}", severity="info")
        required_paths = [
            "wiki/index.md",
            "wiki/log.md",
            "config/project.yml",
            "AGENTS.md",
            "CLAUDE.md",
            str(ALIAS_INDEX_REL_PATH),
        ]

    for rel_path in required_paths:
        # 这里不区分文件还是目录，只要求“该路径存在”。
        path = target / rel_path
        add_check(
            name=f"path_exists:{rel_path}",
            ok=path.exists(),
            details=f"Expected path: {path}",
        )

    if target != root:
        config_path = target / "config" / "project.yml"
        raw_dir = resolve_workspace_path(target, load_simple_yaml(config_path)["paths"]["raw"]) if config_path.exists() else target / "raw"
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
            ok=(target / SEARCH_PAGES_INDEX_REL_PATH).exists(),
            details=f"Workspace should contain {target / SEARCH_PAGES_INDEX_REL_PATH}.",
        )
        add_check(
            name="index_aliases_exists",
            ok=alias_index_path(target).exists(),
            details=f"Workspace should contain {alias_index_path(target)}.",
        )

        chunk_records = load_jsonl(target / "state" / "chunks.jsonl") if (target / "state" / "chunks.jsonl").exists() else []
        if chunk_records:
            chunk_ids = [record.get("chunk_id") for record in chunk_records]
            add_check(
                name="chunk_ids_unique",
                ok=len(chunk_ids) == len(set(chunk_ids)),
                details="All chunk_id values in state/chunks.jsonl should be unique.",
            )

        claim_records = load_jsonl(target / "state" / "claims.jsonl") if (target / "state" / "claims.jsonl").exists() else []
        if claim_records:
            claim_records = [ensure_claim_lifecycle_defaults(record) for record in claim_records]
            live_claim_records = filter_live_claim_records(claim_records)
            historical_claim_records = [
                record for record in claim_records
                if not is_live_claim_record(record)
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

        review_records = load_jsonl(target / "state" / "reviews.jsonl") if (target / "state" / "reviews.jsonl").exists() else []
        if review_records:
            review_records = [ensure_review_lifecycle_defaults(record) for record in review_records]
            live_review_records = filter_live_review_records(review_records)
            historical_review_records = [
                record for record in review_records
                if not is_live_review_record(record)
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

        page_records = load_jsonl(target / "state" / "pages.jsonl") if (target / "state" / "pages.jsonl").exists() else []
        if page_records:
            page_records = [ensure_page_lifecycle_defaults(record) for record in page_records]
            live_page_records = filter_live_page_records(page_records)
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
                ok=all(not is_live_page_record(record) for record in removed_page_records),
                details="Removed page records should not be treated as live pages for index/query rebuilds.",
            )

            canonical_ids = [record.get("canonical_id") for record in live_page_records if record.get("canonical_id")]
            add_check(
                name="canonical_ids_unique",
                ok=len(canonical_ids) == len(set(canonical_ids)),
                details="Live page canonical_id values should be unique.",
            )

            alias_index = load_alias_index(target) if alias_index_path(target).exists() else {}
            alias_conflicts = alias_index.get("conflicts", []) if alias_index else []
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

            search_index_records = load_search_pages_index(target) if (target / SEARCH_PAGES_INDEX_REL_PATH).exists() else []
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
            "## 检查结果 / Checks",
            "",
        ]
        for check in checks:
            marker = "PASS" if check["ok"] else ("WARN" if check["severity"] == "warning" else "FAIL")
            report_lines.append(f"- [{marker}] `{check['name']}`: {check['details']}")
        atomic_write_text(
            target / "reports" / "lint" / "lint_latest.md",
            "\n".join(report_lines).strip() + "\n",
            encoding="utf-8",
        )

    # 先把 error / warning 分开统计，后面扩展更多级别也会比较自然。
    errors = [check for check in checks if not check["ok"] and check["severity"] == "error"]
    warnings = [check for check in checks if not check["ok"] and check["severity"] == "warning"]
    payload = {
        "target": str(target),
        "checks": checks,
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "ok": len(errors) == 0,
        },
    }
    return CommandResult(
        exit_code=0 if len(errors) == 0 else 1,
        payload=payload,
        message="Lint completed." if len(errors) == 0 else "Lint found issues.",
    )


def build_parser() -> argparse.ArgumentParser:
    # 所有 CLI 子命令都在这里集中声明，方便一眼看清当前系统有哪些入口。
    parser = argparse.ArgumentParser(
        prog="myagentwiki",
        description="MyAgentWiki CLI scaffold.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init: 创建一个新的 MyAgentWiki 工作区，并复用/创建其外部 sibling raw 目录。
    init_parser = subparsers.add_parser("init", help="Initialize a new MyAgentWiki workspace.")
    init_parser.add_argument(
        "--source-dir",
        help="Optional path to the sibling raw directory. If omitted, create/use ../raw next to the workspace.",
    )
    init_parser.add_argument("--project-name", required=True, help="Name of the new wiki workspace.")
    init_parser.add_argument("--target-dir", help="Optional explicit target directory.")
    init_parser.add_argument("--json", action="store_true", help="Output JSON.")
    init_parser.set_defaults(handler=command_init)

    # ingest: 扫描 raw，登记来源，并对已支持的文本类型做标准化。
    ingest_parser = subparsers.add_parser("ingest", help="Register raw files into workspace metadata.")
    ingest_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    ingest_parser.add_argument("--json", action="store_true", help="Output JSON.")
    ingest_parser.set_defaults(handler=command_ingest)

    # doctor: 检查当前机器是否满足项目运行要求。
    doctor_parser = subparsers.add_parser("doctor", help="Check runtime environment.")
    doctor_parser.add_argument("--json", action="store_true", help="Output JSON.")
    doctor_parser.set_defaults(handler=command_doctor)

    # bootstrap: 安装本项目声明的 Python 依赖。
    bootstrap_parser = subparsers.add_parser("bootstrap", help="Install or repair Python dependencies.")
    bootstrap_parser.add_argument("--dry-run", action="store_true", help="Show planned install command without running it.")
    bootstrap_parser.add_argument(
        "--extra",
        dest="extras",
        action="append",
        choices=("ocr", "office", "pdf", "dev"),
        default=[],
        help="Optional dependency group to install.",
    )
    bootstrap_parser.add_argument("--json", action="store_true", help="Output JSON.")
    bootstrap_parser.set_defaults(handler=command_bootstrap)

    # lint: 检查仓库骨架或某个已初始化工作区的完整性。
    lint_parser = subparsers.add_parser("lint")
    lint_parser.add_argument("--target-dir", help="Optional workspace directory to lint.")
    lint_parser.add_argument("--json", action="store_true", help="Output JSON.")
    lint_parser.set_defaults(handler=command_lint)

    # query: 在现有 wiki/claim/page 产物上执行多字段 BM25 检索。
    query_parser = subparsers.add_parser("query", help="Search generated wiki pages with weighted BM25 ranking.")
    query_parser.add_argument("text", help="Search query text.")
    query_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    query_parser.add_argument("--limit", type=int, default=5, help="Maximum number of results to return.")
    query_parser.add_argument("--claim-limit", type=int, default=3, help="Maximum matched claims per page.")
    query_parser.add_argument("--chunk-limit", type=int, default=2, help="Maximum matched chunks per page.")
    query_parser.add_argument("--json", action="store_true", help="Output JSON.")
    query_parser.set_defaults(handler=command_query)

    # review-list: 查看当前 review 队列及其候选 claim。
    review_list_parser = subparsers.add_parser("review-list", help="List review items and candidate claims.")
    review_list_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    review_list_parser.add_argument("--status", choices=("open", "resolved"), help="Optional review status filter.")
    review_list_parser.add_argument("--json", action="store_true", help="Output JSON.")
    review_list_parser.set_defaults(handler=command_review_list)

    # review-apply: 对单条 review 执行人工裁决动作。
    review_apply_parser = subparsers.add_parser("review-apply", help="Apply an action to a review item.")
    review_apply_parser.add_argument("review_id", help="Review id to apply action to.")
    review_apply_parser.add_argument(
        "action",
        choices=("keep_both", "archive_one", "merge", "edit_then_resume", "assign_alias", "remove_alias"),
        help="Decision action to apply.",
    )
    review_apply_parser.add_argument("--primary-claim-id", help="Primary claim id for archive_one / merge.")
    review_apply_parser.add_argument("--secondary-claim-id", help="Secondary claim id for merge.")
    review_apply_parser.add_argument("--primary-page-id", help="Primary page id for alias-conflict assign_alias.")
    review_apply_parser.add_argument("--alias-value", help="Alias value to assign during alias-conflict handling.")
    review_apply_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    review_apply_parser.add_argument("--json", action="store_true", help="Output JSON.")
    review_apply_parser.set_defaults(handler=command_review_apply)

    return parser


def main() -> int:
    # main 保持很薄，只负责“解析参数 -> 调用命令 -> 输出结果”这条主线。
    parser = build_parser()
    args = parser.parse_args()
    result = args.handler(args)
    return print_result(result, as_json=getattr(args, "json", False))


if __name__ == "__main__":
    raise SystemExit(main())
