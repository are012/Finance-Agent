from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from ..models import ChartContext


class MarketDataService:
    def resolve_chart_context(self, ticker: str, market: str) -> ChartContext:
        raw_ticker = ticker.strip().upper()
        if not raw_ticker:
            raise ValueError("ticker must not be empty")

        notes: list[str] = []
        data_ticker = raw_ticker
        tradingview_symbol = raw_ticker

        if market == "kr_equity":
            normalized = raw_ticker
            if ":" in normalized:
                normalized = normalized.split(":", 1)[1]
            if normalized.endswith(".KS") or normalized.endswith(".KQ"):
                code = normalized.split(".", 1)[0]
                data_ticker = normalized
            elif normalized.isdigit() and len(normalized) == 6:
                code = normalized
                data_ticker = f"{normalized}.KS"
                notes.append("KR 시장은 접미사가 없으면 기본적으로 코스피(.KS)로 해석합니다.")
            else:
                code = normalized
            tradingview_symbol = f"KRX:{code}"
        elif market == "usa_equity":
            tradingview_symbol = raw_ticker
        else:
            notes.append("알 수 없는 market 값이라 원본 ticker를 그대로 사용합니다.")

        return ChartContext(
            ticker=raw_ticker,
            market=market,
            data_ticker=data_ticker,
            tradingview_symbol=tradingview_symbol,
            notes=notes,
        )

    def fetch_history(
        self,
        ticker: str,
        market: str,
        start_date: date,
        end_date: date,
    ) -> tuple[ChartContext, pd.DataFrame]:
        context = self.resolve_chart_context(ticker=ticker, market=market)
        frame = yf.download(
            context.data_ticker,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        frame = self._normalize_frame(frame)

        if frame.empty:
            raise ValueError(f"No market data returned for {context.data_ticker}")

        return context, frame

    @staticmethod
    def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame.copy()

        if isinstance(normalized.columns, pd.MultiIndex):
            normalized.columns = [item[0] for item in normalized.columns]

        normalized.columns = [str(column).strip().lower() for column in normalized.columns]
        normalized.index = pd.to_datetime(normalized.index)
        if getattr(normalized.index, "tz", None) is not None:
            normalized.index = normalized.index.tz_localize(None)
        normalized = normalized.rename(
            columns={
                "adj close": "close",
            }
        )

        required_columns = ["open", "high", "low", "close", "volume"]
        missing_columns = [column for column in required_columns if column not in normalized.columns]
        if missing_columns:
            raise ValueError("Downloaded data is missing required columns: " + ", ".join(missing_columns))

        return normalized[required_columns].dropna(subset=["close"])
