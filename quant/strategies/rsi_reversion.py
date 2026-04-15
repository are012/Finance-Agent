from __future__ import annotations

from ..models import StrategyParameter, StrategyRequest
from .base import StrategySpec


class RsiMeanReversionStrategy(StrategySpec):
    key = "rsi_reversion"
    name = "RSI Mean Reversion"
    description = "Buys oversold conditions and exits when RSI mean-reverts."
    lean_class_name = "RsiMeanReversionAlgorithm"
    parameter_definitions = (
        StrategyParameter(
            name="rsi_period",
            default="14",
            description="Lookback window for RSI.",
        ),
        StrategyParameter(
            name="oversold_threshold",
            default="30",
            description="RSI threshold that triggers an entry.",
        ),
        StrategyParameter(
            name="exit_threshold",
            default="55",
            description="RSI threshold that triggers an exit.",
        ),
        StrategyParameter(
            name="position_size",
            default="0.50",
            description="Target portfolio weight used when the strategy is long.",
        ),
    )

    def resolve_parameters(self, request: StrategyRequest) -> dict[str, str]:
        params = super().resolve_parameters(request)

        rsi_period = int(params["rsi_period"])
        oversold_threshold = float(params["oversold_threshold"])
        exit_threshold = float(params["exit_threshold"])
        position_size = float(params["position_size"])

        if rsi_period <= 0:
            raise ValueError("rsi_period must be positive")
        if oversold_threshold <= 0 or oversold_threshold >= 100:
            raise ValueError("oversold_threshold must be between 0 and 100")
        if exit_threshold <= oversold_threshold or exit_threshold >= 100:
            raise ValueError("exit_threshold must be greater than oversold_threshold and below 100")
        if position_size <= 0 or position_size > 1:
            raise ValueError("position_size must be between 0 and 1")

        return {
            "rsi_period": str(rsi_period),
            "oversold_threshold": f"{oversold_threshold:.1f}",
            "exit_threshold": f"{exit_threshold:.1f}",
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

        self.rsi_period = int(self.get_parameter("rsi_period") or "{parameters["rsi_period"]}")
        self.oversold_threshold = float(self.get_parameter("oversold_threshold") or "{parameters["oversold_threshold"]}")
        self.exit_threshold = float(self.get_parameter("exit_threshold") or "{parameters["exit_threshold"]}")
        self.position_size = float(self.get_parameter("position_size") or "{parameters["position_size"]}")

        self.symbol = self.add_equity(ticker, resolution=resolution).symbol
        self.rsi_indicator = self.rsi(self.symbol, self.rsi_period, MovingAverageType.WILDERS, resolution)
        self.set_warm_up(self.rsi_period, resolution)

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up or not self.rsi_indicator.is_ready:
            return

        invested = self.portfolio[self.symbol].invested
        rsi_value = self.rsi_indicator.current.value
        self.plot("Signals", "RSI", rsi_value)

        if not invested and rsi_value <= self.oversold_threshold:
            self.set_holdings(self.symbol, self.position_size)
        elif invested and rsi_value >= self.exit_threshold:
            self.liquidate(self.symbol)
"""
