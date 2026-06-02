from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from research.costs import CostModel
from research.metrics import compute_metrics


@dataclass(frozen=True)
class SplitConfig:
    train_fraction: float | None = None
    validation_fraction: float | None = None
    holdout_fraction: float | None = None
    train_start: str | None = None
    train_end: str | None = None
    validation_start: str | None = None
    validation_end: str | None = None
    final_holdout_start: str | None = None
    final_holdout_end: str | None = None

    def __post_init__(self) -> None:
        if self.train_start:
            required = [
                self.train_end,
                self.validation_start,
                self.validation_end,
                self.final_holdout_start,
                self.final_holdout_end,
            ]
            if any(value is None for value in required):
                raise ValueError("Date-based splits must define train, validation, and final_holdout ranges")
            return
        fractions = [self.train_fraction, self.validation_fraction, self.holdout_fraction]
        if any(value is None for value in fractions):
            raise ValueError("Split fractions must define train_fraction, validation_fraction, and holdout_fraction")
        total = float(self.train_fraction) + float(self.validation_fraction) + float(self.holdout_fraction)
        if abs(total - 1.0) > 1e-9:
            raise ValueError("Split fractions must sum to 1.0")
        if min(float(self.train_fraction), float(self.validation_fraction), float(self.holdout_fraction)) <= 0:
            raise ValueError("Split fractions must be positive")

    @classmethod
    def from_config(cls, config: dict) -> "SplitConfig":
        if "train_start" in config:
            return cls(
                train_start=config["train_start"],
                train_end=config["train_end"],
                validation_start=config["validation_start"],
                validation_end=config["validation_end"],
                final_holdout_start=config["final_holdout_start"],
                final_holdout_end=config["final_holdout_end"],
            )
        return cls(
            train_fraction=float(config["train_fraction"]),
            validation_fraction=float(config["validation_fraction"]),
            holdout_fraction=float(config["holdout_fraction"]),
        )


@dataclass(frozen=True)
class DataSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    holdout: pd.DataFrame


def split_by_date(frame: pd.DataFrame, config: SplitConfig) -> DataSplit:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    if config.train_start:
        train = _between(data, config.train_start, config.train_end)
        validation = _between(data, config.validation_start, config.validation_end)
        holdout = _between(data, config.final_holdout_start, config.final_holdout_end)
    else:
        unique_dates = sorted(data["date"].unique())
        if len(unique_dates) < 5:
            raise ValueError("At least 5 unique dates are required for train/validation/holdout split")
        train_count = max(1, int(len(unique_dates) * float(config.train_fraction)))
        validation_count = max(1, int(len(unique_dates) * float(config.validation_fraction)))
        if train_count + validation_count >= len(unique_dates):
            validation_count = max(1, len(unique_dates) - train_count - 1)
        train_dates = set(unique_dates[:train_count])
        validation_dates = set(unique_dates[train_count : train_count + validation_count])
        holdout_dates = set(unique_dates[train_count + validation_count :])
        train = data[data["date"].isin(train_dates)].copy()
        validation = data[data["date"].isin(validation_dates)].copy()
        holdout = data[data["date"].isin(holdout_dates)].copy()

    if train.empty or validation.empty or holdout.empty:
        raise ValueError("Train, validation, and final_holdout splits must all contain rows")
    if train["date"].max() >= validation["date"].min() or validation["date"].max() >= holdout["date"].min():
        raise ValueError("Splits must be chronological and non-overlapping")
    return DataSplit(train=train, validation=validation, holdout=holdout)


def walk_forward_splits(frame: pd.DataFrame, *, train_size: int, validation_size: int, step_size: int | None = None) -> list[DataSplit]:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    unique_dates = sorted(data["date"].unique())
    step = step_size or validation_size
    windows = []
    start = 0
    while start + train_size + validation_size <= len(unique_dates):
        train_dates = set(unique_dates[start : start + train_size])
        validation_dates = set(unique_dates[start + train_size : start + train_size + validation_size])
        train = data[data["date"].isin(train_dates)].copy()
        validation = data[data["date"].isin(validation_dates)].copy()
        windows.append(DataSplit(train=train, validation=validation, holdout=pd.DataFrame(columns=data.columns)))
        start += step
    return windows


def validation_gates_pass(metrics: dict[str, float], trades_count: int, gates: dict) -> tuple[bool, list[str]]:
    findings = []
    if metrics.get("total_return", 0.0) < float(gates.get("min_total_return", -10**9)):
        findings.append("validation total return is below gate")
    if metrics.get("cagr", 0.0) < float(gates.get("min_cagr", -10**9)):
        findings.append("validation CAGR is below gate")
    if metrics.get("sharpe", 0.0) < float(gates.get("min_sharpe", -10**9)):
        findings.append("validation Sharpe is below gate")
    max_mdd = gates.get("max_mdd")
    if max_mdd is not None and abs(metrics.get("max_drawdown", 0.0)) > float(max_mdd):
        findings.append("validation max drawdown breaches gate")
    if metrics.get("max_drawdown", 0.0) < float(gates.get("max_drawdown_floor", -1.0)):
        findings.append("validation max drawdown breaches floor")
    min_trades = int(gates.get("min_trade_count", gates.get("min_trades", 1)))
    if trades_count < min_trades:
        findings.append("trade count is below gate")
    max_turnover = gates.get("max_turnover")
    if max_turnover is not None and metrics.get("turnover", 0.0) > float(max_turnover):
        findings.append("turnover is above gate")
    return not findings, findings


def cost_sensitivity_summary(
    evaluate: Callable[[CostModel], object],
    base_cost_model: CostModel,
    multipliers: list[float],
) -> dict:
    rows = []
    for multiplier in multipliers:
        result = evaluate(base_cost_model.scaled(float(multiplier)))
        metrics = compute_metrics(result.equity_curve, trades=result.trades, orders=result.orders)
        rows.append({"multiplier": float(multiplier), "metrics": metrics})
    return {
        "rows": rows,
        "passed": all(row["metrics"].get("total_return", 0.0) >= 0 for row in rows if row["multiplier"] >= 2.0),
    }


def parameter_sensitivity_summary(base_parameters: dict, variants: list[dict] | None = None) -> dict:
    variants = variants or []
    return {
        "base_parameters": base_parameters,
        "variant_count": len(variants),
        "passed": True if not variants else all(variant.get("passed", False) for variant in variants),
        "note": "Approximate placeholder: variants are recorded; exhaustive parameter search is intentionally not performed.",
    }


def concentration_summary(trades: pd.DataFrame, equity_curve: pd.DataFrame) -> dict:
    if trades.empty or "gross_pnl" not in trades.columns:
        return {"passed": False, "max_symbol_pnl_share": 1.0, "max_year_pnl_share": 1.0, "top_trade_pnl_share": 1.0}
    pnl = trades["gross_pnl"].abs()
    total = float(pnl.sum()) or 1.0
    symbol_share = float(trades.groupby("symbol")["gross_pnl"].sum().abs().max() / total) if "symbol" in trades.columns else 1.0
    years = pd.to_datetime(trades["exit_date"]).dt.year if "exit_date" in trades.columns else pd.Series([0] * len(trades))
    year_share = float(trades.groupby(years)["gross_pnl"].sum().abs().max() / total)
    top_trade_share = float(pnl.max() / total)
    return {
        "passed": max(symbol_share, year_share, top_trade_share) <= 0.8,
        "max_symbol_pnl_share": symbol_share,
        "max_year_pnl_share": year_share,
        "top_trade_pnl_share": top_trade_share,
    }


def _between(data: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    return data[(data["date"] >= pd.Timestamp(start)) & (data["date"] <= pd.Timestamp(end))].copy()
