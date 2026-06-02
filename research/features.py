from __future__ import annotations

import numpy as np
import pandas as pd

from research.schema import validate_ohlcv_frame


FEATURE_EXTRA_COLUMNS = {
    "return_1",
    "log_return_1",
    "gap_return",
    "intraday_range",
    "candle_body",
    "upper_wick",
    "lower_wick",
    "typical_price",
    "vwap_proxy",
}


def add_chart_features(frame: pd.DataFrame, *, windows: list[int] | None = None) -> pd.DataFrame:
    windows = windows or [5, 20]
    input_attrs = dict(getattr(frame, "attrs", {}))
    data = validate_ohlcv_frame(frame)
    if "listing_status_profile" in input_attrs:
        data.attrs["listing_status_profile"] = input_attrs["listing_status_profile"]
    if "schema_decisions" in input_attrs:
        data.attrs["schema_decisions"] = input_attrs["schema_decisions"]
    pieces = []
    for _, group in data.groupby("symbol", sort=False):
        pieces.append(_add_symbol_features(group.copy(), windows))
    featured = pd.concat(pieces, ignore_index=True)
    featured = featured.sort_values(["symbol", "date"]).reset_index(drop=True)
    featured.attrs["schema_decisions"] = list(data.attrs.get("schema_decisions", []))
    featured.attrs["listing_status_profile"] = data.attrs.get("listing_status_profile", {})
    return featured


def _add_symbol_features(group: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    close = group["adjusted_close"]
    prev_close = close.shift(1)

    group["return_1"] = close.pct_change()
    group["log_return_1"] = np.log(close / prev_close)
    group["gap_return"] = group["open"] / prev_close - 1.0
    group["intraday_range"] = (group["high"] - group["low"]) / group["open"]
    group["candle_body"] = (group["close"] - group["open"]) / group["open"]
    group["upper_wick"] = (group["high"] - group[["open", "close"]].max(axis=1)) / group["open"]
    group["lower_wick"] = (group[["open", "close"]].min(axis=1) - group["low"]) / group["open"]
    group["typical_price"] = (group["high"] + group["low"] + group["close"]) / 3.0
    group["vwap_proxy"] = group["traded_value"] / group["volume"].replace(0, np.nan)

    true_range = pd.concat(
        [
            group["high"] - group["low"],
            (group["high"] - prev_close).abs(),
            (group["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    for window in windows:
        group[f"ma_{window}"] = close.rolling(window, min_periods=window).mean()
        group[f"ma_distance_{window}"] = close / group[f"ma_{window}"] - 1.0
        group[f"momentum_{window}"] = close / close.shift(window) - 1.0
        group[f"reversal_{window}"] = -group[f"return_1"].rolling(window, min_periods=window).sum()
        group[f"volatility_{window}"] = group["return_1"].rolling(window, min_periods=window).std()
        group[f"atr_{window}"] = true_range.rolling(window, min_periods=window).mean()
        group[f"volume_ma_{window}"] = group["volume"].rolling(window, min_periods=window).mean()
        group[f"volume_surge_{window}"] = group["volume"] / group[f"volume_ma_{window}"] - 1.0
        group[f"volume_ratio_{window}"] = group["volume"] / group[f"volume_ma_{window}"]
        group[f"traded_value_ma_{window}"] = group["traded_value"].rolling(window, min_periods=window).mean()
        group[f"prior_high_{window}"] = group["high"].shift(1).rolling(window, min_periods=window).max()
        group[f"prior_low_{window}"] = group["low"].shift(1).rolling(window, min_periods=window).min()
        group[f"high_breakout_{window}"] = (group["high"] > group[f"prior_high_{window}"]).map(bool).astype(object)
        group[f"low_breakdown_{window}"] = (group["low"] < group[f"prior_low_{window}"]).map(bool).astype(object)
        group[f"rsi_{window}"] = _rsi(group["return_1"], window)
        group[f"range_contraction_{window}"] = group["intraday_range"] / group["intraday_range"].rolling(window, min_periods=window).mean()

        ema_fast = close.ewm(span=max(2, window // 2), adjust=False, min_periods=window).mean()
        ema_slow = close.ewm(span=window, adjust=False, min_periods=window).mean()
        group[f"macd_{window}"] = ema_fast - ema_slow
        group[f"ma_trend_{window}"] = (close > group[f"ma_{window}"]).map(bool).astype(object)

    return group


def _rsi(returns: pd.Series, window: int) -> pd.Series:
    gains = returns.clip(lower=0).rolling(window, min_periods=window).mean()
    losses = (-returns.clip(upper=0)).rolling(window, min_periods=window).mean()
    rs = gains / losses.replace(0, np.nan)
    return 100 - (100 / (1 + rs))
