from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path | None = None) -> dict:
    # 验证脚本统一走真实 CLI，而不是直接 import 内部函数。
    # 这样能同时覆盖参数解析、JSON 输出和工作区路径处理。
    command = [sys.executable, "-m", "myagentwiki.cli", *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        env={
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "MYAGENTWIKI_LLM_MODE": "deterministic",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def prepare_demo_source(source_dir: Path) -> None:
    # 这里准备一组很小但覆盖面足够的样例资料：
    # 一方面验证 raw 子目录递归扫描，另一方面验证 ingest/query/lint 主链路。
    nested_dir = source_dir / "notes" / "architecture"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "claims.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层应该支持 Wiki 结论回链到 Claim、Chunk 和 Source。\n\n"
        "知识声明层还应该统计自己被多少个 Wiki 页面引用。\n",
        encoding="utf-8",
    )
    (source_dir / "process.md").write_text(
        "# 审核闭环\n\n"
        "系统需要把冲突结论送入 review 队列，并支持人工裁决。\n",
        encoding="utf-8",
    )


def validate_workspace(workspace_dir: Path) -> dict:
    # 这组步骤就是我们想交付给用户的最小闭环：
    # doctor -> bootstrap(dry-run) -> init -> ingest -> query -> lint
    source_dir = workspace_dir / "raw"
    prepare_demo_source(source_dir)

    init_target = workspace_dir / "demo_wiki"
    doctor = run_cli("doctor")
    bootstrap = run_cli("bootstrap", "--dry-run", "--extra", "dev")
    init_result = run_cli(
        "init",
        "--source-dir",
        str(source_dir),
        "--project-name",
        "DemoWiki",
        "--target-dir",
        str(init_target),
    )
    ingest_result = run_cli("ingest", "--target-dir", str(init_target))
    query_result = run_cli("query", "什么是知识声明层", "--target-dir", str(init_target))
    lint_result = run_cli("lint", "--target-dir", str(init_target))

    return {
        "doctor_summary": doctor["summary"],
        "bootstrap_action": bootstrap["action"],
        "workspace": init_result["target_dir"],
        "ingest_summary": ingest_result["summary"],
        "query_summary": query_result["summary"],
        "query_intent": query_result["intent"],
        "lint_summary": lint_result["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the MyAgentWiki end-to-end workflow.")
    parser.add_argument(
        "--workspace-root",
        help="Optional directory used to create a temporary validation workspace.",
    )
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Keep the generated validation workspace for manual inspection.",
    )
    args = parser.parse_args()

    temp_dir_obj: tempfile.TemporaryDirectory[str] | None = None
    if args.workspace_root:
        workspace_root = Path(args.workspace_root).expanduser().resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
    else:
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="myagentwiki-validate-")
        workspace_root = Path(temp_dir_obj.name)

    try:
        result = validate_workspace(workspace_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        if temp_dir_obj is not None and not args.keep_workspace:
            temp_dir_obj.cleanup()
        elif temp_dir_obj is not None and args.keep_workspace:
            print(f"validation workspace kept at: {workspace_root}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
