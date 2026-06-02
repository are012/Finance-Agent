import pandas as pd

from research.features import add_chart_features


def test_features_use_only_current_and_past_bars():
    raw = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "symbol": ["AAA"] * 5,
            "open": [10, 11, 12, 13, 14],
            "high": [11, 13, 16, 50, 19],
            "low": [9, 10, 11, 12, 13],
            "close": [10, 12, 15, 16, 18],
            "adjusted_close": [10, 12, 15, 16, 18],
            "volume": [100, 100, 100, 1000, 100],
            "traded_value": [1000, 1200, 1500, 16000, 1800],
            "market": ["KOSPI"] * 5,
        }
    )

    featured = add_chart_features(raw, windows=[2, 3])

    row_3 = featured.loc[featured["date"] == pd.Timestamp("2024-01-03")].iloc[0]
    assert row_3["return_1"] == 0.25
    assert row_3["momentum_2"] == 0.5

    row_4 = featured.loc[featured["date"] == pd.Timestamp("2024-01-04")].iloc[0]
    assert row_4["prior_high_3"] == 16
    assert row_4["high_breakout_3"] is True


def test_features_do_not_emit_future_return_or_forward_columns():
    raw = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "symbol": ["AAA"] * 4,
            "open": [10, 11, 12, 13],
            "high": [11, 13, 16, 17],
            "low": [9, 10, 11, 12],
            "close": [10, 12, 15, 16],
            "adjusted_close": [10, 12, 15, 16],
            "volume": [100, 100, 100, 100],
            "traded_value": [1000, 1200, 1500, 1600],
            "market": ["KOSPI"] * 4,
        }
    )

    featured = add_chart_features(raw, windows=[2])

    forbidden_terms = ("future", "forward", "lead", "target")
    assert not any(term in column for column in featured.columns for term in forbidden_terms)
