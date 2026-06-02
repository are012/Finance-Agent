import pandas as pd

from research.metrics import compute_metrics


def test_metrics_compute_risk_adjusted_values_and_drawdown():
    equity = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "equity": [100.0, 110.0, 105.0, 120.0, 115.0],
        }
    )

    metrics = compute_metrics(equity, periods_per_year=252)

    assert metrics["total_return"] == 0.15
    assert metrics["max_drawdown"] == -0.045454545454545456
    assert metrics["sharpe"] != 0
    assert metrics["calmar"] > 0
