from __future__ import annotations

from math import sqrt

import numpy as np
import pandas as pd

from ..models import (
    BacktestMetrics,
    BacktestPoint,
    BacktestRequest,
    BacktestResponse,
    BacktestTrade,
)
from ..strategies.registry import StrategyRegistry
from .market_data import MarketDataService


class BacktestEngine:
    def __init__(self, registry: StrategyRegistry, market_data: MarketDataService) -> None:
        self.registry = registry
        self.market_data = market_data

    def run(self, request: BacktestRequest) -> BacktestResponse:
        strategy = self.registry.get(request.strategy_key)
        context, frame = self.market_data.fetch_history(
            ticker=request.ticker,
            market=request.market,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        positions = strategy.compute_positions(frame.copy(), request).reindex(frame.index).fillna(0.0).clip(lower=0.0, upper=1.0)
        asset_returns = frame["close"].pct_change().fillna(0.0)
        strategy_returns = positions.shift(1).fillna(0.0) * asset_returns
        benchmark_returns = asset_returns

        strategy_equity = request.initial_cash * (1.0 + strategy_returns).cumprod()
        benchmark_equity = request.initial_cash * (1.0 + benchmark_returns).cumprod()

        trades = self._extract_trades(positions=positions, prices=frame["close"])
        metrics = self._build_metrics(
            initial_cash=request.initial_cash,
            strategy_equity=strategy_equity,
            benchmark_equity=benchmark_equity,
            strategy_returns=strategy_returns,
            trades=trades,
            positions=positions,
        )

        sampled = self._downsample(
            pd.DataFrame(
                {
                    "close": frame["close"],
                    "strategy_equity": strategy_equity,
                    "benchmark_equity": benchmark_equity,
                    "position": positions,
                }
            ),
            request.max_points,
        )

        equity_curve = [
            BacktestPoint(
                date=index.date(),
                close=float(row["close"]),
                strategy_equity=float(row["strategy_equity"]),
                benchmark_equity=float(row["benchmark_equity"]),
                position=float(row["position"]),
            )
            for index, row in sampled.iterrows()
        ]

        parameters = strategy.resolve_parameters(request)

        return BacktestResponse(
            strategy=strategy.metadata(),
            ticker=request.ticker,
            market=request.market,
            data_ticker=context.data_ticker,
            tradingview_symbol=context.tradingview_symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_cash=request.initial_cash,
            parameters=parameters,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
            notes=[
                f"{context.data_ticker} 기준으로 {len(frame)}개 봉 데이터를 불러왔습니다.",
                "Strategy equity uses daily close-to-close returns with next-bar position application.",
                *context.notes,
            ],
        )

    @staticmethod
    def _build_metrics(
        initial_cash: float,
        strategy_equity: pd.Series,
        benchmark_equity: pd.Series,
        strategy_returns: pd.Series,
        trades: list[BacktestTrade],
        positions: pd.Series,
    ) -> BacktestMetrics:
        total_return = float(strategy_equity.iloc[-1] / initial_cash - 1.0)
        benchmark_return = float(benchmark_equity.iloc[-1] / initial_cash - 1.0)
        periods = max(len(strategy_equity) - 1, 1)
        annual_return = float((strategy_equity.iloc[-1] / initial_cash) ** (252 / periods) - 1.0)

        drawdown = strategy_equity / strategy_equity.cummax() - 1.0
        max_drawdown = float(drawdown.min())

        daily_std = float(strategy_returns.std(ddof=0))
        sharpe_ratio = 0.0 if daily_std == 0.0 else float((strategy_returns.mean() / daily_std) * sqrt(252))
        volatility = float(daily_std * sqrt(252))

        closed_trade_returns = [
            trade.return_pct
            for trade in trades
            if trade.return_pct is not None and trade.exited_at is not None
        ]
        wins = [value for value in closed_trade_returns if value > 0]
        win_rate = float(len(wins) / len(closed_trade_returns)) if closed_trade_returns else 0.0

        exposure = float(positions.mean())

        return BacktestMetrics(
            total_return=total_return,
            annual_return=annual_return,
            benchmark_return=benchmark_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            volatility=volatility,
            win_rate=win_rate,
            exposure=exposure,
            trade_count=len(trades),
        )

    @staticmethod
    def _extract_trades(positions: pd.Series, prices: pd.Series) -> list[BacktestTrade]:
        trades: list[BacktestTrade] = []
        current_entry_date = None
        current_entry_price = None

        previous_position = 0.0
        for index, position in positions.items():
            price = float(prices.loc[index])
            if previous_position <= 0.0 and position > 0.0:
                current_entry_date = index.date()
                current_entry_price = price
            elif previous_position > 0.0 and position <= 0.0 and current_entry_date is not None and current_entry_price is not None:
                trades.append(
                    BacktestTrade(
                        entered_at=current_entry_date,
                        exited_at=index.date(),
                        entry_price=current_entry_price,
                        exit_price=price,
                        return_pct=(price / current_entry_price) - 1.0,
                    )
                )
                current_entry_date = None
                current_entry_price = None

            previous_position = float(position)

        if current_entry_date is not None and current_entry_price is not None:
            trades.append(
                BacktestTrade(
                    entered_at=current_entry_date,
                    exited_at=None,
                    entry_price=current_entry_price,
                    exit_price=float(prices.iloc[-1]),
                    return_pct=(float(prices.iloc[-1]) / current_entry_price) - 1.0,
                )
            )

        return trades

    @staticmethod
    def _downsample(frame: pd.DataFrame, max_points: int) -> pd.DataFrame:
        if len(frame) <= max_points:
            return frame

        indices = np.linspace(0, len(frame) - 1, max_points, dtype=int)
        return frame.iloc[indices]
