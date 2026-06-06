import pandas as pd
import pytest

from research.backtester import backtest_signals
from research.costs import CostModel
from research.hypothesis import generate_hypotheses
from research.strategy import build_signals


def _multi_symbol_bars() -> pd.DataFrame:
    rows = []
    for date in pd.date_range("2024-01-01", periods=6, freq="D"):
        for symbol, offset in (("AAA", 0), ("BBB", 10)):
            close = 100.0 + offset
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "adjusted_close": close,
                    "volume": 1000,
                    "traded_value": 100000,
                    "market": "KOSPI",
                    "momentum_20": 0.1,
                    "traded_value_ma_20": 100000,
                }
            )
    return pd.DataFrame(rows)


def test_build_signals_does_not_scan_full_date_column_per_group(monkeypatch):
    original_eq = pd.Series.__eq__

    def guarded_eq(self, other):
        if self.name == "date":
            raise AssertionError("date groups should be reused instead of rescanning the full frame")
        return original_eq(self, other)

    monkeypatch.setattr(pd.Series, "__eq__", guarded_eq)
    strategy = generate_hypotheses(1)[0].to_strategy()

    signals = build_signals(_multi_symbol_bars(), strategy, max_positions=1)

    assert not signals.empty
    assert set(signals.columns) == {"date", "symbol", "target_weight"}


def test_backtester_does_not_scan_full_date_column_per_bar(monkeypatch):
    original_series_eq = pd.Series.eq

    def guarded_series_eq(self, other, *args, **kwargs):
        if self.name == "date":
            raise AssertionError("daily bars should be reused instead of rescanning the full frame")
        return original_series_eq(self, other, *args, **kwargs)

    monkeypatch.setattr(pd.Series, "eq", guarded_series_eq)
    bars = _multi_symbol_bars()[["date", "symbol", "open", "high", "low", "close", "adjusted_close", "volume", "traded_value", "market"]]
    signals = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, freq="D").repeat(2),
            "symbol": ["AAA", "BBB"] * 6,
            "target_weight": [1.0, 0.0] * 6,
        }
    )

    result = backtest_signals(
        bars,
        signals,
        initial_cash=1000.0,
        cost_model=CostModel(commission_rate=0.0, tax_rate=0.0, slippage_bps=0.0),
    )

    assert not result.equity_curve.empty


def test_backtester_preserves_feature_columns_without_merge(monkeypatch):
    def forbidden_merge(self, *args, **kwargs):
        raise AssertionError("extra chart features should be preserved during validation without a merge")

    monkeypatch.setattr(pd.DataFrame, "merge", forbidden_merge)
    bars = _multi_symbol_bars()
    signals = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, freq="D").repeat(2),
            "symbol": ["AAA", "BBB"] * 6,
            "target_weight": [1.0, 0.0] * 6,
        }
    )

    result = backtest_signals(
        bars,
        signals,
        initial_cash=1000.0,
        cost_model=CostModel(commission_rate=0.0, tax_rate=0.0, slippage_bps=0.0),
    )

    assert not result.orders.empty
