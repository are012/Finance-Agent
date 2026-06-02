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
from research.schema import ALLOWED_COLUMNS, apply_universe_filters, validate_ohlcv_frame
from research.utils import file_hash, git_hash, utc_stamp

SOURCE_TYPES = {"krx_csv", "pykrx", "fdr"}
PROCESSED_FORMATS = {"csv", "parquet"}
STATUS_FILE_STATUSES = {"delisted", "admin", "suspended"}
STATUS_FILE_COLUMN_ALIASES = {
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

    raw_frame, collection_results = _collect_source(source)
    raw_rows = int(len(raw_frame))
    input_files = _input_files(source, raw_dir)
    raw_frame, status_files = _merge_status_files(raw_frame, config.get("status_files", {}))

    staging_frame = validate_ohlcv_frame(raw_frame)
    staging_path = staging_dir / output.get("staging_filename", "staging_ohlcv.csv")
    staging_frame.to_csv(staging_path, index=False)

    processed_frame = apply_universe_filters(staging_frame, _filter_config(config.get("filters", {})))
    processed_path, processed_format = _processed_output(output, processed_dir)
    _write_processed_frame(processed_frame, processed_path, processed_format)

    manifest_path = processed_dir / output.get("manifest_filename", "manifest.json")
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
    _processed_output(output, Path(output.get("processed_dir", "data/processed")))
    _retry_config(source)
    _rate_limit_config(source)
    filters = config.get("filters", {})
    for key in ("markets", "exclude_listing_statuses"):
        if key in filters and not isinstance(filters[key], list):
            raise ValueError(f"filters.{key} must be a list")
    status_files = config.get("status_files", {})
    if status_files and not isinstance(status_files, dict):
        raise ValueError("status_files must be a mapping of status to local file paths")
    for status, paths in status_files.items():
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
    for path_value in source.get("input_paths", []):
        path = Path(path_value)
        raw_copy = raw_dir / path.name
        if path.resolve() != raw_copy.resolve():
            shutil.copy2(path, raw_copy)
        files.append(
            {
                "path": str(path),
                "raw_copy_path": str(raw_copy),
                "sha256": file_hash(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return files


def _merge_status_files(frame: pd.DataFrame, status_files: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if not status_files:
        return frame, []
    data = frame.copy()
    if "listing_status" not in data.columns:
        data["listing_status"] = "listed"
    metadata = []
    decisions = list(data.attrs.get("schema_decisions", []))
    for status in ("admin", "suspended", "delisted"):
        for path_value in _as_path_list(status_files.get(status, [])):
            status_frame = _read_status_file(path_value)
            before = data["listing_status"].copy()
            mask = _status_match_mask(data, status_frame)
            data.loc[mask, "listing_status"] = status
            changed = int((before != data["listing_status"]).sum())
            metadata.append(
                {
                    "status": status,
                    "path": str(path_value),
                    "sha256": file_hash(path_value),
                    "rows": int(len(status_frame)),
                    "matched_rows": int(mask.sum()),
                    "changed_rows": changed,
                }
            )
            decisions.append(f"merged {int(mask.sum())} {status} status-file matches from {path_value}; changed {changed} rows")
    data.attrs["schema_decisions"] = decisions
    return data, metadata


def _read_status_file(path: str | Path) -> pd.DataFrame:
    source_path = Path(path)
    if source_path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(source_path)
    else:
        frame = pd.read_csv(source_path, dtype=str)
    frame = frame.rename(columns={column: _status_file_column(column) for column in frame.columns})
    allowed = {"date", "symbol", "name"}
    unknown = sorted(set(frame.columns) - allowed)
    if unknown:
        raise ValueError(f"Forbidden or unknown status file columns: {unknown}")
    if "symbol" not in frame.columns:
        raise ValueError(f"Status file must include symbol: {source_path}")
    result = frame[[column for column in ("date", "symbol") if column in frame.columns]].copy()
    result["symbol"] = result["symbol"].map(_normalize_symbol)
    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"], errors="raise").dt.strftime("%Y-%m-%d")
    return result.drop_duplicates().reset_index(drop=True)


def _status_match_mask(data: pd.DataFrame, status_frame: pd.DataFrame) -> pd.Series:
    if status_frame.empty:
        return pd.Series(False, index=data.index)
    if "date" not in status_frame.columns:
        return data["symbol"].astype(str).isin(set(status_frame["symbol"]))
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


def _write_processed_frame(frame: pd.DataFrame, path: Path, processed_format: str) -> None:
    if processed_format == "csv":
        frame.to_csv(path, index=False)
        return
    if processed_format == "parquet":
        frame.to_parquet(path, index=False)
        return
    raise ValueError(f"Unsupported processed output format: {processed_format}")


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
) -> dict[str, Any]:
    filters = config.get("filters", {})
    return {
        "dataset_id": config.get("metadata", {}).get("dataset_id", processed_path.stem),
        "created_at": utc_stamp(),
        "git_hash": git_hash(),
        "config_path": str(config_path),
        "source": {"type": source.get("type"), "research_only": True},
        "input_files": input_files,
        "status_files": status_files,
        "collection_results": collection_results,
        "raw_rows": raw_rows,
        "staging_rows": int(len(staging_frame)),
        "processed_rows": int(len(processed_frame)),
        "raw_dir": str(Path(config["output"].get("raw_dir", "data/raw"))),
        "staging_file": {"path": str(staging_path), "format": "csv", "sha256": file_hash(staging_path)},
        "processed_file": {"path": str(processed_path), "format": processed_format, "sha256": file_hash(processed_path)},
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


def _status_file_column(column: str) -> str:
    key = str(column).strip()
    return STATUS_FILE_COLUMN_ALIASES.get(key, STATUS_FILE_COLUMN_ALIASES.get(key.lower(), key))


def _normalize_symbol(value: object) -> str:
    symbol = str(value).strip()
    if symbol.endswith(".0"):
        symbol = symbol[:-2]
    return symbol.zfill(6) if symbol.isdigit() and len(symbol) <= 6 else symbol
