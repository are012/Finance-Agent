from __future__ import annotations

from math import sqrt

import pandas as pd


def compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.mask(avg_loss == 0.0)
    return (100 - (100 / (1 + rs))).fillna(50.0)


def compute_macd(close: pd.Series, fast_period: int, slow_period: int, signal_period: int) -> tuple[pd.Series, pd.Series]:
    fast_ema = close.ewm(span=fast_period, adjust=False).mean()
    slow_ema = close.ewm(span=slow_period, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    return macd_line, signal_line


def rsi_mean_reversion_positions(
    close: pd.Series,
    rsi_period: int,
    oversold_threshold: float,
    exit_threshold: float,
    position_size: float,
) -> pd.Series:
    rsi = compute_rsi(close, rsi_period)

    positions: list[float] = []
    current_position = 0.0
    for value in rsi:
        if current_position == 0.0 and value <= oversold_threshold:
            current_position = position_size
        elif current_position > 0.0 and value >= exit_threshold:
            current_position = 0.0
        positions.append(current_position)

    return pd.Series(positions, index=close.index, dtype=float)


def macd_trend_positions(
    close: pd.Series,
    fast_period: int,
    slow_period: int,
    signal_period: int,
    position_size: float,
) -> pd.Series:
    macd_line, signal_line = compute_macd(close, fast_period, slow_period, signal_period)
    positions = pd.Series(0.0, index=close.index, dtype=float)
    positions.loc[macd_line > signal_line] = position_size
    return positions


def bollinger_mean_reversion_positions(
    close: pd.Series,
    lookback_period: int,
    band_width: float,
    position_size: float,
) -> pd.Series:
    mean = close.rolling(window=lookback_period).mean()
    std = close.rolling(window=lookback_period).std(ddof=0)
    lower_band = mean - (std * band_width)

    positions: list[float] = []
    current_position = 0.0
    for current_close, mid, lower in zip(close, mean, lower_band):
        if pd.isna(mid) or pd.isna(lower):
            positions.append(0.0)
            continue

        if current_position == 0.0 and current_close <= lower:
            current_position = position_size
        elif current_position > 0.0 and current_close >= mid:
            current_position = 0.0
        positions.append(current_position)

    return pd.Series(positions, index=close.index, dtype=float)


def strategy_returns_from_positions(close: pd.Series, positions: pd.Series) -> pd.Series:
    asset_returns = close.pct_change().fillna(0.0)
    return positions.shift(1).fillna(0.0) * asset_returns


def score_strategy_window(returns: pd.Series) -> float:
    if returns.empty:
        return float("-inf")

    clean_returns = returns.fillna(0.0)
    equity_curve = (1.0 + clean_returns).cumprod()
    total_return = float(equity_curve.iloc[-1] - 1.0)
    drawdown = equity_curve / equity_curve.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    daily_std = float(clean_returns.std(ddof=0))
    sharpe_ratio = 0.0 if daily_std == 0.0 else float((clean_returns.mean() / daily_std) * sqrt(252))

    return total_return - (abs(max_drawdown) * 0.35) + (sharpe_ratio * 0.03)


def normalize_strategy_weights(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}

    best_key = max(scores, key=scores.get)
    positive_scores = {key: max(value, 0.0) for key, value in scores.items()}
    total = sum(positive_scores.values())

    if total <= 0.0:
        return {key: 1.0 if key == best_key else 0.0 for key in scores}

    return {key: value / total for key, value in positive_scores.items()}
