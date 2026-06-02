from __future__ import annotations

from typing import Iterable

import pandas as pd


def collect_pykrx_ohlcv(*, symbols: Iterable[str], start: str, end: str, market: str = "KRX") -> pd.DataFrame:
    try:
        from pykrx import stock
    except ImportError as exc:
        raise ImportError("pykrx is optional. Install the data extra to use the pykrx source.") from exc

    rows = []
    for symbol in symbols:
        ticker = str(symbol).zfill(6)
        frame = stock.get_market_ohlcv_by_date(start.replace("-", ""), end.replace("-", ""), ticker)
        if frame.empty:
            continue
        data = frame.reset_index().rename(
            columns={
                "날짜": "date",
                "시가": "open",
                "고가": "high",
                "저가": "low",
                "종가": "close",
                "거래량": "volume",
                "거래대금": "traded_value",
            }
        )
        data["symbol"] = ticker
        data["name"] = stock.get_market_ticker_name(ticker)
        data["adjusted_close"] = data["close"]
        data["market"] = market
        data["listing_status"] = "listed"
        rows.append(data)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)
