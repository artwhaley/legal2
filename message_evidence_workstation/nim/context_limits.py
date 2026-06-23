"""Learn and detect model context limits from provider metadata and API errors."""

from __future__ import annotations

import json
import re
from typing import Any

from message_evidence_workstation.config.settings import load_settings, save_settings
from message_evidence_workstation.nim.client import NimClientError

_CONTEXT_LIMIT_PATTERNS = (
    re.compile(r"maximum context length is (\d+) tokens", re.IGNORECASE),
    re.compile(r"max(?:imum)?[_ ]?(?:context|sequence)[_ ]?length.*?(\d+)", re.IGNORECASE),
    re.compile(r"only (\d+) is supported", re.IGNORECASE),
    re.compile(r"prompt is .*? long while only (\d+) is supported", re.IGNORECASE),
)


def parse_context_window_from_error(body: str) -> int | None:
    if not body:
        return None
    for pattern in _CONTEXT_LIMIT_PATTERNS:
        match = pattern.search(body)
        if match:
            try:
                parsed = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    error_text = str(payload.get("error", ""))
    for pattern in _CONTEXT_LIMIT_PATTERNS:
        match = pattern.search(error_text)
        if match:
            try:
                parsed = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
    return None


def is_context_limit_error(exc: BaseException) -> bool:
    if not isinstance(exc, NimClientError) or exc.error_type != "http_error":
        return False
    status_code = exc.details.get("status_code")
    if status_code not in (400, 413, 500):
        return False
    body = str(exc.details.get("body", ""))
    if parse_context_window_from_error(body) is not None:
        return True
    lowered = body.lower()
    return (
        "context length" in lowered
        or "maximum context" in lowered
        or "only" in lowered
        and "is supported" in lowered
        and "prompt is" in lowered
    )


def record_learned_model_context(model_id: str, context_tokens: int) -> dict[str, Any]:
    settings = load_settings()
    metadata = dict(settings.nim_model_metadata.get(model_id, {}))
    learned = int(context_tokens)
    existing = metadata.get("context_length")
    if existing is not None:
        try:
            learned = min(learned, int(existing))
        except (TypeError, ValueError):
            pass
    metadata["context_length"] = learned
    metadata["context_source"] = "learned_from_api_error"
    settings.nim_model_metadata[model_id] = metadata
    save_settings(settings)
    return metadata
