import pandas as pd
import pytest

from research.schema import validate_ohlcv_frame


def test_schema_accepts_only_chart_columns_and_sorts_rows():
    raw = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "symbol": "AAA",
                "open": 11,
                "high": 12,
                "low": 10,
                "close": 11,
                "adjusted_close": 11,
                "volume": 100,
                "traded_value": 1100,
                "market": "KOSPI",
                "listing_status": "listed",
            },
            {
                "date": "2024-01-01",
                "symbol": "AAA",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "adjusted_close": 10,
                "volume": 100,
                "traded_value": 1000,
                "market": "KOSPI",
                "listing_status": "listed",
            },
        ]
    )

    validated = validate_ohlcv_frame(raw)

    assert list(validated["date"]) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")]
    assert list(validated["symbol"]) == ["AAA", "AAA"]


def test_schema_rejects_forbidden_non_chart_columns():
    raw = pd.DataFrame(
        [
            {
                "date": "2024-01-01",
                "symbol": "AAA",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "adjusted_close": 10,
                "volume": 100,
                "traded_value": 1000,
                "market": "KOSPI",
                "pe_ratio": 7.5,
            }
        ]
    )

    with pytest.raises(ValueError, match="Forbidden or unknown columns"):
        validate_ohlcv_frame(raw)


def test_schema_rejects_missing_required_columns():
    raw = pd.DataFrame(
        [
            {
                "date": "2024-01-01",
                "symbol": "AAA",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "adjusted_close": 10,
                "volume": 100,
                "market": "KOSPI",
            }
        ]
    )

    with pytest.raises(ValueError, match="Missing required columns"):
        validate_ohlcv_frame(raw)
