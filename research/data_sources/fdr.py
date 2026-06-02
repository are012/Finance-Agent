from __future__ import annotations

from typing import Iterable

import pandas as pd


def collect_fdr_ohlcv(*, symbols: Iterable[str], start: str, end: str, market: str = "KRX") -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr
    except ImportError as exc:
        raise ImportError("FinanceDataReader is optional. Install the data extra to use the FDR source.") from exc

    rows = []
    for symbol in symbols:
        frame = fdr.DataReader(str(symbol), start, end)
        if frame.empty:
            continue
        data = frame.reset_index().rename(
            columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        data["symbol"] = str(symbol).zfill(6)
        data["adjusted_close"] = data["close"]
        data["traded_value"] = data["close"].astype(float) * data["volume"].astype(float)
        data["market"] = market
        data["listing_status"] = "listed"
        rows.append(data)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)
