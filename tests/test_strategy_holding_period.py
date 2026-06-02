import pandas as pd

from research.hypothesis import generate_hypotheses
from research.strategy import build_signals


def test_strategy_honors_holding_period_without_extending_existing_position():
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    featured = pd.DataFrame(
        {
            "date": dates,
            "symbol": ["AAA"] * 6,
            "open": [10] * 6,
            "high": [11] * 6,
            "low": [9] * 6,
            "close": [10] * 6,
            "adjusted_close": [10] * 6,
            "volume": [100] * 6,
            "traded_value": [1000] * 6,
            "market": ["KOSPI"] * 6,
            "momentum_20": [0.1] * 6,
            "traded_value_ma_20": [1000] * 6,
        }
    )
    strategy = generate_hypotheses(1)[0].to_strategy()

    signals = build_signals(featured, strategy, max_positions=1)

    assert list(signals["target_weight"]) == [1.0, 1.0, 1.0, 0.0, 1.0, 1.0]
