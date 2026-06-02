import pandas as pd

from research.backtester import backtest_signals
from research.costs import CostModel


def test_backtester_executes_signals_on_next_bar_open():
    bars = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "symbol": ["AAA"] * 4,
            "open": [100.0, 110.0, 120.0, 130.0],
            "high": [101.0, 111.0, 121.0, 131.0],
            "low": [99.0, 109.0, 119.0, 129.0],
            "close": [100.0, 115.0, 125.0, 135.0],
            "adjusted_close": [100.0, 115.0, 125.0, 135.0],
            "volume": [1000, 1000, 1000, 1000],
            "traded_value": [100000, 115000, 125000, 135000],
            "market": ["KOSPI"] * 4,
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "symbol": ["AAA"] * 4,
            "target_weight": [1.0, 0.0, 0.0, 0.0],
        }
    )

    result = backtest_signals(
        bars,
        signals,
        initial_cash=1100.0,
        cost_model=CostModel(commission_rate=0.0, tax_rate=0.0, slippage_bps=0.0),
    )

    trade = result.trades.iloc[0]
    assert trade["entry_date"] == pd.Timestamp("2024-01-02")
    assert trade["entry_price"] == 110.0
    assert trade["exit_date"] == pd.Timestamp("2024-01-03")
    assert trade["exit_price"] == 120.0
    assert trade["quantity"] == 10
    assert result.equity_curve.iloc[-1]["equity"] == 1200.0


def test_backtester_liquidates_open_position_at_final_close():
    bars = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "symbol": ["AAA"] * 3,
            "open": [100.0, 110.0, 120.0],
            "high": [101.0, 111.0, 121.0],
            "low": [99.0, 109.0, 119.0],
            "close": [100.0, 115.0, 125.0],
            "adjusted_close": [100.0, 115.0, 125.0],
            "volume": [1000, 1000, 1000],
            "traded_value": [100000, 115000, 125000],
            "market": ["KOSPI"] * 3,
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "symbol": ["AAA"] * 3,
            "target_weight": [1.0, 1.0, 1.0],
        }
    )

    result = backtest_signals(
        bars,
        signals,
        initial_cash=1100.0,
        cost_model=CostModel(commission_rate=0.0, tax_rate=0.0, slippage_bps=0.0),
    )

    trade = result.trades.iloc[0]
    assert trade["entry_date"] == pd.Timestamp("2024-01-02")
    assert trade["exit_date"] == pd.Timestamp("2024-01-03")
    assert trade["exit_price"] == 125.0
    assert result.equity_curve.iloc[-1]["cash"] == 1250.0
    assert result.equity_curve.iloc[-1]["equity"] == 1250.0
