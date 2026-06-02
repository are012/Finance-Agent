from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StrategySpec:
    hypothesis_id: str
    name: str
    signal_family: str
    lookback_bars: int
    holding_bars: int
    required_features: list[str]


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
        weight = 1.0 / len(active_symbols) if active_symbols else 0.0
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

    if strategy.signal_family == "momentum":
        signal = f"momentum_{strategy.lookback_bars}"
        eligible = eligible[eligible[signal] > 0].sort_values([signal, liquid_column], ascending=False)
    elif strategy.signal_family == "breakout":
        signal = f"high_breakout_{strategy.lookback_bars}"
        eligible = eligible[eligible[signal].eq(True)].sort_values([liquid_column], ascending=False)
    elif strategy.signal_family == "reversal":
        signal = f"reversal_{strategy.lookback_bars}"
        eligible = eligible[eligible[signal] > 0].sort_values([signal, liquid_column], ascending=False)
    else:
        raise ValueError(f"Unsupported signal family: {strategy.signal_family}")

    return eligible.head(max_positions)
