from __future__ import annotations

import json
import shutil
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


def load_collection_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if "source" not in config or "type" not in config["source"]:
        raise ValueError("Data collection config must define source.type")
    if "output" not in config:
        raise ValueError("Data collection config must define output directories")
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

    raw_frame = _collect_source(source)
    raw_rows = int(len(raw_frame))
    input_files = _input_files(source, raw_dir)

    staging_frame = validate_ohlcv_frame(raw_frame)
    staging_path = staging_dir / output.get("staging_filename", "staging_ohlcv.csv")
    staging_frame.to_csv(staging_path, index=False)

    processed_frame = apply_universe_filters(staging_frame, _filter_config(config.get("filters", {})))
    processed_path = processed_dir / output.get("processed_filename", "collected_ohlcv.csv")
    processed_frame.to_csv(processed_path, index=False)

    manifest_path = processed_dir / output.get("manifest_filename", "manifest.json")
    manifest = _manifest(
        config=config,
        config_path=Path(config_path),
        source=source,
        input_files=input_files,
        raw_rows=raw_rows,
        staging_frame=staging_frame,
        staging_path=staging_path,
        processed_frame=processed_frame,
        processed_path=processed_path,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _collect_source(source: dict[str, Any]) -> pd.DataFrame:
    source_type = source.get("type")
    if source_type == "krx_csv":
        return collect_krx_csv(source.get("input_paths", []))
    if source_type == "pykrx":
        return collect_pykrx_ohlcv(
            symbols=source.get("symbols", []),
            start=str(source["start"]),
            end=str(source["end"]),
            market=str(source.get("market", "KRX")),
        )
    if source_type == "fdr":
        return collect_fdr_ohlcv(
            symbols=source.get("symbols", []),
            start=str(source["start"]),
            end=str(source["end"]),
            market=str(source.get("market", "KRX")),
        )
    raise ValueError(f"Unsupported data source type: {source_type}")


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


def _filter_config(filters: dict[str, Any]) -> dict[str, Any]:
    result = {
        "markets": filters.get("markets", []),
        "exclude_listing_statuses": filters.get("exclude_listing_statuses", []),
    }
    return {key: value for key, value in result.items() if value not in (None, [])}


def _manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    source: dict[str, Any],
    input_files: list[dict[str, Any]],
    raw_rows: int,
    staging_frame: pd.DataFrame,
    staging_path: Path,
    processed_frame: pd.DataFrame,
    processed_path: Path,
) -> dict[str, Any]:
    filters = config.get("filters", {})
    return {
        "dataset_id": config.get("metadata", {}).get("dataset_id", processed_path.stem),
        "created_at": utc_stamp(),
        "git_hash": git_hash(),
        "config_path": str(config_path),
        "source": {"type": source.get("type"), "research_only": True},
        "input_files": input_files,
        "raw_rows": raw_rows,
        "staging_rows": int(len(staging_frame)),
        "processed_rows": int(len(processed_frame)),
        "raw_dir": str(Path(config["output"].get("raw_dir", "data/raw"))),
        "staging_file": {"path": str(staging_path), "sha256": file_hash(staging_path)},
        "processed_file": {"path": str(processed_path), "sha256": file_hash(processed_path)},
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
