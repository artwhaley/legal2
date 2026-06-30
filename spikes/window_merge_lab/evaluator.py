"""Evaluation and comparison of strategy outputs.

Imports the deterministic validator for evidence-ledger strategies and
falls back to heuristic provenance for legacy strategies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spikes.window_merge_lab.validator import validate_synthesis_output


METADATA_TITLE_RE = __import__("re").compile(
    r"^(Conversation|School Discussion|Discussion|Chat) (on|about|re) ",
    __import__("re").IGNORECASE,
)


def evaluate_strategy_outputs(
    parsed: dict,
    source_windows: list[dict],
    *,
    strategy_name: str | None = None,
    planner_plans: list[dict] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("# Strategy Output Evaluation")
    lines.append("")

    # Parse success
    lines.append(f"**Parse success:** {'Yes' if parsed else 'No'}")
    if not parsed:
        return "\n".join(lines)

    # Determine mode from planner_plans or coverage summary
    inferred_mode: str | None = None
    if planner_plans:
        modes = set(p.get("mode", "") for p in planner_plans if p.get("mode"))
        if modes:
            inferred_mode = ", ".join(sorted(modes))
    if not inferred_mode:
        coverage = parsed.get("coverage_summary") or {}
        inferred_mode = coverage.get("mode") or parsed.get("planner_mode") or "?"

    # Range counts
    ranges = parsed.get("answer_ranges", [])
    if isinstance(ranges, list):
        range_count = len(ranges)
    else:
        range_count = 0
    lines.append(f"**Mode/Profile:** {inferred_mode}")
    lines.append(f"**Answer range count:** {range_count}")

    # Deterministic validation (evidence_ledger_synthesis only)
    vr: Any = None
    ledgers: list[dict] = []
    for w in source_windows:
        for r in w.get("answer_ranges", []):
            if isinstance(r, dict) and r.get("range_id"):
                ledgers.append(r)
    if ledgers and strategy_name and "evidence_ledger" in strategy_name:
        mode_for_val: str = "full" if "full" in inferred_mode else "compact"
        vr = validate_synthesis_output(parsed, ledgers, mode=mode_for_val)
        lines.append(f"\n## Deterministic Validation")
        lines.append(f"**Valid:** {'PASS' if vr.ok else 'FAIL'}")
        lines.append(f"**Issues:** {vr.summary()}")
        lines.append(f"**Input range count:** {vr.input_range_count}")
        lines.append(f"**Output range count:** {vr.output_range_count}")
        lines.append(f"**Represented range count:** {vr.represented_range_count}")
        if vr.missing_range_ids:
            lines.append(f"**Missing range IDs:** {len(vr.missing_range_ids)}")
            for rid in vr.missing_range_ids[:5]:
                lines.append(f"- MISSING: `{rid}`")
            if len(vr.missing_range_ids) > 5:
                lines.append(f"- ... and {len(vr.missing_range_ids) - 5} more")
        if vr.unknown_range_ids:
            lines.append(f"**Unknown range IDs:** {len(vr.unknown_range_ids)}")
            for rid in vr.unknown_range_ids[:5]:
                lines.append(f"- UNKNOWN: `{rid}`")
            if len(vr.unknown_range_ids) > 5:
                lines.append(f"- ... and {len(vr.unknown_range_ids) - 5} more")
        if vr.invalid_message_ids:
            lines.append(f"**Invalid message IDs:** {len(vr.invalid_message_ids)}")
        lines.append("")
    else:
        ledgers = []

    # Source window range counts for comparison
    total_source_ranges = 0
    for w in source_windows:
        total_source_ranges += len(w.get("answer_ranges", []))
    lines.append(f"**Source window range total:** {total_source_ranges}")
    if total_source_ranges > 0:
        pct = round(range_count / total_source_ranges * 100, 1)
        if pct > 120:
            lines.append(f"- WARN: Merge output is {pct}% of source range count (may be over-inclusive)")
        elif pct < 50:
            lines.append(f"- WARN: Merge output is {pct}% of source range count (may be under-inclusive)")
        else:
            lines.append(f"- OK: Merge output is {pct}% of source range count (reasonable range)")

    # Invalid message IDs (legacy check)
    all_source_ids: set[str] = set()
    for w in source_windows:
        all_source_ids.update(w.get("message_ids", []))
    all_cited_ranges_ids: set[str] = set()
    for r in ranges:
        if isinstance(r, dict):
            for key in ("hit_message_id", "start_message_id", "end_message_id"):
                val = str(r.get(key, "")).strip()
                if val:
                    all_cited_ranges_ids.add(val)
    cited = set(parsed.get("cited_message_ids", []) or [])
    all_cited_ids = cited | all_cited_ranges_ids
    invalid_ids_legacy = [mid for mid in all_cited_ids if mid and mid not in all_source_ids]
    if invalid_ids_legacy:
        lines.append(f"\n**Invalid message IDs (legacy):** {len(invalid_ids_legacy)}")
        for mid in invalid_ids_legacy[:10]:
            lines.append(f"- BAD: `{mid}`")
        if len(invalid_ids_legacy) > 10:
            lines.append(f"- ... and {len(invalid_ids_legacy) - 10} more")
    else:
        lines.append("\n**Invalid message IDs (legacy):** None")

    # Duplicate-looking ranges
    seen_titles: set[str] = set()
    duplicates = 0
    for r in ranges:
        if isinstance(r, dict):
            t = r.get("title", "")
            if t in seen_titles:
                duplicates += 1
            else:
                seen_titles.add(t)
    if duplicates:
        lines.append(f"\n**Duplicate-looking ranges:** {duplicates} (by title)")
    else:
        lines.append("\n**Duplicate-looking ranges:** None")

    # Source windows represented
    all_range_window_ids: set[str] = set()
    for w in source_windows:
        wid = w.get("window_id", "")
        if not wid:
            continue
        for r in ranges:
            if not isinstance(r, dict):
                continue
            for mid in (r.get("hit_message_id", ""), r.get("start_message_id", ""), r.get("end_message_id", "")):
                if mid in w.get("message_ids", []):
                    all_range_window_ids.add(wid)
                    break

    source_window_ids = [w.get("window_id", "") or f"run_{w['model_run_id']}" for w in source_windows]
    represented = [wid for wid in source_window_ids if wid in all_range_window_ids]
    dropped = [wid for wid in source_window_ids if wid not in all_range_window_ids]
    lines.append(f"\n**Source windows represented:** {len(represented)}/{len(source_window_ids)}")
    if dropped:
        lines.append(f"- BAD: Likely dropped windows: {', '.join(dropped)}")
    else:
        lines.append("- All source windows appear represented")

    # Provenance: track which input ranges survived / merged / vanished
    provenance = _build_provenance(parsed, source_windows)
    lines.append(f"\n## Range Provenance")
    lines.append("")
    lines.append(f"**Input ranges (total):** {provenance['input_count']}")
    lines.append(f"**Output ranges:** {provenance['output_count']}")
    lines.append(f"**Ranges matched 1:1:** {provenance['matched_count']}")
    lines.append(f"**Ranges merged (2+ inputs → 1 output):** {provenance['merged_count']}")
    lines.append(f"**Orphaned input ranges (no output match):** {provenance['orphaned_count']}")
    lines.append(f"**Output ranges with no input match (hallucinated?):** {provenance['unmatched_output_count']}")
    if provenance.get("model_reported_provenance"):
        lines.append("\n*Provenance based on model-reported source_range_keys*")
        if provenance.get("fallback_match_count"):
            lines.append(
                f"*Recovered {provenance['fallback_match_count']} ranges by title/hit-message fallback "
                "after malformed or unmatched source_range_keys*"
            )
    else:
        lines.append("\n*Provenance based on heuristic matching (title/hit_message_id)*")
    if provenance["orphaned_list"]:
        lines.append("\n**Orphaned input ranges (likely lost):**")
        for o in provenance["orphaned_list"][:20]:
            lines.append(f"- `{o['window_id']}` / {o['title']}  (hit: {o['hit_message_id']})")
        if len(provenance["orphaned_list"]) > 20:
            lines.append(f"- ... and {len(provenance['orphaned_list']) - 20} more")
    if provenance["merged_list"]:
        lines.append("\n**Merged groups (multiple inputs → one output):**")
        for m in provenance["merged_list"][:10]:
            sources = ", ".join(f"`{s['window_id']}`/{s['title']}" for s in m["sources"])
            lines.append(f"- Output `{m['output_title']}` ← {sources}")
        if len(provenance["merged_list"]) > 10:
            lines.append(f"- ... and {len(provenance['merged_list']) - 10} more")
    if provenance["unmatched_output_list"]:
        lines.append("\n**Output ranges with no input match (possible hallucination):**")
        for u in provenance["unmatched_output_list"][:10]:
            lines.append(f"- `{u['title']}`  (hit: {u['hit_message_id']})")
        if len(provenance["unmatched_output_list"]) > 10:
            lines.append(f"- ... and {len(provenance['unmatched_output_list']) - 10} more")

    # Output length
    answer = parsed.get("answer", "") or ""
    summary = parsed.get("answer_summary", "") or ""
    lines.append(f"\n**Output length:** answer={len(answer)} chars, summary={len(summary)} chars")

    # Metadata-only titles
    metadata_title_count = 0
    for r in ranges:
        if isinstance(r, dict):
            title = (r.get("title") or "").strip()
            if title and METADATA_TITLE_RE.match(title):
                metadata_title_count += 1
    lines.append(f"\n**Metadata-only titles:** {metadata_title_count}")

    # Uncertainties
    uncertainties = list(parsed.get("uncertainties", []) or [])
    if uncertainties:
        lines.append(f"\n**Model-reported uncertainties:** {len(uncertainties)}")
        for u in uncertainties[:5]:
            lines.append(f"- {u}")
        if len(uncertainties) > 5:
            lines.append(f"- ... and {len(uncertainties) - 5} more")
    else:
        lines.append("\n**Model-reported uncertainties:** None")

    # Quality checklist
    lines.append("\n## Quality Checklist")
    lines.append("")
    has_synthesis = len(answer) > 50 or len(summary) > 50
    is_compact = "compact" in inferred_mode.lower()
    if is_compact:
        lines.append(f"- {'PASS' if has_synthesis else 'INFO'}: Compact mode — short narrative is expected")
    else:
        lines.append(f"- {'PASS' if has_synthesis else 'FAIL'}: Synthesizes rather than merely lists")
    has_dates = any(r.get("date_description", "") for r in ranges if isinstance(r, dict))
    lines.append(f"- {'PASS' if has_dates else 'FAIL'}: Preserves dates and concrete evidence")
    if vr is not None:
        lines.append(f"- {'PASS' if vr.ok else 'FAIL'}: Deterministic validation")
    else:
        no_hallucinated_ids = len(invalid_ids_legacy) == 0
        lines.append(f"- {'PASS' if no_hallucinated_ids else 'FAIL'}: Avoids hallucinated IDs")
    all_windows_present = len(dropped) == 0
    lines.append(f"- {'PASS' if all_windows_present else 'FAIL'}: Avoids losing smaller but important clusters")
    ranges_useful = range_count > 0
    lines.append(f"- {'PASS' if ranges_useful else 'FAIL'}: Answer ranges are useful for transcript navigation")
    no_orphaned = provenance["orphaned_count"] == 0
    lines.append(f"- {'PASS' if no_orphaned else 'FAIL'}: Preserves all input ranges (0 orphaned, {provenance['orphaned_count']} lost)")
    metadata_ok = metadata_title_count <= range_count * 0.3
    lines.append(f"- {'PASS' if metadata_ok else 'WARN'}: Metadata-only titles = {metadata_title_count}/{range_count}")

    return "\n".join(lines)


def compare_strategy_outputs(output_dir: Path) -> str:
    lines: list[str] = []
    lines.append("# Strategy Comparison Summary")
    lines.append("")

    result_dirs = sorted(output_dir.iterdir()) if output_dir.is_dir() else []
    if not result_dirs:
        return "No strategy output directories found."

    for d in result_dirs:
        if not d.is_dir():
            continue
        metrics_file = d / "metrics.json"
        parsed_file = d / "result_parsed.json"
        if not metrics_file.exists():
            continue
        try:
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            lines.append(f"## {d.name}")
            lines.append(f"- **Strategy:** {metrics.get('strategy', '?')}")
            lines.append(f"- **Calls:** {metrics.get('call_count', '?')}")
            lines.append(f"- **Latency:** {metrics.get('latency_ms', '?')}ms")
            lines.append(f"- **Error:** {metrics.get('error', 'none')}")
            lines.append(f"- **Range count:** {metrics.get('range_count', '?')}")
            if parsed_file.exists():
                parsed = json.loads(parsed_file.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    lines.append(f"- **Summary:** {parsed.get('answer_summary', '(none)')[:100]}")
            lines.append("")
        except Exception:
            pass

    return "\n".join(lines)


def _build_provenance(parsed: dict, source_windows: list[dict]) -> dict:
    """Cross-reference input ranges vs output ranges to trace merges and drops."""
    output_ranges = parsed.get("answer_ranges", []) or []

    # Index all input ranges by (window_id, title, hit_message_id)
    input_index: dict[str, dict] = {}
    input_order: list[str] = []
    for w in source_windows:
        wid = w.get("window_id", "")
        for r in w.get("answer_ranges", []):
            if not isinstance(r, dict):
                continue
            title = r.get("title", "")
            hit = r.get("hit_message_id", "")
            key = f"{wid}||{title}||{hit}"
            input_index[key] = {
                "window_id": wid,
                "title": title,
                "hit_message_id": hit,
                "summary": r.get("summary", ""),
            }
            input_order.append(key)

    matched: set[str] = set()
    merged_groups: list[dict] = []
    unmatched_output: list[dict] = []
    model_reported = False
    fallback_match_count = 0

    for out_r in output_ranges:
        if not isinstance(out_r, dict):
            continue
        out_title = out_r.get("title", "")
        out_hit = out_r.get("hit_message_id", "")
        srk = out_r.get("source_range_keys", [])

        if srk:
            # Model self-reported provenance
            model_reported = True
            sources_found: list[str] = []
            for sk in srk:
                # source_range_keys format: "window_id::Range Title"
                parts = sk.split("::", 1)
                if len(parts) == 2:
                    swid, stitle = parts
                else:
                    swid, stitle = "", sk
                for key, info in input_index.items():
                    if info["window_id"] == swid and info["title"] == stitle:
                        sources_found.append(key)
                        matched.add(key)
                        break
            if not sources_found:
                sources_found = _match_by_title_or_hit(input_index, out_title, out_hit)
                if sources_found:
                    fallback_match_count += len(sources_found)
                    for key in sources_found:
                        matched.add(key)
            if len(sources_found) >= 2:
                merged_groups.append({
                    "output_title": out_title,
                    "sources": [input_index[k] for k in sources_found],
                })
            elif not sources_found:
                unmatched_output.append({"title": out_title, "hit_message_id": out_hit})
        else:
            # Heuristic matching by title and hit_message_id
            matched_keys = _match_by_title_or_hit(input_index, out_title, out_hit)
            if matched_keys:
                for k in matched_keys:
                    matched.add(k)
                if len(matched_keys) >= 2:
                    merged_groups.append({
                        "output_title": out_title,
                        "sources": [input_index[k] for k in matched_keys],
                    })
            else:
                unmatched_output.append({"title": out_title, "hit_message_id": out_hit})

    orphaned = [
        input_index[k] for k in input_order
        if k not in matched
    ]

    merged_count = sum(
        1 for g in merged_groups if len(g["sources"]) >= 2
    )

    return {
        "input_count": len(input_index),
        "output_count": len(output_ranges),
        "matched_count": len(matched),
        "merged_count": merged_count,
        "orphaned_count": len(orphaned),
        "orphaned_list": orphaned,
        "merged_list": merged_groups,
        "unmatched_output_count": len(unmatched_output),
        "unmatched_output_list": unmatched_output,
        "model_reported_provenance": model_reported,
        "fallback_match_count": fallback_match_count,
    }


def _match_by_title_or_hit(
    input_index: dict[str, dict],
    out_title: str,
    out_hit: str,
) -> list[str]:
    matched_keys: list[str] = []
    for key, info in input_index.items():
        if info["title"] == out_title or (
            info["hit_message_id"] and info["hit_message_id"] == out_hit
        ):
            matched_keys.append(key)
    return matched_keys


def main() -> None:
    from spikes.window_merge_lab.data_loader import load_compact_windows

    windows = load_compact_windows()
    print(f"Loaded {len(windows)} source windows")
    from spikes.window_merge_lab.strategies import run_deterministic_baseline

    result = run_deterministic_baseline("test", windows)
    if result.last_parsed:
        print(evaluate_strategy_outputs(result.last_parsed, windows))


if __name__ == "__main__":
    main()
