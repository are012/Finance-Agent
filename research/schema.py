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
    "volume",
    "traded_value",
    "market",
}

OPTIONAL_COLUMNS = {
    "adjusted_close",
    "listing_status",
    "name",
    "security_type",
}
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
    decisions: list[str] = []
    validated["date"] = pd.to_datetime(validated["date"], errors="raise")
    validated["symbol"] = validated["symbol"].astype(str)
    validated["market"] = validated["market"].astype(str)
    listing_status_available = "listing_status" in validated.columns
    if "listing_status" not in validated.columns:
        validated["listing_status"] = "listed"
        decisions.append("filled missing listing_status with listed")
    if "adjusted_close" not in validated.columns:
        validated["adjusted_close"] = validated["close"]
        decisions.append("filled missing adjusted_close from close")

    for column in NUMERIC_COLUMNS:
        validated[column] = pd.to_numeric(validated[column], errors="raise")

    _validate_prices(validated)
    _validate_non_negative(validated)

    duplicate_count = int(validated.duplicated(subset=["date", "symbol"], keep="last").sum())
    if duplicate_count:
        validated = validated.sort_values(["symbol", "date"]).drop_duplicates(subset=["date", "symbol"], keep="last")
        decisions.append(f"deduplicated {duplicate_count} duplicate date/symbol rows using last row")

    validated = validated.sort_values(["symbol", "date"]).reset_index(drop=True)
    validated.attrs["schema_decisions"] = decisions
    inherited_profile = frame.attrs.get("listing_status_profile") if hasattr(frame, "attrs") else None
    validated.attrs["listing_status_profile"] = inherited_profile or _listing_status_profile(
        validated,
        available=listing_status_available,
    )
    return validated


def apply_universe_filters(frame: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    config = config or {}
    data = frame.copy()
    decisions = list(data.attrs.get("schema_decisions", []))

    markets = set(config.get("markets") or [])
    if markets:
        before = len(data)
        data = data[data["market"].isin(markets)].copy()
        decisions.append(f"universe market filter removed {before - len(data)} rows")

    if config.get("exclude_suspended", False):
        before = len(data)
        data = data[~data["listing_status"].fillna("listed").str.lower().isin({"suspended", "halted"})].copy()
        decisions.append(f"excluded suspended rows: {before - len(data)}")

    if config.get("exclude_delisted", False):
        before = len(data)
        data = data[~data["listing_status"].fillna("listed").str.lower().eq("delisted")].copy()
        decisions.append(f"excluded delisted rows: {before - len(data)}")

    excluded_statuses = {str(status).lower() for status in config.get("exclude_listing_statuses", []) or []}
    if excluded_statuses:
        before = len(data)
        data = data[~data["listing_status"].fillna("listed").str.lower().isin(excluded_statuses)].copy()
        decisions.append(f"excluded listing statuses {sorted(excluded_statuses)}: {before - len(data)}")

    low_price = config.get("exclude_low_price_below")
    if low_price is not None:
        before = len(data)
        data = data[data["close"] >= float(low_price)].copy()
        decisions.append(f"excluded low-price rows: {before - len(data)}")

    min_traded_value = config.get("min_traded_value")
    if min_traded_value is not None:
        lookback = int(config.get("min_traded_value_lookback", 20))
        tv_ma = (
            data.sort_values(["symbol", "date"])
            .groupby("symbol")["traded_value"]
            .transform(lambda series: series.rolling(lookback, min_periods=1).mean())
        )
        before = len(data)
        data = data[tv_ma >= float(min_traded_value)].copy()
        decisions.append(f"excluded illiquid rows: {before - len(data)}")

    for option, pattern in (
        ("exclude_preferred", "preferred"),
        ("exclude_spacs", "spac"),
        ("exclude_etfs", "etf"),
    ):
        if config.get(option, False) and "security_type" in data.columns:
            before = len(data)
            data = data[~data["security_type"].fillna("").str.lower().str.contains(pattern)].copy()
            decisions.append(f"{option} removed {before - len(data)} rows")

    data = data.sort_values(["symbol", "date"]).reset_index(drop=True)
    data.attrs["schema_decisions"] = decisions
    data.attrs["listing_status_profile"] = _with_filtered_listing_status_counts(
        frame.attrs.get("listing_status_profile", _listing_status_profile(frame, available="listing_status" in frame.columns)),
        data,
    )
    return data


def _validate_prices(frame: pd.DataFrame) -> None:
    if (frame[["open", "high", "low", "close", "adjusted_close"]] <= 0).any().any():
        raise ValueError("Price columns must be positive")
    if (frame["high"] < frame["low"]).any():
        raise ValueError("high must be >= low")
    if (frame["high"] < frame["open"]).any():
        raise ValueError("high must be >= open")
    if (frame["high"] < frame["close"]).any():
        raise ValueError("high must be >= close")
    if (frame["low"] > frame["open"]).any():
        raise ValueError("low must be <= open")
    if (frame["low"] > frame["close"]).any():
        raise ValueError("low must be <= close")


def _validate_non_negative(frame: pd.DataFrame) -> None:
    if (frame[["volume", "traded_value"]] < 0).any().any():
        raise ValueError("Volume and traded_value must be non-negative")


def _listing_status_profile(frame: pd.DataFrame, *, available: bool) -> dict:
    counts = _listing_status_counts(frame)
    return {
        "available": bool(available),
        "row_count": int(len(frame)),
        "counts": counts,
        "filtered_counts": counts,
        "delisted_count": int(counts.get("delisted", 0)),
        "suspended_count": int(counts.get("suspended", 0)) + int(counts.get("halted", 0)),
        "admin_count": int(counts.get("admin", 0)),
    }


def _with_filtered_listing_status_counts(profile: dict, filtered: pd.DataFrame) -> dict:
    updated = dict(profile)
    filtered_counts = _listing_status_counts(filtered)
    updated["filtered_row_count"] = int(len(filtered))
    updated["filtered_counts"] = filtered_counts
    return updated


def _listing_status_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = {"listed": 0, "suspended": 0, "halted": 0, "delisted": 0, "admin": 0, "missing": 0}
    if "listing_status" not in frame.columns:
        return counts
    statuses = frame["listing_status"].fillna("missing").astype(str).str.lower()
    counts.update({str(key): int(value) for key, value in statuses.value_counts().sort_index().items()})
    return counts
