from __future__ import annotations

import pandas as pd

from ..models import StrategyParameter, StrategyRequest
from .base import StrategySpec
from .signal_utils import (
    bollinger_mean_reversion_positions,
    macd_trend_positions,
    normalize_strategy_weights,
    rsi_mean_reversion_positions,
    score_strategy_window,
    strategy_returns_from_positions,
)


class AdaptiveSignalEnsembleStrategy(StrategySpec):
    key = "adaptive_signal_ensemble"
    name = "Adaptive RSI/MACD/Bollinger Ensemble"
    description = "Scores basic RSI, MACD, and Bollinger models on the symbol's recent history and allocates to the best-fitting mix."
    lean_class_name = "AdaptiveSignalEnsembleAlgorithm"
    family = "adaptive"
    parameter_definitions = (
        StrategyParameter(
            name="training_window",
            default="126",
            description="Trailing bars used to evaluate which of RSI, MACD, and Bollinger fits the symbol best.",
        ),
        StrategyParameter(
            name="review_interval",
            default="21",
            description="How often the ensemble refreshes its model weights.",
        ),
        StrategyParameter(
            name="position_size",
            default="0.90",
            description="Maximum portfolio weight when the ensemble is fully long.",
        ),
    )

    def resolve_parameters(self, request: StrategyRequest) -> dict[str, str]:
        params = super().resolve_parameters(request)

        training_window = int(params["training_window"])
        review_interval = int(params["review_interval"])
        position_size = float(params["position_size"])

        if training_window < 40:
            raise ValueError("training_window must be at least 40 bars")
        if review_interval <= 0:
            raise ValueError("review_interval must be positive")
        if review_interval > training_window:
            raise ValueError("review_interval must be less than or equal to training_window")
        if position_size <= 0 or position_size > 1:
            raise ValueError("position_size must be between 0 and 1")

        return {
            "training_window": str(training_window),
            "review_interval": str(review_interval),
            "position_size": f"{position_size:.2f}",
        }

    def render_lean_algorithm(self, request: StrategyRequest) -> str:
        parameters = self.resolve_parameters(request)

        return f"""from AlgorithmImports import *
import pandas as pd


class {self.lean_class_name}(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date({request.start_date.year}, {request.start_date.month}, {request.start_date.day})
        self.set_end_date({request.end_date.year}, {request.end_date.month}, {request.end_date.day})
        self.set_cash({request.initial_cash:.2f})

        ticker = self.get_parameter("ticker") or "{request.ticker}"
        resolution_name = (self.get_parameter("resolution") or "{request.resolution}").upper()
        resolution = getattr(Resolution, resolution_name, Resolution.DAILY)

        self.training_window = int(self.get_parameter("training_window") or "{parameters["training_window"]}")
        self.review_interval = int(self.get_parameter("review_interval") or "{parameters["review_interval"]}")
        self.position_size = float(self.get_parameter("position_size") or "{parameters["position_size"]}")

        self.symbol = self.add_equity(ticker, resolution=resolution).symbol
        self.lookback_bars = max(self.training_window + 60, 220)
        self.review_counter = 0
        self.model_weights = {{"rsi": 1 / 3, "macd": 1 / 3, "bollinger": 1 / 3}}

    def on_data(self, data: Slice) -> None:
        if not data.contains_key(self.symbol):
            return

        history = self.history(self.symbol, self.lookback_bars, Resolution.DAILY)
        close = self._extract_close_series(history)
        if len(close) < 40:
            return

        if self.review_counter <= 0:
            self.model_weights = self._calculate_weights(close)
            self.review_counter = self.review_interval

        self.review_counter -= 1
        signals = self._latest_signals(close)
        target = sum(self.model_weights[name] * signals[name] for name in signals)

        if target <= 0.01:
            if self.portfolio[self.symbol].invested:
                self.liquidate(self.symbol)
            return

        self.set_holdings(self.symbol, min(target, self.position_size))

    def _extract_close_series(self, history: pd.DataFrame) -> pd.Series:
        if history.empty:
            return pd.Series(dtype=float)

        frame = history.copy()
        if isinstance(frame.index, pd.MultiIndex):
            frame = frame.reset_index(level=0, drop=True)

        if "close" not in frame.columns:
            return pd.Series(dtype=float)

        close = frame["close"].astype(float)
        close.index = pd.to_datetime(close.index)
        return close

    def _compute_rsi(self, close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gains = delta.clip(lower=0.0)
        losses = -delta.clip(upper=0.0)
        avg_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.mask(avg_loss == 0.0)
        return (100 - (100 / (1 + rs))).fillna(50.0)

    def _rsi_positions(self, close: pd.Series) -> pd.Series:
        rsi = self._compute_rsi(close, 14)
        positions = []
        current_position = 0.0
        for value in rsi:
            if current_position == 0.0 and value <= 30:
                current_position = self.position_size
            elif current_position > 0.0 and value >= 55:
                current_position = 0.0
            positions.append(current_position)
        return pd.Series(positions, index=close.index, dtype=float)

    def _macd_positions(self, close: pd.Series) -> pd.Series:
        fast_ema = close.ewm(span=12, adjust=False).mean()
        slow_ema = close.ewm(span=26, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        positions = pd.Series(0.0, index=close.index, dtype=float)
        positions.loc[macd_line > signal_line] = self.position_size
        return positions

    def _bollinger_positions(self, close: pd.Series) -> pd.Series:
        mean = close.rolling(window=20).mean()
        std = close.rolling(window=20).std(ddof=0)
        lower_band = mean - (std * 2.0)

        positions = []
        current_position = 0.0
        for current_close, mid, lower in zip(close, mean, lower_band):
            if pd.isna(mid) or pd.isna(lower):
                positions.append(0.0)
                continue
            if current_position == 0.0 and current_close <= lower:
                current_position = self.position_size
            elif current_position > 0.0 and current_close >= mid:
                current_position = 0.0
            positions.append(current_position)
        return pd.Series(positions, index=close.index, dtype=float)

    def _strategy_returns(self, close: pd.Series, positions: pd.Series) -> pd.Series:
        asset_returns = close.pct_change().fillna(0.0)
        return positions.shift(1).fillna(0.0) * asset_returns

    def _score_returns(self, returns: pd.Series) -> float:
        if returns.empty:
            return float("-inf")

        clean_returns = returns.fillna(0.0)
        equity_curve = (1.0 + clean_returns).cumprod()
        total_return = float(equity_curve.iloc[-1] - 1.0)
        drawdown = equity_curve / equity_curve.cummax() - 1.0
        max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

        daily_std = float(clean_returns.std(ddof=0))
        sharpe_ratio = 0.0 if daily_std == 0.0 else float((clean_returns.mean() / daily_std) * (252 ** 0.5))

        return total_return - (abs(max_drawdown) * 0.35) + (sharpe_ratio * 0.03)

    def _normalize_weights(self, scores: dict[str, float]) -> dict[str, float]:
        best_key = max(scores, key=scores.get)
        positive_scores = {{key: max(value, 0.0) for key, value in scores.items()}}
        total = sum(positive_scores.values())
        if total <= 0.0:
            return {{key: 1.0 if key == best_key else 0.0 for key in scores}}
        return {{key: value / total for key, value in positive_scores.items()}}

    def _calculate_weights(self, close: pd.Series) -> dict[str, float]:
        candidates = {{
            "rsi": self._rsi_positions(close),
            "macd": self._macd_positions(close),
            "bollinger": self._bollinger_positions(close),
        }}
        returns = {{
            key: self._strategy_returns(close, positions)
            for key, positions in candidates.items()
        }}

        if len(close) <= self.training_window:
            return {{"rsi": 1 / 3, "macd": 1 / 3, "bollinger": 1 / 3}}

        scores = {{
            key: self._score_returns(series.iloc[-self.training_window:])
            for key, series in returns.items()
        }}
        return self._normalize_weights(scores)

    def _latest_signals(self, close: pd.Series) -> dict[str, float]:
        return {{
            "rsi": float(self._rsi_positions(close).iloc[-1]),
            "macd": float(self._macd_positions(close).iloc[-1]),
            "bollinger": float(self._bollinger_positions(close).iloc[-1]),
        }}
"""

    def compute_positions(self, frame: pd.DataFrame, request: StrategyRequest) -> pd.Series:
        parameters = self.resolve_parameters(request)
        training_window = int(parameters["training_window"])
        review_interval = int(parameters["review_interval"])
        position_size = float(parameters["position_size"])

        candidates = {
            "rsi": rsi_mean_reversion_positions(
                close=frame["close"],
                rsi_period=14,
                oversold_threshold=30.0,
                exit_threshold=55.0,
                position_size=position_size,
            ),
            "macd": macd_trend_positions(
                close=frame["close"],
                fast_period=12,
                slow_period=26,
                signal_period=9,
                position_size=position_size,
            ),
            "bollinger": bollinger_mean_reversion_positions(
                close=frame["close"],
                lookback_period=20,
                band_width=2.0,
                position_size=position_size,
            ),
        }

        candidate_returns = {
            key: strategy_returns_from_positions(frame["close"], positions)
            for key, positions in candidates.items()
        }

        current_weights = {key: 1 / len(candidates) for key in candidates}
        ensemble_positions = pd.Series(0.0, index=frame.index, dtype=float)

        for index, _ in enumerate(frame.index):
            if index == 0:
                continue

            if index >= training_window and (index == training_window or (index - training_window) % review_interval == 0):
                scores = {
                    key: score_strategy_window(returns.iloc[index - training_window:index])
                    for key, returns in candidate_returns.items()
                }
                current_weights = normalize_strategy_weights(scores)

            ensemble_positions.iloc[index] = sum(
                current_weights[key] * positions.iloc[index]
                for key, positions in candidates.items()
            )

        return ensemble_positions.clip(lower=0.0, upper=position_size)
