from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_AUTH_KEY_ENV = "KRX_AUTH_KEY"
DEFAULT_ENDPOINT_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis/sto"
DEFAULT_RESPONSE_FORMAT = "json"

MARKET_ENDPOINTS = {
    "KOSPI": "stk_bydd_trd",
    "KOSDAQ": "ksq_bydd_trd",
}
DEFAULT_FIELD_MAP = {
    "date": "BAS_DD",
    "symbol": "ISU_CD",
    "name": "ISU_NM",
    "market": "MKT_NM",
    "security_type": "SECT_TP_NM",
    "open": "TDD_OPNPRC",
    "high": "TDD_HGPRC",
    "low": "TDD_LWPRC",
    "close": "TDD_CLSPRC",
    "volume": "ACC_TRDVOL",
    "traded_value": "ACC_TRDVAL",
}
MARKET_ALIASES = {
    "KOSPI": "KOSPI",
    "KRX": "KOSPI",
    "유가증권": "KOSPI",
    "유가증권시장": "KOSPI",
    "코스피": "KOSPI",
    "KOSDAQ": "KOSDAQ",
    "코스닥": "KOSDAQ",
    "코스닥시장": "KOSDAQ",
}

Transport = Callable[..., Any]


def collect_krx_openapi_ohlcv(
    *,
    start: str,
    end: str,
    markets: Iterable[str],
    auth_key_env: str = DEFAULT_AUTH_KEY_ENV,
    endpoint_base_url: str = DEFAULT_ENDPOINT_BASE_URL,
    response_format: str = DEFAULT_RESPONSE_FORMAT,
    market_endpoints: dict[str, str] | None = None,
    field_map: dict[str, str] | None = None,
    cache_dir: str | Path | None = None,
    cache_refresh: bool = False,
    timeout_seconds: float = 30,
    retry_attempts: int = 1,
    retry_backoff_seconds: float = 0,
    rate_limit_sleep_seconds: float = 0,
    transport: Transport | None = None,
) -> pd.DataFrame:
    env_name = str(auth_key_env or DEFAULT_AUTH_KEY_ENV).strip()
    auth_key = os.environ.get(env_name)
    if not auth_key:
        raise ValueError(f"KRX OpenAPI auth key environment variable is not set: {env_name}")

    requested_dates = _date_range(start, end)
    requested_markets = _normalize_markets(markets)
    endpoints = _market_endpoints(market_endpoints)
    fields = _field_map(field_map)
    cache_path = Path(cache_dir) if cache_dir else None
    if cache_path is not None:
        cache_path.mkdir(parents=True, exist_ok=True)
    endpoint_base_url = str(endpoint_base_url or DEFAULT_ENDPOINT_BASE_URL).rstrip("/")
    response_format = str(response_format if response_format is not None else DEFAULT_RESPONSE_FORMAT).strip().lstrip(".")
    timeout_seconds = float(timeout_seconds)
    retry_attempts = int(retry_attempts)
    retry_backoff_seconds = float(retry_backoff_seconds)
    rate_limit_sleep_seconds = float(rate_limit_sleep_seconds)
    request = transport or _urllib_json_transport

    rows: list[dict[str, Any]] = []
    successful_requests: list[dict[str, Any]] = []
    empty_requests: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []
    cache_hits: list[dict[str, Any]] = []
    cache_writes: list[dict[str, Any]] = []
    skipped_rows = 0
    request_count = len(requested_dates) * len(requested_markets)
    request_index = 0

    for date_value in requested_dates:
        bas_dd = date_value.replace("-", "")
        for market in requested_markets:
            request_index += 1
            api_id = endpoints[market]
            url = _endpoint_url(endpoint_base_url, api_id, response_format)
            payload: dict[str, Any] | None = None
            last_error = ""
            request_cache_path = _cache_path(cache_path, date_value=date_value, market=market, api_id=api_id, response_format=response_format)
            if request_cache_path is not None and request_cache_path.exists() and not cache_refresh:
                payload = json.loads(request_cache_path.read_text(encoding="utf-8"))
                cache_hits.append({"date": date_value, "market": market})
            else:
                for attempt in range(1, retry_attempts + 1):
                    try:
                        payload = _call_json_transport(
                            request,
                            url,
                            params={"basDd": bas_dd},
                            headers={"AUTH_KEY": auth_key},
                            timeout=timeout_seconds,
                        )
                        last_error = ""
                        break
                    except Exception as exc:
                        last_error = _safe_error(exc)
                        if attempt < retry_attempts and retry_backoff_seconds > 0:
                            time.sleep(retry_backoff_seconds)
            if last_error:
                failed_requests.append({"date": date_value, "market": market, "error": last_error, "attempts": retry_attempts})
                _sleep_between_requests(request_index, request_count, rate_limit_sleep_seconds)
                continue
            if request_cache_path is not None and (cache_refresh or not request_cache_path.exists()):
                request_cache_path.write_text(json.dumps(payload or {}, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
                cache_writes.append({"date": date_value, "market": market})

            raw_rows = _outblock_rows(payload or {})
            parsed_for_request = []
            for raw_row in raw_rows:
                parsed = _canonical_row(raw_row, fallback_date=date_value, fallback_market=market, field_map=fields)
                if parsed is None:
                    skipped_rows += 1
                    continue
                parsed_for_request.append(parsed)
            rows.extend(parsed_for_request)
            if parsed_for_request:
                successful_requests.append({"date": date_value, "market": market, "rows": len(parsed_for_request)})
            else:
                empty_requests.append({"date": date_value, "market": market})
            _sleep_between_requests(request_index, request_count, rate_limit_sleep_seconds)

    frame = pd.DataFrame(rows)
    metadata = {
        "requested_dates": requested_dates,
        "requested_markets": requested_markets,
        "successful_requests": successful_requests,
        "empty_requests": empty_requests,
        "failed_requests": failed_requests,
        "skipped_rows": skipped_rows,
        "endpoint_base_url": endpoint_base_url,
        "response_format": response_format,
        "market_endpoints": endpoints,
        "field_map": fields,
        "cache_enabled": cache_path is not None,
        "cache_dir": str(cache_path) if cache_path is not None else None,
        "cache_refresh": bool(cache_refresh),
        "cache_hits": cache_hits,
        "cache_writes": cache_writes,
    }
    frame.attrs["krx_openapi"] = metadata
    decisions = []
    if skipped_rows:
        decisions.append(f"krx_openapi skipped {skipped_rows} rows with missing or non-numeric OHLCV fields")
    frame.attrs["schema_decisions"] = decisions
    return frame


def _call_json_transport(request: Transport, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    response = request(url, params=params, headers=headers, timeout=timeout)
    status_code = int(getattr(response, "status_code", 200))
    if status_code >= 400:
        raise RuntimeError(f"KRX OpenAPI HTTP {status_code}")
    if isinstance(response, dict):
        return response
    if hasattr(response, "json"):
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("KRX OpenAPI response JSON must be an object")
        return payload
    if isinstance(response, bytes):
        return json.loads(response.decode("utf-8"))
    if isinstance(response, str):
        return json.loads(response)
    raise TypeError("KRX OpenAPI transport must return a mapping, JSON string, bytes, or object with json()")


def _urllib_json_transport(url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(full_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            if status >= 400:
                raise RuntimeError(f"KRX OpenAPI HTTP {status}")
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"KRX OpenAPI HTTP {exc.code}") from exc


def _endpoint_url(base_url: str, api_id: str, response_format: str) -> str:
    suffix = f".{response_format}" if response_format else ""
    return f"{base_url.rstrip('/')}/{api_id}{suffix}"


def _market_endpoints(overrides: dict[str, str] | None) -> dict[str, str]:
    endpoints = dict(MARKET_ENDPOINTS)
    for market, api_id in (overrides or {}).items():
        normalized_market = _normalize_markets([market])[0]
        api_id_text = str(api_id).strip()
        if not api_id_text:
            raise ValueError("KRX OpenAPI market endpoint ids must be non-empty")
        endpoints[normalized_market] = api_id_text
    return endpoints


def _field_map(overrides: dict[str, str] | None) -> dict[str, str]:
    fields = dict(DEFAULT_FIELD_MAP)
    for canonical, provider_field in (overrides or {}).items():
        canonical_text = str(canonical).strip()
        if canonical_text not in fields:
            raise ValueError(f"Unsupported KRX OpenAPI field_map key: {canonical_text}")
        provider_text = str(provider_field).strip()
        if not provider_text:
            raise ValueError("KRX OpenAPI field_map values must be non-empty")
        fields[canonical_text] = provider_text
    return fields


def _cache_path(cache_dir: Path | None, *, date_value: str, market: str, api_id: str, response_format: str) -> Path | None:
    if cache_dir is None:
        return None
    safe_api_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in api_id)
    suffix = response_format or "json"
    return cache_dir / f"{date_value.replace('-', '')}_{market}_{safe_api_id}.{suffix}"


def _date_range(start: str, end: str) -> list[str]:
    start_date = pd.Timestamp(start).date()
    end_date = pd.Timestamp(end).date()
    if start_date > end_date:
        raise ValueError("source.start must be <= source.end")
    return [day.strftime("%Y-%m-%d") for day in pd.date_range(start_date, end_date, freq="D")]


def _normalize_markets(markets: Iterable[str]) -> list[str]:
    normalized = []
    for market in markets:
        key = str(market).strip().upper()
        resolved = MARKET_ALIASES.get(key, MARKET_ALIASES.get(str(market).strip()))
        if resolved is None or resolved not in MARKET_ENDPOINTS:
            raise ValueError(f"Unsupported KRX OpenAPI market: {market}")
        normalized.append(resolved)
    if not normalized:
        raise ValueError("source.markets must include at least one KRX OpenAPI market")
    return list(dict.fromkeys(normalized))


def _outblock_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("OutBlock_1", [])
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("KRX OpenAPI response OutBlock_1 must be a list")
    return [row for row in rows if isinstance(row, dict)]


def _canonical_row(raw: dict[str, Any], *, fallback_date: str, fallback_market: str, field_map: dict[str, str]) -> dict[str, Any] | None:
    date_value = _normalize_date(raw.get(field_map["date"]) or fallback_date)
    symbol = _normalize_symbol(raw.get(field_map["symbol"], ""))
    numeric = {
        "open": _parse_number(raw.get(field_map["open"])),
        "high": _parse_number(raw.get(field_map["high"])),
        "low": _parse_number(raw.get(field_map["low"])),
        "close": _parse_number(raw.get(field_map["close"])),
        "volume": _parse_number(raw.get(field_map["volume"])),
        "traded_value": _parse_number(raw.get(field_map["traded_value"])),
    }
    if not symbol or any(value is None for value in numeric.values()):
        return None
    close = float(numeric["close"])
    return {
        "date": date_value,
        "symbol": symbol,
        "open": float(numeric["open"]),
        "high": float(numeric["high"]),
        "low": float(numeric["low"]),
        "close": close,
        "adjusted_close": close,
        "volume": float(numeric["volume"]),
        "traded_value": float(numeric["traded_value"]),
        "market": _normalize_market_name(raw.get(field_map["market"]), fallback_market),
        "listing_status": "listed",
        "name": str(raw.get(field_map["name"], "")).strip(),
        "security_type": str(raw.get(field_map["security_type"], "")).strip(),
    }


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_date(value: Any) -> str:
    text = str(value).strip().replace("/", "").replace("-", "")
    return pd.Timestamp(text).strftime("%Y-%m-%d")


def _normalize_symbol(value: Any) -> str:
    symbol = str(value).strip()
    if symbol.endswith(".0"):
        symbol = symbol[:-2]
    return symbol.zfill(6) if symbol.isdigit() and len(symbol) <= 6 else symbol


def _normalize_market_name(value: Any, fallback: str) -> str:
    text = "" if value is None else str(value).strip()
    key = text.upper()
    return MARKET_ALIASES.get(key, MARKET_ALIASES.get(text, fallback))


def _safe_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:500]


def _sleep_between_requests(request_index: int, request_count: int, seconds: float) -> None:
    if request_index < request_count and seconds > 0:
        time.sleep(seconds)
