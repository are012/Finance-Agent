from __future__ import annotations

import argparse
from pathlib import Path

from research.backtester import backtest_signals
from research.costs import CostModel
from research.data_loader import load_config, load_configured_data
from research.features import add_chart_features
from research.hypothesis import generate_hypotheses
from research.metrics import compute_metrics
from research.strategy import build_signals
from research.validation import SplitConfig, split_by_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic chart-only hypothesis.")
    parser.add_argument("--config", default="configs/example.yaml")
    parser.add_argument("--hypothesis-id", required=True)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    data = add_chart_features(load_configured_data(config), windows=list(config["research"].get("feature_windows", [5, 20])))
    split = split_by_date(data, SplitConfig.from_config(config["split"]))
    hypotheses = {hypothesis.hypothesis_id: hypothesis for hypothesis in generate_hypotheses(config["research"]["budget"])}
    if args.hypothesis_id not in hypotheses:
        raise SystemExit(f"Unknown hypothesis id: {args.hypothesis_id}")
    strategy = hypotheses[args.hypothesis_id].to_strategy()
    signals = build_signals(split.validation, strategy, max_positions=int(config["research"].get("max_positions", 3)))
    result = backtest_signals(
        split.validation,
        signals,
        initial_cash=float(config["research"].get("initial_cash", 1000000)),
        cost_model=CostModel.from_config(config.get("costs", {})),
    )
    print(compute_metrics(result.equity_curve))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
