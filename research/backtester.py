from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from research.costs import CostModel
from research.schema import ALLOWED_COLUMNS, validate_ohlcv_frame


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    orders: pd.DataFrame


def backtest_signals(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    initial_cash: float,
    cost_model: CostModel,
) -> BacktestResult:
    data = validate_ohlcv_frame(bars[[column for column in bars.columns if column in ALLOWED_COLUMNS]])
    signal_frame = signals.copy()
    signal_frame["date"] = pd.to_datetime(signal_frame["date"])
    if not {"date", "symbol", "target_weight"}.issubset(signal_frame.columns):
        raise ValueError("Signals must contain date, symbol, target_weight")

    dates = sorted(data["date"].unique())
    signal_by_date = {
        pd.Timestamp(date): daily.set_index("symbol")["target_weight"].to_dict()
        for date, daily in signal_frame.groupby("date", sort=True)
    }

    cash = float(initial_cash)
    positions: dict[str, int] = {}
    open_lots: dict[str, dict] = {}
    pending_targets: dict[str, float] = {}
    equity_rows = []
    order_rows = []
    trade_rows = []

    for date in dates:
        daily_bars = data[data["date"].eq(date)].set_index("symbol")
        if pending_targets:
            equity_before_orders = _mark_equity(cash, positions, daily_bars, price_column="open")
            symbols = sorted(set(daily_bars.index) | set(positions) | set(pending_targets))
            for symbol in symbols:
                if symbol not in daily_bars.index:
                    continue
                target_weight = pending_targets.get(symbol, 0.0)
                open_price = float(daily_bars.loc[symbol, "open"])
                current_qty = positions.get(symbol, 0)
                current_value = current_qty * open_price
                target_value = equity_before_orders * target_weight
                delta_value = target_value - current_value
                if abs(delta_value) < open_price:
                    continue
                if delta_value > 0:
                    one_share = cost_model.estimate("buy", price=open_price, quantity=1)
                    quantity = int(min(delta_value, cash) // abs(one_share.cash_delta))
                    if quantity <= 0:
                        continue
                    estimate = cost_model.estimate("buy", price=open_price, quantity=quantity)
                    if abs(estimate.cash_delta) > cash:
                        continue
                    cash += estimate.cash_delta
                    positions[symbol] = current_qty + quantity
                    if symbol not in open_lots:
                        open_lots[symbol] = {
                            "entry_date": date,
                            "entry_price": estimate.fill_price,
                            "quantity": quantity,
                            "entry_cost": estimate.commission,
                        }
                    else:
                        lot = open_lots[symbol]
                        total_qty = lot["quantity"] + quantity
                        lot["entry_price"] = ((lot["entry_price"] * lot["quantity"]) + (estimate.fill_price * quantity)) / total_qty
                        lot["quantity"] = total_qty
                        lot["entry_cost"] += estimate.commission
                    order_rows.append(_order_row(date, symbol, "buy", quantity, estimate))
                else:
                    quantity = min(current_qty, int(abs(delta_value) // open_price))
                    if target_weight == 0.0:
                        quantity = current_qty
                    if quantity <= 0:
                        continue
                    estimate = cost_model.estimate("sell", price=open_price, quantity=quantity)
                    cash += estimate.cash_delta
                    remaining = current_qty - quantity
                    if remaining:
                        positions[symbol] = remaining
                    else:
                        positions.pop(symbol, None)
                    lot = open_lots.get(symbol)
                    if lot:
                        trade_rows.append(
                            {
                                "symbol": symbol,
                                "entry_date": lot["entry_date"],
                                "entry_price": lot["entry_price"],
                                "exit_date": date,
                                "exit_price": estimate.fill_price,
                                "quantity": quantity,
                                "gross_pnl": (estimate.fill_price - lot["entry_price"]) * quantity,
                                "costs": lot["entry_cost"] + estimate.commission + estimate.tax,
                            }
                        )
                        if remaining:
                            lot["quantity"] = remaining
                        else:
                            open_lots.pop(symbol, None)
                    order_rows.append(_order_row(date, symbol, "sell", quantity, estimate))

        close_equity = _mark_equity(cash, positions, daily_bars, price_column="close")
        equity_rows.append({"date": date, "cash": cash, "positions_value": close_equity - cash, "equity": close_equity})
        pending_targets = signal_by_date.get(pd.Timestamp(date), {})

    if dates and positions:
        last_date = dates[-1]
        last_bars = data[data["date"].eq(last_date)].set_index("symbol")
        for symbol, quantity in list(positions.items()):
            if quantity <= 0 or symbol not in last_bars.index:
                continue
            close_price = float(last_bars.loc[symbol, "close"])
            estimate = cost_model.estimate("sell", price=close_price, quantity=quantity)
            cash += estimate.cash_delta
            positions.pop(symbol, None)
            lot = open_lots.pop(symbol, None)
            if lot:
                trade_rows.append(
                    {
                        "symbol": symbol,
                        "entry_date": lot["entry_date"],
                        "entry_price": lot["entry_price"],
                        "exit_date": last_date,
                        "exit_price": estimate.fill_price,
                        "quantity": quantity,
                        "gross_pnl": (estimate.fill_price - lot["entry_price"]) * quantity,
                        "costs": lot["entry_cost"] + estimate.commission + estimate.tax,
                    }
                )
            order_rows.append(_order_row(last_date, symbol, "sell", quantity, estimate))
        if equity_rows:
            equity_rows[-1] = {"date": last_date, "cash": cash, "positions_value": 0.0, "equity": cash}

    return BacktestResult(
        equity_curve=pd.DataFrame(equity_rows),
        trades=pd.DataFrame(trade_rows),
        orders=pd.DataFrame(order_rows),
    )


def _mark_equity(cash: float, positions: dict[str, int], daily_bars: pd.DataFrame, *, price_column: str) -> float:
    value = cash
    for symbol, quantity in positions.items():
        if symbol in daily_bars.index:
            value += quantity * float(daily_bars.loc[symbol, price_column])
    return round(value, 10)


def _order_row(date: pd.Timestamp, symbol: str, side: str, quantity: int, estimate) -> dict:
    return {
        "date": date,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "fill_price": estimate.fill_price,
        "gross_value": estimate.gross_value,
        "commission": estimate.commission,
        "tax": estimate.tax,
        "cash_delta": estimate.cash_delta,
    }
