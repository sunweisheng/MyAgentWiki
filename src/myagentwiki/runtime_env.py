from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT_MARKERS = ("pyproject.toml", ".git")
PACKAGE_IMPORT_ALIASES = {
    "python-docx": "docx",
    "python-pptx": "pptx",
    "pdfminer-six": "pdfminer",
    "pillow": "PIL",
}
ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def load_simple_env(path: Path) -> dict[str, str]:
    # 只读取项目所需的 KEY=VALUE 配置，不修改当前进程环境，调用方可以自行决定优先级。
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, raw_value = stripped.partition("=")
        key = key.strip()
        if not separator or not ENVIRONMENT_VARIABLE_PATTERN.fullmatch(key):
            raise ValueError(f"Invalid environment setting in {path}: {raw_line}")

        value = raw_value.strip()
        if value.startswith(("\"", "'")):
            try:
                parsed_value = ast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f"Invalid quoted value for `{key}` in {path}") from exc
            if not isinstance(parsed_value, str):
                raise ValueError(f"Invalid quoted value for `{key}` in {path}")
            values[key] = parsed_value
        else:
            values[key] = value.split(" #", 1)[0].rstrip()
    return values


def load_runtime_manifest(root: Path) -> dict:
    # runtime_manifest 是运行环境的统一来源，doctor/bootstrap 都会依赖它。
    manifest_path = root / "config" / "runtime_manifest.yml"
    return load_simple_yaml(manifest_path)


def load_project_metadata(root: Path) -> dict:
    # pyproject.toml 负责项目名、版本、依赖和 CLI 入口等元信息。
    with (root / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


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
