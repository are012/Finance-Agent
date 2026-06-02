from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SplitConfig:
    train_fraction: float
    validation_fraction: float
    holdout_fraction: float

    def __post_init__(self) -> None:
        total = self.train_fraction + self.validation_fraction + self.holdout_fraction
        if abs(total - 1.0) > 1e-9:
            raise ValueError("Split fractions must sum to 1.0")
        if min(self.train_fraction, self.validation_fraction, self.holdout_fraction) <= 0:
            raise ValueError("Split fractions must be positive")

    @classmethod
    def from_config(cls, config: dict) -> "SplitConfig":
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
    unique_dates = sorted(data["date"].unique())
    if len(unique_dates) < 5:
        raise ValueError("At least 5 unique dates are required for train/validation/holdout split")

    train_count = max(1, int(len(unique_dates) * config.train_fraction))
    validation_count = max(1, int(len(unique_dates) * config.validation_fraction))
    if train_count + validation_count >= len(unique_dates):
        validation_count = max(1, len(unique_dates) - train_count - 1)
    train_dates = set(unique_dates[:train_count])
    validation_dates = set(unique_dates[train_count : train_count + validation_count])
    holdout_dates = set(unique_dates[train_count + validation_count :])

    return DataSplit(
        train=data[data["date"].isin(train_dates)].copy(),
        validation=data[data["date"].isin(validation_dates)].copy(),
        holdout=data[data["date"].isin(holdout_dates)].copy(),
    )


def validation_gates_pass(metrics: dict[str, float], trades_count: int, gates: dict) -> tuple[bool, list[str]]:
    findings = []
    if metrics.get("total_return", 0.0) < float(gates.get("min_total_return", 0.0)):
        findings.append("validation total return is below gate")
    if metrics.get("max_drawdown", 0.0) < float(gates.get("max_drawdown_floor", -1.0)):
        findings.append("validation max drawdown breaches gate")
    if trades_count < int(gates.get("min_trades", 1)):
        findings.append("trade count is below gate")
    return not findings, findings
