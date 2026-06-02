from __future__ import annotations

import math
from decimal import Decimal

import pandas as pd


def compute_metrics(equity_curve: pd.DataFrame, *, periods_per_year: int = 252) -> dict[str, float]:
    if equity_curve.empty:
        return _empty_metrics()

    equity = equity_curve["equity"].astype(float)
    returns = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0 if equity.iloc[0] else 0.0
    max_drawdown = _max_drawdown(equity)

    if len(equity) > 1 and equity.iloc[0] > 0:
        years = max((len(equity) - 1) / periods_per_year, 1 / periods_per_year)
        cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    else:
        cagr = 0.0

    volatility = returns.std(ddof=0)
    sharpe = math.sqrt(periods_per_year) * returns.mean() / volatility if volatility and not math.isnan(volatility) else 0.0
    downside = returns[returns < 0].std(ddof=0)
    sortino = math.sqrt(periods_per_year) * returns.mean() / downside if downside and not math.isnan(downside) else 0.0
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else cagr
    win_rate = float((returns > 0).mean()) if len(returns) else 0.0

    return {
        "total_return": round(float(total_return), 12),
        "cagr": float(cagr),
        "max_drawdown": max_drawdown,
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "calmar": float(calmar),
        "win_rate": win_rate,
        "periods": float(len(equity)),
    }


def _empty_metrics() -> dict[str, float]:
    return {
        "total_return": 0.0,
        "cagr": 0.0,
        "max_drawdown": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "calmar": 0.0,
        "win_rate": 0.0,
        "periods": 0.0,
    }


def _max_drawdown(equity: pd.Series) -> float:
    peak: Decimal | None = None
    worst = Decimal("0")
    for value in equity:
        current = Decimal(str(float(value)))
        if peak is None or current > peak:
            peak = current
        drawdown = current / peak - Decimal("1")
        if drawdown < worst:
            worst = drawdown
    return float(worst)
