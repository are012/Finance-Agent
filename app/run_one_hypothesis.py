from __future__ import annotations

import argparse
from pathlib import Path

from research.data_loader import load_config, load_configured_data
from research.experiment import evaluate_hypothesis, rejected_hypothesis_row
from research.features import add_chart_features
from research.hypothesis import InvalidHypothesis, generate_hypotheses, load_hypothesis_spec
from research.ledger import ExperimentLedger
from research.utils import ensure_output_dirs
from research.validation import SplitConfig, split_by_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic chart-only hypothesis.")
    parser.add_argument("--config", default="configs/example.yaml")
    parser.add_argument("--hypothesis", help="Path to YAML or JSON hypothesis spec.")
    parser.add_argument("--hypothesis-id", help="Built-in hypothesis id for backward-compatible runs.")
    parser.add_argument("--output-dir", default="outputs")
    args = parser.parse_args(argv)

    row = run_one_hypothesis(
        config_path=args.config,
        output_dir=args.output_dir,
        hypothesis_path=args.hypothesis,
        hypothesis_id=args.hypothesis_id,
    )
    print({"status": row["status"], "score": row["score"], "hypothesis_id": row["hypothesis_id"]})
    return 0


def run_one_hypothesis(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    hypothesis_path: str | Path | None = None,
    hypothesis_id: str | None = None,
) -> dict:
    if not hypothesis_path and not hypothesis_id:
        raise SystemExit("Provide --hypothesis or --hypothesis-id")
    config = load_config(config_path)
    paths = ensure_output_dirs(output_dir)
    data = load_configured_data(config)
    featured = add_chart_features(data, windows=list(config["research"].get("feature_windows", [5, 20])))
    split = split_by_date(featured, SplitConfig.from_config(config.get("splits", config.get("split"))))
    if hypothesis_path:
        try:
            hypothesis = load_hypothesis_spec(hypothesis_path)
        except Exception as exc:
            hypothesis = InvalidHypothesis(
                hypothesis_id=f"INVALID-{Path(hypothesis_path).stem}",
                name=f"Invalid hypothesis spec: {hypothesis_path}",
                rationale=str(exc),
                error=str(exc),
                source_path=str(hypothesis_path),
            )
    else:
        hypotheses = {hypothesis.hypothesis_id: hypothesis for hypothesis in generate_hypotheses(config["research"]["max_hypotheses"])}
        if hypothesis_id not in hypotheses:
            raise SystemExit(f"Unknown hypothesis id: {hypothesis_id}")
        hypothesis = hypotheses[hypothesis_id]
    if getattr(hypothesis, "is_invalid", False):
        row = rejected_hypothesis_row(hypothesis=hypothesis, config=config, sequence=1)
    else:
        row = evaluate_hypothesis(hypothesis=hypothesis, split=split, featured=featured, config=config, output_paths=paths, sequence=1)
    ExperimentLedger(paths["ledger"] / "experiments.jsonl").append(row)
    return row


if __name__ == "__main__":
    raise SystemExit(main())
