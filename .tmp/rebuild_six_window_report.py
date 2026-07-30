from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_six_window_model_comparison import (
    GOLD_PATH,
    captured_windows,
    gold_recall,
    markdown_report,
    range_inventory,
    raw_model_inventory,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()

    source_windows = captured_windows()
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    shared = json.loads(
        (output_dir / "shared-input-manifest.json").read_text(encoding="utf-8")
    )

    model_results = {}
    for model_key in ("glm", "ultra", "minimax"):
        path = output_dir / model_key / "model-result.json"
        model_result = json.loads(path.read_text(encoding="utf-8"))
        results = model_result["windows"]
        inventory, ledger = range_inventory(source_windows, results)
        raw_inventory = raw_model_inventory(results)
        model_result["inventory"] = inventory
        model_result["ledger"] = ledger
        model_result["gold_recall"] = gold_recall(
            source_windows, inventory, gold
        )
        model_result["raw_model_inventory"] = raw_inventory
        model_result["raw_model_gold_recall"] = gold_recall(
            source_windows, raw_inventory, gold
        )
        path.write_text(
            json.dumps(model_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        model_results[model_key] = model_result

    comparison = {"shared": shared, "models": model_results}
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "comparison.md").write_text(
        markdown_report(output_dir, shared, model_results),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
