from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from myagentwiki.llm.contracts import get_function_spec, registered_task_names
from myagentwiki.llm.errors import LLMClientError, LLMRouteError
from myagentwiki.llm.repair import RawFunctionCall
from myagentwiki.llm.router import LLMRouter, LLMSettings


def _valid_arguments(task_name: str) -> dict[str, Any]:
    values = {
        "claim_stable_promotion": {"decision": "skip", "confidence": 0.8, "reason": "insufficient evidence"},
        "review_auto_decision": {
            "decision": "skip",
            "action": None,
            "primary_claim_id": None,
            "secondary_claim_id": None,
            "primary_page_id": None,
            "alias_value": None,
            "confidence": 0.8,
            "reason": "manual review retained",
        },
    }
    return values[task_name]


def _valid_call(task_name: str) -> RawFunctionCall:
    spec = get_function_spec(task_name)
    return RawFunctionCall(
        function_name=spec.function_name,
        arguments_json=json.dumps(_valid_arguments(task_name), ensure_ascii=False),
    )


def _payload(task_name: str) -> dict[str, Any]:
    if task_name == "claim_stable_promotion":
        return {"task": task_name, "claim": {"claim_id": "claim-1", "text": "example"}}
    return {
        "task": task_name,
        "review": {
            "allowed_actions": ["keep_both"],
            "candidate_claim_ids": ["claim-1"],
            "candidate_page_ids": [],
        },
    }


class FixedOnlineClient:
    def __init__(self, results: list[RawFunctionCall | Exception], **_: Any) -> None:
        self.results = results

    def __enter__(self) -> "FixedOnlineClient":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def request(self, **_: Any) -> RawFunctionCall:
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FixedCLIClient:
    def __init__(self, result: RawFunctionCall | Exception, **_: Any) -> None:
        self.result = result

    def request(self, **_: Any) -> RawFunctionCall:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _online_error(*, status: int | None = None, retryable: bool = True) -> LLMClientError:
    return LLMClientError(
        "simulated online failure",
        backend="online",
        kind="http_error" if status else "connection_error",
        retryable=retryable,
        http_status=status,
    )


def _scenarios() -> dict[str, dict[str, Any]]:
    stable_valid = _valid_call("claim_stable_promotion")
    review_valid = _valid_call("review_auto_decision")
    review_spec = get_function_spec("review_auto_decision")
    invalid_business = {
        **_valid_arguments("review_auto_decision"),
        "decision": "auto_apply",
        "action": "merge",
        "primary_claim_id": "claim-1",
        "secondary_claim_id": "claim-2",
    }
    return {
        "online_first_success": {"task": "claim_stable_promotion", "online": [stable_valid], "cli": stable_valid},
        "online_retry_success": {
            "task": "claim_stable_promotion",
            "online": [_online_error(status=500), stable_valid],
            "cli": stable_valid,
        },
        "http_403_to_cli": {
            "task": "claim_stable_promotion",
            "online": [_online_error(status=403, retryable=False)],
            "cli": stable_valid,
        },
        "http_404_to_cli": {
            "task": "claim_stable_promotion",
            "online": [_online_error(status=404, retryable=False)],
            "cli": stable_valid,
        },
        "http_429_exhausted": {
            "task": "claim_stable_promotion",
            "online": [_online_error(status=429), _online_error(status=429), _online_error(status=429)],
            "cli": stable_valid,
        },
        "http_5xx_exhausted": {
            "task": "claim_stable_promotion",
            "online": [_online_error(status=503), _online_error(status=503), _online_error(status=503)],
            "cli": stable_valid,
        },
        "repairable_json": {
            "task": "claim_stable_promotion",
            "online": [RawFunctionCall(stable_valid.function_name, "{'decision':'skip','confidence':0.8,'reason':'ok',}")],
            "cli": stable_valid,
        },
        "unrepairable_json": {
            "task": "claim_stable_promotion",
            "online": [RawFunctionCall(stable_valid.function_name, "not-json")] * 3,
            "cli": stable_valid,
        },
        "wrong_function_name": {
            "task": "claim_stable_promotion",
            "online": [RawFunctionCall("wrong_function", stable_valid.arguments_json)] * 3,
            "cli": stable_valid,
        },
        "schema_validation_failure": {
            "task": "claim_stable_promotion",
            "online": [RawFunctionCall(stable_valid.function_name, '{"decision":"skip"}')] * 3,
            "cli": stable_valid,
        },
        "business_validation_failure": {
            "task": "review_auto_decision",
            "online": [RawFunctionCall(review_spec.function_name, json.dumps(invalid_business))] * 3,
            "cli": review_valid,
        },
        "cli_success": {
            "task": "claim_stable_promotion",
            "online": [_online_error(retryable=False)],
            "cli": stable_valid,
        },
        "both_routes_failed": {
            "task": "claim_stable_promotion",
            "online": [_online_error(status=500), _online_error(status=500), _online_error(status=500)],
            "cli": LLMClientError(
                "simulated CLI failure",
                backend="cli",
                kind="process_error",
                retryable=False,
            ),
        },
    }


def _settings() -> LLMSettings:
    return LLMSettings(
        primary_max_retries=2,
        retry_backoff_seconds=(1.0, 2.0),
        retry_jitter_max_seconds=0.25,
        document_max_chars=24000,
        image_max_bytes=20 * 1024 * 1024,
        image_mime_types=frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"}),
        cli_timeout_seconds=120,
        cli_model="",
    )


def run_simulation(name: str) -> dict[str, Any]:
    scenario = _scenarios()[name]
    online_results = list(scenario["online"])
    cli_result = scenario["cli"]
    with tempfile.TemporaryDirectory(prefix="myagentwiki-llm-sim-") as tmpdir:
        workspace = Path(tmpdir)
        router = LLMRouter(
            workspace,
            settings=_settings(),
            sleep=lambda _: None,
            random_uniform=lambda _start, _end: 0.0,
            online_client_factory=lambda *_args, **kwargs: FixedOnlineClient(online_results, **kwargs),
            cli_client_factory=lambda *_args, **kwargs: FixedCLIClient(cli_result, **kwargs),
        )
        try:
            result = router.request(
                task_name=scenario["task"],
                payload=_payload(scenario["task"]),
            )
            outcome: dict[str, Any] = {"status": "success", "result": result}
        except LLMRouteError as exc:
            outcome = {"status": "failed", "error": exc.payload}
        log_path = workspace / "logs" / "llm_requests.jsonl"
        diagnostic = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    return {"scenario": name, **outcome, "diagnostic": diagnostic}


def command_contract(args: argparse.Namespace) -> int:
    spec = get_function_spec(args.task)
    print(json.dumps({
        "task_name": spec.task_name,
        "function_name": spec.function_name,
        "schema_version": spec.schema_version,
        "prompt_version": spec.prompt_version,
        "supports_images": spec.supports_images,
        "parameters_schema": spec.parameters_schema,
    }, ensure_ascii=False, indent=2))
    return 0


def command_simulate(args: argparse.Namespace) -> int:
    names = list(_scenarios()) if args.scenario == "all" else [args.scenario]
    print(json.dumps([run_simulation(name) for name in names], ensure_ascii=False, indent=2))
    return 0


def command_live(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if args.payload_file:
        payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    elif args.payload_json:
        payload = json.loads(args.payload_json)
    else:
        payload = _payload(args.task)
    images = [Path(path).expanduser().resolve() for path in args.image]
    try:
        result = LLMRouter(workspace).request(
            task_name=args.task,
            payload=payload,
            image_paths=images,
            timeout_seconds=args.timeout_seconds,
        )
    except LLMRouteError as exc:
        print(json.dumps(exc.payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "success", "task_name": args.task, "result": result}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and debug MyAgentWiki LLM routing without exposing credentials.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    contract = subparsers.add_parser("contract", help="Inspect one Function Calling contract offline.")
    contract.add_argument("--task", required=True, choices=registered_task_names())
    contract.set_defaults(handler=command_contract)

    simulate = subparsers.add_parser("simulate", help="Run fixed online/CLI routing scenarios.")
    simulate.add_argument("--scenario", default="all", choices=("all", *_scenarios().keys()))
    simulate.set_defaults(handler=command_simulate)

    live = subparsers.add_parser("live", help="Run one real primary/fallback request.")
    live.add_argument("--workspace", default=".")
    live.add_argument("--task", default="claim_stable_promotion", choices=registered_task_names())
    live.add_argument("--payload-file")
    live.add_argument("--payload-json")
    live.add_argument("--image", action="append", default=[])
    live.add_argument("--timeout-seconds", type=int)
    live.set_defaults(handler=command_live)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
