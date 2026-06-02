import json
import subprocess
import sys

import pandas as pd
import pytest
import yaml

from research.backtester import backtest_signals
from research.costs import CostModel
from research.critic import critique_experiment
from research.hypothesis import load_hypothesis_spec
from research.ledger import ExperimentLedger
from research.metrics import compute_metrics
from research.schema import validate_ohlcv_frame
from research.scoring import score_candidate
from research.validation import SplitConfig, split_by_date, walk_forward_splits


def _strict_bars(symbol="AAA"):
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, freq="D"),
            "symbol": [symbol] * 6,
            "open": [100, 101, 102, 103, 104, 105],
            "high": [101, 102, 103, 104, 105, 106],
            "low": [99, 100, 101, 102, 103, 104],
            "close": [100, 102, 103, 104, 105, 106],
            "volume": [1000] * 6,
            "traded_value": [100000] * 6,
            "market": ["KOSPI"] * 6,
            "listing_status": ["listed"] * 6,
        }
    )


def test_schema_fills_adjusted_close_deduplicates_and_rejects_impossible_ohlc():
    raw = _strict_bars()
    duplicate = raw.iloc[[0]].copy()
    duplicate["close"] = 100
    deduped = validate_ohlcv_frame(pd.concat([raw, duplicate], ignore_index=True))

    assert "adjusted_close" in deduped.columns
    assert len(deduped) == len(raw)
    assert deduped.iloc[0]["adjusted_close"] == deduped.iloc[0]["close"]

    bad = raw.copy()
    bad.loc[0, "high"] = bad.loc[0, "low"] - 1
    with pytest.raises(ValueError, match="high must be >= low"):
        validate_ohlcv_frame(bad)


def test_date_based_split_and_walk_forward_keep_final_holdout_separate():
    data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=12, freq="D"),
            "symbol": ["AAA"] * 12,
            "close": range(12),
        }
    )

    split = split_by_date(
        data,
        SplitConfig(
            train_start="2024-01-01",
            train_end="2024-01-05",
            validation_start="2024-01-06",
            validation_end="2024-01-09",
            final_holdout_start="2024-01-10",
            final_holdout_end="2024-01-12",
        ),
    )
    windows = walk_forward_splits(split.train, train_size=4, validation_size=1)

    assert split.train["date"].max() < split.validation["date"].min()
    assert split.validation["date"].max() < split.holdout["date"].min()
    assert len(windows) == 1
    assert windows[0].validation["date"].min() > windows[0].train["date"].max()


def test_yaml_hypothesis_spec_validates_chart_only_contract(tmp_path):
    path = tmp_path / "hypothesis.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "id": "H-YAML",
                "idea": "20-bar breakout with chart-only liquidity.",
                "family": "breakout_volume",
                "parameters": {"lookback_bars": 20, "holding_bars": 5, "volume_ratio_min": 1.5},
                "features": ["prior_high_20", "volume_surge_20", "traded_value_ma_20"],
                "entry_rule": {"expression": "close > prior_high_20 and volume_surge_20 >= 0.5"},
                "exit_rule": {"holding_period_days": 5},
                "position_sizing": {"method": "equal_weight", "max_positions": 5, "max_position_pct": 0.2},
                "falsification": {"min_trades": 1, "min_validation_sharpe": 0.0},
            }
        ),
        encoding="utf-8",
    )

    hypothesis = load_hypothesis_spec(path)

    assert hypothesis.hypothesis_id == "H-YAML"
    assert hypothesis.signal_family == "breakout_volume"
    assert hypothesis.to_strategy().parameters["volume_ratio_min"] == 1.5


def test_backtester_rejects_orders_over_liquidity_cap():
    bars = _strict_bars()
    signals = pd.DataFrame(
        {
            "date": bars["date"],
            "symbol": bars["symbol"],
            "target_weight": [1.0] * len(bars),
        }
    )

    result = backtest_signals(
        bars,
        signals,
        initial_cash=1000000.0,
        cost_model=CostModel(commission_rate=0.0, tax_rate=0.0, slippage_bps=0.0),
        liquidity_config={"max_order_pct_of_avg_traded_value": 0.001, "avg_traded_value_lookback": 2, "on_limit": "reject"},
    )

    assert "status" in result.orders.columns
    assert result.orders.iloc[0]["status"] == "rejected"
    assert result.orders.iloc[0]["reason"] == "liquidity_cap"
    assert result.trades.empty


def test_metrics_scoring_and_structured_critic_do_not_reward_raw_return_alone():
    equity = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "equity": [100.0, 150.0, 80.0, 160.0, 120.0],
            "positions_value": [0.0, 100.0, 80.0, 100.0, 0.0],
        }
    )
    trades = pd.DataFrame({"gross_pnl": [100.0, -20.0], "costs": [1.0, 1.0], "symbol": ["A", "B"]})
    orders = pd.DataFrame({"gross_value": [100.0, 120.0], "status": ["filled", "filled"]})

    metrics = compute_metrics(equity, trades=trades, orders=orders)
    score = score_candidate(
        metrics,
        validation_outputs={
            "cost_sensitivity": {"passed": False},
            "parameter_sensitivity": {"passed": False},
            "concentration": {"max_symbol_pnl_share": 0.9},
        },
        gates={"min_trade_count": 10},
    )
    critic = critique_experiment(
        hypothesis_id="H",
        feature_columns=["future_return"],
        metrics=metrics,
        trades_count=2,
        gates={"min_trade_count": 10, "max_mdd": 0.25},
        validation_outputs={"used_final_holdout": True, "cost_sensitivity": {"passed": False}},
    )

    assert "annualized_volatility" in metrics
    assert "turnover" in metrics
    assert score < metrics["total_return"] * 100
    assert critic["status"] == "reject"
    assert {flag["code"] for flag in critic["flags"]} >= {"LOOKAHEAD_RISK", "FINAL_HOLDOUT_CONTAMINATION"}


def test_ledger_records_reconstruction_metadata(tmp_path):
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")

    ledger.append(
        {
            "experiment_id": "e1",
            "hypothesis_id": "h1",
            "status": "WARN",
            "config_snapshot": {"research": {"random_seed": 42}},
            "data_hash": "abc",
            "git_hash": "def",
            "artifacts": {"validation": "artifact.json"},
            "final_holdout_access": {"used_during_research": False, "evaluated": False},
        }
    )

    row = ledger.read_all()[0]
    assert row["config_snapshot"]["research"]["random_seed"] == 42
    assert row["final_holdout_access"]["used_during_research"] is False
    assert row["artifacts"]["validation"] == "artifact.json"


def test_cli_end_to_end_uses_external_hypothesis_and_locks_holdout_once(tmp_path):
    output_dir = tmp_path / "outputs"
    hypothesis_path = "configs/sample_hypothesis.yaml"

    one = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.run_one_hypothesis",
            "--config",
            "configs/example.yaml",
            "--hypothesis",
            hypothesis_path,
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert one.returncode == 0, one.stderr

    research = subprocess.run(
        [sys.executable, "-m", "app.run_research", "--config", "configs/example.yaml", "--output-dir", str(output_dir)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert research.returncode == 0, research.stderr

    report = subprocess.run(
        [sys.executable, "-m", "app.final_report", "--config", "configs/example.yaml", "--output-dir", str(output_dir / "reports")],
        check=False,
        text=True,
        capture_output=True,
    )
    assert report.returncode == 0, report.stderr

    report_again = subprocess.run(
        [sys.executable, "-m", "app.final_report", "--config", "configs/example.yaml", "--output-dir", str(output_dir / "reports")],
        check=False,
        text=True,
        capture_output=True,
    )
    assert report_again.returncode == 0, report_again.stderr

    ledger_rows = [json.loads(line) for line in (output_dir / "ledger" / "experiments.jsonl").read_text().splitlines()]
    summary = json.loads((output_dir / "reports" / "final_report.json").read_text())
    holdout_files = list((output_dir / "reports").glob("holdout_*.json"))

    assert ledger_rows
    assert all(row["final_holdout_access"]["used_during_research"] is False for row in ledger_rows)
    assert summary["decision"] in {"PASS", "FAIL", "NEEDS_MORE_RESEARCH"}
    assert holdout_files
    assert "reused locked result" in (output_dir / "reports" / "final_report.md").read_text()
