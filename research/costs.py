from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionEstimate:
    side: str
    fill_price: float
    gross_value: float
    commission: float
    tax: float
    cash_delta: float


@dataclass(frozen=True)
class CostModel:
    commission_rate: float = 0.00015
    tax_rate: float = 0.0020
    slippage_bps: float = 5.0

    def estimate(self, side: str, *, price: float, quantity: int) -> ExecutionEstimate:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if price <= 0:
            raise ValueError("price must be positive")
        if quantity < 0:
            raise ValueError("quantity must be non-negative")

        slip = self.slippage_bps / 10000.0
        fill_price = price * (1 + slip if side == "buy" else 1 - slip)
        gross_value = fill_price * quantity
        commission = gross_value * self.commission_rate
        tax = gross_value * self.tax_rate if side == "sell" else 0.0
        cash_delta = -(gross_value + commission) if side == "buy" else gross_value - commission - tax
        return ExecutionEstimate(
            side=side,
            fill_price=round(fill_price, 10),
            gross_value=round(gross_value, 10),
            commission=round(commission, 10),
            tax=round(tax, 10),
            cash_delta=round(cash_delta, 10),
        )

    @classmethod
    def from_config(cls, config: dict) -> "CostModel":
        return cls(
            commission_rate=float(config.get("commission_rate", cls.commission_rate)),
            tax_rate=float(config.get("tax_rate", cls.tax_rate)),
            slippage_bps=float(config.get("slippage_bps", cls.slippage_bps)),
        )
