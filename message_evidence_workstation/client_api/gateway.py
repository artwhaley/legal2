"""Temporary Python harness gateway for the five v4 product operations."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
import threading
from typing import Any, Iterator

from message_evidence_workstation.client_api.contracts import (
    StreamEvent,
    validate_analysis_plan,
    validate_stream_value,
)


class RemoteGatewayError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        interrupted: bool = False,
        request_id: str | None = None,
        stage: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        self.status_code = status_code
        self.error_code = error_code
        self.interrupted = interrupted
        self.request_id = request_id
        self.stage = stage
        self.retryable = retryable
        self.details = dict(details or {})
        context: list[str] = []
        if request_id:
            context.append(f"request {request_id}")
        completed = self.details.get("completed_windows")
        total = self.details.get("window_count")
        if isinstance(completed, int) and isinstance(total, int):
            context.append(f"{completed}/{total} windows completed")
        rendered = f"{message} ({'; '.join(context)})" if context else message
        super().__init__(rendered)


class RemoteGatewayCancelled(RemoteGatewayError):
    def __init__(self) -> None:
        super().__init__("Request cancelled by user", interrupted=True)


class RequestCancellation:
    """Thread-safe cancellation handle for one blocking urllib stream."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._closer = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            closer = self._closer
        if closer is not None:
            try:
                closer()
            except OSError:
                pass

    def bind(self, closer) -> None:
        with self._lock:
            self._closer = closer
            cancelled = self._cancelled.is_set()
        if cancelled:
            try:
                closer()
            except OSError:
                pass
            raise RemoteGatewayCancelled()

    def unbind(self, closer) -> None:
        with self._lock:
            if self._closer is closer:
                self._closer = None

    def checkpoint(self) -> None:
        if self.cancelled:
            raise RemoteGatewayCancelled()


class RemoteGateway:
    def __init__(self, server_url: str, *, timeout_seconds: float = 120.0):
        self.server_url = server_url.rstrip("/")
        if not self.server_url.startswith(("http://", "https://")):
            raise ValueError("server URL must begin with http:// or https://")
        if timeout_seconds <= 0:
            raise ValueError("gateway timeout must be positive")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _parse_http_error(exc: urllib.error.HTTPError) -> RemoteGatewayError:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            error = json.loads(body)
        except json.JSONDecodeError:
            return RemoteGatewayError(f"Server HTTP {exc.code}: malformed error response", status_code=exc.code)
        required = {"request_id", "code", "message", "stage", "retryable", "details"}
        if not isinstance(error, dict) or set(error) != required:
            return RemoteGatewayError(f"Server HTTP {exc.code}: invalid error contract", status_code=exc.code)
        return RemoteGatewayError(
            str(error["message"]),
            status_code=exc.code,
            error_code=str(error["code"]),
            request_id=(
                str(error["request_id"])
                if error["request_id"] is not None
                else None
            ),
            stage=str(error["stage"]),
            retryable=bool(error["retryable"]),
            details=dict(error["details"]),
        )

    def _request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        cancellation: RequestCancellation | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(self.server_url + path, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        try:
            if cancellation is not None:
                cancellation.checkpoint()
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                closer = response.close if cancellation is not None else None
                if cancellation is not None:
                    cancellation.bind(closer)
                try:
                    body = response.read().decode("utf-8")
                finally:
                    if cancellation is not None:
                        cancellation.unbind(closer)
        except urllib.error.HTTPError as exc:
            raise self._parse_http_error(exc) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RemoteGatewayError("Server connection failed or timed out") from exc
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RemoteGatewayError("Server returned malformed JSON") from exc
        if not isinstance(result, dict):
            raise RemoteGatewayError("Server returned a non-object JSON response")
        return result

    def keyword_expansion(self, query: str) -> list[str]:
        request_id = self._request_id()
        result = self._request("/v1/keyword-expansion", {"request_id": request_id, "query": query})
        if set(result) != {"request_id", "config_version", "terms", "usage"} or result.get("request_id") != request_id or not isinstance(result.get("config_version"), int):
            raise RemoteGatewayError("Server returned malformed keyword response")
        terms = result.get("terms")
        if not isinstance(terms, list) or not terms or any(not isinstance(term, str) or not term or term != term.strip() for term in terms) or len(terms) != len(set(terms)):
            raise RemoteGatewayError("Server returned malformed keyword terms")
        return terms

    def conversational_plan(
        self,
        question: str,
        *,
        cancellation: RequestCancellation | None = None,
    ) -> dict[str, Any]:
        request_id = self._request_id()
        result = self._request(
            "/v1/conversational-plan",
            {"request_id": request_id, "question": question},
            cancellation=cancellation,
        )
        try:
            validate_analysis_plan(result)
        except ValueError as exc:
            raise RemoteGatewayError(
                "Server returned a malformed conversational analysis plan"
            ) from exc
        if result["request_id"] != request_id:
            raise RemoteGatewayError(
                "Server changed the analysis-plan request identity"
            )
        return result

    def _stream(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        cancellation: RequestCancellation | None = None,
    ) -> Iterator[StreamEvent]:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(self.server_url + path, data=data, headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"}, method="POST")
        expected_request_id = str(payload["request_id"])
        expected_sequence = 1
        config_version: int | None = None
        terminal: StreamEvent | None = None
        try:
            if cancellation is not None:
                cancellation.checkpoint()
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                closer = response.close if cancellation is not None else None
                if cancellation is not None:
                    cancellation.bind(closer)
                content_type = response.headers.get_content_type()
                if content_type != "application/x-ndjson":
                    raise RemoteGatewayError("Server stream has the wrong content type", interrupted=True)
                try:
                    for raw_line in response:
                        if cancellation is not None:
                            cancellation.checkpoint()
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue
                        if terminal is not None:
                            raise RemoteGatewayError("Server emitted data after its terminal event", interrupted=True)
                        try:
                            value = json.loads(line)
                            validate_stream_value(value, endpoint=path)
                        except (json.JSONDecodeError, ValueError) as exc:
                            raise RemoteGatewayError(
                                f"Server stream violated its exact event contract: {exc}",
                                interrupted=True,
                            ) from exc
                        if value["request_id"] != expected_request_id or value["sequence"] != expected_sequence:
                            raise RemoteGatewayError("Server stream changed request identity or sequence", interrupted=True)
                        if config_version is None:
                            config_version = value["config_version"]
                        elif value["config_version"] != config_version:
                            raise RemoteGatewayError("Server stream changed configuration version", interrupted=True)
                        event = StreamEvent(value)
                        expected_sequence += 1
                        if event.terminal:
                            terminal = event
                        else:
                            yield event
                finally:
                    if cancellation is not None:
                        cancellation.unbind(closer)
        except RemoteGatewayCancelled:
            raise
        except urllib.error.HTTPError as exc:
            raise self._parse_http_error(exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if cancellation is not None and cancellation.cancelled:
                raise RemoteGatewayCancelled() from exc
            raise RemoteGatewayError("Server stream connection failed or timed out", interrupted=True) from exc
        except Exception as exc:
            if cancellation is not None and cancellation.cancelled:
                raise RemoteGatewayCancelled() from exc
            raise
        if terminal is None:
            raise RemoteGatewayError("Server stream ended before a terminal event", interrupted=True)
        yield terminal

    def conversational_analysis(
        self,
        *,
        question: str,
        scope_id: str,
        messages: list[dict[str, Any]],
        analysis_context: dict[str, Any],
        cancellation: RequestCancellation | None = None,
    ) -> Iterator[StreamEvent]:
        return self._stream(
            "/v1/conversational-analysis",
            {
                "request_id": self._request_id(),
                "question": question,
                "working_corpus": {"scope_id": scope_id, "messages": messages},
                "analysis_context": analysis_context,
            },
            cancellation=cancellation,
        )

    def embeddings(
        self,
        items: list[dict[str, str]],
        *,
        cancellation: RequestCancellation | None = None,
    ) -> Iterator[StreamEvent]:
        return self._stream(
            "/v1/embeddings",
            {"request_id": self._request_id(), "items": items},
            cancellation=cancellation,
        )
