from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from research.data_sources.fdr import collect_fdr_ohlcv
from research.data_sources.krx_csv import collect_krx_csv
from research.data_sources.pykrx import collect_pykrx_ohlcv
from research.reporting import FORBIDDEN_DATA
from research.schema import ALLOWED_COLUMNS, REQUIRED_COLUMNS, apply_universe_filters, validate_ohlcv_frame
from research.utils import file_hash, git_hash, utc_stamp

SOURCE_TYPES = {"krx_csv", "pykrx", "fdr"}
PROCESSED_FORMATS = {"csv", "parquet"}
STATUS_FILE_STATUSES = {"delisted", "admin", "suspended"}
DEFAULT_STATUS_PRECEDENCE = ["admin", "suspended", "delisted"]
ZERO_ROW_POLICIES = {"error", "write_empty"}
CANONICAL_OHLCV_COLUMNS = [
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
STATUS_FILE_COLUMN_ALIASES = {
    "date": "date",
    "일자": "date",
    "날짜": "date",
    "start": "start_date",
    "start_date": "start_date",
    "시작일": "start_date",
    "end": "end_date",
    "end_date": "end_date",
    "종료일": "end_date",
    "symbol": "symbol",
    "ticker": "symbol",
    "종목코드": "symbol",
    "단축코드": "symbol",
    "code": "symbol",
    "name": "name",
    "종목명": "name",
}


def load_collection_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if "source" not in config or "type" not in config["source"]:
        raise ValueError("Data collection config must define source.type")
    if "output" not in config:
        raise ValueError("Data collection config must define output directories")
    _validate_collection_config(config)
    return config


def collect_data(*, config_path: str | Path) -> dict[str, Any]:
    config = load_collection_config(config_path)
    source = config["source"]
    output = config["output"]
    raw_dir = Path(output.get("raw_dir", "data/raw"))
    staging_dir = Path(output.get("staging_dir", "data/staging"))
    processed_dir = Path(output.get("processed_dir", "data/processed"))
    for directory in (raw_dir, staging_dir, processed_dir):
        directory.mkdir(parents=True, exist_ok=True)

    staging_path = staging_dir / output.get("staging_filename", "staging_ohlcv.csv")
    processed_path, processed_format = _processed_output(output, processed_dir)
    manifest_path = processed_dir / output.get("manifest_filename", "manifest.json")
    zero_row_policy = _zero_row_policy(config, source)

    raw_frame, collection_results = _collect_source(source)
    raw_rows = int(len(raw_frame))
    if raw_rows == 0:
        if zero_row_policy == "error":
            raise ValueError("Collection produced zero rows; set zero_row_policy=write_empty to persist an empty manifest")
        raw_frame = _canonical_empty_ohlcv_frame()
    input_files = _input_files(source, raw_dir)
    raw_frame, status_files = _merge_status_files(raw_frame, config.get("status_files", {}), raw_dir)

    staging_frame = validate_ohlcv_frame(raw_frame)
    staging_frame.to_csv(staging_path, index=False)

    processed_frame = apply_universe_filters(staging_frame, _filter_config(config.get("filters", {})))
    _write_processed_frame(processed_frame, processed_path, processed_format)
    data_quality_report = _write_data_quality_report(
        raw_frame=raw_frame,
        processed_frame=processed_frame,
        processed_dir=processed_dir,
        output=output,
    )
    research_config_file = _write_research_config_if_requested(
        output=output,
        processed_dir=processed_dir,
        processed_path=processed_path,
        processed_format=processed_format,
    )

    manifest = _manifest(
        config=config,
        config_path=Path(config_path),
        source=source,
        input_files=input_files,
        status_files=status_files,
        collection_results=collection_results,
        raw_rows=raw_rows,
        staging_frame=staging_frame,
        staging_path=staging_path,
        processed_frame=processed_frame,
        processed_path=processed_path,
        processed_format=processed_format,
        zero_row_policy=zero_row_policy,
        status_precedence=_status_precedence(config.get("status_files", {})),
        data_quality_report=data_quality_report,
        research_config_file=research_config_file,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _validate_collection_config(config: dict[str, Any]) -> None:
    source = config["source"]
    output = config["output"]
    source_type = source.get("type")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Unsupported data source type: {source_type}")
    if source_type == "krx_csv":
        input_paths = source.get("input_paths", [])
        if not isinstance(input_paths, list) or not input_paths:
            raise ValueError("source.input_paths must include at least one local KRX CSV file")
        for path_value in input_paths:
            _require_existing_file(path_value, "source.input_paths")
    else:
        symbols = source.get("symbols", [])
        if not isinstance(symbols, list) or not symbols:
            raise ValueError("source.symbols must include at least one ticker for optional remote sources")
        if "start" not in source or "end" not in source:
            raise ValueError("source.start and source.end are required for optional remote sources")
    _validate_output_path_collisions(output)
    _processed_output(output, Path(output.get("processed_dir", "data/processed")))
    _retry_config(source)
    _rate_limit_config(source)
    _zero_row_policy(config, source)
    filters = config.get("filters", {})
    for key in ("markets", "exclude_listing_statuses"):
        if key in filters and not isinstance(filters[key], list):
            raise ValueError(f"filters.{key} must be a list")
    status_files = config.get("status_files", {})
    if status_files and not isinstance(status_files, dict):
        raise ValueError("status_files must be a mapping of status to local file paths")
    precedence = _status_precedence(status_files)
    configured_statuses = {status for status in status_files if status != "precedence"}
    if not configured_statuses.issubset(set(precedence)):
        raise ValueError("status_files.precedence must include every configured status")
    for status, paths in status_files.items():
        if status == "precedence":
            continue
        if status not in STATUS_FILE_STATUSES:
            raise ValueError(f"Unsupported status_files key: {status}")
        for path_value in _as_path_list(paths):
            _require_existing_file(path_value, f"status_files.{status}")


def _collect_source(source: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    source_type = source.get("type")
    if source_type == "krx_csv":
        frame = collect_krx_csv(source.get("input_paths", []))
        return frame, {
            "source_type": "krx_csv",
            "requested_symbols": [],
            "successful_symbols": [],
            "empty_symbols": [],
            "failed_symbols": [],
            "retry": _retry_config(source),
            "rate_limit": _rate_limit_config(source),
        }
    if source_type == "pykrx":
        return _collect_remote_source(source, collect_pykrx_ohlcv)
    if source_type == "fdr":
        return _collect_remote_source(source, collect_fdr_ohlcv)
    raise ValueError(f"Unsupported data source type: {source_type}")


def _collect_remote_source(source: dict[str, Any], collector) -> tuple[pd.DataFrame, dict[str, Any]]:
    retry = _retry_config(source)
    rate_limit = _rate_limit_config(source)
    rows = []
    requested = [_normalize_symbol(symbol) for symbol in source.get("symbols", [])]
    successful: list[str] = []
    empty: list[str] = []
    failed: list[dict[str, Any]] = []
    for index, symbol in enumerate(requested):
        frame = pd.DataFrame()
        last_error = ""
        for attempt in range(1, int(retry["attempts"]) + 1):
            try:
                frame = collector(
                    symbols=[symbol],
                    start=str(source["start"]),
                    end=str(source["end"]),
                    market=str(source.get("market", "KRX")),
                )
                last_error = ""
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt < int(retry["attempts"]) and retry["backoff_seconds"] > 0:
                    time.sleep(retry["backoff_seconds"])
        if last_error:
            failed.append({"symbol": symbol, "error": last_error, "attempts": int(retry["attempts"])})
        elif frame.empty:
            empty.append(symbol)
        else:
            rows.append(frame)
            successful.append(symbol)
        if index < len(requested) - 1 and rate_limit["sleep_seconds"] > 0:
            time.sleep(rate_limit["sleep_seconds"])
    combined = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return combined, {
        "source_type": source.get("type"),
        "requested_symbols": requested,
        "successful_symbols": successful,
        "empty_symbols": empty,
        "failed_symbols": failed,
        "retry": retry,
        "rate_limit": rate_limit,
    }


def _input_files(source: dict[str, Any], raw_dir: Path) -> list[dict[str, Any]]:
    if source.get("type") != "krx_csv":
        return []
    files = []
    for index, path_value in enumerate(source.get("input_paths", [])):
        path = Path(path_value)
        raw_copy = _copy_local_file(path, raw_dir, prefix=f"source_{index:03d}")
        files.append(
            {
                "path": str(path),
                "raw_copy_path": str(raw_copy),
                "sha256": file_hash(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return files


def _merge_status_files(frame: pd.DataFrame, status_files: dict[str, Any], raw_dir: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if not status_files:
        return frame, []
    data = frame.copy()
    if "listing_status" not in data.columns:
        data["listing_status"] = "listed"
    metadata = []
    decisions = list(data.attrs.get("schema_decisions", []))
    for status in _status_precedence(status_files):
        for index, path_value in enumerate(_as_path_list(status_files.get(status, []))):
            raw_copy_path = _copy_local_file(path_value, raw_dir, prefix=f"status_{status}_{index:03d}")
            status_frame = _read_status_file(path_value)
            before = data["listing_status"].copy()
            mask = _status_match_mask(data, status_frame)
            data.loc[mask, "listing_status"] = status
            changed = int((before != data["listing_status"]).sum())
            metadata.append(
                {
                    "status": status,
                    "path": str(path_value),
                    "raw_copy_path": str(raw_copy_path),
                    "sha256": file_hash(path_value),
                    "rows": int(len(status_frame)),
                    "matched_rows": int(mask.sum()),
                    "changed_rows": changed,
                }
            )
            decisions.append(f"merged {int(mask.sum())} {status} status-file matches from {path_value}; changed {changed} rows")
    data.attrs["schema_decisions"] = decisions
    return data, metadata


def _status_precedence(status_files: dict[str, Any]) -> list[str]:
    configured = status_files.get("precedence")
    if configured is None:
        return list(DEFAULT_STATUS_PRECEDENCE)
    if not isinstance(configured, list) or not configured:
        raise ValueError("status_files.precedence must be a non-empty list")
    precedence = [str(status) for status in configured]
    invalid = sorted(set(precedence) - STATUS_FILE_STATUSES)
    if invalid:
        raise ValueError(f"status_files.precedence contains unsupported statuses: {invalid}")
    if len(precedence) != len(set(precedence)):
        raise ValueError("status_files.precedence must not contain duplicates")
    return precedence


def _read_status_file(path: str | Path) -> pd.DataFrame:
    source_path = Path(path)
    if source_path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(source_path)
    else:
        frame = pd.read_csv(source_path, dtype=str)
    frame = frame.rename(columns={column: _status_file_column(column) for column in frame.columns})
    allowed = {"date", "start_date", "end_date", "symbol", "name"}
    unknown = sorted(set(frame.columns) - allowed)
    if unknown:
        raise ValueError(f"Forbidden or unknown status file columns: {unknown}")
    if "symbol" not in frame.columns:
        raise ValueError(f"Status file must include symbol: {source_path}")
    result = frame[[column for column in ("date", "start_date", "end_date", "symbol") if column in frame.columns]].copy()
    result["symbol"] = result["symbol"].map(_normalize_symbol)
    for column in ("date", "start_date", "end_date"):
        if column in result.columns:
            result[column] = _parse_status_date_column(result[column], column=column, source_path=source_path)
    if "start_date" in result.columns and "end_date" in result.columns:
        start_dates = pd.to_datetime(result["start_date"], errors="coerce")
        end_dates = pd.to_datetime(result["end_date"], errors="coerce")
        invalid_range = start_dates.notna() & end_dates.notna() & (start_dates > end_dates)
        if invalid_range.any():
            raise ValueError(f"Invalid status file date range in {source_path}: start_date must be <= end_date")
    return result.drop_duplicates().reset_index(drop=True)


def _parse_status_date_column(series: pd.Series, *, column: str, source_path: Path) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    present = values.ne("")
    parsed = pd.to_datetime(values.where(present), errors="coerce")
    invalid = present & parsed.isna()
    if invalid.any():
        bad_values = sorted(set(values[invalid]))
        raise ValueError(f"Invalid status file {column} value in {source_path}: {bad_values}")
    return parsed.dt.strftime("%Y-%m-%d")


def _status_match_mask(data: pd.DataFrame, status_frame: pd.DataFrame) -> pd.Series:
    if status_frame.empty:
        return pd.Series(False, index=data.index)
    if "date" not in status_frame.columns:
        row_dates = pd.to_datetime(data["date"], errors="raise")
        symbol_values = data["symbol"].astype(str)
        mask = pd.Series(False, index=data.index)
        has_range = "start_date" in status_frame.columns or "end_date" in status_frame.columns
        if not has_range:
            return symbol_values.isin(set(status_frame["symbol"]))
        for _, row in status_frame.iterrows():
            row_mask = symbol_values.eq(str(row["symbol"]))
            start_date = row.get("start_date")
            end_date = row.get("end_date")
            if pd.notna(start_date):
                row_mask &= row_dates >= pd.Timestamp(start_date)
            if pd.notna(end_date):
                row_mask &= row_dates <= pd.Timestamp(end_date)
            mask |= row_mask
        return mask
    row_dates = pd.to_datetime(data["date"], errors="raise").dt.strftime("%Y-%m-%d")
    row_keys = pd.Series(list(zip(row_dates, data["symbol"].astype(str))), index=data.index)
    status_keys = set(zip(status_frame["date"], status_frame["symbol"]))
    return row_keys.isin(status_keys)


def _filter_config(filters: dict[str, Any]) -> dict[str, Any]:
    result = {
        "markets": filters.get("markets", []),
        "exclude_listing_statuses": filters.get("exclude_listing_statuses", []),
    }
    return {key: value for key, value in result.items() if value not in (None, [])}


def _processed_output(output: dict[str, Any], processed_dir: Path) -> tuple[Path, str]:
    filename = str(output.get("processed_filename", "collected_ohlcv.csv"))
    path = processed_dir / filename
    explicit_format = output.get("processed_format")
    suffix = path.suffix.lower().lstrip(".")
    if explicit_format is not None:
        processed_format = str(explicit_format).lower()
        if processed_format not in PROCESSED_FORMATS:
            raise ValueError("processed output format must be csv or parquet")
        if suffix and suffix != processed_format:
            raise ValueError("processed output filename extension must match processed_format")
        return path, processed_format
    if suffix in PROCESSED_FORMATS:
        return path, suffix
    raise ValueError("processed output must use .csv or .parquet, or define output.processed_format")


def _validate_output_path_collisions(output: dict[str, Any]) -> None:
    staging_dir = Path(output.get("staging_dir", "data/staging"))
    processed_dir = Path(output.get("processed_dir", "data/processed"))
    paths = {
        "staging": staging_dir / output.get("staging_filename", "staging_ohlcv.csv"),
        "processed": processed_dir / str(output.get("processed_filename", "collected_ohlcv.csv")),
        "manifest": processed_dir / output.get("manifest_filename", "manifest.json"),
    }
    resolved: dict[Path, str] = {}
    for label, path in paths.items():
        resolved_path = path.resolve(strict=False)
        if resolved_path in resolved:
            raise ValueError(f"Output paths must not collide: {resolved[resolved_path]} and {label} both use {resolved_path}")
        resolved[resolved_path] = label


def _write_processed_frame(frame: pd.DataFrame, path: Path, processed_format: str) -> None:
    if processed_format == "csv":
        frame.to_csv(path, index=False)
        return
    if processed_format == "parquet":
        frame.to_parquet(path, index=False)
        return
    raise ValueError(f"Unsupported processed output format: {processed_format}")


def _write_data_quality_report(
    *,
    raw_frame: pd.DataFrame,
    processed_frame: pd.DataFrame,
    processed_dir: Path,
    output: dict[str, Any],
) -> dict[str, Any]:
    json_path = processed_dir / output.get("data_quality_report_json_filename", "data_quality_report.json")
    csv_path = processed_dir / output.get("data_quality_report_csv_filename", "data_quality_report.csv")
    payload = _data_quality_payload(raw_frame=raw_frame, processed_frame=processed_frame)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    _data_quality_rows(payload).to_csv(csv_path, index=False)
    return {
        "json": {"path": str(json_path), "sha256": file_hash(json_path)},
        "csv": {"path": str(csv_path), "sha256": file_hash(csv_path)},
    }


def _data_quality_payload(*, raw_frame: pd.DataFrame, processed_frame: pd.DataFrame) -> dict[str, Any]:
    processed = processed_frame.copy()
    if processed.empty:
        row_counts_by_symbol: dict[str, int] = {}
        date_coverage = {"start": None, "end": None, "unique_dates": 0, "row_count": 0}
        listing_status_counts: dict[str, int] = {}
        market_counts: dict[str, int] = {}
    else:
        dates = pd.to_datetime(processed["date"], errors="raise")
        row_counts_by_symbol = {str(key): int(value) for key, value in processed["symbol"].astype(str).value_counts().sort_index().items()}
        date_coverage = {
            "start": dates.min().strftime("%Y-%m-%d"),
            "end": dates.max().strftime("%Y-%m-%d"),
            "unique_dates": int(dates.nunique()),
            "row_count": int(len(processed)),
        }
        listing_status_counts = {
            str(key): int(value) for key, value in processed["listing_status"].fillna("missing").astype(str).value_counts().sort_index().items()
        }
        market_counts = {str(key): int(value) for key, value in processed["market"].astype(str).value_counts().sort_index().items()}
    return {
        "row_counts_by_symbol": row_counts_by_symbol,
        "date_coverage": date_coverage,
        "missing_required_columns": sorted(REQUIRED_COLUMNS - set(raw_frame.columns)),
        "ohlc_anomaly_counts": _ohlc_anomaly_counts(raw_frame),
        "listing_status_counts": listing_status_counts,
        "market_counts": market_counts,
        "duplicate_removal_summary": _duplicate_removal_summary(raw_frame),
    }


def _data_quality_rows(payload: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for section, values in payload.items():
        if isinstance(values, dict):
            for key, value in values.items():
                rows.append({"section": section, "key": key, "value": value})
        else:
            rows.append({"section": section, "key": "value", "value": values})
    return pd.DataFrame(rows, columns=["section", "key", "value"])


def _ohlc_anomaly_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = {
        "non_positive_price_rows": 0,
        "high_below_low_rows": 0,
        "high_below_open_rows": 0,
        "high_below_close_rows": 0,
        "low_above_open_rows": 0,
        "low_above_close_rows": 0,
        "negative_volume_or_traded_value_rows": 0,
    }
    required = {"open", "high", "low", "close", "volume", "traded_value"}
    if not required.issubset(frame.columns):
        return counts
    numeric = frame[list(required)].apply(pd.to_numeric, errors="coerce")
    counts["non_positive_price_rows"] = int((numeric[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    counts["high_below_low_rows"] = int((numeric["high"] < numeric["low"]).sum())
    counts["high_below_open_rows"] = int((numeric["high"] < numeric["open"]).sum())
    counts["high_below_close_rows"] = int((numeric["high"] < numeric["close"]).sum())
    counts["low_above_open_rows"] = int((numeric["low"] > numeric["open"]).sum())
    counts["low_above_close_rows"] = int((numeric["low"] > numeric["close"]).sum())
    counts["negative_volume_or_traded_value_rows"] = int((numeric[["volume", "traded_value"]] < 0).any(axis=1).sum())
    return counts


def _duplicate_removal_summary(frame: pd.DataFrame) -> dict[str, int]:
    if not {"date", "symbol"}.issubset(frame.columns):
        return {"duplicate_date_symbol_rows": 0, "duplicate_date_symbol_keys": 0, "removed_rows": 0}
    duplicate_rows = int(frame.duplicated(subset=["date", "symbol"], keep="last").sum())
    duplicate_keys = int(frame.loc[frame.duplicated(subset=["date", "symbol"], keep=False), ["date", "symbol"]].drop_duplicates().shape[0])
    return {
        "duplicate_date_symbol_rows": duplicate_rows,
        "duplicate_date_symbol_keys": duplicate_keys,
        "removed_rows": duplicate_rows,
    }


def _write_research_config_if_requested(*, output: dict[str, Any], processed_dir: Path, processed_path: Path, processed_format: str) -> dict[str, Any] | None:
    filename = output.get("research_config_filename")
    if not filename:
        return None
    path = processed_dir / filename
    template_path = Path(output.get("research_config_template", "configs/example.yaml"))
    if template_path.exists():
        with template_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    else:
        payload = {}
    payload["data"] = {
        **dict(payload.get("data") or {}),
        "path": str(processed_path),
        "format": processed_format,
        "date_column": "date",
        "symbol_column": "symbol",
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"path": str(path), "sha256": file_hash(path)}


def _retry_config(source: dict[str, Any]) -> dict[str, Any]:
    retry = source.get("retry", {}) or {}
    attempts = int(retry.get("attempts", 1))
    backoff_seconds = float(retry.get("backoff_seconds", 0))
    if attempts < 1:
        raise ValueError("retry.attempts must be >= 1")
    if backoff_seconds < 0:
        raise ValueError("retry.backoff_seconds must be >= 0")
    return {"attempts": attempts, "backoff_seconds": backoff_seconds}


def _rate_limit_config(source: dict[str, Any]) -> dict[str, Any]:
    rate_limit = source.get("rate_limit", {}) or {}
    sleep_seconds = float(rate_limit.get("sleep_seconds", 0))
    if sleep_seconds < 0:
        raise ValueError("rate_limit.sleep_seconds must be >= 0")
    return {"sleep_seconds": sleep_seconds}


def _zero_row_policy(config: dict[str, Any], source: dict[str, Any]) -> str:
    default = "write_empty" if source.get("type") in {"pykrx", "fdr"} else "error"
    policy = str(config.get("zero_row_policy", source.get("zero_row_policy", default)))
    if policy not in ZERO_ROW_POLICIES:
        raise ValueError("zero_row_policy must be error or write_empty")
    return policy


def _canonical_empty_ohlcv_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_OHLCV_COLUMNS)


def _source_manifest(source: dict[str, Any]) -> dict[str, Any]:
    source_type = source.get("type")
    base = {"type": source_type, "research_only": True}
    if source_type == "krx_csv":
        base.update(
            {
                "provider_name": "local_krx_csv",
                "provider_mode": "local_offline",
                "adjusted_close_policy": "uses_local_adjusted_close_or_fills_from_close",
                "traded_value_policy": "uses_local_traded_value",
                "warnings": [],
            }
        )
    elif source_type == "pykrx":
        base.update(
            {
                "provider_name": "pykrx",
                "provider_mode": "optional_remote_convenience",
                "adjusted_close_policy": "raw_close_copied_to_adjusted_close",
                "traded_value_policy": "uses_provider_traded_value",
                "warnings": [],
            }
        )
    elif source_type == "fdr":
        base.update(
            {
                "provider_name": "FinanceDataReader",
                "provider_mode": "optional_remote_convenience",
                "adjusted_close_policy": "raw_close_copied_to_adjusted_close",
                "traded_value_policy": "estimated_close_times_volume",
                "warnings": ["FDR source estimates traded_value as close * volume because provider output lacks traded_value."],
            }
        )
    return base


def _manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    source: dict[str, Any],
    input_files: list[dict[str, Any]],
    status_files: list[dict[str, Any]],
    collection_results: dict[str, Any],
    raw_rows: int,
    staging_frame: pd.DataFrame,
    staging_path: Path,
    processed_frame: pd.DataFrame,
    processed_path: Path,
    processed_format: str,
    zero_row_policy: str,
    status_precedence: list[str],
    data_quality_report: dict[str, Any],
    research_config_file: dict[str, Any] | None,
) -> dict[str, Any]:
    filters = config.get("filters", {})
    return {
        "dataset_id": config.get("metadata", {}).get("dataset_id", processed_path.stem),
        "created_at": utc_stamp(),
        "git_hash": git_hash(),
        "config_path": str(config_path),
        "source": _source_manifest(source),
        "input_files": input_files,
        "status_files": status_files,
        "status_precedence": status_precedence,
        "collection_results": collection_results,
        "zero_row_policy": zero_row_policy,
        "raw_rows": raw_rows,
        "staging_rows": int(len(staging_frame)),
        "processed_rows": int(len(processed_frame)),
        "raw_dir": str(Path(config["output"].get("raw_dir", "data/raw"))),
        "staging_file": {"path": str(staging_path), "format": "csv", "sha256": file_hash(staging_path)},
        "processed_file": {"path": str(processed_path), "format": processed_format, "sha256": file_hash(processed_path)},
        "data_quality_report": data_quality_report,
        "research_config_file": research_config_file,
        "allowed_columns": sorted(ALLOWED_COLUMNS),
        "forbidden_data": FORBIDDEN_DATA,
        "market_filter": list(filters.get("markets", [])),
        "excluded_listing_statuses": list(filters.get("exclude_listing_statuses", [])),
        "schema_decisions": list(processed_frame.attrs.get("schema_decisions", [])),
        "listing_status_profile": processed_frame.attrs.get("listing_status_profile", {}),
        "collection_constraints": {
            "offline_reproducible": source.get("type") == "krx_csv",
            "chart_allowed_only": True,
            "live_trading_data": False,
            "broker_integration": False,
        },
        "notes": config.get("metadata", {}).get("notes", ""),
    }


def _as_path_list(paths: Any) -> list[str | Path]:
    if paths in (None, ""):
        return []
    if isinstance(paths, (str, Path)):
        return [paths]
    if isinstance(paths, list):
        return paths
    raise ValueError("status file paths must be a path string or list of path strings")


def _require_existing_file(path_value: str | Path, field: str) -> None:
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        raise ValueError(f"{field} must reference an existing local file: {path}")


def _copy_local_file(path_value: str | Path, raw_dir: Path, *, prefix: str) -> Path:
    path = Path(path_value)
    raw_copy = raw_dir / f"{prefix}_{file_hash(path)[:12]}_{path.name}"
    if path.resolve() != raw_copy.resolve():
        shutil.copy2(path, raw_copy)
    return raw_copy


def _status_file_column(column: str) -> str:
    key = str(column).strip()
    return STATUS_FILE_COLUMN_ALIASES.get(key, STATUS_FILE_COLUMN_ALIASES.get(key.lower(), key))


def _normalize_symbol(value: object) -> str:
    symbol = str(value).strip()
    if symbol.endswith(".0"):
        symbol = symbol[:-2]
    return symbol.zfill(6) if symbol.isdigit() and len(symbol) <= 6 else symbol
