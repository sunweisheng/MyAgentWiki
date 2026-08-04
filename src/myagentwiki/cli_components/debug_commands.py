from __future__ import annotations

import json
from pathlib import Path

from ..debug_trace import list_debug_runs, load_debug_run
from .result import CommandResult


def command_debug_list(args) -> CommandResult:  # noqa: ANN001
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    runs = list_debug_runs(target)
    payload = {
        "workspace": str(target),
        "run_count": len(runs),
        "runs": runs,
    }
    lines = [f"Debug runs: {len(runs)}", f"Workspace: {target}"]
    for run in runs:
        lines.append(
            f"- {run.get('run_id')}: status={run.get('status')}, "
            f"record_complete={run.get('record_complete', False)}, "
            f"command={run.get('command')}, started_at={run.get('started_at')}"
        )
    return CommandResult(payload=payload, message="\n".join(lines))


def command_debug_show(args) -> CommandResult:  # noqa: ANN001
    target = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.cwd()
    try:
        payload = load_debug_run(
            target,
            args.run_id,
            source_id=args.source_id,
            step_id=args.step_id,
            request_id=args.request_id,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            exit_code=1,
            payload={"error": "debug_run_not_found", "message": str(exc)},
            message=str(exc),
        )

    if args.source_id or args.step_id or args.request_id:
        message = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        report_path = Path(payload["report_path"])
        message = report_path.read_text(encoding="utf-8") if report_path.exists() else json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    return CommandResult(payload=payload, message=message)
