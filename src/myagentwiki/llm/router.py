from __future__ import annotations

import random
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..runtime_env import load_simple_yaml
from .cli_client import CLILLMClient
from .contracts import build_task_context, get_function_spec
from .diagnostics import append_request_record
from .errors import LLMClientError, LLMProjectConfigurationError, LLMRouteError
from .online_client import OnlineLLMClient
from .repair import repair_and_validate


@dataclass(frozen=True)
class LLMSettings:
    primary_max_retries: int
    retry_backoff_seconds: tuple[float, ...]
    retry_jitter_max_seconds: float
    document_max_chars: int
    image_max_bytes: int
    image_mime_types: frozenset[str]
    cli_timeout_seconds: int
    cli_model: str
    cli_executable: str = "codex"
    retryable_http_statuses: frozenset[int] = frozenset({408, 409, 429})
    retryable_http_status_min: int = 500
    routing_version: str = "online-primary-cli-fallback-v1"
    contract_version: str = "v2"


def _int(value: Any, default: int, minimum: int = 0) -> int:
    try:
        return max(int(value), minimum)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float, minimum: float = 0.0) -> float:
    try:
        return max(float(value), minimum)
    except (TypeError, ValueError):
        return default


def load_llm_settings(workspace: Path) -> LLMSettings:
    project_path = workspace / "config" / "project.yml"
    config = load_simple_yaml(project_path) if project_path.exists() else {}
    llm = config.get("llm", {}) if isinstance(config.get("llm"), dict) else {}
    routing = llm.get("routing", {}) if isinstance(llm.get("routing"), dict) else {}
    retry = llm.get("retry", {}) if isinstance(llm.get("retry"), dict) else {}
    context = llm.get("context", {}) if isinstance(llm.get("context"), dict) else {}
    cli = llm.get("cli", {}) if isinstance(llm.get("cli"), dict) else {}
    backoff = retry.get("backoff_seconds", [1.0, 2.0])
    if not isinstance(backoff, list):
        backoff = [1.0, 2.0]
    backoff_values = tuple(_float(item, 1.0) for item in backoff) or (1.0, 2.0)
    mime_types = context.get("image_mime_types", ["image/png", "image/jpeg", "image/webp", "image/gif"])
    if not isinstance(mime_types, list):
        mime_types = ["image/png", "image/jpeg", "image/webp", "image/gif"]
    primary = str(routing.get("primary", "online")).strip() or "online"
    fallback = str(routing.get("fallback", "cli")).strip() or "cli"
    if primary != "online" or fallback != "cli":
        raise LLMProjectConfigurationError(
            "`llm.routing` must use `primary: online` and `fallback: cli`.",
            config_path="config/project.yml",
        )
    contract_version = str(llm.get("contract_version", "v2")).strip() or "v2"
    if contract_version != "v2":
        raise LLMProjectConfigurationError(
            f"Unsupported `llm.contract_version` `{contract_version}`; expected `v2`.",
            config_path="config/project.yml",
        )
    retry_statuses = retry.get("http_statuses", [408, 409, 429])
    if not isinstance(retry_statuses, list):
        raise LLMProjectConfigurationError(
            "`llm.retry.http_statuses` must be a list of HTTP status codes.",
            config_path="config/project.yml",
        )
    try:
        normalized_retry_statuses = frozenset(int(item) for item in retry_statuses)
    except (TypeError, ValueError) as exc:
        raise LLMProjectConfigurationError(
            "`llm.retry.http_statuses` contains a non-integer value.",
            config_path="config/project.yml",
        ) from exc
    timeout_env = str(cli.get("timeout_env", "MYAGENTWIKI_CODEX_TIMEOUT_SECONDS")).strip()
    timeout_value = os.environ.get(timeout_env, cli.get("timeout_seconds", 120)) if timeout_env else cli.get("timeout_seconds", 120)
    model_env = str(cli.get("model_env", "MYAGENTWIKI_CODEX_MODEL")).strip()
    executable_env = str(cli.get("executable_env", "MYAGENTWIKI_CODEX_BIN")).strip()
    return LLMSettings(
        primary_max_retries=min(_int(retry.get("online_max_retries", 2), 2), 2),
        retry_backoff_seconds=backoff_values,
        retry_jitter_max_seconds=_float(retry.get("jitter_max_seconds", 0.25), 0.25),
        document_max_chars=_int(context.get("document_max_chars", 24000), 24000, 1000),
        image_max_bytes=_int(context.get("image_max_bytes", 20 * 1024 * 1024), 20 * 1024 * 1024, 1),
        image_mime_types=frozenset(str(item).strip() for item in mime_types if str(item).strip()),
        cli_timeout_seconds=_int(timeout_value, 120, 5),
        cli_model=(os.environ.get(model_env, "").strip() if model_env else "") or str(cli.get("model", "")).strip(),
        cli_executable=(os.environ.get(executable_env, "").strip() if executable_env else "") or str(cli.get("executable", "codex")).strip() or "codex",
        retryable_http_statuses=normalized_retry_statuses,
        retryable_http_status_min=_int(retry.get("http_status_min", 500), 500, 400),
        contract_version=contract_version,
    )


def build_route_identity(workspace: Path, task_name: str, *, strategy: str) -> dict[str, Any]:
    spec = get_function_spec(task_name)
    settings = load_llm_settings(workspace)
    identity: dict[str, Any] = {
        "routing_version": settings.routing_version,
        "strategy": strategy,
        "function_name": spec.function_name,
        "function_schema_version": spec.schema_version,
        "function_prompt_version": spec.prompt_version,
        "contract_version": settings.contract_version,
    }
    if strategy != "llm_assisted":
        return identity

    online_path = workspace / "config" / "llm.local.yml"
    online_identity: dict[str, Any] = {"configured": online_path.exists(), "model": "", "api_style": ""}
    if online_path.exists():
        try:
            online_config = load_simple_yaml(online_path)
            provider = online_config.get("provider", {}) if isinstance(online_config.get("provider"), dict) else {}
            transport = online_config.get("transport", {}) if isinstance(online_config.get("transport"), dict) else {}
            online_identity["model"] = str(provider.get("model", "")).strip()
            online_identity["api_style"] = str(transport.get("api_style", "responses")).strip() or "responses"
        except Exception:
            online_identity["configured"] = "invalid"
    identity["online"] = online_identity
    identity["cli"] = {"model": settings.cli_model}
    return identity


class LLMRouter:
    def __init__(
        self,
        workspace: Path,
        *,
        settings: LLMSettings | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
        online_client_factory: Callable[..., Any] = OnlineLLMClient,
        cli_client_factory: Callable[..., Any] = CLILLMClient,
    ) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings or load_llm_settings(self.workspace)
        self.sleep = sleep
        self.random_uniform = random_uniform
        self.online_client_factory = online_client_factory
        self.cli_client_factory = cli_client_factory

    def request(
        self,
        *,
        task_name: str,
        payload: dict[str, Any],
        image_paths: list[Path] | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        request_id = f"llm_{uuid.uuid4().hex}"
        spec = get_function_spec(task_name)
        images = [Path(path).resolve() for path in (image_paths or [])]
        if images and not spec.supports_images:
            raise ValueError(f"LLM task `{task_name}` does not accept images.")
        context = build_task_context(
            spec,
            payload,
            document_max_chars=self.settings.document_max_chars,
        )
        attempts: list[dict[str, Any]] = []
        max_online_attempts = self.settings.primary_max_retries + 1

        try:
            with self.online_client_factory(
                self.workspace,
                image_max_bytes=self.settings.image_max_bytes,
                image_mime_types=set(self.settings.image_mime_types),
                timeout_seconds=timeout_seconds,
                retryable_http_statuses=set(self.settings.retryable_http_statuses),
                retryable_http_status_min=self.settings.retryable_http_status_min,
            ) as online:
                for attempt_number in range(1, max_online_attempts + 1):
                    started = time.monotonic()
                    try:
                        raw_call = online.request(spec=spec, context=context, image_paths=images)
                        validated = repair_and_validate(
                            spec=spec,
                            raw_call=raw_call,
                            payload=payload,
                            backend="online",
                        )
                        attempt = self._success_attempt(
                            backend="online",
                            attempt_number=attempt_number,
                            started=started,
                            repaired=validated.repaired,
                        )
                        attempts.append(attempt)
                        self._write_final_record(request_id, spec, attempts, status="success", backend="online")
                        return validated.arguments
                    except LLMClientError as exc:
                        attempts.append(self._failed_attempt(exc, attempt_number, started))
                        if not exc.retryable or attempt_number >= max_online_attempts:
                            break
                        backoff_index = min(attempt_number - 1, len(self.settings.retry_backoff_seconds) - 1)
                        delay = self.settings.retry_backoff_seconds[backoff_index]
                        delay += self.random_uniform(0.0, self.settings.retry_jitter_max_seconds)
                        self.sleep(delay)
        except LLMClientError as exc:
            attempts.append(self._failed_attempt(exc, 1, time.monotonic()))

        cli = self.cli_client_factory(
            self.workspace,
            timeout_seconds=timeout_seconds or self.settings.cli_timeout_seconds,
            model=self.settings.cli_model,
            executable=self.settings.cli_executable,
        )
        started = time.monotonic()
        try:
            raw_call = cli.request(spec=spec, context=context, image_paths=images)
            validated = repair_and_validate(
                spec=spec,
                raw_call=raw_call,
                payload=payload,
                backend="cli",
            )
            attempts.append(self._success_attempt(
                backend="cli",
                attempt_number=1,
                started=started,
                repaired=validated.repaired,
            ))
            self._write_final_record(request_id, spec, attempts, status="success", backend="cli")
            return validated.arguments
        except LLMClientError as exc:
            attempts.append(self._failed_attempt(exc, 1, started))

        message = f"LLM request `{task_name}` failed on both online and CLI routes. Request ID: {request_id}."
        self._write_final_record(request_id, spec, attempts, status="failed", backend=None)
        raise LLMRouteError(
            message,
            request_id=request_id,
            task_name=task_name,
            attempts=attempts,
        )

    def _success_attempt(
        self,
        *,
        backend: str,
        attempt_number: int,
        started: float,
        repaired: bool,
    ) -> dict[str, Any]:
        return {
            "backend": backend,
            "attempt": attempt_number,
            "status": "success",
            "duration_ms": round((time.monotonic() - started) * 1000),
            "repaired": repaired,
        }

    def _failed_attempt(
        self,
        error: LLMClientError,
        attempt_number: int,
        started: float,
    ) -> dict[str, Any]:
        return {
            **error.as_record(),
            "attempt": attempt_number,
            "status": "failed",
            "duration_ms": round((time.monotonic() - started) * 1000),
        }

    def _write_final_record(
        self,
        request_id: str,
        spec,
        attempts: list[dict[str, Any]],
        *,
        status: str,
        backend: str | None,
    ) -> None:
        append_request_record(self.workspace, {
            "request_id": request_id,
            "task_name": spec.task_name,
            "function_name": spec.function_name,
            "schema_version": spec.schema_version,
            "prompt_version": spec.prompt_version,
            "status": status,
            "backend": backend,
            "attempts": attempts,
            "route_attempt_counts": {
                route: sum(1 for attempt in attempts if attempt.get("backend") == route)
                for route in ("online", "cli")
            },
            "total_duration_ms": sum(int(attempt.get("duration_ms", 0)) for attempt in attempts),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })


def request(
    *,
    workspace: Path,
    task_name: str,
    payload: dict[str, Any],
    image_paths: list[Path] | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    return LLMRouter(workspace).request(
        task_name=task_name,
        payload=payload,
        image_paths=image_paths,
        timeout_seconds=timeout_seconds,
    )
