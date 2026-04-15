from __future__ import annotations

import pandas as pd

from ..models import StrategyParameter, StrategyRequest
from .base import StrategySpec


class BuyAndHoldStrategy(StrategySpec):
    key = "buy_hold"
    name = "Buy and Hold"
    description = "Benchmark-style allocation that buys once and holds through the full period."
    lean_class_name = "BuyAndHoldAlgorithm"
    family = "benchmark"
    parameter_definitions = (
        StrategyParameter(
            name="position_size",
            default="1.00",
            description="Target portfolio weight held for the full backtest window.",
        ),
    )

    def resolve_parameters(self, request: StrategyRequest) -> dict[str, str]:
        params = super().resolve_parameters(request)
        position_size = float(params["position_size"])
        if position_size <= 0 or position_size > 1:
            raise ValueError("position_size must be between 0 and 1")
        return {"position_size": f"{position_size:.2f}"}

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
        self.position_size = float(self.get_parameter("position_size") or "{parameters["position_size"]}")

        self.symbol = self.add_equity(ticker, resolution=resolution).symbol
        self.invested_once = False

    def on_data(self, data: Slice) -> None:
        if self.invested_once:
            return

        self.set_holdings(self.symbol, self.position_size)
        self.invested_once = True
"""

    def compute_positions(self, frame: pd.DataFrame, request: StrategyRequest) -> pd.Series:
        parameters = self.resolve_parameters(request)
        position_size = float(parameters["position_size"])
        return pd.Series(position_size, index=frame.index, dtype=float)
