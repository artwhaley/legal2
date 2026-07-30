"""Exact generated provider-payload accounting and cost estimation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from server.config import OperationConfig


@lru_cache(maxsize=16)
def _load_local_tokenizer(name: str, revision: str):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(
        name,
        revision=revision or None,
        local_files_only=True,
    )


@dataclass(frozen=True, slots=True)
class AccountingResult:
    input_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    context_window_tokens: int
    mode: str
    encoding_or_revision: str
    target_input_tokens: int | None

    @property
    def fits(self) -> bool:
        context_fits = self.input_tokens + self.reserved_output_tokens + self.safety_margin_tokens <= self.context_window_tokens
        target_fits = self.target_input_tokens is None or self.input_tokens <= self.target_input_tokens
        return context_fits and target_fits


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def build_provider_payload(config: OperationConfig, *, operation: str, messages: list[dict[str, str]], user_object: dict[str, Any], response_schema: dict[str, Any] | None) -> dict[str, Any]:
    if len(messages) != 2 or messages[0].get("role") != "system" or messages[1].get("role") != "user":
        raise ValueError("provider calls require exactly one system and one user message")
    if messages[0].get("content") != config.system_prompt:
        raise ValueError("system message must be the complete active prompt")
    if messages[1].get("content") != canonical_json(user_object):
        raise ValueError("user message must be canonical generated JSON")
    payload: dict[str, Any] = {"model": config.model_id, "messages": messages, "temperature": config.temperature, "max_tokens": config.max_output_tokens}
    if config.structured_output_mode == "json_schema":
        if response_schema is None:
            raise ValueError("json_schema mode requires a response schema")
        payload["response_format"] = {"type": "json_schema", "json_schema": {"name": operation, "strict": True, "schema": response_schema}}
    elif config.structured_output_mode == "json_object":
        payload["response_format"] = {"type": "json_object"}
    elif config.structured_output_mode != "prompt_only":
        raise ValueError("unsupported structured output mode")
    return payload


def _deepseek_v4_prompt(payload: dict[str, Any]) -> str:
    """Render the server's two-message call with DeepSeek's official V4 format."""
    messages = payload["messages"]
    if (
        len(messages) != 2
        or messages[0].get("role") != "system"
        or messages[1].get("role") != "user"
    ):
        raise ValueError(
            "DeepSeek V4 accounting requires exactly one system and one user message"
        )
    system_content = str(messages[0].get("content", ""))
    response_format = payload.get("response_format")
    if response_format is not None:
        system_content += (
            "\n\n## Response Format:\n\n"
            "You MUST strictly adhere to the following schema to reply:\n"
            + json.dumps(response_format, ensure_ascii=False)
        )
    return (
        "<｜begin▁of▁sentence｜>"
        + system_content
        + "<｜User｜>"
        + str(messages[1].get("content", ""))
        + "<｜Assistant｜><think>"
    )


def count_provider_payload(payload: dict[str, Any], config: OperationConfig) -> AccountingResult:
    serialized = canonical_json(payload)
    if config.accounting_mode == "serialized_payload_tiktoken":
        import tiktoken
        try:
            encoding = tiktoken.get_encoding(config.encoding_name)
        except Exception as exc:
            raise ValueError(f"configured tokenizer {config.encoding_name!r} cannot be loaded") from exc
        count = len(encoding.encode(serialized, disallowed_special=()))
        label = config.encoding_name
    elif config.accounting_mode == "huggingface_chat_template":
        if not config.tokenizer_name:
            raise ValueError("tokenizer_name is required for huggingface_chat_template")
        tokenizer = _load_local_tokenizer(
            config.tokenizer_name, config.tokenizer_revision
        )
        messages = payload["messages"]
        token_ids = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=False,
        )
        if not isinstance(token_ids, list):
            raise ValueError(
                "configured Hugging Face chat template did not return token IDs"
            )
        count = len(token_ids)
        response_format = payload.get("response_format")
        if response_format is not None:
            count += len(tokenizer.encode(canonical_json(response_format), add_special_tokens=False))
        count += config.provider_wrapper_tokens
        label = config.tokenizer_revision or config.tokenizer_name
    elif config.accounting_mode == "deepseek_v4_official":
        if not config.tokenizer_name:
            raise ValueError("tokenizer_name is required for deepseek_v4_official")
        tokenizer = _load_local_tokenizer(
            config.tokenizer_name, config.tokenizer_revision
        )
        count = len(
            tokenizer.encode(
                _deepseek_v4_prompt(payload),
                add_special_tokens=False,
            )
        )
        count += config.provider_wrapper_tokens
        label = config.tokenizer_revision or config.tokenizer_name
    else:
        raise ValueError(f"unsupported accounting mode {config.accounting_mode!r}")
    return AccountingResult(count, config.max_output_tokens, config.safety_margin_tokens, config.context_window_tokens, config.accounting_mode, label, config.target_input_tokens)


def count_text_tokens(text: str, config: OperationConfig) -> int:
    """Estimate output text with the operation's configured tokenizer only."""
    if config.accounting_mode == "serialized_payload_tiktoken":
        import tiktoken
        try:
            encoding = tiktoken.get_encoding(config.encoding_name)
        except Exception as exc:
            raise ValueError(f"configured tokenizer {config.encoding_name!r} cannot be loaded") from exc
        return len(encoding.encode(text, disallowed_special=()))
    if config.accounting_mode in {
        "huggingface_chat_template",
        "deepseek_v4_official",
    }:
        tokenizer = _load_local_tokenizer(
            config.tokenizer_name, config.tokenizer_revision
        )
        return len(tokenizer.encode(text, add_special_tokens=False))
    raise ValueError(f"unsupported accounting mode {config.accounting_mode!r}")


def count_texts_tokens(texts: list[str], config: OperationConfig) -> list[int]:
    """Count independent texts efficiently with the configured native tokenizer."""
    if config.accounting_mode == "serialized_payload_tiktoken":
        import tiktoken

        try:
            encoding = tiktoken.get_encoding(config.encoding_name)
        except Exception as exc:
            raise ValueError(
                f"configured tokenizer {config.encoding_name!r} cannot be loaded"
            ) from exc
        return [
            len(encoding.encode(text, disallowed_special=())) for text in texts
        ]
    if config.accounting_mode in {
        "huggingface_chat_template",
        "deepseek_v4_official",
    }:
        tokenizer = _load_local_tokenizer(
            config.tokenizer_name, config.tokenizer_revision
        )
        counts: list[int] = []
        for start in range(0, len(texts), 1024):
            encoded = tokenizer(
                texts[start : start + 1024],
                add_special_tokens=False,
                padding=False,
                truncation=False,
                return_attention_mask=False,
                return_token_type_ids=False,
            )
            input_ids = encoded.get("input_ids")
            if not isinstance(input_ids, list):
                raise ValueError(
                    "configured Hugging Face tokenizer did not return batched token IDs"
                )
            counts.extend(len(item) for item in input_ids)
        return counts
    raise ValueError(f"unsupported accounting mode {config.accounting_mode!r}")


def estimate_cost(config: OperationConfig, input_tokens: int, output_tokens: int) -> float | None:
    if config.input_price_per_million is None or config.output_price_per_million is None:
        return None
    return input_tokens * config.input_price_per_million / 1_000_000 + output_tokens * config.output_price_per_million / 1_000_000
