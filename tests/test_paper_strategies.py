import json
import subprocess
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest
import yaml

from research.features import add_chart_features
from research.paper_strategies import load_paper_strategy_template, load_paper_strategy_templates


def _paper_payload(**overrides):
    payload = {
        "id": "paper-test-momentum",
        "name": "Paper-inspired chart momentum",
        "source_type": "paper_inspired",
        "paper_id": "TEST_MOMENTUM_CHART_ONLY",
        "paper_reference": {
            "title": "Test chart-only momentum reference",
            "authors": ["Example"],
            "year": 2026,
            "needs_verification": True,
        },
        "idea": "Use only local OHLCV momentum and traded-value liquidity.",
        "strategy_family": "formula_rank",
        "features": ["momentum_20", "traded_value_ma_20"],
        "formula": {
            "score": "rank(momentum_20) + rank(traded_value_ma_20)",
            "entry": "momentum_20 > 0 and traded_value_ma_20 >= 100000",
        },
        "parameters": {"lookback_bars": 20, "holding_bars": 5, "min_traded_value": 100000},
        "position_sizing": {"method": "equal_weight", "max_positions": 3, "max_position_pct": 0.34},
        "falsification": {"min_trades": 1, "min_validation_sharpe": -10.0, "max_validation_mdd": 0.95},
        "data_requirements": {
            "required": ["open", "high", "low", "close", "adjusted_close", "volume", "traded_value"],
            "allowed": ["local OHLCV", "chart-derived momentum", "traded-value liquidity"],
            "disallowed": ["fundamentals", "earnings", "news", "analyst", "macro", "investor-flow", "final_holdout"],
        },
        "implementation_notes": ["Paper effect is adapted into a chart-only long-only KRX hypothesis."],
        "implementation_caveats": ["This is not exact paper replication and must be validated on KRX data."],
    }
    payload.update(overrides)
    return payload


def _write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_paper_strategy_template_loads_chart_only_metadata(tmp_path):
    template_path = _write_yaml(tmp_path / "paper.yaml", _paper_payload())

    hypothesis = load_paper_strategy_template(template_path)

    assert hypothesis.source_type == "paper_inspired"
    assert hypothesis.paper_id == "TEST_MOMENTUM_CHART_ONLY"
    assert hypothesis.paper_reference["needs_verification"] is True
    assert "traded-value liquidity" in hypothesis.data_requirements["allowed"]
    assert hypothesis.formula_metadata["complexity_score"] > 0
    assert hypothesis.to_dict()["implementation_caveats"]


def test_paper_strategy_template_rejects_forbidden_required_data(tmp_path):
    payload = _paper_payload(
        data_requirements={
            "required": ["open", "close", "eps_growth"],
            "allowed": ["local OHLCV"],
            "disallowed": ["fundamentals", "earnings"],
        }
    )
    template_path = _write_yaml(tmp_path / "bad.yaml", payload)

    with pytest.raises(ValueError, match="Forbidden non-chart data"):
        load_paper_strategy_template(template_path)


def test_paper_strategy_template_rejects_forbidden_formula_terms(tmp_path):
    payload = _paper_payload(
        features=["momentum_20", "traded_value_ma_20", "analyst_rating"],
        formula={"score": "rank(analyst_rating)", "entry": "analyst_rating > 0"},
    )
    template_path = _write_yaml(tmp_path / "bad_formula.yaml", payload)

    with pytest.raises(ValueError, match="Forbidden"):
        load_paper_strategy_template(template_path)


def test_configured_paper_strategy_library_contains_required_templates():
    templates = load_paper_strategy_templates("configs/paper_strategies")
    ids = {hypothesis.paper_id for hypothesis in templates}

    assert {
        "CROSS_SECTIONAL_MOMENTUM_12M",
        "TIME_SERIES_MOMENTUM_12M",
        "FIFTY_TWO_WEEK_HIGH_MOMENTUM",
        "LOW_VOLATILITY_MOMENTUM",
        "SHORT_TERM_REVERSAL",
        "VOLATILITY_CONTRACTION_BREAKOUT",
        "PRICE_VOLUME_MOMENTUM",
        "LIQUIDITY_FILTERED_MOMENTUM",
        "MULTI_HORIZON_MOMENTUM",
    }.issubset(ids)
    assert all(hypothesis.source_type == "paper_inspired" for hypothesis in templates)
    assert all(hypothesis.data_requirements.get("required") for hypothesis in templates)


def test_paper_strategy_features_include_long_horizon_chart_only_columns():
    rows = []
    dates = pd.date_range("2023-01-01", periods=260, freq="D")
    for index, date in enumerate(dates):
        close = 100.0 + index
        rows.append(
            {
                "date": date,
                "symbol": "AAA",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "adjusted_close": close,
                "volume": 1000 + index,
                "traded_value": close * (1000 + index),
                "market": "KOSPI",
            }
        )

    featured = add_chart_features(pd.DataFrame(rows), windows=[20, 60, 120, 252])
    latest = featured.iloc[-1]

    assert {"prior_high_120", "prior_high_252", "distance_to_52w_high", "multi_horizon_momentum_agreement"}.issubset(
        featured.columns
    )
    assert latest["distance_to_52w_high"] == pytest.approx(latest["close"] / latest["prior_high_252"] - 1.0)
    assert latest["multi_horizon_momentum_agreement"] == pytest.approx(1.0)
    forbidden_terms = ("future", "forward", "lead", "target")
    assert not any(term in column for column in featured.columns for term in forbidden_terms)


def test_extended_paper_feature_windows_do_not_fragment_frames():
    rows = []
    dates = pd.date_range("2023-01-01", periods=260, freq="D")
    for index, date in enumerate(dates):
        close = 100.0 + index
        rows.append(
            {
                "date": date,
                "symbol": "AAA",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "adjusted_close": close,
                "volume": 1000 + index,
                "traded_value": close * (1000 + index),
                "market": "KOSPI",
            }
        )

    with warnings.catch_warnings():
        warnings.simplefilter("error", pd.errors.PerformanceWarning)
        featured = add_chart_features(pd.DataFrame(rows), windows=[3, 5, 10, 15, 20, 25, 60, 120, 252])

    assert "distance_to_52w_high" in featured.columns


def test_paper_inspired_end_to_end_run_records_ledger_tags(tmp_path):
    hypothesis_path = _write_yaml(tmp_path / "paper.yaml", _paper_payload())
    output_dir = tmp_path / "outputs"

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
    rows = [json.loads(line) for line in (output_dir / "ledger" / "experiments.jsonl").read_text().splitlines()]
    row = rows[-1]
    assert row["source_type"] == "paper_inspired"
    assert row["paper_id"] == "TEST_MOMENTUM_CHART_ONLY"
    assert row["formula_complexity"] > 0
    assert row["data_requirements"]["required"]
    assert row["hypothesis"]["implementation_notes"]
    assert row["validation_outputs"]["used_final_holdout"] is False
    assert row["final_holdout_access"]["used_during_research"] is False
