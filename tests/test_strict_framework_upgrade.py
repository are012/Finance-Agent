import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from app.run_one_hypothesis import run_one_hypothesis
from app.run_research import run_research
from research.backtester import backtest_signals
from research.costs import CostModel
from research.critic import critique_experiment
from research.data_loader import load_config, load_configured_data
from research.features import add_chart_features
from research.hypothesis import generate_hypotheses, load_hypothesis_spec
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


def test_sample_hypothesis_directory_and_builtin_family_names_match_spec():
    sample_path = Path("configs/hypotheses/momentum_20.yaml")

    hypothesis = load_hypothesis_spec(sample_path)
    builtin_families = {candidate.signal_family for candidate in generate_hypotheses(20)}

    assert hypothesis.hypothesis_id == "momentum_20"
    assert hypothesis.signal_family == "momentum"
    assert {
        "breakout_volume",
        "ma_trend",
        "short_reversal",
        "volatility_contraction_breakout",
        "gap_continuation",
        "gap_reversal",
        "rsi_mean_reversion",
        "price_volume_momentum",
        "traded_value_momentum",
    }.issubset(builtin_families)


def test_all_builtin_hypotheses_use_example_config_feature_windows():
    config = load_config("configs/example.yaml")
    featured = add_chart_features(load_configured_data(config), windows=config["research"]["feature_windows"])
    available_features = set(featured.columns)

    for hypothesis in generate_hypotheses(20):
        assert set(hypothesis.required_features).issubset(available_features), hypothesis.hypothesis_id


def test_hypothesis_validation_rejects_missing_entry_or_exit_rules(tmp_path):
    missing_entry = tmp_path / "missing_entry.yaml"
    missing_entry.write_text(
        yaml.safe_dump(
            {
                "id": "H-MISSING-ENTRY",
                "idea": "A momentum idea without an entry rule is incomplete.",
                "strategy_family": "momentum",
                "parameters": {"lookback_bars": 20, "holding_bars": 3},
                "features": ["momentum_20", "traded_value_ma_20"],
                "exit_rule": {"holding_period_days": 3},
            }
        ),
        encoding="utf-8",
    )
    missing_exit = tmp_path / "missing_exit.yaml"
    missing_exit.write_text(
        yaml.safe_dump(
            {
                "id": "H-MISSING-EXIT",
                "idea": "A momentum idea without an exit rule is incomplete.",
                "strategy_family": "momentum",
                "parameters": {"lookback_bars": 20, "holding_bars": 3},
                "features": ["momentum_20", "traded_value_ma_20"],
                "entry_rule": {"expression": "momentum_20 > 0"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="entry_rule"):
        load_hypothesis_spec(missing_entry)
    with pytest.raises(ValueError, match="exit_rule"):
        load_hypothesis_spec(missing_exit)


def test_research_loop_logs_invalid_hypothesis_and_continues(tmp_path):
    config = yaml.safe_load(Path("configs/example.yaml").read_text(encoding="utf-8"))
    config["hypotheses"] = {"paths": [str(tmp_path / "missing.yaml")], "include_builtin": False}
    config["research"]["max_hypotheses"] = 1
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    ledger_path = run_research(config_path=config_path, output_dir=tmp_path / "outputs")

    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["hypothesis_id"].startswith("INVALID-")
    assert rows[0]["critic"]["flags"][0]["code"] == "INVALID_HYPOTHESIS"


def test_one_hypothesis_logs_invalid_hypothesis_path(tmp_path):
    invalid_path = tmp_path / "invalid.yaml"
    invalid_path.write_text(
        yaml.safe_dump(
            {
                "id": "H-INVALID-ONE",
                "idea": "Missing exit rule should be logged instead of crashing.",
                "strategy_family": "momentum",
                "features": ["momentum_20", "traded_value_ma_20"],
                "entry_rule": {"expression": "momentum_20 > 0"},
                "parameters": {"lookback_bars": 20, "holding_bars": 3},
            }
        ),
        encoding="utf-8",
    )

    row = run_one_hypothesis(
        config_path="configs/example.yaml",
        hypothesis_path=invalid_path,
        output_dir=tmp_path / "outputs",
    )

    ledger_rows = [json.loads(line) for line in (tmp_path / "outputs" / "ledger" / "experiments.jsonl").read_text().splitlines()]
    assert row["status"] == "FAIL"
    assert ledger_rows[0]["hypothesis_id"].startswith("INVALID-")
    assert ledger_rows[0]["critic"]["flags"][0]["code"] == "INVALID_HYPOTHESIS"


def test_research_loop_records_real_walk_forward_and_parameter_sensitivity(tmp_path):
    ledger_path = run_research(config_path="configs/example.yaml", output_dir=tmp_path / "outputs")

    first_row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])
    walk_forward = first_row["validation_outputs"]["walk_forward"]
    parameter_sensitivity = first_row["validation_outputs"]["parameter_sensitivity"]

    assert walk_forward["window_count"] > 0
    assert walk_forward["rows"]
    assert {"train_metrics", "validation_metrics", "validation_trades"}.issubset(walk_forward["rows"][0])
    assert "deferred" not in json.dumps(walk_forward).lower()
    assert parameter_sensitivity["variant_count"] > 0
    assert parameter_sensitivity["rows"]
    assert {"parameters", "metrics", "trade_count", "status"}.issubset(parameter_sensitivity["rows"][0])
    assert "placeholder" not in json.dumps(parameter_sensitivity).lower()


def test_structured_critic_covers_remaining_risk_codes():
    critic = critique_experiment(
        hypothesis_id="H-RISK",
        feature_columns=["pe_ratio", "future_return", "foreign_net_buy"],
        metrics={"periods": 30, "max_drawdown": -0.01, "turnover": 1.0, "sharpe": 1.0},
        trades_count=5,
        gates={"min_trade_count": 1},
        config={
            "backtest": {"signal_timing": "close", "execution_timing": "same_close", "allow_same_bar_execution": True},
            "costs": {"commission_bps": 0},
            "universe": {"survivorship_bias_risk": True},
        },
        validation_outputs={
            "schema": {"inconsistencies": ["filled missing adjusted_close from close"]},
            "liquidity": {"rejected_order_count": 2, "partial_fill_count": 1},
            "concentration": {"max_symbol_pnl_share": 0.2, "max_year_pnl_share": 0.95, "top_trade_pnl_share": 0.1},
        },
    )

    codes = {flag["code"] for flag in critic["flags"]}
    assert {
        "SAME_BAR_EXECUTION_RISK",
        "SURVIVORSHIP_BIAS_RISK",
        "MISSING_COST_ASSUMPTION",
        "FORBIDDEN_DATA",
        "SCHEMA_INCONSISTENCY",
        "UNREALISTIC_EXECUTION",
        "ILLIQUID_EXECUTION",
        "PROFIT_CONCENTRATION",
    }.issubset(codes)


def test_final_report_contains_required_research_sections(tmp_path):
    ledger_path = run_research(config_path="configs/example.yaml", output_dir=tmp_path / "outputs")
    report_dir = tmp_path / "outputs" / "reports"

    report = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.final_report",
            "--config",
            "configs/example.yaml",
            "--ledger",
            str(ledger_path),
            "--output-dir",
            str(report_dir),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert report.returncode == 0, report.stderr

    summary = json.loads((report_dir / "final_report.json").read_text(encoding="utf-8"))
    markdown = (report_dir / "final_report.md").read_text(encoding="utf-8")

    for key in [
        "research_objective",
        "data_assumptions",
        "allowed_data",
        "forbidden_data",
        "schema_summary",
        "split_ranges",
        "selected_strategy_parameters",
        "train_metrics",
        "validation_metrics",
        "yearly_results",
        "trade_count",
        "turnover",
        "exposure",
        "cost_sensitivity",
        "parameter_sensitivity",
        "concentration_analysis",
        "walk_forward_summary",
        "critic_flags",
        "overfitting_controls",
        "limitations",
        "final_conclusion",
    ]:
        assert key in summary
    assert summary["final_conclusion"] in {"PASS", "FAIL", "NEEDS_MORE_RESEARCH"}
    for heading in [
        "## Research Objective",
        "## Data Assumptions",
        "## Schema Summary",
        "## Split Ranges",
        "## Selected Strategy Parameters",
        "## Train Metrics",
        "## Yearly Results",
        "## Cost Sensitivity",
        "## Parameter Sensitivity",
        "## Walk-Forward Summary",
        "## Critic Flags",
        "## Final Conclusion",
    ]:
        assert heading in markdown


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
    hypothesis_path = "configs/hypotheses/momentum_20.yaml"

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
