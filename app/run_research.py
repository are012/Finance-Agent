from __future__ import annotations

import argparse
from pathlib import Path

from research.data_loader import load_config, load_configured_data
from research.experiment import evaluate_hypothesis, rejected_hypothesis_row
from research.features import add_chart_features
from research.hypothesis import load_hypotheses_from_config
from research.ledger import ExperimentLedger
from research.utils import ensure_output_dirs
from research.validation import SplitConfig, split_by_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run chart-only hypothesis research.")
    parser.add_argument("--config", default="configs/example.yaml")
    parser.add_argument("--output-dir", default="outputs")
    args = parser.parse_args(argv)

    ledger_path = run_research(config_path=args.config, output_dir=args.output_dir)
    print(f"ledger={ledger_path}")
    return 0


def run_research(*, config_path: str | Path, output_dir: str | Path) -> Path:
    config = load_config(config_path)
    if config.get("research", {}).get("allow_final_holdout_during_research", False):
        raise ValueError("Research loop cannot use final_holdout")
    paths = ensure_output_dirs(output_dir)
    ledger_path = paths["ledger"] / "experiments.jsonl"
    ledger = ExperimentLedger(ledger_path)

    data = load_configured_data(config)
    featured = add_chart_features(data, windows=list(config["research"].get("feature_windows", [5, 20])))
    split = split_by_date(featured, SplitConfig.from_config(config.get("splits", config.get("split"))))
    hypotheses = load_hypotheses_from_config(config)

    for index, hypothesis in enumerate(hypotheses, start=1):
        if getattr(hypothesis, "is_invalid", False):
            row = rejected_hypothesis_row(hypothesis=hypothesis, config=config, sequence=index)
        else:
            row = evaluate_hypothesis(
                hypothesis=hypothesis,
                split=split,
                featured=featured,
                config=config,
                output_paths=paths,
                sequence=index,
            )
        ledger.append(row)
        if row["status"] == "PASS":
            break

    return ledger_path


if __name__ == "__main__":
    raise SystemExit(main())
