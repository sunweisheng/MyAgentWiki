from __future__ import annotations

import base64
import json
import os
import ssl
from pathlib import Path
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, DefaultHttpxClient, OpenAI
from PIL import Image

from ..debug_trace import current_debug_tracer, file_metadata, make_json_safe
from ..runtime_env import load_simple_env
from .contracts import (
    LLMFunctionSpec,
    chat_completions_function_tool,
    openai_function_tool,
)
from .errors import LLMClientError, LLMConfigurationError, LLMResponseError
from .repair import RawFunctionCall


ONLINE_ENV_REL_PATH = Path(".env")
RESPONSES_API_STYLE = "responses"
CHAT_COMPLETIONS_API_STYLE = "chat_completions"
SUPPORTED_API_STYLES = {RESPONSES_API_STYLE, CHAT_COMPLETIONS_API_STYLE}

ONLINE_ENVIRONMENT_KEYS = {
    "protocol": "MYAGENTWIKI_LLM_PROTOCOL",
    "base_url": "MYAGENTWIKI_LLM_BASE_URL",
    "model": "MYAGENTWIKI_LLM_MODEL",
    "api_key": "MYAGENTWIKI_LLM_API_KEY",
    "timeout_seconds": "MYAGENTWIKI_LLM_TIMEOUT_SECONDS",
    "api_style": "MYAGENTWIKI_LLM_API_STYLE",
    "verify_ssl": "MYAGENTWIKI_LLM_VERIFY_SSL",
}


def _online_environment_value(local_values: dict[str, str], name: str, default: str = "") -> str:
    # 系统环境变量适合 CI 和临时覆盖，本地 .env 适合保存当前用户的固定配置。
    return os.environ.get(name, local_values.get(name, default)).strip()


def load_online_config(workspace: Path) -> dict[str, Any]:
    path = workspace / ONLINE_ENV_REL_PATH
    try:
        local_values = load_simple_env(path)
    except Exception as exc:
        raise LLMConfigurationError(f"Online configuration `.env` could not be parsed: {exc}") from exc
    values = {
        "protocol": _online_environment_value(
            local_values,
            ONLINE_ENVIRONMENT_KEYS["protocol"],
            "openai_compatible",
        ),
        "base_url": _online_environment_value(local_values, ONLINE_ENVIRONMENT_KEYS["base_url"]).rstrip("/"),
        "model": _online_environment_value(local_values, ONLINE_ENVIRONMENT_KEYS["model"]),
        "api_key": _online_environment_value(local_values, ONLINE_ENVIRONMENT_KEYS["api_key"]),
        "api_style": _online_environment_value(
            local_values,
            ONLINE_ENVIRONMENT_KEYS["api_style"],
            RESPONSES_API_STYLE,
        ) or RESPONSES_API_STYLE,
    }
    missing = [key for key in ("protocol", "base_url", "model", "api_key") if not values[key]]
    if missing:
        raise LLMConfigurationError(f"Online configuration in `.env` is missing: {', '.join(missing)}.")
    if values["protocol"] != "openai_compatible":
        raise LLMConfigurationError("Only `openai_compatible` online providers are supported.")
    if values["api_style"] not in SUPPORTED_API_STYLES:
        raise LLMConfigurationError(f"Unsupported API style `{values['api_style']}`.")
    try:
        values["timeout_seconds"] = max(int(_online_environment_value(
            local_values,
            ONLINE_ENVIRONMENT_KEYS["timeout_seconds"],
            "120",
        )), 5)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError("`MYAGENTWIKI_LLM_TIMEOUT_SECONDS` must be an integer >= 5.") from exc
    verify_ssl = _online_environment_value(local_values, ONLINE_ENVIRONMENT_KEYS["verify_ssl"], "true")
    values["verify_ssl"] = verify_ssl.lower() not in {"0", "false", "no", "off"}
    return values


def _has_ssl_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _status_is_retryable(
    status: int | None,
    retryable_statuses: set[int] | None = None,
    retryable_status_min: int = 500,
) -> bool:
    configured_statuses = retryable_statuses or {408, 409, 429}
    return status in configured_statuses or bool(status and status >= retryable_status_min)


def _provider_request_id(response: Any) -> str | None:
    value = getattr(response, "_request_id", None) or getattr(response, "id", None)
    return str(value) if value else None


def _usage_number(usage: Any, *names: str) -> int:
    for name in names:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(name)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _online_usage_payload(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"available": False}
    input_tokens = _usage_number(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_number(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_number(usage, "total_tokens") or input_tokens + output_tokens
    return {
        "available": True,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _response_debug_payload(response: Any) -> Any:
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:
            return model_dump()
    if isinstance(response, dict):
        return response
    return make_json_safe(getattr(response, "__dict__", str(response)))


def _image_data_url(path: Path, *, max_bytes: int, allowed_mime_types: set[str]) -> str:
    resolved = path.resolve()
    if not resolved.is_file():
        raise LLMConfigurationError(f"Image file does not exist: {resolved}")
    size = resolved.stat().st_size
    if size > max_bytes:
        raise LLMConfigurationError(f"Image exceeds configured size limit: {size} > {max_bytes} bytes.")
    try:
        with Image.open(resolved) as image:
            image_format = str(image.format or "").upper()
            image.verify()
    except Exception as exc:
        raise LLMConfigurationError(f"Image content could not be identified: {resolved.name}") from exc
    mime_type = Image.MIME.get(image_format, "application/octet-stream")
    if mime_type not in allowed_mime_types:
        raise LLMConfigurationError(f"Unsupported image MIME type `{mime_type}`.")
    encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


class OnlineLLMClient:
    backend = "online"

    def __init__(
        self,
        workspace: Path,
        *,
        image_max_bytes: int,
        image_mime_types: set[str],
        timeout_seconds: int | None = None,
        retryable_http_statuses: set[int] | None = None,
        retryable_http_status_min: int = 500,
    ) -> None:
        self.workspace = workspace
        self.config = load_online_config(workspace)
        self.image_max_bytes = image_max_bytes
        self.image_mime_types = image_mime_types
        self.timeout_seconds = timeout_seconds
        self.retryable_http_statuses = retryable_http_statuses or {408, 409, 429}
        self.retryable_http_status_min = retryable_http_status_min
        self._client: OpenAI | None = None

    def __enter__(self) -> OnlineLLMClient:
        try:
            transport = httpx.HTTPTransport(retries=0, verify=self.config["verify_ssl"])
            http_client = DefaultHttpxClient(
                transport=transport,
                timeout=self.timeout_seconds or self.config["timeout_seconds"],
            )
            self._client = OpenAI(
                api_key=self.config["api_key"],
                base_url=self.config["base_url"],
                http_client=http_client,
                max_retries=0,
            )
        except Exception as exc:
            kind = "tls_error" if _has_ssl_error(exc) else "configuration_error"
            raise LLMClientError(
                "Online model TLS setup failed." if kind == "tls_error" else "Online client setup failed.",
                backend=self.backend,
                kind=kind,
                retryable=False,
            ) from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def model(self) -> str:
        return str(self.config["model"])

    @property
    def api_style(self) -> str:
        return str(self.config["api_style"])

    def request(
        self,
        *,
        spec: LLMFunctionSpec,
        context: dict[str, Any],
        image_paths: list[Path],
    ) -> RawFunctionCall:
        if self._client is None:
            raise RuntimeError("OnlineLLMClient must be used as a context manager.")
        debug_request = None
        if current_debug_tracer() is not None:
            debug_request = {
                "model": self.model,
                "api_style": self.api_style,
                "instructions": spec.instructions,
                "description": spec.description,
                "function": {
                    "name": spec.function_name,
                    "parameters_schema": spec.parameters_schema,
                },
                "context": context,
                "images": [file_metadata(path) for path in image_paths],
            }
        try:
            if self.api_style == RESPONSES_API_STYLE:
                response = self._request_responses(spec=spec, context=context, image_paths=image_paths)
                call = self._extract_responses_call(response, spec)
            else:
                response = self._request_chat_completions(spec=spec, context=context, image_paths=image_paths)
                call = self._extract_chat_call(response, spec)
            if debug_request is None:
                return call
            return RawFunctionCall(
                function_name=call.function_name,
                arguments_json=call.arguments_json,
                debug={
                    "request": debug_request,
                    "raw_response": _response_debug_payload(response),
                    "provider_request_id": _provider_request_id(response),
                    "usage": _online_usage_payload(response),
                },
            )
        except LLMClientError as exc:
            if debug_request is not None and not exc.debug_details:
                exc.debug_details = {"request": debug_request}
            raise
        except APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            raise LLMClientError(
                f"Online model returned HTTP {status}.",
                backend=self.backend,
                kind="http_error",
                retryable=_status_is_retryable(
                    status,
                    self.retryable_http_statuses,
                    self.retryable_http_status_min,
                ),
                http_status=status,
                debug_details={
                    "request": debug_request,
                    "provider_request_id": getattr(exc, "request_id", None),
                    "response_body": getattr(getattr(exc, "response", None), "text", None),
                } if debug_request is not None else None,
            ) from exc
        except APITimeoutError as exc:
            raise LLMClientError(
                "Online model request timed out.",
                backend=self.backend,
                kind="timeout",
                retryable=True,
                debug_details={"request": debug_request} if debug_request is not None else None,
            ) from exc
        except APIConnectionError as exc:
            if _has_ssl_error(exc):
                raise LLMClientError(
                    "Online model TLS validation failed.",
                    backend=self.backend,
                    kind="tls_error",
                    retryable=False,
                    debug_details={"request": debug_request} if debug_request is not None else None,
                ) from exc
            raise LLMClientError(
                "Online model connection failed.",
                backend=self.backend,
                kind="connection_error",
                retryable=True,
                debug_details={"request": debug_request} if debug_request is not None else None,
            ) from exc
        except Exception as exc:
            raise LLMClientError(
                f"Online model request failed: {type(exc).__name__}.",
                backend=self.backend,
                kind="request_error",
                retryable=True,
                debug_details={
                    "request": debug_request,
                    "exception_type": type(exc).__name__,
                } if debug_request is not None else None,
            ) from exc

    def _responses_input(self, context: dict[str, Any], image_paths: list[Path]) -> Any:
        text = json.dumps(context, ensure_ascii=False, sort_keys=True)
        if not image_paths:
            return text
        content: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
        content.extend({
            "type": "input_image",
            "image_url": _image_data_url(
                path,
                max_bytes=self.image_max_bytes,
                allowed_mime_types=self.image_mime_types,
            ),
        } for path in image_paths)
        return [{"role": "user", "content": content}]

    def _request_responses(self, *, spec: LLMFunctionSpec, context: dict[str, Any], image_paths: list[Path]):
        assert self._client is not None
        return self._client.responses.create(
            model=self.model,
            instructions=spec.instructions,
            input=self._responses_input(context, image_paths),
            tools=[openai_function_tool(spec)],
            tool_choice={"type": "function", "name": spec.function_name},
            parallel_tool_calls=False,
            stream=False,
        )

    def _chat_user_content(self, context: dict[str, Any], image_paths: list[Path]) -> Any:
        text = json.dumps(context, ensure_ascii=False, sort_keys=True)
        if not image_paths:
            return text
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content.extend({
            "type": "image_url",
            "image_url": {"url": _image_data_url(
                path,
                max_bytes=self.image_max_bytes,
                allowed_mime_types=self.image_mime_types,
            )},
        } for path in image_paths)
        return content

    def _request_chat_completions(self, *, spec: LLMFunctionSpec, context: dict[str, Any], image_paths: list[Path]):
        assert self._client is not None
        return self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": spec.instructions},
                {"role": "user", "content": self._chat_user_content(context, image_paths)},
            ],
            tools=[chat_completions_function_tool(spec)],
            tool_choice={"type": "function", "function": {"name": spec.function_name}},
            parallel_tool_calls=False,
            temperature=0,
            stream=False,
        )

    def _extract_responses_call(self, response: Any, spec: LLMFunctionSpec) -> RawFunctionCall:
        calls = [item for item in (getattr(response, "output", None) or []) if getattr(item, "type", "") == "function_call"]
        if len(calls) != 1:
            raise LLMResponseError(f"Expected one function call, received {len(calls)}.", backend=self.backend)
        return RawFunctionCall(
            function_name=str(getattr(calls[0], "name", "")),
            arguments_json=str(getattr(calls[0], "arguments", "")),
        )

    def _extract_chat_call(self, response: Any, spec: LLMFunctionSpec) -> RawFunctionCall:
        choices = getattr(response, "choices", None) or []
        if len(choices) != 1:
            raise LLMResponseError(f"Expected one chat choice, received {len(choices)}.", backend=self.backend)
        calls = getattr(getattr(choices[0], "message", None), "tool_calls", None) or []
        if len(calls) != 1:
            raise LLMResponseError(f"Expected one function call, received {len(calls)}.", backend=self.backend)
        function = getattr(calls[0], "function", None)
        return RawFunctionCall(
            function_name=str(getattr(function, "name", "")),
            arguments_json=str(getattr(function, "arguments", "")),
        )
