from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from research.costs import CostModel
from research.schema import ALLOWED_COLUMNS, validate_ohlcv_frame


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    orders: pd.DataFrame
    drawdown_curve: pd.DataFrame
    positions: pd.DataFrame


def backtest_signals(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    initial_cash: float,
    cost_model: CostModel,
    liquidity_config: dict[str, Any] | None = None,
    force_liquidate_at_end: bool = True,
) -> BacktestResult:
    data = _validated_bars_with_extras(bars)
    signal_frame = signals.copy()
    signal_frame["date"] = pd.to_datetime(signal_frame["date"])
    if not {"date", "symbol", "target_weight"}.issubset(signal_frame.columns):
        raise ValueError("Signals must contain date, symbol, target_weight")

    daily_bars_by_date = {
        pd.Timestamp(date): daily.set_index("symbol") for date, daily in data.groupby("date", sort=True)
    }
    dates = list(daily_bars_by_date)
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
    position_rows = []

    for date in dates:
        daily_bars = daily_bars_by_date[pd.Timestamp(date)]
        if pending_targets:
            equity_before_orders = _mark_equity(cash, positions, daily_bars, price_column="open")
            symbols = sorted(set(daily_bars.index) | set(positions) | set(pending_targets))
            for symbol in symbols:
                if symbol not in daily_bars.index:
                    continue
                if _is_untradable(daily_bars.loc[symbol]):
                    order_rows.append(_rejected_order(date, symbol, "none", 0, "untradable"))
                    continue
                target_weight = float(pending_targets.get(symbol, 0.0))
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
                    quantity, status, reason = _apply_liquidity_limit(
                        daily_bars.loc[symbol],
                        open_price=open_price,
                        requested_quantity=quantity,
                        liquidity_config=liquidity_config,
                    )
                    if status == "rejected":
                        order_rows.append(_rejected_order(date, symbol, "buy", 0, reason, requested_quantity=quantity))
                        continue
                    estimate = cost_model.estimate("buy", price=open_price, quantity=quantity)
                    if abs(estimate.cash_delta) > cash:
                        order_rows.append(_rejected_order(date, symbol, "buy", 0, "insufficient_cash", requested_quantity=quantity))
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
                    order_rows.append(_order_row(date, symbol, "buy", quantity, estimate, status=status))
                else:
                    quantity = min(current_qty, int(abs(delta_value) // open_price))
                    if target_weight == 0.0:
                        quantity = current_qty
                    if quantity <= 0:
                        continue
                    quantity, status, reason = _apply_liquidity_limit(
                        daily_bars.loc[symbol],
                        open_price=open_price,
                        requested_quantity=quantity,
                        liquidity_config=liquidity_config,
                    )
                    if status == "rejected":
                        order_rows.append(_rejected_order(date, symbol, "sell", 0, reason, requested_quantity=quantity))
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
                        trade_rows.append(_trade_row(symbol, lot, date, estimate, quantity))
                        if remaining:
                            lot["quantity"] = remaining
                        else:
                            open_lots.pop(symbol, None)
                    order_rows.append(_order_row(date, symbol, "sell", quantity, estimate, status=status))

        close_equity = _mark_equity(cash, positions, daily_bars, price_column="close")
        equity_rows.append({"date": date, "cash": cash, "positions_value": close_equity - cash, "equity": close_equity})
        position_rows.extend(_position_rows(date, positions, daily_bars))
        pending_targets = signal_by_date.get(pd.Timestamp(date), {})

    if dates and positions and force_liquidate_at_end:
        last_date = dates[-1]
        last_bars = daily_bars_by_date[pd.Timestamp(last_date)]
        for symbol, quantity in list(positions.items()):
            if quantity <= 0 or symbol not in last_bars.index:
                continue
            if _is_untradable(last_bars.loc[symbol]):
                order_rows.append(_rejected_order(last_date, symbol, "sell", 0, "untradable", requested_quantity=quantity))
                continue
            close_price = float(last_bars.loc[symbol, "close"])
            requested_quantity = quantity
            quantity, status, reason = _apply_liquidity_limit(
                last_bars.loc[symbol],
                open_price=close_price,
                requested_quantity=quantity,
                liquidity_config=liquidity_config,
            )
            if status == "rejected":
                order_rows.append(_rejected_order(last_date, symbol, "sell", 0, reason, requested_quantity=requested_quantity))
                continue
            estimate = cost_model.estimate("sell", price=close_price, quantity=quantity)
            cash += estimate.cash_delta
            remaining = requested_quantity - quantity
            if remaining:
                positions[symbol] = remaining
            else:
                positions.pop(symbol, None)
            lot = open_lots.get(symbol)
            if lot:
                trade_rows.append(_trade_row(symbol, lot, last_date, estimate, quantity))
                if remaining:
                    lot["quantity"] = remaining
                else:
                    open_lots.pop(symbol, None)
            order_rows.append(
                _order_row(
                    last_date,
                    symbol,
                    "sell",
                    quantity,
                    estimate,
                    status=status,
                    reason=reason or "final_liquidation",
                    requested_quantity=requested_quantity,
                )
            )
        if equity_rows:
            final_equity = _mark_equity(cash, positions, last_bars, price_column="close")
            equity_rows[-1] = {"date": last_date, "cash": cash, "positions_value": final_equity - cash, "equity": final_equity}

    equity_curve = pd.DataFrame(equity_rows)
    orders = pd.DataFrame(order_rows, columns=_order_columns())
    trades = pd.DataFrame(trade_rows, columns=_trade_columns())
    positions_frame = pd.DataFrame(position_rows, columns=["date", "symbol", "quantity", "market_value"])
    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        orders=orders,
        drawdown_curve=_drawdown_curve(equity_curve),
        positions=positions_frame,
    )


def _validated_bars_with_extras(bars: pd.DataFrame) -> pd.DataFrame:
    extras = [column for column in bars.columns if column not in ALLOWED_COLUMNS]
    return validate_ohlcv_frame(bars, allowed_extra_columns=extras)


def _apply_liquidity_limit(
    row: pd.Series,
    *,
    open_price: float,
    requested_quantity: int,
    liquidity_config: dict[str, Any] | None,
) -> tuple[int, str, str]:
    if not liquidity_config:
        return requested_quantity, "filled", ""
    max_pct = liquidity_config.get("max_order_pct_of_avg_traded_value")
    if max_pct is None:
        return requested_quantity, "filled", ""
    lookback = int(liquidity_config.get("avg_traded_value_lookback", 20))
    traded_column = f"traded_value_ma_{lookback}"
    raw_avg_traded_value = row.get(traded_column, row.get("traded_value", 0.0))
    avg_traded_value = 0.0 if pd.isna(raw_avg_traded_value) else float(raw_avg_traded_value)
    cap_value = avg_traded_value * float(max_pct)
    requested_value = requested_quantity * open_price
    if requested_value <= cap_value:
        return requested_quantity, "filled", ""
    capped_quantity = int(cap_value // open_price)
    if liquidity_config.get("on_limit", "reject") == "partial" and capped_quantity > 0:
        return capped_quantity, "partial", "liquidity_cap"
    return 0, "rejected", "liquidity_cap"


def _is_untradable(row: pd.Series) -> bool:
    return str(row.get("listing_status", "listed")).lower() in {"suspended", "halted", "delisted"}


def _mark_equity(cash: float, positions: dict[str, int], daily_bars: pd.DataFrame, *, price_column: str) -> float:
    value = cash
    for symbol, quantity in positions.items():
        if symbol in daily_bars.index and pd.notna(daily_bars.loc[symbol, price_column]):
            value += quantity * float(daily_bars.loc[symbol, price_column])
    return round(value, 10)


def _order_row(
    date: pd.Timestamp,
    symbol: str,
    side: str,
    quantity: int,
    estimate,
    *,
    status: str,
    reason: str = "",
    requested_quantity: int | None = None,
) -> dict:
    return {
        "date": date,
        "symbol": symbol,
        "side": side,
        "status": status,
        "reason": reason,
        "requested_quantity": quantity if requested_quantity is None else requested_quantity,
        "quantity": quantity,
        "fill_price": estimate.fill_price,
        "gross_value": estimate.gross_value,
        "commission": estimate.commission,
        "tax": estimate.tax,
        "cash_delta": estimate.cash_delta,
    }


def _rejected_order(
    date: pd.Timestamp,
    symbol: str,
    side: str,
    quantity: int,
    reason: str,
    *,
    requested_quantity: int | None = None,
) -> dict:
    return {
        "date": date,
        "symbol": symbol,
        "side": side,
        "status": "rejected",
        "reason": reason,
        "requested_quantity": requested_quantity if requested_quantity is not None else quantity,
        "quantity": quantity,
        "fill_price": 0.0,
        "gross_value": 0.0,
        "commission": 0.0,
        "tax": 0.0,
        "cash_delta": 0.0,
    }


def _trade_row(symbol: str, lot: dict, exit_date: pd.Timestamp, estimate, quantity: int) -> dict:
    return {
        "symbol": symbol,
        "entry_date": lot["entry_date"],
        "entry_price": lot["entry_price"],
        "exit_date": exit_date,
        "exit_price": estimate.fill_price,
        "quantity": quantity,
        "gross_pnl": (estimate.fill_price - lot["entry_price"]) * quantity,
        "costs": lot["entry_cost"] + estimate.commission + estimate.tax,
        "holding_period": max(1, (pd.Timestamp(exit_date) - pd.Timestamp(lot["entry_date"])).days),
    }


def _position_rows(date: pd.Timestamp, positions: dict[str, int], daily_bars: pd.DataFrame) -> list[dict]:
    rows = []
    for symbol, quantity in positions.items():
        if symbol in daily_bars.index:
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "quantity": quantity,
                    "market_value": quantity * float(daily_bars.loc[symbol, "close"]),
                }
            )
    return rows


def _drawdown_curve(equity_curve: pd.DataFrame) -> pd.DataFrame:
    if equity_curve.empty:
        return pd.DataFrame(columns=["date", "drawdown"])
    equity = equity_curve["equity"].astype(float)
    drawdown = equity / equity.cummax() - 1.0
    return pd.DataFrame({"date": equity_curve["date"], "drawdown": drawdown})


def _order_columns() -> list[str]:
    return [
        "date",
        "symbol",
        "side",
        "status",
        "reason",
        "requested_quantity",
        "quantity",
        "fill_price",
        "gross_value",
        "commission",
        "tax",
        "cash_delta",
    ]


def _trade_columns() -> list[str]:
    return [
        "symbol",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "quantity",
        "gross_pnl",
        "costs",
        "holding_period",
    ]
