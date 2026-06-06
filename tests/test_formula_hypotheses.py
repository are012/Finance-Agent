import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from research.backtester import backtest_signals
from research.costs import CostModel
from research.formula import FormulaValidationError, formula_fingerprint, validate_formula_spec
from research.hypothesis import InvalidHypothesis, hypothesis_from_spec, load_hypotheses_from_config, load_hypothesis_spec
from research.strategy import StrategySpec, build_signals


def _formula_frame() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    for index, date in enumerate(dates):
        for symbol, base in (("AAA", 100.0), ("BBB", 90.0), ("CCC", 80.0)):
            momentum = {"AAA": 0.12, "BBB": 0.04, "CCC": -0.03}[symbol]
            close = base + index
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close + 0.5,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "adjusted_close": close,
                    "volume": 1000 + index,
                    "traded_value": 100000 + index,
                    "market": "KOSPI",
                    "momentum_5": momentum,
                    "momentum_20": momentum,
                    "rsi_5": {"AAA": 45.0, "BBB": 48.0, "CCC": 55.0}[symbol],
                    "traded_value_ma_5": {"AAA": 300000.0, "BBB": 200000.0, "CCC": 150000.0}[symbol],
                    "traded_value_ma_20": {"AAA": 300000.0, "BBB": 200000.0, "CCC": 150000.0}[symbol],
                    "volume_ratio_5": {"AAA": 1.3, "BBB": 1.1, "CCC": 0.8}[symbol],
                }
            )
    return pd.DataFrame(rows)


def _rank_payload(**overrides):
    payload = {
        "id": "formula-rank-001",
        "name": "Simple formula rank",
        "idea": "Rank liquid positive momentum names with volume confirmation.",
        "strategy_family": "formula_rank",
        "features": ["momentum_5", "volume_ratio_5", "traded_value_ma_5"],
        "formula": {
            "score": "rank(momentum_5) + rank(volume_ratio_5)",
            "entry": "momentum_5 > 0 and traded_value_ma_5 >= 100000",
            "exit": "momentum_5 < 0",
        },
        "parameters": {"lookback_bars": 5, "holding_bars": 3},
        "position_sizing": {"method": "equal_weight", "max_positions": 2, "max_position_pct": 0.5},
        "cost_model": {"commission_bps": 1.5, "sell_tax_bps": 20, "slippage_bps": 5},
        "falsification": {"min_trades": 1},
        "notes": ["Formula proposed from persistent momentum and liquidity evidence."],
    }
    payload.update(overrides)
    return payload


def test_valid_formula_hypothesis_parses_and_records_metadata():
    hypothesis = hypothesis_from_spec(_rank_payload())

    assert hypothesis.signal_family == "formula_rank"
    assert hypothesis.formula["score"] == "rank(momentum_5) + rank(volume_ratio_5)"
    assert hypothesis.formula_metadata["complexity_score"] > 0
    assert hypothesis.formula_metadata["hash"] == formula_fingerprint(hypothesis.formula)


def test_formula_rejects_forbidden_feature_terms():
    payload = _rank_payload(features=["momentum_5", "eps_growth"], formula={"score": "rank(eps_growth)", "entry": "eps_growth > 0"})

    with pytest.raises(ValueError, match="Forbidden"):
        hypothesis_from_spec(payload)


def test_formula_rejects_unsupported_operator_and_python_execution(tmp_path):
    with pytest.raises(FormulaValidationError, match="Unsupported formula syntax"):
        validate_formula_spec({"score": "momentum_5 ** 2", "entry": "momentum_5 > 0"}, declared_features=["momentum_5"])

    target = tmp_path / "executed"
    with pytest.raises(FormulaValidationError):
        validate_formula_spec(
            {"score": f"__import__('pathlib').Path('{target}').write_text('bad')", "entry": "momentum_5 > 0"},
            declared_features=["momentum_5"],
        )
    assert not target.exists()


def test_formula_rejects_excessive_depth_and_undeclared_features():
    too_deep = "clip(clip(clip(clip(clip(clip(momentum_5, -1, 1), -1, 1), -1, 1), -1, 1), -1, 1), -1, 1)"

    with pytest.raises(FormulaValidationError, match="depth"):
        validate_formula_spec({"score": too_deep, "entry": "momentum_5 > 0"}, declared_features=["momentum_5"], max_depth=5)
    with pytest.raises(FormulaValidationError, match="Unsupported feature"):
        validate_formula_spec({"score": "rank(momentum_5)", "entry": "custom_factor > 0"}, declared_features=["momentum_5"])


def test_formula_allows_zscore_and_clip_but_limits_constants():
    metadata = validate_formula_spec(
        {"score": "clip(zscore(momentum_5, 5), -2, 2)", "entry": "momentum_5 > 0"},
        declared_features=["momentum_5"],
    )
    assert metadata["features"] == ["momentum_5"]
    assert "clip" in metadata["operators"]
    assert "zscore" in metadata["operators"]

    with pytest.raises(FormulaValidationError, match="too many constants"):
        validate_formula_spec(
            {"score": "momentum_5 + 1 + 2 + 3", "entry": "momentum_5 > 0"},
            declared_features=["momentum_5"],
            max_constants=2,
        )
    with pytest.raises(FormulaValidationError, match="too many features"):
        validate_formula_spec(
            {"score": "momentum_5 + volume_ratio_5", "entry": "momentum_5 > 0"},
            declared_features=["momentum_5", "volume_ratio_5"],
            max_features=1,
        )


def test_rank_formula_generates_long_only_top_rank_signals():
    strategy = hypothesis_from_spec(_rank_payload()).to_strategy()

    signals = build_signals(_formula_frame(), strategy, max_positions=2)
    first_day = signals[signals["date"].eq(pd.Timestamp("2024-01-01"))]

    assert set(first_day[first_day["target_weight"] > 0]["symbol"]) == {"AAA", "BBB"}
    assert first_day["target_weight"].max() == pytest.approx(0.5)


def test_signal_builder_revalidates_direct_formula_strategy_specs():
    strategy = StrategySpec(
        hypothesis_id="manual-bad-formula",
        name="Manual unsafe formula",
        signal_family="formula_rank",
        lookback_bars=5,
        holding_bars=3,
        required_features=["momentum_5"],
        formula={"score": "rank(momentum_5, x=1)", "entry": "momentum_5 > 0"},
    )

    with pytest.raises(FormulaValidationError, match="keyword arguments"):
        build_signals(_formula_frame(), strategy, max_positions=1)


def test_boolean_formula_rule_entry_exit_and_next_open_execution():
    payload = _rank_payload(
        id="formula-rule-001",
        strategy_family="formula_rule",
        features=["momentum_5", "rsi_5", "traded_value_ma_5"],
        formula={"entry": "momentum_5 > 0 and rsi_5 < 50", "exit": "momentum_5 < 0"},
    )
    strategy = hypothesis_from_spec(payload).to_strategy()
    signals = build_signals(_formula_frame(), strategy, max_positions=1)

    first_day = signals[signals["date"].eq(pd.Timestamp("2024-01-01"))]
    assert set(first_day[first_day["target_weight"] > 0]["symbol"]) == {"AAA"}

    result = backtest_signals(
        _formula_frame(),
        signals,
        initial_cash=1000.0,
        cost_model=CostModel(commission_rate=0.0, tax_rate=0.0, slippage_bps=0.0),
        force_liquidate_at_end=False,
    )
    assert not result.orders.empty
    assert pd.Timestamp(result.orders.iloc[0]["date"]) == pd.Timestamp("2024-01-02")


def test_duplicate_formula_specs_are_rejected_when_loading_config(tmp_path):
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text(yaml.safe_dump(_rank_payload(id="formula-a")), encoding="utf-8")
    second.write_text(yaml.safe_dump(_rank_payload(id="formula-b")), encoding="utf-8")
    config = {
        "hypotheses": {"paths": [str(first), str(second)], "include_builtin": False},
        "research": {"max_hypotheses": 2},
    }

    hypotheses = load_hypotheses_from_config(config)

    assert not getattr(hypotheses[0], "is_invalid", False)
    assert isinstance(hypotheses[1], InvalidHypothesis)
    assert "Duplicate formula" in hypotheses[1].error


def test_formula_end_to_end_run_records_ledger_metadata(tmp_path):
    hypothesis_path = tmp_path / "formula.yaml"
    output_dir = tmp_path / "outputs"
    hypothesis_path.write_text(yaml.safe_dump(_rank_payload()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.run_one_hypothesis",
            "--config",
            "configs/example.yaml",
            "--hypothesis",
            str(hypothesis_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    ledger_rows = [json.loads(line) for line in (output_dir / "ledger" / "experiments.jsonl").read_text().splitlines()]
    row = ledger_rows[-1]
    assert row["strategy_family"] == "formula_rank"
    assert row["strategy"]["formula"]["hash"]
    assert row["validation_outputs"]["formula"]["complexity_score"] > 0
    assert row["tested_formula_count"] == 1
    assert row["final_holdout_access"]["used_during_research"] is False


def test_existing_builtin_strategy_compatibility_remains_unchanged():
    strategy = load_hypothesis_spec("configs/hypotheses/momentum_20.yaml").to_strategy()

    signals = build_signals(_formula_frame(), strategy, max_positions=1)

    assert not signals.empty
