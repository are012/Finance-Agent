from __future__ import annotations

from .base import StrategySpec
from .ema_cross import ExponentialMovingAverageCrossStrategy
from .moving_average_cross import MovingAverageCrossStrategy
from .rsi_reversion import RsiMeanReversionStrategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, StrategySpec] = {
            "ema_cross": ExponentialMovingAverageCrossStrategy(),
            "rsi_reversion": RsiMeanReversionStrategy(),
            "sma_cross": MovingAverageCrossStrategy(),
        }

    def list(self) -> list[StrategySpec]:
        return list(self._strategies.values())

    def get(self, key: str) -> StrategySpec:
        try:
            return self._strategies[key]
        except KeyError as exc:
            available = ", ".join(sorted(self._strategies))
            raise ValueError(f"unknown strategy '{key}'. Available strategies: {available}") from exc
