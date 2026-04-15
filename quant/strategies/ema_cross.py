from __future__ import annotations

import pandas as pd

from ..models import StrategyParameter, StrategyRequest
from .base import StrategySpec


class ExponentialMovingAverageCrossStrategy(StrategySpec):
    key = "ema_cross"
    name = "Exponential Moving Average Cross"
    description = "Trend-following strategy using fast and slow exponential moving averages."
    lean_class_name = "ExponentialMovingAverageCrossAlgorithm"
    family = "trend"
    parameter_definitions = (
        StrategyParameter(
            name="fast_period",
            default="12",
            description="Lookback window for the fast exponential moving average.",
        ),
        StrategyParameter(
            name="slow_period",
            default="26",
            description="Lookback window for the slow exponential moving average.",
        ),
        StrategyParameter(
            name="position_size",
            default="0.95",
            description="Target portfolio weight used when the strategy is long.",
        ),
    )

    def resolve_parameters(self, request: StrategyRequest) -> dict[str, str]:
        params = super().resolve_parameters(request)

        fast_period = int(params["fast_period"])
        slow_period = int(params["slow_period"])
        position_size = float(params["position_size"])

        if fast_period <= 0 or slow_period <= 0:
            raise ValueError("fast_period and slow_period must be positive integers")
        if fast_period >= slow_period:
            raise ValueError("slow_period must be greater than fast_period")
        if position_size <= 0 or position_size > 1:
            raise ValueError("position_size must be between 0 and 1")

        return {
            "fast_period": str(fast_period),
            "slow_period": str(slow_period),
            "position_size": f"{position_size:.2f}",
        }

    def render_lean_algorithm(self, request: StrategyRequest) -> str:
        parameters = self.resolve_parameters(request)

        return f"""from AlgorithmImports import *


class {self.lean_class_name}(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date({request.start_date.year}, {request.start_date.month}, {request.start_date.day})
        self.set_end_date({request.end_date.year}, {request.end_date.month}, {request.end_date.day})
        self.set_cash({request.initial_cash:.2f})

        ticker = self.get_parameter("ticker") or "{request.ticker}"
        resolution_name = (self.get_parameter("resolution") or "{request.resolution}").upper()
        resolution = getattr(Resolution, resolution_name, Resolution.DAILY)

        self.fast_period = int(self.get_parameter("fast_period") or "{parameters["fast_period"]}")
        self.slow_period = int(self.get_parameter("slow_period") or "{parameters["slow_period"]}")
        self.position_size = float(self.get_parameter("position_size") or "{parameters["position_size"]}")

        self.symbol = self.add_equity(ticker, resolution=resolution).symbol
        self.fast = self.ema(self.symbol, self.fast_period, resolution)
        self.slow = self.ema(self.symbol, self.slow_period, resolution)
        self.set_warm_up(self.slow_period, resolution)

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up or not self.fast.is_ready or not self.slow.is_ready:
            return

        invested = self.portfolio[self.symbol].invested
        fast_value = self.fast.current.value
        slow_value = self.slow.current.value

        self.plot("Signals", "FastEMA", fast_value)
        self.plot("Signals", "SlowEMA", slow_value)

        if not invested and fast_value > slow_value:
            self.set_holdings(self.symbol, self.position_size)
        elif invested and fast_value < slow_value:
            self.liquidate(self.symbol)
"""

    def compute_positions(self, frame: pd.DataFrame, request: StrategyRequest) -> pd.Series:
        parameters = self.resolve_parameters(request)
        fast_period = int(parameters["fast_period"])
        slow_period = int(parameters["slow_period"])
        position_size = float(parameters["position_size"])

        fast = frame["close"].ewm(span=fast_period, adjust=False).mean()
        slow = frame["close"].ewm(span=slow_period, adjust=False).mean()
        positions = pd.Series(0.0, index=frame.index)
        positions.loc[fast > slow] = position_size
        return positions.fillna(0.0)
