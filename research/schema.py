from __future__ import annotations

from typing import Iterable

import pandas as pd

REQUIRED_COLUMNS = {
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "traded_value",
    "market",
}

OPTIONAL_COLUMNS = {"listing_status"}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS

NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "traded_value",
]


def validate_ohlcv_frame(frame: pd.DataFrame, *, allowed_extra_columns: Iterable[str] = ()) -> pd.DataFrame:
    allowed = ALLOWED_COLUMNS | set(allowed_extra_columns)
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    unknown = sorted(set(frame.columns) - allowed)
    if unknown:
        raise ValueError(f"Forbidden or unknown columns: {unknown}")

    validated = frame.copy()
    validated["date"] = pd.to_datetime(validated["date"], errors="raise")
    validated["symbol"] = validated["symbol"].astype(str)
    validated["market"] = validated["market"].astype(str)

    for column in NUMERIC_COLUMNS:
        validated[column] = pd.to_numeric(validated[column], errors="raise")

    if (validated[["open", "high", "low", "close", "adjusted_close"]] <= 0).any().any():
        raise ValueError("Price columns must be positive")
    if (validated[["volume", "traded_value"]] < 0).any().any():
        raise ValueError("Volume and traded_value must be non-negative")

    duplicate_mask = validated.duplicated(subset=["date", "symbol"], keep=False)
    if duplicate_mask.any():
        duplicates = validated.loc[duplicate_mask, ["date", "symbol"]].to_dict("records")
        raise ValueError(f"Duplicate date/symbol rows: {duplicates[:5]}")

    return validated.sort_values(["symbol", "date"]).reset_index(drop=True)
