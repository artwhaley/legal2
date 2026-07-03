"""Keyword expansion via NIM."""

from __future__ import annotations

import json
import re
import sqlite3

from message_evidence_workstation.llm.types import ModelTaskRole
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import RUN_TYPE_KEYWORD_EXPANSION

# T25: internal task role for expand_keywords (see llm.task_roles.RUN_TYPE_TO_TASK_ROLE).
TASK_ROLE = ModelTaskRole.SEARCH_EXPANSION

KEYWORD_EXPANSION_MAX_TOKENS = 1024

_TERMS_ARRAY_RE = re.compile(r'"terms"\s*:\s*\[', re.IGNORECASE)
_QUOTED_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _clean_term_list(raw_terms: list[object], max_terms: int = 20) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        term = str(raw).strip()
        if not term:
            continue
        if term.startswith("{") and "terms" in term:
            for nested in parse_expansion_terms(term, max_terms=max_terms):
                key = nested.casefold()
                if key not in seen:
                    seen.add(key)
                    cleaned.append(nested)
            continue
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            cleaned.append(term)
        if len(cleaned) >= max_terms:
            break
    return cleaned


def _terms_from_quoted_strings(content: str, max_terms: int = 20) -> list[str]:
    match = _TERMS_ARRAY_RE.search(content)
    if not match:
        return []
    tail = content[match.end() :]
    terms: list[str] = []
    for quoted in _QUOTED_STRING_RE.finditer(tail):
        term = quoted.group(1).strip()
        if term:
            terms.append(term)
        if len(terms) >= max_terms:
            break
    return _clean_term_list(terms, max_terms=max_terms)


def parse_expansion_terms(
    content: str,
    logger: ProcessLogger | None = None,
    max_terms: int = 20,
) -> list[str]:
    content = content.strip()
    if not content:
        return []
    failures: list[str] = []

    try:
        payload = json.loads(content)
        if isinstance(payload, dict) and isinstance(payload.get("terms"), list):
            return _clean_term_list(payload["terms"], max_terms=max_terms)
    except json.JSONDecodeError as exc:
        failures.append(f"json_root: {exc}")

    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(content[start : end + 1])
            if isinstance(payload, dict) and isinstance(payload.get("terms"), list):
                if failures and logger is not None:
                    logger.warning(
                        component="search.keyword_expansion",
                        operation="parse_fallback",
                        message="Bracket extraction parse succeeded after root JSON failed",
                        details={
                            "failed_strategies": list(failures),
                            "winning_strategy": "bracket_extraction",
                            "content_preview": content[:200],
                        },
                    )
                return _clean_term_list(payload["terms"], max_terms=max_terms)
        except json.JSONDecodeError as exc:
            failures.append(f"bracket_extraction: {exc}")

    quoted = _terms_from_quoted_strings(content, max_terms=max_terms)
    if quoted:
        if failures and logger is not None:
            logger.warning(
                component="search.keyword_expansion",
                operation="parse_fallback",
                message="Quoted-string parse succeeded after earlier strategies failed",
                details={
                    "failed_strategies": list(failures),
                    "winning_strategy": "quoted_strings",
                    "content_preview": content[:200],
                },
            )
        return quoted

    terms = []
    for line in content.splitlines():
        cleaned = re.sub(r"^[-*]\s*", "", line.strip())
        if cleaned:
            terms.append(cleaned)
    result = _clean_term_list(terms, max_terms=max_terms)
    if not result and logger is not None:
        logger.warning(
            component="search.keyword_expansion",
            operation="parse_failed",
            message="All keyword expansion parse strategies failed; returning empty",
            details={
                "failed_strategies": list(failures),
                "content_length": len(content),
                "content_preview": content[:200],
            },
        )
    return result


def expand_keywords(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter,
    query: str,
    *,
    dataset_id: int | None = None,
    max_expansion_terms: int = 20,
) -> list[str]:
    result = run_nim_chat(
        conn,
        logger,
        router,
        run_type=RUN_TYPE_KEYWORD_EXPANSION,
        user_content=query,
        dataset_id=dataset_id,
        max_tokens=KEYWORD_EXPANSION_MAX_TOKENS,
    )
    terms = parse_expansion_terms(result.content, logger=logger, max_terms=max_expansion_terms)
    if len(terms) >= max_expansion_terms and len(result.content) > 0:
        logger.warning(
            component="search.keyword_expansion",
            operation="terms_capped",
            message="Keyword expansion terms capped at limit",
            details={
                "max_expansion_terms": max_expansion_terms,
                "returned_count": len(terms),
                "raw_length": len(result.content),
            },
            dataset_id=dataset_id,
        )
    logger.info(
        component="search.keyword_expansion",
        operation="terms_parsed",
        message="Parsed keyword expansion terms",
        details={"query": query, "terms": terms, "raw_length": len(result.content)},
        dataset_id=dataset_id,
    )
    return terms
