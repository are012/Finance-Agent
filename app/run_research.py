from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.backtester import backtest_signals
from research.costs import CostModel
from research.critic import critique_experiment
from research.data_loader import load_config, load_configured_data
from research.features import add_chart_features
from research.hypothesis import generate_hypotheses
from research.ledger import ExperimentLedger
from research.metrics import compute_metrics
from research.scoring import score_candidate
from research.strategy import build_signals
from research.utils import ensure_output_dirs, utc_stamp
from research.validation import SplitConfig, split_by_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run chart-only hypothesis research.")
    parser.add_argument("--config", default="configs/example.yaml")
    parser.add_argument("--output-dir", default="outputs")
    args = parser.parse_args(argv)

    run_research(config_path=args.config, output_dir=args.output_dir)
    return 0


def run_research(*, config_path: str | Path, output_dir: str | Path) -> Path:
    config = load_config(config_path)
    paths = ensure_output_dirs(output_dir)
    ledger_path = paths["ledger"] / "experiments.jsonl"
    ledger = ExperimentLedger(ledger_path)

    data = load_configured_data(config)
    featured = add_chart_features(data, windows=list(config["research"].get("feature_windows", [5, 20])))
    split = split_by_date(featured, SplitConfig.from_config(config["split"]))
    cost_model = CostModel.from_config(config.get("costs", {}))
    gates = config.get("validation_gates", {})
    budget = int(config["research"].get("budget", 1))
    initial_cash = float(config["research"].get("initial_cash", 1000000))
    max_positions = int(config["research"].get("max_positions", 3))

    for index, hypothesis in enumerate(generate_hypotheses(budget), start=1):
        strategy = hypothesis.to_strategy()
        train_result = _evaluate(split.train, strategy, initial_cash, cost_model, max_positions)
        validation_result = _evaluate(split.validation, strategy, initial_cash, cost_model, max_positions)
        validation_metrics = compute_metrics(validation_result.equity_curve)
        status, findings = critique_experiment(
            hypothesis_id=hypothesis.hypothesis_id,
            feature_columns=list(featured.columns),
            metrics=validation_metrics,
            trades_count=len(validation_result.trades),
            gates=gates,
        )
        score = score_candidate(validation_metrics, gates=gates)
        row = {
            "experiment_id": f"{utc_stamp()}-{index:03d}",
            "hypothesis_id": hypothesis.hypothesis_id,
            "hypothesis": hypothesis.name,
            "status": status,
            "score": score,
            "train_metrics": compute_metrics(train_result.equity_curve),
            "metrics": validation_metrics,
            "validation_trades": len(validation_result.trades),
            "critic_findings": findings,
            "critic_scope": [
                "leakage",
                "overfitting",
                "unrealistic_execution",
                "fragility",
                "data_quality",
            ],
            "data_quality": {
                "rows": int(len(data)),
                "symbols": int(data["symbol"].nunique()),
                "local_csv_only": True,
                "schema_validated": True,
            },
            "execution_model": "signal_at_t_executes_next_bar_open; final_open_positions_liquidated_at_last_close",
            "used_final_holdout": False,
            "strategy": strategy.__dict__,
        }
        ledger.append(row)
        artifact_path = paths["artifacts"] / f"{row['experiment_id']}.json"
        artifact_path.write_text(json.dumps(row, indent=2, sort_keys=True, default=str), encoding="utf-8")
        if status == "PASS":
            break

    return ledger_path


def _evaluate(data, strategy, initial_cash, cost_model, max_positions):
    signals = build_signals(data, strategy, max_positions=max_positions)
    return backtest_signals(data, signals, initial_cash=initial_cash, cost_model=cost_model)


if __name__ == "__main__":
    raise SystemExit(main())
