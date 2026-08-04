from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .runtime_env import load_simple_env, load_simple_yaml


DEBUG_DIR_NAME = "debug"
DEFAULT_RETENTION_DAYS = 7
REDACTED = "[REDACTED]"
TEXT_SNAPSHOT_SUFFIXES = frozenset({
    ".csv",
    ".htm",
    ".html",
    ".json",
    ".jsonl",
    ".md",
    ".markdown",
    ".rst",
    ".toml",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
})
SENSITIVE_FIELD_NAMES = frozenset({
    "access-token",
    "api-key",
    "authorization",
    "client-secret",
    "cookie",
    "credential",
    "password",
    "proxy-authorization",
    "refresh-token",
    "secret",
    "set-cookie",
    "token",
    "x-api-key",
})
SENSITIVE_ENV_NAME_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


class DebugTraceError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.tmp-",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def resolve_debug_settings(workspace: Path) -> tuple[Path, int]:
    config_path = workspace / "config" / "project.yml"
    config = load_simple_yaml(config_path) if config_path.exists() else {}
    paths = config.get("paths", {}) if isinstance(config.get("paths"), dict) else {}
    configured_logs = Path(str(paths.get("logs", "logs"))).expanduser()
    logs_root = configured_logs if configured_logs.is_absolute() else workspace / configured_logs
    debug_config = config.get("debug", {}) if isinstance(config.get("debug"), dict) else {}
    try:
        retention_days = max(int(debug_config.get("retention_days", DEFAULT_RETENTION_DAYS)), 1)
    except (TypeError, ValueError):
        retention_days = DEFAULT_RETENTION_DAYS
    return (logs_root.resolve() / DEBUG_DIR_NAME, retention_days)


def _known_secret_values(workspace: Path) -> tuple[str, ...]:
    values: list[str] = []
    env_path = workspace / ".env"
    if env_path.exists():
        try:
            values.extend(
                value
                for name, value in load_simple_env(env_path).items()
                if any(part in name.casefold() for part in SENSITIVE_ENV_NAME_PARTS)
            )
        except Exception:
            pass
    for name, value in os.environ.items():
        normalized = name.casefold()
        if any(part in normalized for part in SENSITIVE_ENV_NAME_PARTS):
            values.append(value)
    return tuple(sorted({value for value in values if len(value) >= 4}, key=len, reverse=True))


def _redact_text(value: str, secret_values: tuple[str, ...]) -> str:
    redacted = value
    for secret in secret_values:
        redacted = redacted.replace(secret, REDACTED)
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", rf"\1{REDACTED}", redacted)
    redacted = re.sub(
        r"(?i)((?:x-api-key|api[_-]?key|access[_-]?token)\s*[:=]\s*)[^\s,;]+",
        rf"\1{REDACTED}",
        redacted,
    )
    return redacted


def make_json_safe(value: Any, *, secret_values: tuple[str, ...] = ()) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_text(value, secret_values)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {
            "binary": True,
            "size_bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if is_dataclass(value) and not isinstance(value, type):
        return make_json_safe(asdict(value), secret_values=secret_values)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold().replace("_", "-") in SENSITIVE_FIELD_NAMES:
                result[key_text] = REDACTED
            else:
                result[key_text] = make_json_safe(item, secret_values=secret_values)
        return result
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item, secret_values=secret_values) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (make_json_safe(item, secret_values=secret_values) for item in value),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    return _redact_text(str(value), secret_values)


def file_metadata(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return {"path": str(resolved), "exists": False}
    if not resolved.is_file():
        return {"path": str(resolved), "exists": True, "kind": "directory"}
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(resolved),
        "exists": True,
        "kind": "file",
        "size_bytes": resolved.stat().st_size,
        "mime_type": mimetypes.guess_type(resolved.name)[0] or "application/octet-stream",
        "sha256": digest.hexdigest(),
    }


def file_snapshot(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if current_debug_tracer() is None:
        return {"path": str(resolved)}
    metadata = file_metadata(resolved)
    if not resolved.is_file():
        return metadata
    mime_type = str(metadata.get("mime_type", ""))
    if not mime_type.startswith("text/") and resolved.suffix.casefold() not in TEXT_SNAPSHOT_SUFFIXES:
        return metadata
    return {
        "metadata": metadata,
        "text": resolved.read_text(encoding="utf-8", errors="replace"),
    }


def entity_reference(
    entity_type: str,
    entity_id: str,
    *,
    value: Any = None,
    path: str | Path | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    if current_debug_tracer() is None:
        return {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "source_id": str(source_id) if source_id else None,
            "source_ids": [str(source_id)] if source_id else [],
            "path": str(path) if path is not None else None,
            "content_hash": None,
        }
    serialized = make_json_safe(value)
    source_ids = _collect_source_ids(value)
    if source_id:
        source_ids.add(str(source_id))
    content_hash = None
    if value is not None:
        encoded = json.dumps(serialized, ensure_ascii=False, sort_keys=True).encode("utf-8")
        content_hash = hashlib.sha256(encoded).hexdigest()
    return {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "source_id": str(source_id) if source_id else None,
        "source_ids": sorted(source_ids),
        "path": str(path) if path is not None else None,
        "content_hash": content_hash,
        "_snapshot_value": serialized if value is not None else None,
    }


def _collect_source_ids(value: Any) -> set[str]:
    source_ids: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            direct_source_id = item.get("source_id")
            if direct_source_id:
                source_ids.add(str(direct_source_id))
            direct_source_ids = item.get("source_ids")
            if isinstance(direct_source_ids, (list, tuple, set, frozenset)):
                source_ids.update(str(source) for source in direct_source_ids if source)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, (list, tuple, set, frozenset)):
            for nested in item:
                visit(nested)

    visit(value)
    return source_ids


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return normalized[:80] or "item"


def prune_expired_debug_runs(workspace: Path, *, now: datetime | None = None) -> list[str]:
    debug_root, _ = resolve_debug_settings(workspace)
    if not debug_root.exists():
        return []
    root = debug_root.resolve()
    current_time = now or utc_now()
    removed: list[str] = []
    for child in debug_root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        resolved = child.resolve()
        if resolved.parent != root:
            continue
        run_path = resolved / "run.json"
        if not run_path.is_file():
            continue
        try:
            run = _load_json(run_path)
            expires_at = datetime.fromisoformat(str(run["expires_at"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if run.get("status") == "running":
            continue
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at >= current_time:
            continue
        shutil.rmtree(resolved)
        removed.append(child.name)
    return removed


@dataclass
class DebugStep:
    tracer: "DebugTracer | None"
    step_id: str = ""
    name: str = ""
    kind: str = "stage"
    parent_step_id: str | None = None
    started_at: str = ""
    started_monotonic: float = 0.0
    status: str = "success"
    input_snapshot: str | None = None
    output_snapshot: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    output_data: Any = None

    def set_output(self, value: Any | Callable[[], Any]) -> None:
        if self.tracer is None:
            return
        self.output_data = value() if callable(value) else value

    def add_details(self, **values: Any) -> None:
        self.details.update(values)

    def set_status(self, status: str) -> None:
        self.status = status


def _lineage_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _lineage_public_value(item)
            for key, item in value.items()
            if key != "_snapshot_value"
        }
    if isinstance(value, (list, tuple)):
        return [_lineage_public_value(item) for item in value]
    return value


def _lineage_snapshot_value(value: Any) -> Any:
    if isinstance(value, dict):
        result = {
            str(key): _lineage_snapshot_value(item)
            for key, item in value.items()
            if key != "_snapshot_value"
        }
        if value.get("_snapshot_value") is not None:
            result["data"] = value["_snapshot_value"]
        return result
    if isinstance(value, (list, tuple)):
        return [_lineage_snapshot_value(item) for item in value]
    return value


def _summarize_llm_records(llm_records: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = [
        attempt
        for record in llm_records
        for attempt in record.get("attempts", [])
        if isinstance(attempt, dict)
    ]
    backend_duration_ms: dict[str, int] = {}
    input_tokens = 0
    output_tokens = 0
    usage_available_attempt_count = 0
    for attempt in attempts:
        backend = str(attempt.get("backend") or "unknown")
        backend_duration_ms[backend] = backend_duration_ms.get(backend, 0) + int(
            attempt.get("duration_ms", 0) or 0
        )
        usage = attempt.get("usage", {}) if isinstance(attempt.get("usage"), dict) else {}
        if not usage.get("available"):
            continue
        usage_available_attempt_count += 1
        input_tokens += int(usage.get("input_tokens", 0) or 0)
        output_tokens += int(usage.get("output_tokens", 0) or 0)
    return {
        "logical_request_count": len(llm_records),
        "attempt_count": len(attempts),
        "retry_attempt_count": max(len(attempts) - len(llm_records), 0),
        "failed_attempt_count": sum(
            1 for attempt in attempts if attempt.get("status") == "failed"
        ),
        "repaired_attempt_count": sum(
            1 for attempt in attempts if attempt.get("repaired") is True
        ),
        "retry_wait_ms": sum(
            int(attempt.get("backoff_ms", 0) or 0) for attempt in attempts
        ),
        "attempt_duration_ms": sum(
            int(attempt.get("duration_ms", 0) or 0) for attempt in attempts
        ),
        "backend_duration_ms": backend_duration_ms,
        "usage_available_attempt_count": usage_available_attempt_count,
        "usage_unavailable_attempt_count": len(attempts) - usage_available_attempt_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _summarize_lineage_records(lineage: list[dict[str, Any]]) -> dict[str, Any]:
    operation_counts: dict[str, int] = {}
    lineage_record_counts: dict[str, int] = {}
    entity_type_operation_counts: dict[str, dict[str, int]] = {}
    for record in lineage:
        operation = str(record.get("operation") or "unknown")
        lineage_record_counts[operation] = lineage_record_counts.get(operation, 0) + 1
        outputs = record.get("outputs", [])
        inputs = record.get("inputs", [])
        entities = outputs if isinstance(outputs, list) and outputs else inputs
        if not isinstance(entities, list):
            entities = []
        operation_counts[operation] = operation_counts.get(operation, 0) + len(entities)
        type_counts = entity_type_operation_counts.setdefault(operation, {})
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_type = str(entity.get("entity_type") or "unknown")
            type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
    return {
        "operation_counts": operation_counts,
        "lineage_record_counts": lineage_record_counts,
        "entity_type_operation_counts": entity_type_operation_counts,
    }


class DebugTracer:
    def __init__(self, workspace: Path, command: str, arguments: dict[str, Any]) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.debug_root, self.retention_days = resolve_debug_settings(self.workspace)
        started_at = utc_now()
        self.run_id = f"dbg_{started_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"
        self.run_dir = self.debug_root / self.run_id
        self.steps_path = self.run_dir / "steps.jsonl"
        self.lineage_path = self.run_dir / "lineage.jsonl"
        self.snapshots_dir = self.run_dir / "snapshots"
        self.llm_dir = self.run_dir / "llm"
        self.report_path = self.run_dir / "report.md"
        self.started_at = started_at
        self.started_monotonic = time.monotonic()
        self.command = command
        self.arguments = arguments
        self.secret_values = _known_secret_values(self.workspace)
        self._step_counter = 0
        self._lineage_counter = 0
        self._snapshot_counter = 0
        self._step_stack: list[str] = []
        self._trace_incomplete = False
        self._token: Token[DebugTracer | None] | None = None

    def start(self) -> "DebugTracer":
        try:
            prune_expired_debug_runs(self.workspace)
            self.snapshots_dir.mkdir(parents=True, exist_ok=False)
            self.llm_dir.mkdir(parents=True, exist_ok=False)
            self.steps_path.touch()
            self.lineage_path.touch()
            self._write_run(status="running")
        except Exception as exc:
            raise DebugTraceError(f"Debug trace directory could not be created: {exc}") from exc
        self._token = _CURRENT_TRACER.set(self)
        return self

    def close_context(self) -> None:
        if self._token is not None:
            _CURRENT_TRACER.reset(self._token)
            self._token = None

    @property
    def current_step_id(self) -> str | None:
        return self._step_stack[-1] if self._step_stack else None

    def snapshot(self, name: str, value: Any) -> str:
        self._snapshot_counter += 1
        path = self.snapshots_dir / f"{self._snapshot_counter:06d}_{_safe_name(name)}.json"
        payload = {
            "captured_at": utc_iso(),
            "data": make_json_safe(value, secret_values=self.secret_values),
        }
        try:
            _atomic_write_json(path, payload)
        except Exception as exc:
            self._trace_incomplete = True
            raise DebugTraceError(f"Debug snapshot could not be written: {exc}") from exc
        return str(path.relative_to(self.run_dir))

    @contextmanager
    def step(
        self,
        name: str,
        *,
        kind: str = "stage",
        input_data: Any = None,
        details: dict[str, Any] | None = None,
    ) -> Iterator[DebugStep]:
        self._step_counter += 1
        step = DebugStep(
            tracer=self,
            step_id=f"step_{self._step_counter:06d}",
            name=name,
            kind=kind,
            parent_step_id=self.current_step_id,
            started_at=utc_iso(),
            started_monotonic=time.monotonic(),
            details=dict(details or {}),
        )
        if input_data is not None:
            step.input_snapshot = self.snapshot(f"{step.step_id}_{name}_input", input_data)
        self._step_stack.append(step.step_id)
        try:
            yield step
        except KeyboardInterrupt:
            step.status = "interrupted"
            raise
        except BaseException as exc:
            step.status = "failed"
            step.details.setdefault("error_type", type(exc).__name__)
            step.details.setdefault("error", str(exc))
            raise
        finally:
            if step.output_data is not None:
                step.output_snapshot = self.snapshot(f"{step.step_id}_{name}_output", step.output_data)
            finished_at = utc_iso()
            record = {
                "step_id": step.step_id,
                "parent_step_id": step.parent_step_id,
                "name": step.name,
                "kind": step.kind,
                "status": step.status,
                "started_at": step.started_at,
                "finished_at": finished_at,
                "duration_ms": round((time.monotonic() - step.started_monotonic) * 1000),
                "input_snapshot": step.input_snapshot,
                "output_snapshot": step.output_snapshot,
                "details": make_json_safe(step.details, secret_values=self.secret_values),
            }
            try:
                _append_jsonl(self.steps_path, record)
            except Exception as exc:
                self._trace_incomplete = True
                raise DebugTraceError(f"Debug step could not be written: {exc}") from exc
            if self._step_stack and self._step_stack[-1] == step.step_id:
                self._step_stack.pop()

    def lineage(
        self,
        *,
        operation: str,
        reason: str,
        inputs: Any,
        outputs: Any,
        details: dict[str, Any] | None = None,
        snapshot_name: str | None = None,
    ) -> dict[str, Any]:
        self._lineage_counter += 1
        snapshot_ref = None
        if snapshot_name:
            snapshot_ref = self.snapshot(
                snapshot_name,
                {
                    "inputs": _lineage_snapshot_value(inputs),
                    "outputs": _lineage_snapshot_value(outputs),
                },
            )
        record = {
            "lineage_id": f"lineage_{self._lineage_counter:06d}",
            "step_id": self.current_step_id,
            "operation": operation,
            "reason": reason,
            "inputs": make_json_safe(
                _lineage_public_value(inputs),
                secret_values=self.secret_values,
            ),
            "outputs": make_json_safe(
                _lineage_public_value(outputs),
                secret_values=self.secret_values,
            ),
            "snapshot": snapshot_ref,
            "details": make_json_safe(details or {}, secret_values=self.secret_values),
            "created_at": utc_iso(),
        }
        try:
            _append_jsonl(self.lineage_path, record)
        except Exception as exc:
            self._trace_incomplete = True
            raise DebugTraceError(f"Debug lineage record could not be written: {exc}") from exc
        return record
    def write_llm_record(self, request_id: str, payload: dict[str, Any]) -> str:
        path = self.llm_dir / f"{_safe_name(request_id)}.json"
        record = {
            **payload,
            "run_id": self.run_id,
            "request_id": request_id,
            "parent_step_id": payload.get("parent_step_id") or self.current_step_id,
        }
        try:
            _atomic_write_json(path, make_json_safe(record, secret_values=self.secret_values))
        except Exception as exc:
            self._trace_incomplete = True
            raise DebugTraceError(f"Debug LLM record could not be written: {exc}") from exc
        return str(path.relative_to(self.run_dir))

    def finalize(self, *, status: str, error: BaseException | None = None) -> dict[str, Any]:
        final_status = status
        if self._trace_incomplete and final_status == "success":
            final_status = "trace_incomplete"
        error_payload = None
        if error is not None:
            error_payload = {
                "type": type(error).__name__,
                "message": str(error),
            }
        finished_at = utc_now()
        try:
            report = self._build_report(final_status, finished_at)
            self.report_path.write_text(report, encoding="utf-8")
            self._write_run(
                status=final_status,
                finished_at=finished_at,
                error=error_payload,
            )
        except Exception as exc:
            self._trace_incomplete = True
            self._mark_incomplete_run(finished_at=finished_at, error=exc)
            raise DebugTraceError(f"Debug trace could not be finalized: {exc}") from exc
        return self.public_summary(status=final_status)

    def _mark_incomplete_run(self, *, finished_at: datetime, error: BaseException) -> None:
        run_path = self.run_dir / "run.json"
        try:
            payload = _load_json(run_path)
        except Exception:
            payload = {
                "run_id": self.run_id,
                "command": self.command,
                "arguments": make_json_safe(self.arguments, secret_values=self.secret_values),
                "workspace": str(self.workspace),
                "started_at": utc_iso(self.started_at),
                "expires_at": utc_iso(self.started_at + timedelta(days=self.retention_days)),
                "retention_days": self.retention_days,
            }
        payload.update({
            "status": "trace_incomplete",
            "trace_incomplete": True,
            "record_complete": False,
            "finished_at": utc_iso(finished_at),
            "duration_ms": round((time.monotonic() - self.started_monotonic) * 1000),
            "error": make_json_safe({
                "type": type(error).__name__,
                "message": str(error),
            }, secret_values=self.secret_values),
        })
        try:
            _atomic_write_json(run_path, payload)
        except Exception:
            pass

    def public_summary(self, *, status: str | None = None) -> dict[str, Any]:
        steps = _load_jsonl(self.steps_path)
        effective_status = status or "running"
        return {
            "run_id": self.run_id,
            "status": effective_status,
            "record_complete": effective_status != "running" and not self._trace_incomplete,
            "run_dir": str(self.run_dir),
            "report_path": str(self.report_path),
            "step_count": len(steps),
            "llm_request_count": len(list(self.llm_dir.glob("*.json"))),
        }

    def _write_run(
        self,
        *,
        status: str,
        finished_at: datetime | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        steps = _load_jsonl(self.steps_path) if self.steps_path.exists() else []
        lineage = _load_jsonl(self.lineage_path) if self.lineage_path.exists() else []
        llm_records = list(self.llm_dir.glob("*.json")) if self.llm_dir.exists() else []
        llm_payloads = [_load_json(path) for path in llm_records]
        lineage_statistics = _summarize_lineage_records(lineage)
        payload = {
            "run_id": self.run_id,
            "command": self.command,
            "arguments": make_json_safe(self.arguments, secret_values=self.secret_values),
            "workspace": str(self.workspace),
            "status": status,
            "trace_incomplete": self._trace_incomplete,
            "record_complete": finished_at is not None and not self._trace_incomplete,
            "started_at": utc_iso(self.started_at),
            "finished_at": utc_iso(finished_at) if finished_at else None,
            "expires_at": utc_iso(self.started_at + timedelta(days=self.retention_days)),
            "duration_ms": round((time.monotonic() - self.started_monotonic) * 1000) if finished_at else None,
            "retention_days": self.retention_days,
            "statistics": {
                "step_count": len(steps),
                "lineage_count": len(lineage),
                "llm_request_count": len(llm_records),
                "llm": _summarize_llm_records(llm_payloads),
                **lineage_statistics,
            },
            "error": make_json_safe(error, secret_values=self.secret_values),
        }
        _atomic_write_json(self.run_dir / "run.json", payload)

    def _build_report(self, status: str, finished_at: datetime) -> str:
        steps = _load_jsonl(self.steps_path)
        lineage = _load_jsonl(self.lineage_path)
        llm_records = [_load_json(path) for path in sorted(self.llm_dir.glob("*.json"))]
        lineage_statistics = _summarize_lineage_records(lineage)

        llm_statistics = _summarize_llm_records(llm_records)

        lines = [
            "# MyAgentWiki 调试报告",
            "",
            f"- 运行编号：`{self.run_id}`",
            f"- 命令：`{self.command}`",
            f"- 状态：`{status}`",
            f"- 调试记录完整：`{'是' if not self._trace_incomplete else '否'}`",
            f"- 开始时间：`{utc_iso(self.started_at)}`",
            f"- 结束时间：`{utc_iso(finished_at)}`",
            f"- 总耗时：`{round((time.monotonic() - self.started_monotonic) * 1000)} ms`",
            f"- 步骤数：`{len(steps)}`",
            f"- LLM 逻辑请求数：`{len(llm_records)}`",
            "",
            "## 主要步骤",
            "",
            "| 步骤 | 类型 | 状态 | 耗时 |",
            "| --- | --- | --- | ---: |",
        ]
        for step in steps:
            lines.append(
                f"| `{step.get('name', '')}` | `{step.get('kind', '')}` | "
                f"`{step.get('status', '')}` | {int(step.get('duration_ms', 0))} ms |"
            )
        if not steps:
            lines.append("| - | - | - | 0 ms |")

        lines.extend([
            "",
            "## LLM 性能",
            "",
            f"- 请求尝试次数：`{llm_statistics['attempt_count']}`",
            f"- 重试次数：`{llm_statistics['retry_attempt_count']}`",
            f"- 失败尝试次数：`{llm_statistics['failed_attempt_count']}`",
            f"- JSON 修复次数：`{llm_statistics['repaired_attempt_count']}`",
            f"- 全部尝试耗时：`{llm_statistics['attempt_duration_ms']} ms`",
            f"- 在线尝试耗时：`{llm_statistics['backend_duration_ms'].get('online', 0)} ms`",
            f"- CLI 尝试耗时：`{llm_statistics['backend_duration_ms'].get('cli', 0)} ms`",
            f"- 重试等待：`{llm_statistics['retry_wait_ms']} ms`",
            *(
                [
                    f"- 已提供用量的输入 token 合计：`{llm_statistics['input_tokens']}`",
                    f"- 已提供用量的输出 token 合计：`{llm_statistics['output_tokens']}`",
                ]
                if llm_statistics["usage_available_attempt_count"]
                else ["- Token 用量：线路未提供"]
            ),
            *(
                [
                    "- 未提供 token 用量的尝试："
                    f"`{llm_statistics['usage_unavailable_attempt_count']}`"
                ]
                if llm_statistics["usage_unavailable_attempt_count"]
                else []
            ),
            "",
            "## 数据操作",
            "",
            "| 操作 | 数据类型 | 数量 |",
            "| --- | --- | ---: |",
        ])
        for operation, type_counts in sorted(
            lineage_statistics["entity_type_operation_counts"].items()
        ):
            for entity_type, count in sorted(type_counts.items()):
                lines.append(f"| `{operation}` | `{entity_type}` | {count} |")
        if not lineage_statistics["operation_counts"]:
            lines.append("| - | - | 0 |")

        source_rows: dict[str, list[str]] = {}
        for record in lineage:
            values = [*record.get("inputs", []), *record.get("outputs", [])]
            for value in values:
                if not isinstance(value, dict):
                    continue
                source_id = str(value.get("source_id") or "")
                entity_type = str(value.get("entity_type") or "")
                if source_id and entity_type and entity_type not in source_rows.setdefault(source_id, []):
                    source_rows[source_id].append(entity_type)
        lines.extend(["", "## 来源数据流", ""])
        if source_rows:
            for source_id, entity_types in sorted(source_rows.items()):
                lines.append(f"- `{source_id}`：{' -> '.join(entity_types)}")
        else:
            lines.append("- 本次运行没有来源级数据关系记录。")
        return "\n".join(lines) + "\n"


_CURRENT_TRACER: ContextVar[DebugTracer | None] = ContextVar("myagentwiki_debug_tracer", default=None)


def current_debug_tracer() -> DebugTracer | None:
    return _CURRENT_TRACER.get()


@contextmanager
def trace_step(
    name: str,
    *,
    kind: str = "stage",
    input_data: Any | Callable[[], Any] = None,
    details: dict[str, Any] | None = None,
) -> Iterator[DebugStep]:
    tracer = current_debug_tracer()
    if tracer is None:
        yield DebugStep(tracer=None, name=name, kind=kind, details=dict(details or {}))
        return
    resolved_input = input_data() if callable(input_data) else input_data
    with tracer.step(name, kind=kind, input_data=resolved_input, details=details) as step:
        yield step


def trace_lineage(
    *,
    operation: str,
    reason: str,
    inputs: Any | Callable[[], Any],
    outputs: Any | Callable[[], Any],
    details: dict[str, Any] | None = None,
    snapshot_name: str | None = None,
) -> dict[str, Any] | None:
    tracer = current_debug_tracer()
    if tracer is None:
        return None
    return tracer.lineage(
        operation=operation,
        reason=reason,
        inputs=inputs() if callable(inputs) else inputs,
        outputs=outputs() if callable(outputs) else outputs,
        details=details,
        snapshot_name=snapshot_name,
    )


def list_debug_runs(workspace: Path) -> list[dict[str, Any]]:
    prune_expired_debug_runs(workspace)
    debug_root, _ = resolve_debug_settings(workspace)
    if not debug_root.exists():
        return []
    root = debug_root.resolve()
    runs: list[dict[str, Any]] = []
    for child in debug_root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        resolved = child.resolve()
        if resolved.parent != root:
            continue
        run_path = resolved / "run.json"
        if not run_path.is_file():
            continue
        try:
            run = _load_json(run_path)
        except (OSError, json.JSONDecodeError):
            continue
        if str(run.get("run_id") or "") != child.name:
            continue
        runs.append(run)
    return sorted(runs, key=lambda item: str(item.get("started_at", "")), reverse=True)


def load_debug_run(
    workspace: Path,
    run_id: str,
    *,
    source_id: str | None = None,
    step_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    runs = list_debug_runs(workspace)
    if not runs:
        raise FileNotFoundError("No retained debug runs were found.")
    selected_id = str(runs[0]["run_id"]) if run_id == "latest" else run_id
    debug_root, _ = resolve_debug_settings(workspace)
    run_dir = (debug_root / selected_id).resolve()
    if run_dir.parent != debug_root.resolve() or not run_dir.is_dir() or run_dir.is_symlink():
        raise FileNotFoundError(f"Debug run does not exist: {selected_id}")
    run = _load_json(run_dir / "run.json")
    steps = _load_jsonl(run_dir / "steps.jsonl")
    lineage = _load_jsonl(run_dir / "lineage.jsonl")

    if step_id:
        selected_step_ids = {step_id}
        while True:
            descendants = {
                str(record.get("step_id"))
                for record in steps
                if str(record.get("parent_step_id") or "") in selected_step_ids
            }
            expanded = selected_step_ids | descendants
            if expanded == selected_step_ids:
                break
            selected_step_ids = expanded
        steps = [record for record in steps if str(record.get("step_id")) in selected_step_ids]
        lineage = [record for record in lineage if str(record.get("step_id")) in selected_step_ids]
    if source_id:
        lineage = [
            record for record in lineage
            if _record_has_source_id(record, source_id)
        ]
        related_step_ids = {str(record.get("step_id")) for record in lineage}
        steps = [record for record in steps if str(record.get("step_id")) in related_step_ids]

    payload: dict[str, Any] = {
        "run": run,
        "steps": steps,
        "lineage": lineage,
        "report_path": str(run_dir / "report.md"),
    }
    payload["snapshots"] = _load_referenced_snapshots(run_dir, steps=steps, lineage=lineage)
    if request_id:
        request_path = run_dir / "llm" / f"{_safe_name(request_id)}.json"
        if not request_path.is_file():
            raise FileNotFoundError(f"LLM request does not exist in run `{selected_id}`: {request_id}")
        payload["llm_request"] = _load_json(request_path)
    else:
        payload["llm_requests"] = [
            _load_json(path) for path in sorted((run_dir / "llm").glob("*.json"))
        ]
    return payload


def _record_has_source_id(record: dict[str, Any], source_id: str) -> bool:
    for side in ("inputs", "outputs"):
        entities = record.get(side, [])
        if not isinstance(entities, list):
            continue
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            if str(entity.get("source_id") or "") == source_id:
                return True
            entity_source_ids = entity.get("source_ids", [])
            if isinstance(entity_source_ids, list) and source_id in {
                str(item) for item in entity_source_ids
            }:
                return True
    return False


def _load_referenced_snapshots(
    run_dir: Path,
    *,
    steps: list[dict[str, Any]],
    lineage: list[dict[str, Any]],
) -> dict[str, Any]:
    snapshot_refs = {
        str(reference)
        for record in steps
        for reference in (record.get("input_snapshot"), record.get("output_snapshot"))
        if reference
    }
    snapshot_refs.update(
        str(record["snapshot"])
        for record in lineage
        if record.get("snapshot")
    )
    snapshots: dict[str, Any] = {}
    resolved_run_dir = run_dir.resolve()
    resolved_snapshots_dir = (resolved_run_dir / "snapshots").resolve()
    for reference in sorted(snapshot_refs):
        snapshot_path = (resolved_run_dir / reference).resolve()
        if snapshot_path.parent != resolved_snapshots_dir or not snapshot_path.is_file():
            continue
        try:
            snapshots[reference] = _load_json(snapshot_path)
        except (OSError, json.JSONDecodeError):
            snapshots[reference] = {"error": "snapshot_unavailable"}
    return snapshots
