from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class CommandResult:
    # 所有命令统一返回这一层结构，方便后面既能打印给人看，也能转成 JSON 给 Agent 消费。
    exit_code: int = 0
    payload: dict | None = None
    message: str | None = None


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
