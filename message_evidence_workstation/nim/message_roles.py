"""Chat message role compatibility for OpenAI-compatible providers."""

from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger(__name__)

from message_evidence_workstation.config.settings import load_settings, save_settings

MESSAGE_LAYOUT_SYSTEM_USER = "system_user"
MESSAGE_LAYOUT_FOLDED_USER = "folded_user"


def messages_include_system_role(messages: list[dict[str, str]]) -> bool:
    return any(str(message.get("role")) == "system" for message in messages)


def fold_system_into_user(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    system_parts = [str(message.get("content", "")) for message in messages if message.get("role") == "system"]
    if not system_parts:
        return list(messages)
    system_text = "\n\n".join(part for part in system_parts if part).strip()
    folded: list[dict[str, str]] = []
    user_parts: list[str] = []
    for message in messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        if role == "system":
            continue
        if role == "user":
            user_parts.append(content)
            continue
        folded.append({"role": role, "content": content})
    user_body = "\n\n".join(part for part in user_parts if part).strip()
    if system_text and user_body:
        merged_user = f"{system_text}\n\n---\n\n{user_body}"
    else:
        merged_user = system_text or user_body
    return [{"role": "user", "content": merged_user}, *folded]


def build_whole_transcript_cache_messages(
    system_prompt: str,
    *,
    transcript_context: str,
    user_query_content: str,
    include_system_role: bool = True,
) -> list[dict[str, str]]:
    """Place stable transcript context before the per-request question for prefix caching."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcript_context},
        {"role": "user", "content": user_query_content},
    ]
    if include_system_role:
        return messages
    return fold_system_into_user(messages)


def build_chat_messages(
    system_prompt: str,
    user_content: str,
    *,
    include_system_role: bool,
) -> list[dict[str, str]]:
    if include_system_role:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    return fold_system_into_user(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    )


def is_system_role_unsupported_error(exc: BaseException) -> bool:
    error_type = getattr(exc, "error_type", None)
    details = getattr(exc, "details", None)
    if error_type != "http_error" or not isinstance(details, dict):
        return False
    if details.get("status_code") not in (400, 422, 500):
        return False
    body = str(details.get("body", ""))
    lowered = body.lower()
    if "system role not supported" in lowered:
        return True
    if "system message" in lowered and "not support" in lowered:
        return True
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        _log.warning(
            "Non-JSON body in system-role error detection: %s",
            exc,
        )
        return False
    if not isinstance(payload, dict):
        return False
    error_text = str(payload.get("error", "")).lower()
    return "system role not supported" in error_text or (
        "system message" in error_text and "not support" in error_text
    )


def model_supports_system_role(model_id: str) -> bool | None:
    if not model_id:
        return None
    metadata = load_settings().model_metadata.get(model_id, {})
    if "supports_system_role" not in metadata:
        return None
    return bool(metadata["supports_system_role"])


def record_system_role_support(model_id: str, supports_system_role: bool) -> dict[str, Any]:
    settings = load_settings()
    metadata = dict(settings.model_metadata.get(model_id, {}))
    metadata["supports_system_role"] = supports_system_role
    metadata["message_role_source"] = "learned_from_api_error"
    settings.model_metadata[model_id] = metadata
    save_settings(settings)
    return metadata


def prepare_chat_messages(
    model_id: str,
    messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]], str]:
    preference = model_supports_system_role(model_id)
    if preference is False and messages_include_system_role(messages):
        return fold_system_into_user(messages), MESSAGE_LAYOUT_FOLDED_USER
    return list(messages), MESSAGE_LAYOUT_SYSTEM_USER
