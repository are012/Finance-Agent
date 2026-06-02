from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

CANONICAL_COLUMNS = [
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
    "listing_status",
    "name",
    "security_type",
]

COLUMN_ALIASES = {
    "date": "date",
    "일자": "date",
    "날짜": "date",
    "symbol": "symbol",
    "ticker": "symbol",
    "종목코드": "symbol",
    "단축코드": "symbol",
    "code": "symbol",
    "name": "name",
    "종목명": "name",
    "market": "market",
    "시장": "market",
    "시장구분": "market",
    "open": "open",
    "시가": "open",
    "high": "high",
    "고가": "high",
    "low": "low",
    "저가": "low",
    "close": "close",
    "종가": "close",
    "adjusted_close": "adjusted_close",
    "수정종가": "adjusted_close",
    "volume": "volume",
    "거래량": "volume",
    "traded_value": "traded_value",
    "거래대금": "traded_value",
    "listing_status": "listing_status",
    "status": "listing_status",
    "상장상태": "listing_status",
    "상태": "listing_status",
    "security_type": "security_type",
    "종목구분": "security_type",
}

STATUS_ALIASES = {
    "": "listed",
    "상장": "listed",
    "listed": "listed",
    "normal": "listed",
    "거래정지": "suspended",
    "정지": "suspended",
    "suspended": "suspended",
    "halted": "halted",
    "상장폐지": "delisted",
    "폐지": "delisted",
    "delisted": "delisted",
    "관리": "admin",
    "관리종목": "admin",
    "admin": "admin",
}


def collect_krx_csv(input_paths: Iterable[str | Path]) -> pd.DataFrame:
    frames = [_read_one(path) for path in input_paths]
    if not frames:
        raise ValueError("source.input_paths must include at least one local KRX CSV file")
    return pd.concat(frames, ignore_index=True)


def _read_one(path: str | Path) -> pd.DataFrame:
    source_path = Path(path)
    frame = pd.read_csv(source_path, dtype=str)
    frame = frame.rename(columns={column: _canonical_column(column) for column in frame.columns})
    unknown = sorted(column for column in frame.columns if column not in CANONICAL_COLUMNS)
    if unknown:
        raise ValueError(f"Forbidden or unknown columns: {unknown}")
    if "adjusted_close" not in frame.columns and "close" in frame.columns:
        frame["adjusted_close"] = frame["close"]
    if "listing_status" not in frame.columns:
        frame["listing_status"] = "listed"
    if "name" not in frame.columns:
        frame["name"] = ""
    if "security_type" not in frame.columns:
        frame["security_type"] = ""
    frame["symbol"] = frame["symbol"].map(_normalize_symbol)
    frame["market"] = frame["market"].fillna("").astype(str).str.strip().str.upper()
    frame["listing_status"] = frame["listing_status"].map(_normalize_status)
    return frame[[column for column in CANONICAL_COLUMNS if column in frame.columns]]


def _canonical_column(column: str) -> str:
    key = str(column).strip()
    return COLUMN_ALIASES.get(key, COLUMN_ALIASES.get(key.lower(), key))


def _normalize_symbol(value: object) -> str:
    symbol = str(value).strip()
    if symbol.endswith(".0"):
        symbol = symbol[:-2]
    return symbol.zfill(6) if symbol.isdigit() and len(symbol) <= 6 else symbol


def _normalize_status(value: object) -> str:
    key = "" if pd.isna(value) else str(value).strip().lower()
    return STATUS_ALIASES.get(key, key or "listed")
