import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml


def _write_collection_config(
    tmp_path: Path,
    *,
    raw_path: Path,
    processed_name: str = "collected_ohlcv.csv",
    processed_format: str | None = None,
    source_extra: dict | None = None,
    output_extra: dict | None = None,
    status_files: dict | None = None,
) -> Path:
    source = {
        "type": "krx_csv",
        "input_paths": [str(raw_path)],
    }
    source.update(source_extra or {})
    output = {
        "raw_dir": str(tmp_path / "raw"),
        "staging_dir": str(tmp_path / "staging"),
        "processed_dir": str(tmp_path / "processed"),
        "processed_filename": processed_name,
        "manifest_filename": "manifest.json",
    }
    if processed_format is not None:
        output["processed_format"] = processed_format
    output.update(output_extra or {})
    config = {
        "source": source,
        "output": output,
        "filters": {
            "markets": ["KOSPI"],
            "exclude_listing_statuses": [],
        },
        "metadata": {
            "dataset_id": "pytest-krx-sample",
            "notes": "offline fixture only",
        },
    }
    if status_files is not None:
        config["status_files"] = status_files
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


def test_collect_data_merges_separate_local_status_files(tmp_path):
    raw_path = tmp_path / "raw.csv"
    raw_path.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,volume,traded_value,market",
                "2024-01-02,000001,1000,1100,900,1050,100,105000,KOSPI",
                "2024-01-02,000002,2000,2100,1900,2050,100,205000,KOSPI",
                "2024-01-02,000003,3000,3100,2900,3050,100,305000,KOSPI",
            ]
        ),
        encoding="utf-8",
    )
    delisted_path = tmp_path / "delisted.csv"
    admin_path = tmp_path / "admin.csv"
    suspended_path = tmp_path / "suspended.csv"
    delisted_path.write_text("symbol\n000001\n", encoding="utf-8")
    admin_path.write_text("symbol\n000002\n", encoding="utf-8")
    suspended_path.write_text("symbol\n000003\n", encoding="utf-8")
    config_path = _write_collection_config(
        tmp_path,
        raw_path=raw_path,
        status_files={
            "delisted": [str(delisted_path)],
            "admin": [str(admin_path)],
            "suspended": [str(suspended_path)],
        },
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    processed = pd.read_csv(tmp_path / "processed" / "collected_ohlcv.csv", dtype={"symbol": str})
    statuses = dict(zip(processed["symbol"], processed["listing_status"], strict=True))
    assert statuses == {"000001": "delisted", "000002": "admin", "000003": "suspended"}
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    assert {entry["status"] for entry in manifest["status_files"]} == {"delisted", "admin", "suspended"}
    assert all(entry["sha256"] for entry in manifest["status_files"])
    assert all(entry["matched_rows"] == 1 for entry in manifest["status_files"])
    assert all(entry["changed_rows"] == 1 for entry in manifest["status_files"])
    assert all(entry["raw_copy_path"] for entry in manifest["status_files"])


def test_collect_data_merges_status_files_with_effective_date_ranges(tmp_path):
    raw_path = tmp_path / "raw.csv"
    raw_path.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,volume,traded_value,market",
                "2024-01-01,000001,1000,1100,900,1050,100,105000,KOSPI",
                "2024-01-02,000001,1000,1100,900,1050,100,105000,KOSPI",
                "2024-01-03,000001,1000,1100,900,1050,100,105000,KOSPI",
                "2024-01-04,000001,1000,1100,900,1050,100,105000,KOSPI",
            ]
        ),
        encoding="utf-8",
    )
    admin_path = tmp_path / "admin_range.csv"
    admin_path.write_text("symbol,start_date,end_date\n000001,2024-01-02,2024-01-03\n", encoding="utf-8")
    config_path = _write_collection_config(
        tmp_path,
        raw_path=raw_path,
        status_files={"admin": [str(admin_path)]},
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    processed = pd.read_csv(tmp_path / "processed" / "collected_ohlcv.csv", dtype={"symbol": str})
    assert processed["listing_status"].tolist() == ["listed", "admin", "admin", "listed"]
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status_files"] == [
        {
            "status": "admin",
            "path": str(admin_path),
            "raw_copy_path": str(tmp_path / "raw" / "admin_range.csv"),
            "sha256": manifest["status_files"][0]["sha256"],
            "rows": 1,
            "matched_rows": 2,
            "changed_rows": 2,
        }
    ]
    assert (tmp_path / "raw" / "admin_range.csv").exists()


def test_collect_data_writes_parquet_processed_output(tmp_path):
    raw_path = Path("data/sample/raw/krx_ohlcv_sample.csv")
    config_path = _write_collection_config(
        tmp_path,
        raw_path=raw_path,
        processed_name="collected_ohlcv.parquet",
        processed_format="parquet",
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    processed_path = tmp_path / "processed" / "collected_ohlcv.parquet"
    processed = pd.read_parquet(processed_path)
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    assert len(processed) == manifest["processed_rows"]
    assert manifest["processed_file"]["format"] == "parquet"
    assert manifest["processed_file"]["path"].endswith(".parquet")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda config: config["source"].update({"type": "krx_csv", "input_paths": []}), "source.input_paths"),
        (lambda config: config["source"].update({"type": "unsupported"}), "Unsupported data source type"),
        (lambda config: config["output"].update({"processed_filename": "bad.xlsx"}), "processed output"),
        (lambda config: config["source"].update({"type": "pykrx", "symbols": [], "start": "2024-01-01", "end": "2024-01-02"}), "source.symbols"),
        (lambda config: config["source"].update({"retry": {"attempts": 0}}), "retry.attempts"),
        (lambda config: config["source"].update({"rate_limit": {"sleep_seconds": -1}}), "rate_limit.sleep_seconds"),
        (lambda config: config.update({"zero_row_policy": "bad"}), "zero_row_policy"),
        (
            lambda config: config["output"].update({"staging_filename": "same.csv", "processed_filename": "same.csv", "processed_dir": config["output"]["staging_dir"]}),
            "Output paths must not collide",
        ),
        (
            lambda config: config["output"].update({"processed_filename": "manifest.json"}),
            "Output paths must not collide",
        ),
    ],
)
def test_collection_config_validation_errors(tmp_path, mutate, message):
    from research.data_collection import load_collection_config

    raw_path = Path("data/sample/raw/krx_ohlcv_sample.csv")
    config_path = _write_collection_config(tmp_path, raw_path=raw_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    mutate(config)
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_collection_config(config_path)


def test_remote_all_empty_or_failed_writes_empty_outputs_and_manifest(tmp_path, monkeypatch):
    import research.data_collection as data_collection

    columns = [
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
    ]

    def fake_collect_pykrx_ohlcv(*, symbols, start, end, market="KRX"):
        symbol = list(symbols)[0]
        if symbol == "000001":
            return pd.DataFrame(columns=columns)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(data_collection, "collect_pykrx_ohlcv", fake_collect_pykrx_ohlcv)
    config = {
        "source": {
            "type": "pykrx",
            "symbols": ["000001", "000002"],
            "start": "2024-01-01",
            "end": "2024-01-02",
            "market": "KOSPI",
            "retry": {"attempts": 1, "backoff_seconds": 0},
            "rate_limit": {"sleep_seconds": 0},
        },
        "output": {
            "raw_dir": str(tmp_path / "raw"),
            "staging_dir": str(tmp_path / "staging"),
            "processed_dir": str(tmp_path / "processed"),
            "processed_filename": "remote_empty.csv",
            "manifest_filename": "manifest.json",
        },
        "filters": {"markets": ["KOSPI"]},
    }
    config_path = tmp_path / "remote_empty.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    manifest = data_collection.collect_data(config_path=config_path)

    processed_path = tmp_path / "processed" / "remote_empty.csv"
    processed = pd.read_csv(processed_path, dtype={"symbol": str})
    assert processed.empty
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
    assert manifest["raw_rows"] == 0
    assert manifest["processed_rows"] == 0
    assert manifest["zero_row_policy"] == "write_empty"
    assert manifest["collection_results"]["empty_symbols"] == ["000001"]
    assert manifest["collection_results"]["failed_symbols"] == [{"symbol": "000002", "error": "provider unavailable", "attempts": 1}]
    assert Path(manifest["processed_file"]["path"]).exists()
    assert Path(manifest["manifest_path"]).exists()


def test_remote_zero_row_error_policy_rejects_empty_collection(tmp_path, monkeypatch):
    import research.data_collection as data_collection

    def fake_collect_pykrx_ohlcv(*, symbols, start, end, market="KRX"):
        return pd.DataFrame()

    monkeypatch.setattr(data_collection, "collect_pykrx_ohlcv", fake_collect_pykrx_ohlcv)
    config = {
        "zero_row_policy": "error",
        "source": {
            "type": "pykrx",
            "symbols": ["000001"],
            "start": "2024-01-01",
            "end": "2024-01-02",
            "market": "KOSPI",
        },
        "output": {
            "raw_dir": str(tmp_path / "raw"),
            "staging_dir": str(tmp_path / "staging"),
            "processed_dir": str(tmp_path / "processed"),
            "processed_filename": "remote_empty.csv",
            "manifest_filename": "manifest.json",
        },
    }
    config_path = tmp_path / "remote_empty_error.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="zero rows"):
        data_collection.collect_data(config_path=config_path)


def test_remote_manifest_records_empty_failed_symbols_and_retry_config(tmp_path, monkeypatch):
    import research.data_collection as data_collection

    columns = [
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
    ]
    attempts: dict[str, int] = {}

    def fake_collect_pykrx_ohlcv(*, symbols, start, end, market="KRX"):
        symbol = list(symbols)[0]
        attempts[symbol] = attempts.get(symbol, 0) + 1
        if symbol == "000002":
            return pd.DataFrame(columns=columns)
        if symbol == "000003":
            raise RuntimeError("temporary failure")
        return pd.DataFrame(
            [
                {
                    "date": "2024-01-02",
                    "symbol": symbol,
                    "open": 1000,
                    "high": 1100,
                    "low": 900,
                    "close": 1050,
                    "adjusted_close": 1050,
                    "volume": 100,
                    "traded_value": 105000,
                    "market": market,
                    "listing_status": "listed",
                }
            ]
        )

    monkeypatch.setattr(data_collection, "collect_pykrx_ohlcv", fake_collect_pykrx_ohlcv)
    config = {
        "source": {
            "type": "pykrx",
            "symbols": ["000001", "000002", "000003"],
            "start": "2024-01-01",
            "end": "2024-01-02",
            "market": "KOSPI",
            "retry": {"attempts": 2, "backoff_seconds": 0},
            "rate_limit": {"sleep_seconds": 0},
        },
        "output": {
            "raw_dir": str(tmp_path / "raw"),
            "staging_dir": str(tmp_path / "staging"),
            "processed_dir": str(tmp_path / "processed"),
            "processed_filename": "remote.csv",
            "manifest_filename": "manifest.json",
        },
        "filters": {"markets": ["KOSPI"]},
    }
    config_path = tmp_path / "remote.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    manifest = data_collection.collect_data(config_path=config_path)

    assert manifest["processed_rows"] == 1
    assert manifest["collection_results"]["requested_symbols"] == ["000001", "000002", "000003"]
    assert manifest["collection_results"]["successful_symbols"] == ["000001"]
    assert manifest["collection_results"]["empty_symbols"] == ["000002"]
    assert manifest["collection_results"]["failed_symbols"] == [{"symbol": "000003", "error": "temporary failure", "attempts": 2}]
    assert manifest["collection_results"]["retry"] == {"attempts": 2, "backoff_seconds": 0.0}
    assert manifest["collection_results"]["rate_limit"] == {"sleep_seconds": 0.0}
    assert attempts["000003"] == 2
    assert manifest["source"]["provider_name"] == "pykrx"
    assert manifest["source"]["provider_mode"] == "optional_remote_convenience"
    assert manifest["source"]["adjusted_close_policy"]


def test_fdr_manifest_records_estimated_traded_value_and_close_policy(tmp_path, monkeypatch):
    import research.data_collection as data_collection

    def fake_collect_fdr_ohlcv(*, symbols, start, end, market="KRX"):
        return pd.DataFrame(
            [
                {
                    "date": "2024-01-02",
                    "symbol": "000001",
                    "open": 1000,
                    "high": 1100,
                    "low": 900,
                    "close": 1050,
                    "adjusted_close": 1050,
                    "volume": 100,
                    "traded_value": 105000,
                    "market": market,
                    "listing_status": "listed",
                }
            ]
        )

    monkeypatch.setattr(data_collection, "collect_fdr_ohlcv", fake_collect_fdr_ohlcv)
    config = {
        "source": {
            "type": "fdr",
            "symbols": ["000001"],
            "start": "2024-01-01",
            "end": "2024-01-02",
            "market": "KOSPI",
        },
        "output": {
            "raw_dir": str(tmp_path / "raw"),
            "staging_dir": str(tmp_path / "staging"),
            "processed_dir": str(tmp_path / "processed"),
            "processed_filename": "fdr.csv",
            "manifest_filename": "manifest.json",
        },
        "filters": {"markets": ["KOSPI"]},
    }
    config_path = tmp_path / "fdr.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    manifest = data_collection.collect_data(config_path=config_path)

    assert manifest["source"]["provider_name"] == "FinanceDataReader"
    assert manifest["source"]["provider_mode"] == "optional_remote_convenience"
    assert manifest["source"]["traded_value_policy"] == "estimated_close_times_volume"
    assert "estimates traded_value" in manifest["source"]["warnings"][0]
    assert manifest["source"]["adjusted_close_policy"] == "raw_close_copied_to_adjusted_close"


def test_optional_remote_sources_are_lazy_and_research_only(monkeypatch):
    real_import = __import__

    def blocked_optional_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"FinanceDataReader", "pykrx"}:
            raise ImportError(f"blocked optional import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", blocked_optional_import)
    from research.data_sources.fdr import collect_fdr_ohlcv
    from research.data_sources.pykrx import collect_pykrx_ohlcv

    with pytest.raises(ImportError, match="FinanceDataReader"):
        collect_fdr_ohlcv(symbols=["005930"], start="2024-01-01", end="2024-01-02")
    with pytest.raises(ImportError, match="pykrx"):
        collect_pykrx_ohlcv(symbols=["005930"], start="2024-01-01", end="2024-01-02")
