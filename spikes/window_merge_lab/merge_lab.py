"""CLI entry point for Window Merge Lab strategies."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Allow importing from the project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from message_evidence_workstation.config.settings import (
    PROVIDER_GOOGLE,
    PROVIDER_NIM,
    ModelRoleConfig,
    load_settings,
)
from message_evidence_workstation.llm.providers.google_provider import GoogleModelProvider
from message_evidence_workstation.llm.providers.nim_provider import NimModelProvider
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.llm.types import ModelChatResult, ModelProvider, ModelTaskRole

from spikes.window_merge_lab.data_loader import load_compact_windows
from spikes.window_merge_lab.strategies import (
    EXPECTED_CALL_COUNTS,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_REGISTRY,
    StrategyResult,
    _save_outputs,
)

SPIKE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = SPIKE_DIR / "outputs"


def _make_model_call_fn(
    provider: str,
    model_override: str | None = None,
    max_tokens: int = 4096,
    timeout: float = 600.0,
):
    if provider == "settings":
        router = ModelRouter.from_settings()
        def call(messages):
            result = router.chat(
                messages=messages,
                task_role=ModelTaskRole.WINDOWED_RESULT_MERGE,
                max_output_tokens=max_tokens,
                timeout_seconds=timeout,
                temperature=0.1,
            )
            return result.content, result.latency_ms
        return call

    config = ModelRoleConfig(
        provider=provider,
        model=model_override or "",
        max_output_tokens=max_tokens,
        timeout_seconds=timeout,
        temperature=0.1,
    )
    if provider == PROVIDER_NIM:
        prov = NimModelProvider(config)
    elif provider == PROVIDER_GOOGLE:
        prov = GoogleModelProvider(config)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    def call(messages):
        result = prov.chat_completion(
            messages,
            model=config.model or None,
            task_role=ModelTaskRole.WINDOWED_RESULT_MERGE,
        )
        return result.content, result.latency_ms

    return call


def main() -> None:
    parser = argparse.ArgumentParser(description="Window Merge Lab - CLI")
    parser.add_argument("--strategy", choices=list(STRATEGY_REGISTRY.keys()), default="one_shot_compact")
    parser.add_argument("--dry-run", action="store_true", help="Build prompts but do not call any model")
    parser.add_argument("--provider", choices=["settings", "nim", "google"], default="settings")
    parser.add_argument("--model", default=None, help="Override model name")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--max-ranges", type=int, default=0, help="Max ranges per window (0=unlimited)")
    parser.add_argument("--include-raw", action="store_true", help="Include raw scan text in payloads")
    parser.add_argument("--no-api", action="store_true", help="Do not call any API (same as dry-run)")
    parser.add_argument("--input", default=None, help="Path to compact input JSON")
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--list-strategies", action="store_true", help="List available strategies and exit")
    args = parser.parse_args()

    if args.list_strategies:
        print("Available strategies:")
        for name, desc in STRATEGY_DESCRIPTIONS.items():
            expected = EXPECTED_CALL_COUNTS.get(name, "?")
            print(f"  {name:40s} {expected} call(s)  {desc}")
        return

    windows = load_compact_windows(Path(args.input) if args.input else None)
    print(f"Loaded {len(windows)} compact windows")
    for w in windows:
        rc = len(w.get("answer_ranges", []))
        output_chars = w.get('output_estimated_chars', 0)
        print(f"  {w['model_run_id']}: window={w.get('window_id','')} ranges={rc} output_chars={output_chars}")

    strategy_fn = STRATEGY_REGISTRY[args.strategy]
    dry_run = args.dry_run or args.no_api

    kwargs: dict = {}
    if args.strategy == "one_shot_compact":
        kwargs["include_raw_scan"] = args.include_raw
    kwargs["max_ranges_per_window"] = args.max_ranges

    if dry_run:
        print(f"\nRunning {args.strategy} in DRY RUN mode (no API calls)")

        def model_call(messages):
            return "", 0

        user_query = "Show me all the times we talked about school"
        result = strategy_fn(user_query, windows, model_call=model_call, **kwargs)
    else:
        print(f"\nRunning {args.strategy} with provider={args.provider}")
        model_call = _make_model_call_fn(
            args.provider,
            model_override=args.model,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        user_query = "Show me all the times we talked about school"
        result = strategy_fn(user_query, windows, model_call=model_call, **kwargs)

    ts = time.strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) if args.output else OUTPUTS_DIR / f"{ts}_{args.strategy}"
    _save_outputs(
        output_dir,
        result.strategy_name,
        result.messages_per_call,
        result.responses,
        result.latency_ms,
        result.call_count,
        result.last_parsed,
        result.error,
    )

    print(f"\n=== Results ===")
    print(f"Strategy:    {result.strategy_name}")
    print(f"Calls:       {result.call_count} (expected {EXPECTED_CALL_COUNTS.get(result.strategy_name, '?')})")
    print(f"Latency:     {result.latency_ms}ms")
    print(f"Error:       {result.error or 'none'}")
    print(f"Parse:       {'OK' if result.last_parsed else 'FAILED'}")
    if result.last_parsed:
        rc = len(result.last_parsed.get("answer_ranges", []))
        print(f"Ranges:      {rc}")
        summary = result.last_parsed.get("answer_summary", "")
        if summary:
            print(f"Summary:     {summary[:120]}")
    print(f"Output:      {output_dir}")


if __name__ == "__main__":
    main()
