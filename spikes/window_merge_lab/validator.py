"""Deterministic validation of synthesis outputs against the evidence ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import re


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
    missing_range_ids: list[str]
    duplicate_range_ids: list[str]
    unknown_range_ids: list[str]
    invalid_message_ids: list[str]

    def summary(self) -> str:
        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity == "warning"]
        parts = []
        if errors:
            parts.append(f"{len(errors)} error(s)")
        if warnings:
            parts.append(f"{len(warnings)} warning(s)")
        parts.append(
            f"ranges: {self.represented_range_count}/{self.input_range_count}"
        )
        if self.missing_range_ids:
            parts.append(f"missing={self.missing_range_ids}")
        if self.unknown_range_ids:
            parts.append(f"unknown={self.unknown_range_ids}")
        if self.duplicate_range_ids:
            parts.append(f"duplicates={self.duplicate_range_ids}")
        return "; ".join(parts)


METADATA_TITLE_RE = re.compile(
    r"^(Conversation|School Discussion|Discussion|Chat) (on|about|re) ",
    re.IGNORECASE,
)


def validate_synthesis_output(
    parsed_response: Any,
    ledger_records: list[dict],
    mode: Literal["full", "compact"],
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    missing: list[str] = []
    duplicates: list[str] = []
    unknown: list[str] = []
    invalid_message_ids_set: list[str] = []

    input_ranges: dict[str, dict] = {}
    for rec in ledger_records:
        lid = rec.get("range_id")
        if lid:
            input_ranges[lid] = rec

    if not isinstance(parsed_response, dict):
        return ValidationResult(
            ok=False,
            issues=[ValidationIssue("error", "not_object", "Response is not a JSON object")],
            input_range_count=len(input_ranges),
            output_range_count=0,
            represented_range_count=0,
            missing_range_ids=list(input_ranges.keys()),
            duplicate_range_ids=[],
            unknown_range_ids=[],
            invalid_message_ids=[],
        )

    raw_ranges = parsed_response.get("answer_ranges")
    if not isinstance(raw_ranges, list):
        return ValidationResult(
            ok=False,
            issues=[ValidationIssue("error", "missing_answer_ranges", "answer_ranges is missing or not a list")],
            input_range_count=len(input_ranges),
            output_range_count=0,
            represented_range_count=0,
            missing_range_ids=list(input_ranges.keys()),
            duplicate_range_ids=[],
            unknown_range_ids=[],
            invalid_message_ids=[],
        )

    output_range_ids_seen: dict[str, int] = {}

    for i, rng in enumerate(raw_ranges):
        rid = rng.get("range_id")
        if not rid or not isinstance(rid, str):
            issues.append(ValidationIssue(
                "error", "missing_range_id",
                f"answer_ranges[{i}] is missing range_id",
            ))
            continue

        # Check for NaN/Inf in numeric fields
        for float_field in ("start_offset", "end_offset"):
            val = rng.get(float_field)
            if val is not None and not isinstance(val, (int, float)):
                issues.append(ValidationIssue(
                    "error", "invalid_field_type",
                    f"range {rid}: {float_field} must be numeric",
                    range_id=rid,
                ))

        has_source_key = bool(rng.get("source_range_key"))
        has_source_keys = isinstance(rng.get("source_range_keys"), list)
        if not has_source_key and not has_source_keys:
            issues.append(ValidationIssue(
                "error", "missing_source_range_key",
                f"range {rid} is missing source_range_key and source_range_keys",
                range_id=rid,
            ))

        if rid not in input_ranges:
            unknown.append(rid)
            issues.append(ValidationIssue(
                "error", "unknown_range_id",
                f"range {rid} is not in the input ledger",
                range_id=rid,
            ))
            continue

        output_range_ids_seen[rid] = output_range_ids_seen.get(rid, 0) + 1

        input_rec = input_ranges[rid]

        for msg_field in ("hit_message_id", "start_message_id", "end_message_id"):
            out_val = rng.get(msg_field)
            in_val = input_rec.get(msg_field)
            if out_val is not None and out_val != in_val:
                issues.append(ValidationIssue(
                    "error", f"changed_{msg_field}",
                    f"range {rid}: {msg_field} changed from '{in_val}' to '{out_val}'",
                    range_id=rid,
                ))
                if msg_field == "hit_message_id" and out_val not in invalid_message_ids_set:
                    invalid_message_ids_set.append(out_val)

    for rid, count in output_range_ids_seen.items():
        if count > 1:
            duplicates.append(rid)
            issues.append(ValidationIssue(
                "error", "duplicate_range_id",
                f"range {rid} appears {count} times in output",
                range_id=rid,
            ))

    output_range_ids = set(output_range_ids_seen.keys())
    for rid in input_ranges:
        if rid not in output_range_ids:
            missing.append(rid)
            issues.append(ValidationIssue(
                "error", "missing_range_id",
                f"range {rid} is missing from output",
                range_id=rid,
            ))

    represented = len([r for r in input_ranges if r in output_range_ids])

    # Warnings
    if not parsed_response.get("answer_summary"):
        issues.append(ValidationIssue(
            "warning", "missing_answer_summary",
            "answer_summary is missing or empty",
        ))

    if not parsed_response.get("answer"):
        issues.append(ValidationIssue(
            "warning", "missing_answer",
            "answer is missing or empty",
        ))

    for rng in raw_ranges:
        rid = rng.get("range_id", "?")
        if rid not in input_ranges:
            continue
        title = (rng.get("title") or "").strip()
        if not title:
            issues.append(ValidationIssue(
                "warning", "empty_title", f"range {rid}: title is empty", range_id=rid,
            ))
        elif METADATA_TITLE_RE.match(title):
            issues.append(ValidationIssue(
                "warning", "metadata_title",
                f"range {rid}: title appears metadata-only: '{title}'",
                range_id=rid,
            ))

        summary = (rng.get("summary") or "").strip()
        display_text = (rng.get("display_text") or "").strip()
        if mode == "full":
            if not summary:
                issues.append(ValidationIssue(
                    "warning", "empty_summary",
                    f"range {rid}: summary is empty in full mode", range_id=rid,
                ))
            if not display_text:
                issues.append(ValidationIssue(
                    "warning", "empty_display_text",
                    f"range {rid}: display_text is empty in full mode", range_id=rid,
                ))

    themes = parsed_response.get("themes")
    if themes is not None:
        if not isinstance(themes, list):
            issues.append(ValidationIssue(
                "warning", "invalid_themes",
                "themes is present but is not a list",
            ))
        else:
            for idx, theme in enumerate(themes):
                if not isinstance(theme, dict):
                    issues.append(ValidationIssue(
                        "warning", "invalid_theme_entry",
                        f"themes[{idx}] is not an object",
                    ))
                    continue
                range_ids = theme.get("range_ids")
                if range_ids is None:
                    continue
                if not isinstance(range_ids, list):
                    issues.append(ValidationIssue(
                        "warning", "invalid_theme_range_ids",
                        f"themes[{idx}].range_ids is not a list",
                    ))
                    continue
                for rid in range_ids:
                    if not isinstance(rid, str) or not rid.strip():
                        issues.append(ValidationIssue(
                            "warning", "blank_theme_range_id",
                            f"themes[{idx}] contains a blank range_id",
                        ))
                        continue
                    if rid not in input_ranges:
                        issues.append(ValidationIssue(
                            "error", "unknown_theme_range_id",
                            f"themes[{idx}] references unknown range_id '{rid}'",
                            range_id=rid,
                        ))

    cov = parsed_response.get("coverage_summary") or {}
    if not isinstance(cov, dict) or not cov.get("mode"):
        issues.append(ValidationIssue(
            "warning", "missing_coverage_summary",
            "coverage_summary is missing or incomplete",
        ))
    else:
        for field in ("input_range_count", "output_range_count", "represented_range_count"):
            val = cov.get(field)
            if val is None or not isinstance(val, int):
                issues.append(ValidationIssue(
                    "warning", f"inconsistent_{field}",
                    f"coverage_summary.{field} is missing or not an integer",
                ))

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
        invalid_message_ids=invalid_message_ids_set,
    )
