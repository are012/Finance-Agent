from __future__ import annotations

from .adaptive_signal_ensemble import AdaptiveSignalEnsembleStrategy
from .bollinger_reversion import BollingerMeanReversionStrategy
from .base import StrategySpec
from .buy_hold import BuyAndHoldStrategy
from .ema_cross import ExponentialMovingAverageCrossStrategy
from .macd_cross import MacdCrossStrategy
from .moving_average_cross import MovingAverageCrossStrategy
from .rsi_reversion import RsiMeanReversionStrategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, StrategySpec] = {
            "sma_cross": MovingAverageCrossStrategy(),
            "ema_cross": ExponentialMovingAverageCrossStrategy(),
            "macd_cross": MacdCrossStrategy(),
            "bollinger_reversion": BollingerMeanReversionStrategy(),
            "rsi_reversion": RsiMeanReversionStrategy(),
            "adaptive_signal_ensemble": AdaptiveSignalEnsembleStrategy(),
            "buy_hold": BuyAndHoldStrategy(),
        }

    def list(self) -> list[StrategySpec]:
        return list(self._strategies.values())

    def get(self, key: str) -> StrategySpec:
        try:
            return self._strategies[key]
        except KeyError as exc:
            available = ", ".join(sorted(self._strategies))
            raise ValueError(f"unknown strategy '{key}'. Available strategies: {available}") from exc
