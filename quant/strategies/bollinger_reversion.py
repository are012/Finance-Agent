from __future__ import annotations

from ..models import StrategyParameter, StrategyRequest
from .base import StrategySpec
from .signal_utils import bollinger_mean_reversion_positions


class BollingerMeanReversionStrategy(StrategySpec):
    key = "bollinger_reversion"
    name = "Bollinger Mean Reversion"
    description = "Buys when price stretches below the lower Bollinger band and exits on a move back to the middle band."
    lean_class_name = "BollingerMeanReversionAlgorithm"
    family = "volatility"
    parameter_definitions = (
        StrategyParameter(
            name="lookback_period",
            default="20",
            description="Window used to compute the Bollinger moving average and standard deviation.",
        ),
        StrategyParameter(
            name="band_width",
            default="2.0",
            description="Number of standard deviations for the Bollinger bands.",
        ),
        StrategyParameter(
            name="position_size",
            default="0.60",
            description="Target portfolio weight used when the strategy is long.",
        ),
    )

    def resolve_parameters(self, request: StrategyRequest) -> dict[str, str]:
        params = super().resolve_parameters(request)

        lookback_period = int(params["lookback_period"])
        band_width = float(params["band_width"])
        position_size = float(params["position_size"])

        if lookback_period <= 1:
            raise ValueError("lookback_period must be greater than 1")
        if band_width <= 0:
            raise ValueError("band_width must be positive")
        if position_size <= 0 or position_size > 1:
            raise ValueError("position_size must be between 0 and 1")

        return {
            "lookback_period": str(lookback_period),
            "band_width": f"{band_width:.2f}",
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

        self.lookback_period = int(self.get_parameter("lookback_period") or "{parameters["lookback_period"]}")
        self.band_width = float(self.get_parameter("band_width") or "{parameters["band_width"]}")
        self.position_size = float(self.get_parameter("position_size") or "{parameters["position_size"]}")

        self.symbol = self.add_equity(ticker, resolution=resolution).symbol
        self.bbands = self.bb(self.symbol, self.lookback_period, self.band_width, MovingAverageType.SIMPLE, resolution)
        self.set_warm_up(self.lookback_period, resolution)

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up or not self.bbands.is_ready:
            return

        invested = self.portfolio[self.symbol].invested
        middle_band = self.bbands.middle_band.current.value
        lower_band = self.bbands.lower_band.current.value
        price = self.securities[self.symbol].price

        self.plot("Signals", "Price", price)
        self.plot("Signals", "MiddleBand", middle_band)
        self.plot("Signals", "LowerBand", lower_band)

        if not invested and price <= lower_band:
            self.set_holdings(self.symbol, self.position_size)
        elif invested and price >= middle_band:
            self.liquidate(self.symbol)
"""

    def compute_positions(self, frame: pd.DataFrame, request: StrategyRequest) -> pd.Series:
        parameters = self.resolve_parameters(request)
        lookback_period = int(parameters["lookback_period"])
        band_width = float(parameters["band_width"])
        position_size = float(parameters["position_size"])

        return bollinger_mean_reversion_positions(
            close=frame["close"],
            lookback_period=lookback_period,
            band_width=band_width,
            position_size=position_size,
        )
