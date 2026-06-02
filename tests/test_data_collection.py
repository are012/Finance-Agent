import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml


def _write_collection_config(tmp_path: Path, *, raw_path: Path, processed_name: str = "collected_ohlcv.csv") -> Path:
    config = {
        "source": {
            "type": "krx_csv",
            "input_paths": [str(raw_path)],
        },
        "output": {
            "raw_dir": str(tmp_path / "raw"),
            "staging_dir": str(tmp_path / "staging"),
            "processed_dir": str(tmp_path / "processed"),
            "processed_filename": processed_name,
            "manifest_filename": "manifest.json",
        },
        "filters": {
            "markets": ["KOSPI"],
            "exclude_listing_statuses": [],
        },
        "metadata": {
            "dataset_id": "pytest-krx-sample",
            "notes": "offline fixture only",
        },
    }
    path = tmp_path / "collection.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


def test_collect_data_cli_ingests_local_krx_csv_and_writes_manifest(tmp_path):
    raw_path = Path("data/sample/raw/krx_ohlcv_sample.csv")
    config_path = _write_collection_config(tmp_path, raw_path=raw_path)

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    processed_path = tmp_path / "processed" / "collected_ohlcv.csv"
    manifest_path = tmp_path / "processed" / "manifest.json"
    assert processed_path.exists()
    assert manifest_path.exists()

    processed = pd.read_csv(processed_path, dtype={"symbol": str})
    assert processed.columns.tolist() == [
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
    assert set(processed["market"]) == {"KOSPI"}
    assert set(processed["listing_status"]) >= {"listed", "suspended", "delisted", "admin"}
    assert not processed.duplicated(subset=["date", "symbol"]).any()
    samsung = processed[processed["symbol"].astype(str).eq("005930")]
    assert len(samsung) == 2
    assert int(samsung[samsung["date"].eq("2024-01-03")]["close"].iloc[0]) == 71600

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source"]["type"] == "krx_csv"
    assert manifest["dataset_id"] == "pytest-krx-sample"
    assert manifest["raw_rows"] == 7
    assert manifest["processed_rows"] == len(processed)
    assert manifest["market_filter"] == ["KOSPI"]
    assert manifest["listing_status_profile"]["counts"]["suspended"] == 1
    assert manifest["listing_status_profile"]["counts"]["delisted"] == 1
    assert manifest["listing_status_profile"]["counts"]["admin"] == 1
    assert manifest["input_files"][0]["sha256"]
    assert manifest["processed_file"]["sha256"]
    assert any("deduplicated" in decision for decision in manifest["schema_decisions"])


def test_collect_data_rejects_forbidden_non_chart_columns(tmp_path):
    raw_path = tmp_path / "forbidden.csv"
    raw_path.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,volume,traded_value,market,eps",
                "2024-01-02,005930,70000,71000,69500,70500,1000,70500000,KOSPI,1000",
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_collection_config(tmp_path, raw_path=raw_path)

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "Forbidden or unknown columns" in result.stderr
    assert "eps" in result.stderr


def test_optional_remote_sources_are_lazy_and_research_only():
    from research.data_sources.fdr import collect_fdr_ohlcv
    from research.data_sources.pykrx import collect_pykrx_ohlcv

    with pytest.raises(ImportError, match="FinanceDataReader"):
        collect_fdr_ohlcv(symbols=["005930"], start="2024-01-01", end="2024-01-02")
    with pytest.raises(ImportError, match="pykrx"):
        collect_pykrx_ohlcv(symbols=["005930"], start="2024-01-01", end="2024-01-02")
