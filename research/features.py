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
    "distance_to_52w_high",
    "multi_horizon_momentum_agreement",
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
    features: dict[str, pd.Series] = {}

    features["return_1"] = close.pct_change()
    features["log_return_1"] = np.log(close / prev_close)
    features["gap_return"] = group["open"] / prev_close - 1.0
    features["intraday_range"] = (group["high"] - group["low"]) / group["open"]
    features["candle_body"] = (group["close"] - group["open"]) / group["open"]
    features["upper_wick"] = (group["high"] - group[["open", "close"]].max(axis=1)) / group["open"]
    features["lower_wick"] = (group[["open", "close"]].min(axis=1) - group["low"]) / group["open"]
    features["typical_price"] = (group["high"] + group["low"] + group["close"]) / 3.0
    features["vwap_proxy"] = group["traded_value"] / group["volume"].replace(0, np.nan)

    true_range = pd.concat(
        [
            group["high"] - group["low"],
            (group["high"] - prev_close).abs(),
            (group["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    for window in windows:
        ma = close.rolling(window, min_periods=window).mean()
        volume_ma = group["volume"].rolling(window, min_periods=window).mean()
        prior_high = group["high"].shift(1).rolling(window, min_periods=window).max()
        prior_low = group["low"].shift(1).rolling(window, min_periods=window).min()

        features[f"ma_{window}"] = ma
        features[f"ma_distance_{window}"] = close / ma - 1.0
        features[f"momentum_{window}"] = close / close.shift(window) - 1.0
        features[f"reversal_{window}"] = -features["return_1"].rolling(window, min_periods=window).sum()
        features[f"volatility_{window}"] = features["return_1"].rolling(window, min_periods=window).std()
        features[f"atr_{window}"] = true_range.rolling(window, min_periods=window).mean()
        features[f"volume_ma_{window}"] = volume_ma
        features[f"volume_surge_{window}"] = group["volume"] / volume_ma - 1.0
        features[f"volume_ratio_{window}"] = group["volume"] / volume_ma
        features[f"traded_value_ma_{window}"] = group["traded_value"].rolling(window, min_periods=window).mean()
        features[f"prior_high_{window}"] = prior_high
        features[f"prior_low_{window}"] = prior_low
        features[f"distance_to_prior_high_{window}"] = close / prior_high - 1.0
        features[f"high_breakout_{window}"] = (group["high"] > prior_high).map(bool).astype(object)
        features[f"low_breakdown_{window}"] = (group["low"] < prior_low).map(bool).astype(object)
        features[f"rsi_{window}"] = _rsi(features["return_1"], window)
        features[f"range_contraction_{window}"] = features["intraday_range"] / features["intraday_range"].rolling(
            window, min_periods=window
        ).mean()

        ema_fast = close.ewm(span=max(2, window // 2), adjust=False, min_periods=window).mean()
        ema_slow = close.ewm(span=window, adjust=False, min_periods=window).mean()
        features[f"macd_{window}"] = ema_fast - ema_slow
        features[f"ma_trend_{window}"] = (close > ma).map(bool).astype(object)

    if "prior_high_252" in features:
        features["distance_to_52w_high"] = close / features["prior_high_252"] - 1.0
    else:
        features["distance_to_52w_high"] = pd.Series(np.nan, index=group.index)

    momentum_windows = [window for window in (20, 60, 120) if f"momentum_{window}" in features]
    if momentum_windows:
        momentum_values = pd.concat([features[f"momentum_{window}"] for window in momentum_windows], axis=1)
        agreement = momentum_values.gt(0).astype(float).mean(axis=1)
        agreement[momentum_values.notna().sum(axis=1) < len(momentum_windows)] = np.nan
        features["multi_horizon_momentum_agreement"] = agreement
    else:
        features["multi_horizon_momentum_agreement"] = pd.Series(np.nan, index=group.index)

    duplicate_columns = [column for column in features if column in group.columns]
    base = group.drop(columns=duplicate_columns) if duplicate_columns else group
    return pd.concat([base, pd.DataFrame(features, index=group.index)], axis=1)


def _rsi(returns: pd.Series, window: int) -> pd.Series:
    gains = returns.clip(lower=0).rolling(window, min_periods=window).mean()
    losses = (-returns.clip(upper=0)).rolling(window, min_periods=window).mean()
    rs = gains / losses.replace(0, np.nan)
    return 100 - (100 / (1 + rs))
