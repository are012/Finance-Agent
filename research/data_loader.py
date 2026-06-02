from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from research.schema import apply_universe_filters, validate_ohlcv_frame


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    validate_config(config)
    config["_config_path"] = str(path)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if "data" not in config or "path" not in config["data"]:
        raise ValueError("Config must define data.path")
    data = config["data"]
    if data.get("format", "csv") not in {"csv", "parquet"}:
        raise ValueError("data.format must be csv or parquet")
    if "splits" not in config and "split" not in config:
        raise ValueError("Config must define splits or split")
    if config.get("research", {}).get("allow_final_holdout_during_research", False):
        raise ValueError("research.allow_final_holdout_during_research must remain false")


def load_ohlcv(path: str | Path, *, file_format: str = "csv") -> pd.DataFrame:
    if file_format == "csv":
        frame = pd.read_csv(path)
    elif file_format == "parquet":
        frame = pd.read_parquet(path)
    else:
        raise ValueError("file_format must be csv or parquet")
    return validate_ohlcv_frame(frame)


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    return load_ohlcv(path, file_format="csv")


def load_configured_data(config: dict[str, Any]) -> pd.DataFrame:
    data_config = config["data"]
    frame = load_ohlcv(data_config["path"], file_format=data_config.get("format", "csv"))
    date_column = data_config.get("date_column", "date")
    symbol_column = data_config.get("symbol_column", "symbol")
    if date_column != "date" or symbol_column != "symbol":
        frame = frame.rename(columns={date_column: "date", symbol_column: "symbol"})
        frame = validate_ohlcv_frame(frame)
    return apply_universe_filters(frame, config.get("universe", {}))
