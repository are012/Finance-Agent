from __future__ import annotations

import math
from decimal import Decimal

import pandas as pd


def compute_metrics(
    equity_curve: pd.DataFrame,
    *,
    trades: pd.DataFrame | None = None,
    orders: pd.DataFrame | None = None,
    periods_per_year: int = 252,
) -> dict[str, float | dict]:
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
    annualized_volatility = math.sqrt(periods_per_year) * volatility if volatility and not math.isnan(volatility) else 0.0
    sharpe = math.sqrt(periods_per_year) * returns.mean() / volatility if volatility and not math.isnan(volatility) else 0.0
    downside = returns[returns < 0].std(ddof=0)
    sortino = math.sqrt(periods_per_year) * returns.mean() / downside if downside and not math.isnan(downside) else 0.0
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else cagr
    win_rate = float((returns > 0).mean()) if len(returns) else 0.0

    trades = trades if trades is not None else pd.DataFrame()
    orders = orders if orders is not None else pd.DataFrame()
    trade_metrics = _trade_metrics(trades)
    turnover = _turnover(orders, equity)
    exposure = _exposure(equity_curve)

    return {
        "total_return": round(float(total_return), 12),
        "cagr": float(cagr),
        "annualized_volatility": float(annualized_volatility),
        "max_drawdown": max_drawdown,
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "calmar": float(calmar),
        "win_rate": win_rate,
        "periods": float(len(equity)),
        "turnover": turnover,
        "exposure": exposure,
        "yearly_returns": yearly_returns(equity_curve),
        **trade_metrics,
    }


def yearly_returns(equity_curve: pd.DataFrame) -> dict[str, float]:
    if equity_curve.empty:
        return {}
    data = equity_curve.copy()
    data["date"] = pd.to_datetime(data["date"])
    result = {}
    for year, group in data.groupby(data["date"].dt.year):
        first = float(group["equity"].iloc[0])
        last = float(group["equity"].iloc[-1])
        result[str(year)] = last / first - 1.0 if first else 0.0
    return result


def _empty_metrics() -> dict[str, float | dict]:
    return {
        "total_return": 0.0,
        "cagr": 0.0,
        "annualized_volatility": 0.0,
        "max_drawdown": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "calmar": 0.0,
        "win_rate": 0.0,
        "periods": 0.0,
        "trade_count": 0.0,
        "average_win": 0.0,
        "average_loss": 0.0,
        "profit_factor": 0.0,
        "average_holding_period": 0.0,
        "turnover": 0.0,
        "exposure": 0.0,
        "yearly_returns": {},
    }


def _trade_metrics(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {
            "trade_count": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "profit_factor": 0.0,
            "average_holding_period": 0.0,
        }
    pnl = trades.get("gross_pnl", pd.Series(dtype=float)).astype(float) - trades.get("costs", 0.0)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_win = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    holding = trades.get("holding_period", pd.Series([0] * len(trades))).astype(float)
    return {
        "trade_count": float(len(trades)),
        "average_win": float(wins.mean()) if len(wins) else 0.0,
        "average_loss": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else (gross_win if gross_win else 0.0),
        "average_holding_period": float(holding.mean()) if len(holding) else 0.0,
    }


def _turnover(orders: pd.DataFrame, equity: pd.Series) -> float:
    if orders.empty or "gross_value" not in orders.columns or equity.empty:
        return 0.0
    filled = orders[orders.get("status", "filled").eq("filled")] if "status" in orders.columns else orders
    average_equity = float(equity.mean()) or 1.0
    return float(filled["gross_value"].abs().sum() / average_equity)


def _exposure(equity_curve: pd.DataFrame) -> float:
    if "positions_value" not in equity_curve.columns or equity_curve.empty:
        return 0.0
    equity = equity_curve["equity"].replace(0, pd.NA)
    exposure = (equity_curve["positions_value"].abs() / equity).fillna(0.0)
    return float(exposure.mean())


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
