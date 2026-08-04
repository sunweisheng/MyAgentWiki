from __future__ import annotations

import base64
import json
import ssl
from pathlib import Path
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, DefaultHttpxClient, OpenAI
from PIL import Image

from ..runtime_env import load_simple_yaml
from .contracts import (
    LLMFunctionSpec,
    chat_completions_function_tool,
    openai_function_tool,
)
from .errors import LLMClientError, LLMConfigurationError, LLMResponseError
from .repair import RawFunctionCall


ONLINE_CONFIG_REL_PATH = Path("config") / "llm.local.yml"
RESPONSES_API_STYLE = "responses"
CHAT_COMPLETIONS_API_STYLE = "chat_completions"
SUPPORTED_API_STYLES = {RESPONSES_API_STYLE, CHAT_COMPLETIONS_API_STYLE}


def load_online_config(workspace: Path) -> dict[str, Any]:
    path = workspace / ONLINE_CONFIG_REL_PATH
    if not path.exists():
        raise LLMConfigurationError(
            f"Online configuration `{ONLINE_CONFIG_REL_PATH.as_posix()}` is missing."
        )
    try:
        config = load_simple_yaml(path)
    except Exception as exc:
        raise LLMConfigurationError(f"Online configuration could not be parsed: {exc}") from exc
    provider = config.get("provider", {})
    transport = config.get("transport", {})
    if not isinstance(provider, dict) or not isinstance(transport, dict):
        raise LLMConfigurationError("`provider` and `transport` must be mappings.")
    values = {
        "protocol": str(provider.get("protocol", "")).strip(),
        "base_url": str(provider.get("base_url", "")).strip().rstrip("/"),
        "model": str(provider.get("model", "")).strip(),
        "api_key": str(provider.get("api_key", "")).strip(),
        "api_style": str(transport.get("api_style", RESPONSES_API_STYLE)).strip() or RESPONSES_API_STYLE,
    }
    missing = [key for key in ("protocol", "base_url", "model", "api_key") if not values[key]]
    if missing:
        raise LLMConfigurationError(f"Online configuration is missing: {', '.join(missing)}.")
    if values["protocol"] != "openai_compatible":
        raise LLMConfigurationError("Only `openai_compatible` online providers are supported.")
    if values["api_style"] not in SUPPORTED_API_STYLES:
        raise LLMConfigurationError(f"Unsupported API style `{values['api_style']}`.")
    if transport.get("stream") is True:
        raise LLMConfigurationError("Streaming LLM requests are not supported; set `transport.stream` to false.")
    try:
        values["timeout_seconds"] = max(int(provider.get("timeout_seconds", 120)), 5)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError("`provider.timeout_seconds` must be an integer >= 5.") from exc
    verify_ssl = transport.get("verify_ssl", True)
    values["verify_ssl"] = verify_ssl if isinstance(verify_ssl, bool) else str(verify_ssl).lower() not in {"0", "false", "no", "off"}
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
        try:
            if self.api_style == RESPONSES_API_STYLE:
                response = self._request_responses(spec=spec, context=context, image_paths=image_paths)
                return self._extract_responses_call(response, spec)
            response = self._request_chat_completions(spec=spec, context=context, image_paths=image_paths)
            return self._extract_chat_call(response, spec)
        except LLMClientError:
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
            ) from exc
        except APITimeoutError as exc:
            raise LLMClientError(
                "Online model request timed out.",
                backend=self.backend,
                kind="timeout",
                retryable=True,
            ) from exc
        except APIConnectionError as exc:
            if _has_ssl_error(exc):
                raise LLMClientError(
                    "Online model TLS validation failed.",
                    backend=self.backend,
                    kind="tls_error",
                    retryable=False,
                ) from exc
            raise LLMClientError(
                "Online model connection failed.",
                backend=self.backend,
                kind="connection_error",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise LLMClientError(
                f"Online model request failed: {type(exc).__name__}.",
                backend=self.backend,
                kind="request_error",
                retryable=True,
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
