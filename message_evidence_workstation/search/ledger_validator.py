"""Deterministic validation of evidence-ledger synthesis outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ValidationIssue:
    severity: Literal["error", "warning"]
    code: str
    message: str
    range_id: str | None = None


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue]
    input_range_count: int
    output_range_count: int
    represented_range_count: int
    missing_range_ids: list[str] = field(default_factory=list)
    duplicate_range_ids: list[str] = field(default_factory=list)
    unknown_range_ids: list[str] = field(default_factory=list)
    invalid_message_ids: list[str] = field(default_factory=list)


def validate_ledger_analysis_output(
    model_json: Any,
    ledger_records: list[dict],
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    missing: list[str] = []
    duplicates: list[str] = []
    unknown: list[str] = []
    invalid_ids: list[str] = []

    input_ranges: dict[str, dict] = {}
    for rec in ledger_records:
        rid = rec.get("range_id")
        if rid:
            input_ranges[rid] = rec

    if not isinstance(model_json, dict):
        return ValidationResult(
            ok=False,
            issues=[ValidationIssue("error", "not_object", "Response is not a JSON object")],
            input_range_count=len(input_ranges),
            output_range_count=0,
            represented_range_count=0,
            missing_range_ids=list(input_ranges.keys()),
        )

    answer = model_json.get("answer")
    if not answer or not isinstance(answer, str) or not answer.strip():
        issues.append(ValidationIssue("error", "missing_answer", "answer is missing or empty"))
    elif len(answer.strip()) < 20:
        issues.append(ValidationIssue("warning", "short_answer", f"answer is unusually short ({len(answer.strip())} chars)"))

    answer_summary = model_json.get("answer_summary")
    if not answer_summary or not isinstance(answer_summary, str) or not answer_summary.strip():
        issues.append(ValidationIssue("warning", "missing_answer_summary", "answer_summary is missing or empty"))

    themes = model_json.get("themes")
    if themes is not None:
        if not isinstance(themes, list):
            issues.append(ValidationIssue("error", "invalid_themes", "themes is present but is not a list"))
        else:
            if not themes:
                issues.append(ValidationIssue("warning", "empty_themes", "themes list is empty"))
            for idx, theme in enumerate(themes):
                if not isinstance(theme, dict):
                    issues.append(ValidationIssue("error", "invalid_theme_entry", f"themes[{idx}] is not an object"))
                    continue
                range_ids = theme.get("range_ids")
                if range_ids is not None:
                    if not isinstance(range_ids, list):
                        issues.append(
                            ValidationIssue("error", "invalid_theme_range_ids", f"themes[{idx}].range_ids is not a list")
                        )
                        continue
                    for rid in range_ids:
                        if not isinstance(rid, str) or not rid.strip():
                            issues.append(
                                ValidationIssue("warning", "blank_theme_range_id", f"themes[{idx}] contains a blank range_id")
                            )
                            continue
                        if rid not in input_ranges:
                            unknown.append(rid)
                            issues.append(
                                ValidationIssue(
                                    "error",
                                    "unknown_theme_range_id",
                                    f"themes[{idx}] references unknown range_id '{rid}'",
                                    range_id=rid,
                                )
                            )

    for field_name in ("notable_patterns", "contradictions_or_tensions", "uncertainties"):
        val = model_json.get(field_name)
        if val is not None and not isinstance(val, list):
            issues.append(ValidationIssue("error", f"invalid_{field_name}", f"{field_name} is present but is not a list"))

    has_errors = any(i.severity == "error" for i in issues)
    return ValidationResult(
        ok=not has_errors,
        issues=issues,
        input_range_count=len(input_ranges),
        output_range_count=0,
        represented_range_count=0,
        missing_range_ids=missing,
        duplicate_range_ids=duplicates,
        unknown_range_ids=unknown,
        invalid_message_ids=invalid_ids,
    )


def validate_assembled_ledger_output(
    assembled_payload: Any,
    ledger_records: list[dict],
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    missing: list[str] = []
    duplicates: list[str] = []
    unknown: list[str] = []
    invalid_ids: list[str] = []

    input_ranges: dict[str, dict] = {}
    for rec in ledger_records:
        rid = rec.get("range_id")
        if rid:
            input_ranges[rid] = rec

    if not isinstance(assembled_payload, dict):
        return ValidationResult(
            ok=False,
            issues=[ValidationIssue("error", "not_object", "Assembled payload is not a JSON object")],
            input_range_count=len(input_ranges),
            output_range_count=0,
            represented_range_count=0,
            missing_range_ids=list(input_ranges.keys()),
        )

    raw_ranges = assembled_payload.get("answer_ranges")
    if not isinstance(raw_ranges, list):
        return ValidationResult(
            ok=False,
            issues=[ValidationIssue("error", "missing_answer_ranges", "answer_ranges is missing or not a list")],
            input_range_count=len(input_ranges),
            output_range_count=0,
            represented_range_count=0,
            missing_range_ids=list(input_ranges.keys()),
        )

    output_seen: dict[str, int] = {}

    for i, rng in enumerate(raw_ranges):
        if not isinstance(rng, dict):
            issues.append(
                ValidationIssue("error", "invalid_range_entry", f"answer_ranges[{i}] is not a dict")
            )
            continue

        rid = rng.get("range_id")
        if not rid or not isinstance(rid, str):
            issues.append(
                ValidationIssue("error", "missing_range_id", f"answer_ranges[{i}] is missing range_id")
            )
            continue

        output_seen[rid] = output_seen.get(rid, 0) + 1

        if rid not in input_ranges:
            unknown.append(rid)
            issues.append(
                ValidationIssue(
                    "error", "unknown_range_id", f"range {rid} is not in the input ledger",
                    range_id=rid,
                )
            )
            continue

        input_rec = input_ranges[rid]

        for msg_field in ("hit_message_id", "start_message_id", "end_message_id"):
            out_val = rng.get(msg_field)
            in_val = input_rec.get(msg_field)
            if out_val is not None and out_val != in_val:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"changed_{msg_field}",
                        f"range {rid}: {msg_field} changed from '{in_val}' to '{out_val}'",
                        range_id=rid,
                    )
                )
                if msg_field == "hit_message_id" and out_val not in invalid_ids:
                    invalid_ids.append(str(out_val))

        out_skey = rng.get("source_range_key")
        in_skey = input_rec.get("source_range_key")
        if out_skey is not None and out_skey != in_skey:
            issues.append(
                ValidationIssue(
                    "error",
                    "changed_source_range_key",
                    f"range {rid}: source_range_key changed from '{in_skey}' to '{out_skey}'",
                    range_id=rid,
                )
            )

    for rid, count in output_seen.items():
        if count > 1:
            duplicates.append(rid)
            issues.append(
                ValidationIssue(
                    "error", "duplicate_range_id",
                    f"range {rid} appears {count} times in output",
                    range_id=rid,
                )
            )

    output_ids = set(output_seen.keys())
    for rid in input_ranges:
        if rid not in output_ids:
            missing.append(rid)
            issues.append(
                ValidationIssue(
                    "error", "missing_range_id",
                    f"range {rid} is missing from output",
                    range_id=rid,
                )
            )

    represented = sum(1 for rid in input_ranges if rid in output_ids and output_seen.get(rid, 0) == 1 and rid not in unknown)

    has_errors = any(i.severity == "error" for i in issues)
    return ValidationResult(
        ok=not has_errors,
        issues=issues,
        input_range_count=len(input_ranges),
        output_range_count=len(raw_ranges),
        represented_range_count=represented,
        missing_range_ids=missing,
        duplicate_range_ids=duplicates,
        unknown_range_ids=unknown,
        invalid_message_ids=invalid_ids,
    )
