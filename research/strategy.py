from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StrategySpec:
    hypothesis_id: str
    name: str
    signal_family: str
    lookback_bars: int
    holding_bars: int
    required_features: list[str]
    parameters: dict[str, Any] = field(default_factory=dict)
    max_position_pct: float = 0.2


def build_signals(featured: pd.DataFrame, strategy: StrategySpec, *, max_positions: int = 5) -> pd.DataFrame:
    for feature in strategy.required_features:
        if feature not in featured.columns:
            raise ValueError(f"Missing required feature for strategy: {feature}")

    frame = featured.copy()
    selected_frames = []
    active_until: dict[str, int] = {}
    grouped = list(frame.groupby("date", sort=True))
    for index, (date, daily) in enumerate(grouped):
        expired = {symbol for symbol, until in active_until.items() if until < index}
        for symbol in expired:
            active_until.pop(symbol, None)

        selected = _select_daily(daily.copy(), strategy, max_positions=max_positions)
        selected_symbols = list(selected["symbol"]) if not selected.empty else []
        available_slots = max(0, max_positions - len(active_until))
        for symbol in selected_symbols:
            if available_slots <= 0:
                break
            if symbol in active_until or symbol in expired:
                continue
            active_until[symbol] = index + strategy.holding_bars - 1
            available_slots -= 1

        active_symbols = set(active_until)
        weight = min(strategy.max_position_pct, 1.0 / len(active_symbols)) if active_symbols else 0.0
        daily_targets = frame.loc[frame["date"] == date, ["date", "symbol"]].copy()
        daily_targets["target_weight"] = 0.0
        daily_targets.loc[daily_targets["symbol"].isin(active_symbols), "target_weight"] = weight
        selected_frames.append(daily_targets)
    return pd.concat(selected_frames, ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)


def _select_daily(daily: pd.DataFrame, strategy: StrategySpec, *, max_positions: int) -> pd.DataFrame:
    liquid_column = f"traded_value_ma_{strategy.lookback_bars}"
    if liquid_column not in daily.columns:
        liquid_column = "traded_value"

    eligible = daily[daily[liquid_column].notna()].copy()
    if "listing_status" in eligible.columns:
        eligible = eligible[eligible["listing_status"].fillna("listed").eq("listed")]
    if eligible.empty:
        return eligible

    lookback = strategy.lookback_bars
    params = strategy.parameters
    family = strategy.signal_family

    if family == "momentum":
        signal = f"momentum_{lookback}"
        eligible = eligible[eligible[signal] > float(params.get("min_momentum", 0.0))]
        eligible = eligible.sort_values([signal, liquid_column], ascending=False)
    elif family == "breakout":
        signal = f"prior_high_{lookback}"
        eligible = eligible[eligible["close"] > eligible[signal]]
        eligible = eligible.sort_values([liquid_column], ascending=False)
    elif family == "reversal":
        signal = f"reversal_{lookback}"
        eligible = eligible[eligible[signal] > 0].sort_values([signal, liquid_column], ascending=False)
    elif family == "breakout_volume":
        eligible = eligible[
            (eligible["close"] > eligible[f"prior_high_{lookback}"])
            & (eligible[f"volume_ratio_{lookback}"] >= float(params.get("volume_ratio_min", 1.0)))
        ].sort_values([f"volume_ratio_{lookback}", liquid_column], ascending=False)
    elif family == "ma_trend":
        eligible = eligible[eligible["close"] > eligible[f"ma_{lookback}"]].sort_values(
            [f"ma_distance_{lookback}", liquid_column], ascending=False
        )
    elif family == "volatility_contraction_breakout":
        eligible = eligible[
            (eligible["close"] > eligible[f"prior_high_{lookback}"])
            & (eligible[f"range_contraction_{lookback}"] <= float(params.get("max_range_contraction", 1.0)))
        ].sort_values([liquid_column], ascending=False)
    elif family == "gap_continuation":
        eligible = eligible[eligible["gap_return"] >= float(params.get("min_gap", 0.005))]
        eligible = eligible.sort_values(["gap_return", liquid_column], ascending=False)
    elif family == "gap_reversal":
        eligible = eligible[eligible["gap_return"] <= -float(params.get("min_gap", 0.005))]
        eligible = eligible.sort_values([f"reversal_{lookback}", liquid_column], ascending=False)
    elif family == "rsi_mean_reversion":
        eligible = eligible[eligible[f"rsi_{lookback}"] <= float(params.get("max_rsi", 35.0))]
        eligible = eligible.sort_values([f"rsi_{lookback}", liquid_column], ascending=True)
    elif family == "price_volume_momentum":
        eligible = eligible[
            (eligible[f"momentum_{lookback}"] > 0)
            & (eligible[f"volume_ratio_{lookback}"] >= float(params.get("volume_ratio_min", 1.0)))
        ].sort_values([f"momentum_{lookback}", f"volume_ratio_{lookback}", liquid_column], ascending=False)
    elif family == "high_traded_value_momentum":
        eligible = eligible[eligible[f"momentum_{lookback}"] > 0].sort_values(
            [liquid_column, f"momentum_{lookback}"], ascending=False
        )
    else:
        raise ValueError(f"Unsupported signal family: {family}")

    return eligible.head(max_positions)
