from __future__ import annotations

import argparse
import sys

from ..app_services.runtime_services import run_bootstrap_service, run_doctor_service
from .result import CommandResult
from ..runtime_env import find_project_root


def command_doctor(args: argparse.Namespace) -> CommandResult:
    # command_* 函数负责组装业务结果；真正的公共逻辑尽量往辅助函数里收。
    root = find_project_root()
    payload = run_doctor_service(root)
    return CommandResult(payload=payload, message="MyAgentWiki doctor report ready.")


def command_bootstrap(args: argparse.Namespace) -> CommandResult:
    # bootstrap 当前先聚焦 Python 依赖安装，不擅自处理系统级软件。
    # 命令本身保持跨平台：直接调用当前 Python 解释器，不依赖 bash/zsh 专属语法。
    root = find_project_root()
    exit_code, payload = run_bootstrap_service(
        root=root,
        python_executable=sys.executable,
        extras=args.extras,
        dry_run=bool(args.dry_run),
    )
    return CommandResult(
        exit_code=exit_code,
        payload=payload,
        message="Bootstrap dry run complete." if args.dry_run else (
            "Bootstrap finished." if exit_code == 0 else "Bootstrap finished with errors."
        ),
    )


def register_doctor_bootstrap_subparsers(subparsers) -> None:
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
