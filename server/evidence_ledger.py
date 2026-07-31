"""Deterministic evidence-ledger construction and range-granular validation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from server.contracts import MAX_ID_LENGTH, MAX_QUESTION_LENGTH


class LedgerError(ValueError):
    code = "LEDGER_INTERNAL_INTEGRITY_FAILED"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details = dict(details or {})


class LedgerBudgetExceeded(LedgerError):
    code = "LEDGER_BUDGET_EXCEEDED"


class NoUsableWindowOutput(LedgerError):
    code = "NO_USABLE_WINDOW_OUTPUT"


class NoUsableResult(LedgerError):
    code = "NO_USABLE_RESULT"


class UnsplitableMessage(LedgerError):
    code = "UNSPLITTABLE_MESSAGE"


@dataclass(frozen=True, slots=True)
class RangeNormalizationRecord:
    code: str
    window_id: str
    range_index: int
    original_start_message_id: str
    original_end_message_id: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "window_id": self.window_id,
            "range_index": self.range_index,
            "original_start_message_id": self.original_start_message_id,
            "original_end_message_id": self.original_end_message_id,
        }


@dataclass(frozen=True, slots=True)
class RejectedRange:
    window_id: str
    range_index: int
    code: str
    message: str
    declared_thread_id: str | None
    start_message_id: str | None
    end_message_id: str | None

    def model_dump(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "range_index": self.range_index,
            "code": self.code,
            "message": self.message,
            "declared_thread_id": self.declared_thread_id,
            "start_message_id": self.start_message_id,
            "end_message_id": self.end_message_id,
        }


@dataclass(frozen=True, slots=True)
class ValidatedRange:
    source_range_index: int
    thread_id: str
    start_message_id: str
    end_message_id: str
    messages: tuple[Mapping[str, Any], ...]
    summary: str | None
    relevance: str | None
    normalizations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedWindowEvidence:
    window_id: str
    accepted_ranges: tuple[ValidatedRange, ...]
    rejected_ranges: tuple[RejectedRange, ...]
    uncertainties: tuple[str, ...]
    normalizations: tuple[RangeNormalizationRecord, ...]
    warnings: tuple[dict[str, Any], ...]

    @property
    def status(self) -> str:
        return "partial" if self.rejected_ranges else "complete"

    @property
    def accepted_range_count(self) -> int:
        return len(self.accepted_ranges)

    @property
    def rejected_range_count(self) -> int:
        return len(self.rejected_ranges)

    @property
    def normalized_range_count(self) -> int:
        return len(self.normalizations)


@dataclass(frozen=True, slots=True)
class EvidenceRangeRecord:
    range_id: str
    window_id: str
    source_range_index: int
    thread_id: str
    start_message_id: str
    end_message_id: str
    messages: tuple[Mapping[str, Any], ...]
    summary: str | None
    relevance: str | None
    normalizations: tuple[str, ...]
    uncertainties: tuple[str, ...]
    warnings: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class WindowLedgerInput:
    window_id: str
    messages: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    window_id: str
    first_message_id: str
    last_message_id: str
    message_count: int
    evidence_range_count: int
    uncertainties: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LedgerBuild:
    records: tuple[EvidenceRangeRecord, ...]
    coverage: tuple[CoverageReport, ...]
    validation: dict[str, Any]


def _message_maps(messages: Sequence[Mapping[str, Any]]) -> tuple[dict[str, int], dict[str, str]]:
    by_id: dict[str, int] = {}
    by_thread: dict[str, str] = {}
    for index, message in enumerate(messages):
        message_id = str(message.get("message_id", ""))
        thread_id = str(message.get("thread_id", ""))
        if not message_id or not thread_id or message_id in by_id:
            raise LedgerError("window messages must have unique nonblank IDs")
        by_id[message_id] = index
        by_thread[message_id] = thread_id
    return by_id, by_thread


def _rejected(window: WindowLedgerInput, index: int, code: str, message: str, raw: Any) -> RejectedRange:
    if not isinstance(raw, Mapping):
        declared = start = end = None
    else:
        declared = raw.get("thread_id") if isinstance(raw.get("thread_id"), str) else None
        start = raw.get("start_message_id") if isinstance(raw.get("start_message_id"), str) else None
        end = raw.get("end_message_id") if isinstance(raw.get("end_message_id"), str) else None
    return RejectedRange(window.window_id, index, code, message, declared, start, end)


def salvage_window_evidence(window: WindowLedgerInput, raw: Mapping[str, Any]) -> ValidatedWindowEvidence:
    """Salvage a usable extraction envelope and validate each range independently."""
    if not isinstance(raw, Mapping) or raw.get("window_id") != window.window_id or not isinstance(raw.get("evidence_ranges"), list):
        raise LedgerError("window evidence output is machine-unusable", details={"reason": "WINDOW_OUTPUT_UNUSABLE", "window_id": window.window_id})
    by_id, by_thread = _message_maps(window.messages)
    accepted: list[ValidatedRange] = []
    rejected: list[RejectedRange] = []
    normalizations: list[RangeNormalizationRecord] = []
    warnings: list[dict[str, Any]] = []
    extra_fields = sorted(set(raw) - {"window_id", "evidence_ranges", "uncertainties"})
    if extra_fields:
        warnings.extend({"code": "WINDOW_OUTPUT_UNUSABLE", "details": {"reason": "extra_top_level_fields", "field_count": len(extra_fields)}} for _ in [0])
    raw_uncertainties = raw.get("uncertainties", [])
    uncertainties: list[str] = []
    if isinstance(raw_uncertainties, list):
        for value in raw_uncertainties:
            if isinstance(value, str) and value.strip():
                uncertainties.append(value)
            else:
                warnings.append({"code": "WINDOW_OUTPUT_UNUSABLE", "details": {"reason": "malformed_uncertainty"}})
    elif raw_uncertainties is not None:
        warnings.append({"code": "WINDOW_OUTPUT_UNUSABLE", "details": {"reason": "malformed_uncertainties_field"}})
    accepted_pairs: set[tuple[str, str]] = set()
    for range_index, raw_range in enumerate(raw["evidence_ranges"]):
        if not isinstance(raw_range, Mapping):
            rejected.append(_rejected(window, range_index, "RANGE_NOT_OBJECT", "range is not an object", raw_range))
            continue
        start = raw_range.get("start_message_id") if isinstance(raw_range.get("start_message_id"), str) and raw_range.get("start_message_id").strip() else None
        end = raw_range.get("end_message_id") if isinstance(raw_range.get("end_message_id"), str) and raw_range.get("end_message_id").strip() else None
        if start is None or end is None:
            rejected.append(_rejected(window, range_index, "RANGE_SCHEMA_INVALID", "range has no recoverable endpoints", raw_range))
            continue
        if start not in by_id:
            rejected.append(_rejected(window, range_index, "UNKNOWN_START_MESSAGE_ID", "start message ID is unknown", raw_range))
            continue
        if end not in by_id:
            rejected.append(_rejected(window, range_index, "UNKNOWN_END_MESSAGE_ID", "end message ID is unknown", raw_range))
            continue
        authoritative_thread = by_thread[start]
        if authoritative_thread != by_thread[end]:
            rejected.append(_rejected(window, range_index, "CROSS_THREAD_RANGE", "range endpoints belong to different threads", raw_range))
            continue
        declared_thread = raw_range.get("thread_id") if isinstance(raw_range.get("thread_id"), str) else None
        if declared_thread != authoritative_thread:
            warnings.append({"code": "THREAD_ID_CORRECTED", "details": {"window_id": window.window_id, "range_index": range_index}})
        start_index, end_index = by_id[start], by_id[end]
        normalized = False
        normalization_record: RangeNormalizationRecord | None = None
        if start_index > end_index:
            interval = window.messages[end_index : start_index + 1]
            if any(str(message.get("thread_id", "")) != authoritative_thread for message in interval):
                rejected.append(_rejected(window, range_index, "NONCONTIGUOUS_THREAD_RANGE", "range interval crosses a thread boundary", raw_range))
                continue
            normalization_record = RangeNormalizationRecord("ENDPOINT_ORDER_SWAPPED", window.window_id, range_index, start, end)
            warnings.append({"code": "RANGE_ENDPOINTS_REVERSED", "details": {"window_id": window.window_id, "range_index": range_index}})
            start, end = end, start
            start_index, end_index = end_index, start_index
            normalized = True
        interval = window.messages[start_index : end_index + 1]
        if any(str(message.get("thread_id", "")) != authoritative_thread for message in interval):
            rejected.append(_rejected(window, range_index, "NONCONTIGUOUS_THREAD_RANGE", "range interval crosses a thread boundary", raw_range))
            continue
        pair = (start, end)
        if pair in accepted_pairs:
            rejected.append(_rejected(window, range_index, "DUPLICATE_RANGE", "normalized endpoint pair was already accepted", raw_range))
            continue
        accepted_pairs.add(pair)
        if normalization_record is not None:
            normalizations.append(normalization_record)
        summary = raw_range.get("summary") if isinstance(raw_range.get("summary"), str) and raw_range.get("summary").strip() else None
        relevance = raw_range.get("relevance") if isinstance(raw_range.get("relevance"), str) and raw_range.get("relevance").strip() else None
        if summary is None or relevance is None:
            warnings.append({"code": "WINDOW_OUTPUT_UNUSABLE", "details": {"reason": "missing_model_description", "window_id": window.window_id, "range_index": range_index}})
        accepted.append(ValidatedRange(
            source_range_index=range_index,
            thread_id=authoritative_thread,
            start_message_id=start,
            end_message_id=end,
            messages=tuple(MappingProxyType(dict(message)) for message in interval),
            summary=summary,
            relevance=relevance,
            normalizations=("endpoint_order_swapped",) if normalized else (),
        ))
    return ValidatedWindowEvidence(window.window_id, tuple(accepted), tuple(rejected), tuple(uncertainties), tuple(normalizations), tuple(warnings))


def validate_window_evidence(window: WindowLedgerInput, raw: Mapping[str, Any]) -> ValidatedWindowEvidence:
    """Public extraction validator retained as the dedicated salvage entry point."""
    return salvage_window_evidence(window, raw)


def _coerce_validated(window: WindowLedgerInput, output: Mapping[str, Any] | ValidatedWindowEvidence) -> ValidatedWindowEvidence:
    if isinstance(output, ValidatedWindowEvidence):
        if output.window_id != window.window_id:
            raise LedgerError("window output ID does not match request")
        return output
    return validate_window_evidence(window, output)


def build_ledger(windows: Sequence[WindowLedgerInput], outputs: Sequence[Mapping[str, Any] | ValidatedWindowEvidence]) -> LedgerBuild:
    if len(windows) != len(outputs):
        raise LedgerError("every window must produce exactly one output")
    records: list[EvidenceRangeRecord] = []
    coverage: list[CoverageReport] = []
    accepted_count = rejected_count = normalized_count = 0
    rejected_diagnostics: list[dict[str, Any]] = []
    salvage_warnings: list[dict[str, Any]] = []
    seen_windows: set[str] = set()
    for window, raw in zip(windows, outputs):
        if not window.messages:
            raise LedgerError("window has no messages", details={"reason": "empty_window", "window_id": window.window_id})
        if window.window_id in seen_windows:
            raise LedgerError("duplicate window ID", details={"reason": "duplicate_window_id", "window_id": window.window_id})
        seen_windows.add(window.window_id)
        validated = _coerce_validated(window, raw)
        accepted_count += validated.accepted_range_count
        rejected_count += validated.rejected_range_count
        normalized_count += validated.normalized_range_count
        rejected_diagnostics.extend(item.model_dump() for item in validated.rejected_ranges)
        salvage_warnings.extend(validated.warnings)
        for item in validated.accepted_ranges:
            records.append(EvidenceRangeRecord(
                range_id=f"r{len(records) + 1:06d}",
                window_id=window.window_id,
                source_range_index=item.source_range_index,
                thread_id=item.thread_id,
                start_message_id=item.start_message_id,
                end_message_id=item.end_message_id,
                messages=item.messages,
                summary=item.summary,
                relevance=item.relevance,
                normalizations=item.normalizations,
                uncertainties=validated.uncertainties,
                warnings=validated.warnings,
            ))
        coverage.append(CoverageReport(window.window_id, str(window.messages[0]["message_id"]), str(window.messages[-1]["message_id"]), len(window.messages), validated.accepted_range_count, validated.uncertainties))
    validation = {
        "planned_window_count": len(windows),
        "usable_window_count": len(windows),
        "unavailable_window_count": 0,
        "unavailable_windows": [],
        "status": "partial" if rejected_count else "complete",
        "accepted_range_count": accepted_count,
        "rejected_range_count": rejected_count,
        "normalized_range_count": normalized_count,
        "rejected_ranges": rejected_diagnostics,
        "warnings": salvage_warnings,
    }
    return LedgerBuild(tuple(records), tuple(coverage), validation)


def partition_records(records: Sequence[Any], fits: Callable[[Sequence[Any]], bool], *, level: int, max_depth: int = 4) -> tuple[tuple[str, tuple[Any, ...]], ...]:
    if level > max_depth:
        raise LedgerBudgetExceeded("ledger compaction depth exceeded")
    groups: list[tuple[str, tuple[Any, ...]]] = []
    current: list[Any] = []
    for record in records:
        candidate = tuple(current + [record])
        if not fits(candidate):
            if not current:
                raise LedgerBudgetExceeded("one ledger record cannot fit the configured budget")
            groups.append((f"g{level:02d}-{len(groups) + 1:06d}", tuple(current)))
            current = [record]
            if not fits(tuple(current)):
                raise LedgerBudgetExceeded("one ledger record cannot fit the configured budget")
        else:
            current.append(record)
    if current:
        groups.append((f"g{level:02d}-{len(groups) + 1:06d}", tuple(current)))
    return tuple(groups)
