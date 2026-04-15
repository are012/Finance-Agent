from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re

import pandas as pd
import yfinance as yf

from ..models import ChartContext

try:
    import FinanceDataReader as fdr
except ImportError:  # pragma: no cover - optional dependency at runtime
    fdr = None


class MarketDataService:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

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

        cache_path = self._cache_path(context)
        cached_frame = self._load_cache(cache_path)
        cached_slice = self._slice_frame(cached_frame, start_date=start_date, end_date=end_date)

        if self._covers_requested_range(cached_slice, start_date=start_date, end_date=end_date):
            context.notes.append("로컬 시세 캐시를 사용했습니다.")
            return context, cached_slice

        errors: list[str] = []
        fetched_frame = None
        data_source = None

        for source_name, fetcher in (
            ("FinanceDataReader", self._fetch_with_finance_data_reader),
            ("yfinance", self._fetch_with_yfinance),
        ):
            try:
                fetched_frame = fetcher(context=context, start_date=start_date, end_date=end_date)
                data_source = source_name
                break
            except Exception as exc:
                errors.append(f"{source_name}: {exc}")

        if fetched_frame is None:
            if cached_slice is not None and not cached_slice.empty:
                context.notes.append("원격 시세 조회가 실패해 기존 캐시된 데이터를 사용했습니다.")
                context.notes.extend(errors)
                return context, cached_slice
            raise ValueError("시장 데이터를 불러오지 못했습니다. " + " | ".join(errors))

        merged = self._merge_frames(cached_frame, fetched_frame)
        self._save_cache(cache_path, merged)

        sliced = self._slice_frame(merged, start_date=start_date, end_date=end_date)
        if sliced.empty:
            raise ValueError(f"No market data returned for {context.data_ticker}")

        context.notes.append(f"{data_source} 데이터 소스를 사용했습니다.")
        if cached_frame is not None and not cached_frame.empty:
            context.notes.append("새 시세와 기존 캐시를 병합했습니다.")

        return context, sliced

    def _fetch_with_finance_data_reader(
        self,
        context: ChartContext,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        if fdr is None:
            raise RuntimeError("FinanceDataReader is not installed")

        errors: list[str] = []
        for candidate in self._finance_data_reader_candidates(context):
            try:
                frame = fdr.DataReader(candidate, start_date.isoformat(), end_date.isoformat())
                frame = self._normalize_frame(frame)
                if frame.empty:
                    raise ValueError("empty frame")
                return frame
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")

        raise RuntimeError(" / ".join(errors) if errors else "no valid FinanceDataReader ticker candidates")

    def _fetch_with_yfinance(
        self,
        context: ChartContext,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
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
        return frame

    @staticmethod
    def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame.copy()

        if normalized.empty:
            return normalized

        if isinstance(normalized.columns, pd.MultiIndex):
            normalized.columns = [item[0] for item in normalized.columns]

        normalized.columns = [str(column).strip().lower().replace("_", " ") for column in normalized.columns]
        normalized.index = pd.to_datetime(normalized.index)
        if getattr(normalized.index, "tz", None) is not None:
            normalized.index = normalized.index.tz_localize(None)

        if "adjclose" in normalized.columns and "adj close" not in normalized.columns:
            normalized = normalized.rename(columns={"adjclose": "adj close"})

        if "adj close" in normalized.columns:
            normalized["close"] = normalized["adj close"]
            normalized = normalized.drop(columns=["adj close"])

        required_columns = ["open", "high", "low", "close", "volume"]
        missing_columns = [column for column in required_columns if column not in normalized.columns]
        if missing_columns:
            raise ValueError("Downloaded data is missing required columns: " + ", ".join(missing_columns))

        normalized = normalized[required_columns]
        normalized = normalized.sort_index()
        normalized = normalized.loc[~normalized.index.duplicated(keep="last")]

        return normalized.dropna(subset=["close"])

    @staticmethod
    def _finance_data_reader_candidates(context: ChartContext) -> list[str]:
        if context.market == "kr_equity":
            code = context.data_ticker.split(".", 1)[0]
            code = code.split(":", 1)[-1]
            return [code]

        if context.market == "usa_equity":
            return [context.ticker, context.data_ticker]

        return [context.ticker, context.data_ticker]

    @staticmethod
    def _merge_frames(cached_frame: pd.DataFrame | None, fetched_frame: pd.DataFrame) -> pd.DataFrame:
        if cached_frame is None or cached_frame.empty:
            return fetched_frame.sort_index()

        merged = pd.concat([cached_frame, fetched_frame]).sort_index()
        merged = merged.loc[~merged.index.duplicated(keep="last")]
        return merged

    @staticmethod
    def _slice_frame(
        frame: pd.DataFrame | None,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        return frame.loc[start_date.isoformat() : end_date.isoformat()].copy()

    @staticmethod
    def _covers_requested_range(frame: pd.DataFrame, start_date: date, end_date: date) -> bool:
        if frame.empty:
            return False

        first_date = frame.index.min().date()
        last_date = frame.index.max().date()
        return first_date <= start_date + timedelta(days=7) and last_date >= end_date - timedelta(days=7)

    def _cache_path(self, context: ChartContext) -> Path | None:
        if self.cache_dir is None:
            return None

        market_dir = self.cache_dir / context.market
        market_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", context.ticker)
        return market_dir / f"{safe_name}.csv"

    @staticmethod
    def _load_cache(cache_path: Path | None) -> pd.DataFrame | None:
        if cache_path is None or not cache_path.exists():
            return None

        frame = pd.read_csv(cache_path, index_col="date", parse_dates=["date"])
        return MarketDataService._normalize_frame(frame)

    @staticmethod
    def _save_cache(cache_path: Path | None, frame: pd.DataFrame) -> None:
        if cache_path is None or frame.empty:
            return

        cached = frame.copy()
        cached.index.name = "date"
        cached.to_csv(cache_path)
