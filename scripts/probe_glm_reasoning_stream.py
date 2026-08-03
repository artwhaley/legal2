"""Isolated GLM reasoning-stream probe using the server's real wire contracts.

This script deliberately does not call or modify the running server. It reads
the active server configuration, builds requests with the production payload
builder, and calls the configured provider directly. No retry or fallback is
performed.

The long arm reuses the user object from the most recent captured production
single-window ~100K corpus request. It does not write the corpus or provider
credential into its artifacts.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from server.config import OperationConfig, default_state_dir
from server.config_store import ConfigStore
from server.contracts import (
    AnalysisPlanningOutput,
    LedgerSynthesisOutput,
    SCHEMA_REGISTRY,
    WindowEvidenceEnvelope,
)
from server.model_runtime import ModelOutputInvalid, parse_model_output
from server.token_accounting import (
    build_provider_payload,
    canonical_json,
    count_provider_payload,
)


QUESTION = "Show me fights about school."
TARGET_MODEL = "z-ai/glm-5.2"


@dataclass(slots=True)
class StreamResult:
    label: str
    operation: str
    http_status: int
    provider_request_id: str | None
    elapsed_seconds: float
    first_event_seconds: float | None
    first_reasoning_seconds: float | None
    first_content_seconds: float | None
    event_count: int
    reasoning_chunk_count: int
    content_chunk_count: int
    reasoning: str
    content: str
    finish_reason: str | None
    usage: dict[str, Any] | None
    schema_valid: bool
    validation_error: str | None
    response_error: Any | None

    def public_summary(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("reasoning")
        value.pop("content")
        value.pop("response_error")
        value["reasoning_characters"] = len(self.reasoning)
        value["content_characters"] = len(self.content)
        return value


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _active_config() -> tuple[int, dict[str, OperationConfig]]:
    store = ConfigStore()
    try:
        config = store.active()
        if config is None:
            raise RuntimeError("no active server configuration exists")
        operations = config.operations
        for name in ("analysis_planning", "window_evidence_extraction"):
            operation = operations[name]
            if operation.model_id != TARGET_MODEL:
                raise RuntimeError(
                    f"active {name} model is {operation.model_id!r}, not {TARGET_MODEL!r}"
                )
            if not operation.api_key:
                raise RuntimeError(f"active {name} provider credential is unavailable")
        return config.config_version, operations
    finally:
        store.close()


def _build_payload(
    operation_name: str,
    operation: OperationConfig,
    user_object: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    schema = SCHEMA_REGISTRY[operation_name]["model_output"]
    messages = [
        {"role": "system", "content": operation.system_prompt},
        {"role": "user", "content": canonical_json(user_object)},
    ]
    payload = build_provider_payload(
        operation,
        operation=operation_name,
        messages=messages,
        user_object=user_object,
        response_schema=schema,
    )
    accounting = count_provider_payload(payload, operation)
    if not accounting.fits:
        raise RuntimeError(
            f"{operation_name} payload has {accounting.input_tokens:,} input tokens "
            "and does not fit the active operation budget"
        )
    return payload, accounting.input_tokens


def _captured_100k_user_object() -> tuple[dict[str, Any], dict[str, Any]]:
    capture_dir = default_state_dir() / "debug-captures"
    candidates: list[tuple[str, Path, dict[str, Any], dict[str, Any]]] = []
    for path in capture_dir.glob("*.jsonl"):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("kind") != "provider_request":
                    continue
                data = record.get("data") or {}
                payload = data.get("payload") or {}
                observability = data.get("observability") or {}
                user_object = data.get("user_object") or {}
                messages = user_object.get("messages")
                if (
                    data.get("operation") != "window_evidence_extraction"
                    or payload.get("model") != TARGET_MODEL
                    or observability.get("window_count") != 1
                    or not isinstance(messages, list)
                    or not 1_000 <= len(messages) <= 2_000
                    or "school" not in str(user_object.get("question", "")).casefold()
                ):
                    continue
                metadata = {
                    "capture_file": path.name,
                    "captured_at": record.get("timestamp"),
                    "source_request_id": record.get("request_id"),
                    "source_window_id": data.get("operation_instance"),
                    "message_count": len(messages),
                    "question": user_object.get("question"),
                    "had_suggestion_ranges": bool(user_object.get("suggestion_ranges")),
                }
                candidates.append(
                    (str(record.get("timestamp", "")), path, user_object, metadata)
                )
    if not candidates:
        raise RuntimeError("no captured single-window ~100K GLM request was found")
    _, _, user_object, metadata = max(candidates, key=lambda item: item[0])
    return user_object, metadata


def _validate_content(operation: str, content: str) -> tuple[bool, str | None]:
    model = {
        "analysis_planning": AnalysisPlanningOutput,
        "window_evidence_extraction": WindowEvidenceEnvelope,
        "ledger_synthesis": LedgerSynthesisOutput,
    }[operation]
    try:
        parse_model_output(content, model)
    except ModelOutputInvalid as exc:
        return False, str(exc)
    return True, None


def _stream_request(
    *,
    label: str,
    operation_name: str,
    operation: OperationConfig,
    base_payload: dict[str, Any],
    enable_thinking: bool | None,
) -> StreamResult:
    payload = dict(base_payload)
    payload["stream"] = True
    payload["stream_options"] = {"include_usage": True}
    if enable_thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": enable_thinking}

    started = time.perf_counter()
    first_event = None
    first_reasoning = None
    first_content = None
    event_count = 0
    reasoning_chunks: list[str] = []
    content_chunks: list[str] = []
    finish_reason = None
    usage = None
    response_error = None
    request_id = None
    status = 0

    timeout = httpx.Timeout(
        operation.read_timeout_seconds,
        connect=operation.connect_timeout_seconds,
        write=operation.write_timeout_seconds,
        pool=operation.pool_timeout_seconds,
    )
    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST",
            f"{operation.base_url}/chat/completions",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {operation.api_key}",
            },
        ) as response:
            status = response.status_code
            request_id = response.headers.get("x-request-id")
            if status >= 400:
                body = response.read().decode("utf-8", errors="replace")
                try:
                    response_error = json.loads(body)
                except json.JSONDecodeError:
                    response_error = body
            else:
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    event_count += 1
                    now = time.perf_counter() - started
                    if first_event is None:
                        first_event = now
                    event = json.loads(raw)
                    if isinstance(event.get("usage"), dict):
                        usage = event["usage"]
                    choices = event.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason") is not None:
                        finish_reason = str(choice["finish_reason"])
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning:
                        if first_reasoning is None:
                            first_reasoning = now
                        reasoning_chunks.append(reasoning)
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        if first_content is None:
                            first_content = now
                        content_chunks.append(content)

    elapsed = time.perf_counter() - started
    content = "".join(content_chunks)
    schema_valid, validation_error = _validate_content(operation_name, content)
    if status >= 400:
        validation_error = f"provider returned HTTP {status}"
        schema_valid = False
    return StreamResult(
        label=label,
        operation=operation_name,
        http_status=status,
        provider_request_id=request_id,
        elapsed_seconds=elapsed,
        first_event_seconds=first_event,
        first_reasoning_seconds=first_reasoning,
        first_content_seconds=first_content,
        event_count=event_count,
        reasoning_chunk_count=len(reasoning_chunks),
        content_chunk_count=len(content_chunks),
        reasoning="".join(reasoning_chunks),
        content=content,
        finish_reason=finish_reason,
        usage=usage,
        schema_valid=schema_valid,
        validation_error=validation_error,
        response_error=response_error,
    )


def _fenced(text: str) -> str:
    return f"````text\n{text}\n````"


def _write_markdown(
    path: Path,
    *,
    title: str,
    result: StreamResult,
    input_tokens: int,
    extra: dict[str, Any] | None = None,
) -> None:
    summary = result.public_summary()
    lines = [
        f"# {title}",
        "",
        "This is an isolated direct-provider probe. It did not pass through or modify the server.",
        "",
        "## Request metadata",
        "",
        f"- Operation: `{result.operation}`",
        f"- Production-counted input tokens before stream controls: `{input_tokens:,}`",
    ]
    if extra:
        for key, value in extra.items():
            lines.append(f"- {key.replace('_', ' ').title()}: `{value}`")
    lines.extend(
        [
            "",
            "## Stream result",
            "",
            _fenced(json.dumps(summary, indent=2, ensure_ascii=False)),
            "",
            "## Streamed reasoning",
            "",
            _fenced(result.reasoning or "[No reasoning_content was streamed.]"),
            "",
            "## Final content",
            "",
            _fenced(result.content or "[No final content was streamed.]"),
        ]
    )
    if result.response_error is not None:
        lines.extend(
            [
                "",
                "## Provider error",
                "",
                _fenced(json.dumps(result.response_error, indent=2, ensure_ascii=False)),
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp") / "glm-reasoning-stream-probe" / _utc_stamp(),
    )
    parser.add_argument(
        "--tiny-only",
        action="store_true",
        help="run the two tiny arms but do not advance to the 100K arm",
    )
    parser.add_argument(
        "--long-only",
        action="store_true",
        help="run only the explicit-thinking 100K arm after a separately verified tiny probe",
    )
    args = parser.parse_args()
    if args.tiny_only and args.long_only:
        parser.error("--tiny-only and --long-only are mutually exclusive")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    config_version, operations = _active_config()
    if args.long_only:
        user_object, source_metadata = _captured_100k_user_object()
        extraction = operations["window_evidence_extraction"]
        long_payload, long_input_tokens = _build_payload(
            "window_evidence_extraction", extraction, user_object
        )
        print(
            f"100k/thinking: starting {source_metadata['message_count']:,}-message direct-provider scan",
            flush=True,
        )
        long_result = _stream_request(
            label="100k_explicit_thinking",
            operation_name="window_evidence_extraction",
            operation=extraction,
            base_payload=long_payload,
            enable_thinking=True,
        )
        _write_markdown(
            args.output_dir / "03_100k_thinking_scan.md",
            title="100K single-window scan: explicit GLM thinking",
            result=long_result,
            input_tokens=long_input_tokens,
            extra=source_metadata,
        )
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "active_config_version": config_version,
            "model": TARGET_MODEL,
            "provider_base_url": extraction.base_url,
            "production_payload_has_reasoning_control": False,
            "experimental_control": {"chat_template_kwargs": {"enable_thinking": True}},
            "no_retry_or_fallback": True,
            "advanced_after_separately_verified_tiny_probe": True,
            "source_100k": source_metadata,
            "long_input_tokens": long_input_tokens,
            "long_explicit_thinking": long_result.public_summary(),
            "artifact_files": ["03_100k_thinking_scan.md"],
        }
        (args.output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            f"100k/thinking: HTTP {long_result.http_status}; reasoning chars={len(long_result.reasoning):,}; "
            f"schema_valid={long_result.schema_valid}; elapsed={long_result.elapsed_seconds:.1f}s",
            flush=True,
        )
        print(f"artifacts: {args.output_dir.resolve()}", flush=True)
        return 0 if long_result.http_status == 200 else 1

    planning = operations["analysis_planning"]
    tiny_user = {"task": "analysis_planning", "question": QUESTION}
    tiny_payload, tiny_input_tokens = _build_payload(
        "analysis_planning", planning, tiny_user
    )

    print("tiny/current: starting", flush=True)
    current = _stream_request(
        label="tiny_current_payload",
        operation_name="analysis_planning",
        operation=planning,
        base_payload=tiny_payload,
        enable_thinking=None,
    )
    _write_markdown(
        args.output_dir / "01_tiny_current.md",
        title="Tiny probe: current production payload",
        result=current,
        input_tokens=tiny_input_tokens,
    )
    print(
        f"tiny/current: HTTP {current.http_status}; reasoning chars={len(current.reasoning):,}; "
        f"schema_valid={current.schema_valid}; elapsed={current.elapsed_seconds:.1f}s",
        flush=True,
    )

    print("tiny/thinking: starting", flush=True)
    thinking = _stream_request(
        label="tiny_explicit_thinking",
        operation_name="analysis_planning",
        operation=planning,
        base_payload=tiny_payload,
        enable_thinking=True,
    )
    _write_markdown(
        args.output_dir / "02_tiny_thinking.md",
        title="Tiny probe: explicit GLM thinking",
        result=thinking,
        input_tokens=tiny_input_tokens,
        extra={"experimental_control": "chat_template_kwargs.enable_thinking=true"},
    )
    print(
        f"tiny/thinking: HTTP {thinking.http_status}; reasoning chars={len(thinking.reasoning):,}; "
        f"schema_valid={thinking.schema_valid}; elapsed={thinking.elapsed_seconds:.1f}s",
        flush=True,
    )

    meaningful_reasoning = bool(thinking.reasoning.strip())
    long_result = None
    source_metadata = None
    long_input_tokens = None
    if not args.tiny_only and thinking.http_status == 200 and meaningful_reasoning:
        user_object, source_metadata = _captured_100k_user_object()
        extraction = operations["window_evidence_extraction"]
        long_payload, long_input_tokens = _build_payload(
            "window_evidence_extraction", extraction, user_object
        )
        print(
            f"100k/thinking: starting {source_metadata['message_count']:,}-message direct-provider scan",
            flush=True,
        )
        long_result = _stream_request(
            label="100k_explicit_thinking",
            operation_name="window_evidence_extraction",
            operation=extraction,
            base_payload=long_payload,
            enable_thinking=True,
        )
        _write_markdown(
            args.output_dir / "03_100k_thinking_scan.md",
            title="100K single-window scan: explicit GLM thinking",
            result=long_result,
            input_tokens=long_input_tokens,
            extra=source_metadata,
        )
        print(
            f"100k/thinking: HTTP {long_result.http_status}; reasoning chars={len(long_result.reasoning):,}; "
            f"schema_valid={long_result.schema_valid}; elapsed={long_result.elapsed_seconds:.1f}s",
            flush=True,
        )
    elif not args.tiny_only:
        print(
            "100k/thinking: not run because the tiny explicit-thinking arm did not stream reasoning successfully",
            flush=True,
        )

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "active_config_version": config_version,
        "model": TARGET_MODEL,
        "provider_base_url": planning.base_url,
        "production_payload_has_reasoning_control": False,
        "experimental_control": {"chat_template_kwargs": {"enable_thinking": True}},
        "no_retry_or_fallback": True,
        "tiny_input_tokens": tiny_input_tokens,
        "tiny_current": current.public_summary(),
        "tiny_explicit_thinking": thinking.public_summary(),
        "advanced_to_100k": long_result is not None,
        "source_100k": source_metadata,
        "long_input_tokens": long_input_tokens,
        "long_explicit_thinking": (
            long_result.public_summary() if long_result is not None else None
        ),
        "artifact_files": sorted(path.name for path in args.output_dir.glob("*.md")),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"artifacts: {args.output_dir.resolve()}", flush=True)
    return 0 if thinking.http_status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
