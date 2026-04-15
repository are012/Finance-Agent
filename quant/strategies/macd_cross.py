from __future__ import annotations

import pandas as pd

from ..models import StrategyParameter, StrategyRequest
from .base import StrategySpec
from .signal_utils import macd_trend_positions


class MacdCrossStrategy(StrategySpec):
    key = "macd_cross"
    name = "MACD Cross"
    description = "Basic trend-following strategy that stays long when the MACD line is above its signal line."
    lean_class_name = "MacdCrossAlgorithm"
    family = "trend"
    parameter_definitions = (
        StrategyParameter(
            name="fast_period",
            default="12",
            description="Fast EMA period used for the MACD line.",
        ),
        StrategyParameter(
            name="slow_period",
            default="26",
            description="Slow EMA period used for the MACD line.",
        ),
        StrategyParameter(
            name="signal_period",
            default="9",
            description="Signal EMA period used to smooth the MACD line.",
        ),
        StrategyParameter(
            name="position_size",
            default="0.95",
            description="Target portfolio weight used when the MACD model is long.",
        ),
    )

    def resolve_parameters(self, request: StrategyRequest) -> dict[str, str]:
        params = super().resolve_parameters(request)

        fast_period = int(params["fast_period"])
        slow_period = int(params["slow_period"])
        signal_period = int(params["signal_period"])
        position_size = float(params["position_size"])

        if fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
            raise ValueError("fast_period, slow_period, and signal_period must be positive integers")
        if fast_period >= slow_period:
            raise ValueError("slow_period must be greater than fast_period")
        if position_size <= 0 or position_size > 1:
            raise ValueError("position_size must be between 0 and 1")

        return {
            "fast_period": str(fast_period),
            "slow_period": str(slow_period),
            "signal_period": str(signal_period),
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
        self.signal_period = int(self.get_parameter("signal_period") or "{parameters["signal_period"]}")
        self.position_size = float(self.get_parameter("position_size") or "{parameters["position_size"]}")

        self.symbol = self.add_equity(ticker, resolution=resolution).symbol
        self.macd_indicator = self.macd(
            self.symbol,
            self.fast_period,
            self.slow_period,
            self.signal_period,
            MovingAverageType.EXPONENTIAL,
            resolution,
        )
        self.set_warm_up(self.slow_period + self.signal_period, resolution)

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up or not self.macd_indicator.is_ready:
            return

        invested = self.portfolio[self.symbol].invested
        macd_value = self.macd_indicator.current.value
        signal_value = self.macd_indicator.signal.current.value

        self.plot("Signals", "MACD", macd_value)
        self.plot("Signals", "Signal", signal_value)

        if not invested and macd_value > signal_value:
            self.set_holdings(self.symbol, self.position_size)
        elif invested and macd_value < signal_value:
            self.liquidate(self.symbol)
"""

    def compute_positions(self, frame: pd.DataFrame, request: StrategyRequest) -> pd.Series:
        parameters = self.resolve_parameters(request)
        fast_period = int(parameters["fast_period"])
        slow_period = int(parameters["slow_period"])
        signal_period = int(parameters["signal_period"])
        position_size = float(parameters["position_size"])

        return macd_trend_positions(
            close=frame["close"],
            fast_period=fast_period,
            slow_period=slow_period,
            signal_period=signal_period,
            position_size=position_size,
        )
