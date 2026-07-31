"""Result-preserving synthesis inspection and source-citation assembly.

This module is deliberately separate from extraction validation. Extraction
proves source identity; this module annotates model synthesis without making
its structure a publication gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from server.contracts import (
    ConversationalResult,
    LedgerSynthesisOutput,
    PublicResultItem,
    SynthesisValidation,
    UnclassifiedEvidence,
    UnverifiedModelStatement,
    WarningRecord,
)
from server.evidence_ledger import EvidenceRangeRecord


_JSON_FENCE = re.compile(r"^```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```[ \t]*$", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SynthesisInspection:
    raw_content: str | None
    normalized_content: str | None
    normalization_records: tuple[str, ...]
    parse_status: str
    overview: str | None
    results: tuple[dict[str, Any], ...]
    uncertainties: tuple[str, ...]
    warnings: tuple[WarningRecord, ...]


def _warning(code: str, **details: Any) -> WarningRecord:
    return WarningRecord(code=code, details=details)


def _content_is_machine_unusable(content: str | None) -> bool:
    if not isinstance(content, str) or not content.strip():
        return True
    return not any(character.isalnum() for character in content)


def _normalize_json_candidate(content: str) -> tuple[str, tuple[str, ...]]:
    candidate = content.strip()
    records: list[str] = []
    if candidate != content:
        records.append("outer_whitespace_trimmed")
    fenced = _JSON_FENCE.fullmatch(candidate)
    if fenced is not None:
        candidate = fenced.group("body").strip()
        records.append("one_markdown_json_fence_removed")
        return candidate, tuple(records)

    first = candidate.find("{")
    last = candidate.rfind("}")
    if first > 0 and last > first and not candidate[:first].strip().startswith("```"):
        prefix = candidate[:first].strip()
        suffix = candidate[last + 1 :].strip()
        if prefix and suffix and "{" not in prefix and "}" not in prefix and "{" not in suffix and "}" not in suffix:
            candidate = candidate[first : last + 1]
            records.append("explanatory_prefix_suffix_removed")
    return candidate, tuple(records)


def _safe_json_object(candidate: str) -> dict[str, Any] | None:
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _salvage_results(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list):
        return ()
    salvaged: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        statement = item.get("statement")
        range_ids = item.get("range_ids")
        if not isinstance(statement, str) or not statement.strip() or not isinstance(range_ids, list):
            continue
        ids = [value for value in range_ids if isinstance(value, str) and value.strip()]
        uncertainty = item.get("uncertainty")
        if uncertainty is not None and not isinstance(uncertainty, str):
            uncertainty = None
        probability = item.get("probability")
        salvaged.append({
            "probability": probability if isinstance(probability, str) else None,
            "statement": statement,
            "range_ids": ids,
            "uncertainty": uncertainty,
        })
    return tuple(salvaged)


def inspect_synthesis_content(content: str | None) -> SynthesisInspection:
    """Parse exact synthesis or salvage readable known components.

    The raw provider content is never rewritten or returned from this helper;
    the normalization candidate is only an inspection input.
    """
    if _content_is_machine_unusable(content):
        return SynthesisInspection(
            raw_content=content,
            normalized_content=None,
            normalization_records=(),
            parse_status="unavailable",
            overview=None,
            results=(),
            uncertainties=(),
            warnings=(_warning("SYNTHESIS_UNAVAILABLE", reason="content_empty_or_unusable"),),
        )
    assert isinstance(content, str)
    candidate, normalizations = _normalize_json_candidate(content)
    raw_object = _safe_json_object(candidate)
    if raw_object is None:
        return SynthesisInspection(
            raw_content=content,
            normalized_content=candidate,
            normalization_records=normalizations,
            parse_status="unparseable",
            overview=None,
            results=(),
            uncertainties=(),
            warnings=(_warning("SYNTHESIS_OUTPUT_NONCONFORMANT", reason="not_one_json_object"),),
        )
    try:
        parsed = LedgerSynthesisOutput.model_validate(raw_object)
    except ValidationError:
        overview = raw_object.get("overview") if isinstance(raw_object.get("overview"), str) and raw_object.get("overview").strip() else None
        uncertainties = tuple(value for value in raw_object.get("uncertainties", []) if isinstance(value, str) and value.strip()) if isinstance(raw_object.get("uncertainties"), list) else ()
        warnings = [_warning("SYNTHESIS_OUTPUT_NONCONFORMANT", reason="known_object_fields_do_not_match_schema")]
        if normalizations:
            warnings.append(_warning("SYNTHESIS_OUTPUT_NONCONFORMANT", reason="deterministic_normalization_applied", normalization_count=len(normalizations)))
        return SynthesisInspection(
            raw_content=content,
            normalized_content=candidate,
            normalization_records=normalizations,
            parse_status="warnings",
            overview=overview,
            results=_salvage_results(raw_object.get("results")),
            uncertainties=uncertainties,
            warnings=tuple(warnings),
        )
    warnings = ()
    if normalizations:
        warnings = (_warning("SYNTHESIS_OUTPUT_NONCONFORMANT", reason="deterministic_normalization_applied", normalization_count=len(normalizations)),)
    return SynthesisInspection(
        raw_content=content,
        normalized_content=candidate,
        normalization_records=normalizations,
        parse_status="conformant_normalized" if warnings else "conformant",
        overview=parsed.overview,
        results=tuple(item.model_dump() for item in parsed.results),
        uncertainties=tuple(parsed.uncertainties),
        warnings=warnings,
    )


def _record_mapping(record: EvidenceRangeRecord | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(record, EvidenceRangeRecord):
        return {
            "range_id": record.range_id,
            "window_id": record.window_id,
            "source_range_index": record.source_range_index,
            "thread_id": record.thread_id,
            "start_message_id": record.start_message_id,
            "end_message_id": record.end_message_id,
            "summary": record.summary,
            "relevance": record.relevance,
            "normalizations": list(record.normalizations),
            "uncertainties": list(record.uncertainties),
            "warnings": list(record.warnings),
        }
    return record


def _warning_list(items: Sequence[WarningRecord]) -> list[dict[str, Any]]:
    return [item.model_dump() for item in items]


def _public_ledger(records: Sequence[EvidenceRangeRecord | Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(_record_mapping(record)) for record in records]


def _citation_result(
    raw: Mapping[str, Any],
    canonical_ids: set[str],
) -> tuple[dict[str, Any], tuple[WarningRecord, ...]]:
    statement = raw.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        statement = "[unusable model result statement]"
    reported = raw.get("range_ids") if isinstance(raw.get("range_ids"), list) else []
    reported_ids = [value for value in reported if isinstance(value, str) and value.strip()]
    warnings: list[WarningRecord] = []
    if len(reported_ids) != len(set(reported_ids)):
        warnings.append(_warning("DUPLICATE_CITATION", duplicate_count=len(reported_ids) - len(set(reported_ids))))
    verified: list[str] = []
    unverified: list[str] = []
    seen: set[str] = set()
    for range_id in reported_ids:
        if range_id in seen:
            continue
        seen.add(range_id)
        if range_id in canonical_ids:
            verified.append(range_id)
        else:
            unverified.append(range_id)
            warnings.append(_warning("UNKNOWN_RANGE_ID", range_id=range_id))
    if verified and unverified:
        citation_status = "partial"
        warnings.append(_warning("CITATION_PARTIALLY_VERIFIED", verified_count=len(verified), unverified_count=len(unverified)))
    elif verified:
        citation_status = "verified"
    else:
        citation_status = "unverified"
        warnings.append(_warning("CITATION_UNVERIFIED", reported_count=len(reported_ids)))
    probability = raw.get("probability") if raw.get("probability") in {"high_probability", "lower_probability"} else None
    classification = "model_classified" if probability is not None else "unclassified"
    if probability is None:
        warnings.append(_warning("UNKNOWN_PROBABILITY", reported_type=type(raw.get("probability")).__name__))
        warnings.append(_warning("SYNTHESIS_RESULT_UNCLASSIFIED"))
    item = {
        "probability": probability,
        "classification_status": classification,
        "statement": statement,
        "reported_range_ids": reported_ids,
        "verified_range_ids": verified,
        "unverified_range_ids": unverified,
        "citation_status": citation_status,
        "uncertainty": raw.get("uncertainty") if isinstance(raw.get("uncertainty"), str) else None,
        "warnings": _warning_list(warnings),
    }
    return item, tuple(warnings)


def _status(
    *,
    evidence_validation: Mapping[str, Any],
    synthesis_validation_status: str,
    warnings: Sequence[WarningRecord],
    unclassified: Sequence[Any],
    unverified: Sequence[Any],
) -> str:
    if (
        evidence_validation.get("status") == "partial"
        or int(evidence_validation.get("unavailable_window_count", 0)) > 0
        or synthesis_validation_status == "unavailable"
    ):
        return "partial"
    if warnings or unclassified or unverified or synthesis_validation_status != "conformant":
        return "complete_with_warnings"
    return "complete"


def assemble_synthesis_result(
    content: str | None,
    *,
    records: Sequence[EvidenceRangeRecord | Mapping[str, Any]],
    evidence_validation: Mapping[str, Any],
    strategy: str,
    message_count: int,
    planned_window_count: int,
    usable_window_count: int,
    unavailable_window_count: int,
    retrieval_diagnostics: Mapping[str, Any],
    ledger_processing: Mapping[str, Any],
    usage: Mapping[str, Any],
) -> tuple[dict[str, Any], SynthesisInspection]:
    inspection = inspect_synthesis_content(content)
    canonical_records = [_record_mapping(record) for record in records]
    canonical_ids = {str(record["range_id"]) for record in canonical_records}
    result_items: list[dict[str, Any]] = []
    unverified_items: list[dict[str, Any]] = []
    all_warnings = list(inspection.warnings)
    for raw_warning in evidence_validation.get("warnings", []):
        try:
            all_warnings.append(WarningRecord.model_validate(raw_warning))
        except Exception:
            all_warnings.append(_warning("WINDOW_OUTPUT_UNUSABLE", reason="unstructured_extraction_warning"))
    cited_ids: set[str] = set()
    for raw_result in inspection.results:
        item, item_warnings = _citation_result(raw_result, canonical_ids)
        all_warnings.extend(item_warnings)
        cited_ids.update(item["verified_range_ids"])
        if item["verified_range_ids"]:
            result_items.append(item)
        else:
            unverified_items.append({
                "statement": item["statement"],
                "reported_range_ids": item["reported_range_ids"],
                "probability": item["probability"],
                "uncertainty": item["uncertainty"],
                "warnings": item["warnings"],
            })
    result_items.sort(key=lambda item: 0 if item["probability"] == "high_probability" else 1 if item["probability"] == "lower_probability" else 2)
    unclassified: list[dict[str, Any]] = []
    for record in canonical_records:
        range_id = str(record["range_id"])
        if range_id not in cited_ids:
            unclassified.append({
                "range_id": range_id,
                "summary": record.get("summary"),
                "relevance": record.get("relevance"),
                "reason": "not_referenced_by_synthesis",
            })
            all_warnings.append(_warning("SYNTHESIS_OMITTED_LEDGER_RANGE", range_id=range_id))

    if inspection.parse_status in {"conformant", "conformant_normalized"}:
        synthesis_status = "conformant" if not inspection.normalization_records else "warnings"
    elif inspection.parse_status == "unavailable":
        synthesis_status = "unavailable"
    elif inspection.parse_status == "unparseable":
        synthesis_status = "unparseable"
    else:
        synthesis_status = "warnings"
    if synthesis_status == "conformant" and (all_warnings or unclassified or unverified_items):
        synthesis_status = "warnings"
    status = _status(
        evidence_validation=evidence_validation,
        synthesis_validation_status=synthesis_status,
        warnings=all_warnings,
        unclassified=unclassified,
        unverified=unverified_items,
    )
    if inspection.parse_status in {"conformant", "conformant_normalized"} and inspection.overview is not None:
        answer_source = "structured_synthesis"
    elif inspection.parse_status == "unavailable":
        answer_source = "synthesis_unavailable"
    else:
        answer_source = "raw_synthesis_output"

    normalized_evidence = dict(evidence_validation)
    normalized_evidence.setdefault("planned_window_count", planned_window_count)
    normalized_evidence.setdefault("usable_window_count", usable_window_count)
    normalized_evidence.setdefault("unavailable_window_count", unavailable_window_count)
    normalized_evidence.setdefault("unavailable_windows", [])
    normalized_evidence.setdefault("rejected_ranges", [])
    normalized_evidence.setdefault("rejected_range_count", len(normalized_evidence["rejected_ranges"]))
    normalized_evidence.setdefault("accepted_range_count", len(canonical_records))
    normalized_evidence.setdefault("normalized_range_count", 0)
    normalized_evidence["status"] = "partial" if normalized_evidence.get("rejected_range_count", 0) or normalized_evidence.get("unavailable_window_count", 0) else "complete"
    coverage = {
        "message_count": message_count,
        "planned_window_count": planned_window_count,
        "usable_window_count": usable_window_count,
        "unavailable_window_count": unavailable_window_count,
        "evidence_range_count": len(canonical_records),
    }
    result = {
        "completion_status": status,
        "answer_source": answer_source,
        "overview": inspection.overview if answer_source == "structured_synthesis" else None,
        "raw_answer": inspection.raw_content if answer_source == "raw_synthesis_output" else None,
        "results": result_items,
        "unclassified_evidence": unclassified,
        "unverified_model_statements": unverified_items,
        "evidence_ledger": _public_ledger(records),
        "evidence_validation": normalized_evidence,
        "synthesis_validation": {
            "status": synthesis_status,
            "raw_output_preserved": bool(inspection.raw_content) and (
                answer_source == "raw_synthesis_output" or bool(inspection.normalization_records)
            ),
            "warnings": _warning_list(all_warnings),
        },
        "coverage": coverage,
        "retrieval_diagnostics": dict(retrieval_diagnostics),
        "ledger_processing": dict(ledger_processing),
        "usage": dict(usage),
        "uncertainties": list(inspection.uncertainties),
        "strategy": strategy,
    }
    ConversationalResult.model_validate(result)
    return result, inspection


__all__ = ["SynthesisInspection", "assemble_synthesis_result", "inspect_synthesis_content"]
