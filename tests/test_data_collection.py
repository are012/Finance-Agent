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
    filters: dict | None = None,
    status_files: dict | None = None,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
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
        "filters": filters if filters is not None else {"markets": ["KOSPI"], "exclude_listing_statuses": []},
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
    status_entry = manifest["status_files"][0]
    assert status_entry["status"] == "admin"
    assert status_entry["path"] == str(admin_path)
    assert status_entry["rows"] == 1
    assert status_entry["matched_rows"] == 2
    assert status_entry["changed_rows"] == 2
    assert Path(status_entry["raw_copy_path"]).exists()
    assert Path(status_entry["raw_copy_path"]).name.startswith("status_admin_000_")


@pytest.mark.parametrize(
    ("header", "row", "message"),
    [
        ("symbol,date", "000001,not-a-date", "date"),
        ("symbol,start_date,end_date", "000001,not-a-date,2024-01-03", "start_date"),
        ("symbol,start_date,end_date", "000001,2024-01-01,not-a-date", "end_date"),
        ("symbol,start_date,end_date", "000001,2024-01-03,2024-01-01", "start_date must be <= end_date"),
    ],
)
def test_collect_data_rejects_invalid_status_file_dates(tmp_path, header, row, message):
    raw_path = tmp_path / "raw.csv"
    raw_path.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,volume,traded_value,market",
                "2024-01-02,000001,1000,1100,900,1050,100,105000,KOSPI",
            ]
        ),
        encoding="utf-8",
    )
    admin_path = tmp_path / "admin_bad.csv"
    admin_path.write_text(f"{header}\n{row}\n", encoding="utf-8")
    config_path = _write_collection_config(tmp_path, raw_path=raw_path, status_files={"admin": [str(admin_path)]})

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "Invalid status file" in result.stderr
    assert message in result.stderr


def test_collect_data_uses_unique_raw_copy_paths_for_same_basename_files(tmp_path):
    source_a = tmp_path / "source_a"
    source_b = tmp_path / "source_b"
    source_a.mkdir()
    source_b.mkdir()
    raw_a = source_a / "prices.csv"
    raw_b = source_b / "prices.csv"
    raw_a.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,volume,traded_value,market",
                "2024-01-02,000001,1000,1100,900,1050,100,105000,KOSPI",
            ]
        ),
        encoding="utf-8",
    )
    raw_b.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,volume,traded_value,market",
                "2024-01-02,000002,2000,2100,1900,2050,100,205000,KOSPI",
            ]
        ),
        encoding="utf-8",
    )
    status_a = source_a / "status.csv"
    status_b = source_b / "status.csv"
    status_a.write_text("symbol\n000001\n", encoding="utf-8")
    status_b.write_text("symbol\n000002\n", encoding="utf-8")
    config_path = _write_collection_config(
        tmp_path,
        raw_path=raw_a,
        source_extra={"input_paths": [str(raw_a), str(raw_b)]},
        status_files={"admin": [str(status_a), str(status_b)]},
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    raw_copies = [entry["raw_copy_path"] for entry in manifest["input_files"]]
    status_copies = [entry["raw_copy_path"] for entry in manifest["status_files"]]
    assert len(set(raw_copies)) == 2
    assert len(set(status_copies)) == 2
    assert all(Path(path).exists() for path in [*raw_copies, *status_copies])
    assert Path(raw_copies[0]).name.startswith("source_000_")
    assert Path(raw_copies[1]).name.startswith("source_001_")
    assert Path(status_copies[0]).name.startswith("status_admin_000_")
    assert Path(status_copies[1]).name.startswith("status_admin_001_")


def test_collect_data_records_and_applies_status_precedence(tmp_path):
    raw_path = tmp_path / "raw.csv"
    raw_path.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,volume,traded_value,market",
                "2024-01-02,000001,1000,1100,900,1050,100,105000,KOSPI",
            ]
        ),
        encoding="utf-8",
    )
    admin_path = tmp_path / "admin.csv"
    delisted_path = tmp_path / "delisted.csv"
    admin_path.write_text("symbol\n000001\n", encoding="utf-8")
    delisted_path.write_text("symbol\n000001\n", encoding="utf-8")

    default_config = _write_collection_config(
        tmp_path / "default",
        raw_path=raw_path,
        status_files={"admin": [str(admin_path)], "delisted": [str(delisted_path)]},
    )
    custom_config = _write_collection_config(
        tmp_path / "custom",
        raw_path=raw_path,
        status_files={
            "precedence": ["delisted", "admin"],
            "admin": [str(admin_path)],
            "delisted": [str(delisted_path)],
        },
    )

    default_result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(default_config)],
        check=False,
        text=True,
        capture_output=True,
    )
    custom_result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(custom_config)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert default_result.returncode == 0, default_result.stderr
    assert custom_result.returncode == 0, custom_result.stderr
    default_processed = pd.read_csv(tmp_path / "default" / "processed" / "collected_ohlcv.csv", dtype={"symbol": str})
    custom_processed = pd.read_csv(tmp_path / "custom" / "processed" / "collected_ohlcv.csv", dtype={"symbol": str})
    default_manifest = json.loads((tmp_path / "default" / "processed" / "manifest.json").read_text(encoding="utf-8"))
    custom_manifest = json.loads((tmp_path / "custom" / "processed" / "manifest.json").read_text(encoding="utf-8"))
    assert default_processed["listing_status"].iloc[0] == "delisted"
    assert default_manifest["status_precedence"] == ["admin", "suspended", "delisted"]
    assert custom_processed["listing_status"].iloc[0] == "admin"
    assert custom_manifest["status_precedence"] == ["delisted", "admin"]


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
        (lambda config: config.update({"status_files": {"precedence": ["admin", "bad"]}}), "status_files.precedence"),
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


def test_collect_data_writes_data_quality_reports(tmp_path):
    raw_path = Path("data/sample/raw/krx_ohlcv_sample.csv")
    config_path = _write_collection_config(tmp_path, raw_path=raw_path)

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    report = manifest["data_quality_report"]
    json_path = Path(report["json"]["path"])
    csv_path = Path(report["csv"]["path"])
    assert json_path.exists()
    assert csv_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["row_counts_by_symbol"]["005930"] == 2
    assert payload["date_coverage"]["start"] == "2024-01-02"
    assert payload["date_coverage"]["end"] == "2024-01-03"
    assert payload["missing_required_columns"] == []
    assert payload["ohlc_anomaly_counts"] == {
        "non_positive_price_rows": 0,
        "high_below_low_rows": 0,
        "high_below_open_rows": 0,
        "high_below_close_rows": 0,
        "low_above_open_rows": 0,
        "low_above_close_rows": 0,
        "negative_volume_or_traded_value_rows": 0,
    }
    assert payload["listing_status_counts"]["admin"] == 1
    assert payload["market_counts"] == {"KOSPI": 5}
    assert payload["duplicate_removal_summary"]["removed_rows"] == 1
    quality_rows = pd.read_csv(csv_path)
    assert {"section", "key", "value"}.issubset(quality_rows.columns)
    assert report["json"]["sha256"]
    assert report["csv"]["sha256"]


def test_collect_data_writes_expanded_symbol_level_data_quality_report(tmp_path):
    raw_path = tmp_path / "raw_quality.csv"
    raw_path.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,adjusted_close,volume,traded_value,market,listing_status",
                "2024-01-01,000001,1000,1100,900,1050,1040,0,0,KOSPI,listed",
                "2024-01-02,000001,1050,1150,1000,1100,1100,10,11000,KOSPI,listed",
                "2024-01-01,000002,2000,2100,1900,2050,2050,5,0,KOSDAQ,admin",
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_collection_config(
        tmp_path,
        raw_path=raw_path,
        filters={"markets": ["KOSPI", "KOSDAQ"], "exclude_listing_statuses": []},
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    payload = json.loads(Path(manifest["data_quality_report"]["json"]["path"]).read_text(encoding="utf-8"))
    assert payload["date_coverage_summary"] == {
        "start": "2024-01-01",
        "end": "2024-01-02",
        "unique_dates": 2,
        "row_count": 3,
    }
    assert payload["symbol_date_coverage"]["000001"] == {
        "first_date": "2024-01-01",
        "last_date": "2024-01-02",
        "row_count": 2,
    }
    assert payload["zero_volume_rows_by_symbol"] == {"000001": 1, "000002": 0}
    assert payload["zero_traded_value_rows_by_symbol"] == {"000001": 1, "000002": 1}
    assert payload["market_counts_by_symbol"] == {"000001": {"KOSPI": 2}, "000002": {"KOSDAQ": 1}}
    assert payload["listing_status_counts_by_symbol"] == {"000001": {"listed": 2}, "000002": {"admin": 1}}
    assert payload["adjusted_close_divergence_summary"]["total_rows"] == 3
    assert payload["adjusted_close_divergence_summary"]["divergent_rows"] == 1
    assert payload["adjusted_close_divergence_summary"]["divergent_symbols"] == 1
    assert payload["adjusted_close_divergence_summary"]["rows_by_symbol"] == {"000001": 1, "000002": 0}
    assert payload["daily_universe_size_summary"]["by_date"] == {"2024-01-01": 2, "2024-01-02": 1}
    assert payload["daily_universe_size_summary"]["min"] == 1
    assert payload["daily_universe_size_summary"]["max"] == 2
    quality_rows = pd.read_csv(manifest["data_quality_report"]["csv"]["path"])
    assert "symbol_date_coverage.000001.first_date" in set(quality_rows["key"])
    assert "adjusted_close_divergence_summary.rows_by_symbol.000001" in set(quality_rows["key"])


def test_collect_data_writes_status_merge_audit_artifacts_when_status_changes(tmp_path):
    raw_path = tmp_path / "raw.csv"
    raw_path.write_text(
        "\n".join(
            [
                "date,symbol,open,high,low,close,volume,traded_value,market",
                "2024-01-01,000001,1000,1100,900,1050,100,105000,KOSPI",
                "2024-01-02,000001,1000,1100,900,1050,100,105000,KOSPI",
                "2024-01-03,000001,1000,1100,900,1050,100,105000,KOSPI",
                "2024-01-02,000002,2000,2100,1900,2050,100,205000,KOSPI",
            ]
        ),
        encoding="utf-8",
    )
    admin_path = tmp_path / "admin.csv"
    suspended_path = tmp_path / "suspended.csv"
    delisted_path = tmp_path / "delisted.csv"
    admin_path.write_text("symbol,date\n000001,2024-01-02\n", encoding="utf-8")
    suspended_path.write_text("symbol,start_date,end_date\n000001,2024-01-03,2024-01-03\n", encoding="utf-8")
    delisted_path.write_text("symbol\n000002\n", encoding="utf-8")
    config_path = _write_collection_config(
        tmp_path,
        raw_path=raw_path,
        output_extra={"research_config_filename": "generated_research.yaml"},
        status_files={
            "admin": [str(admin_path)],
            "suspended": [str(suspended_path)],
            "delisted": [str(delisted_path)],
        },
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    for artifact in (
        manifest["data_quality_report"]["json"],
        manifest["data_quality_report"]["csv"],
        manifest["status_merge_audit"]["json"],
        manifest["status_merge_audit"]["csv"],
        manifest["research_config_file"],
    ):
        assert Path(artifact["path"]).exists()
        assert artifact["sha256"]
    audit_json = json.loads(Path(manifest["status_merge_audit"]["json"]["path"]).read_text(encoding="utf-8"))
    audit_csv = pd.read_csv(manifest["status_merge_audit"]["csv"]["path"], dtype={"symbol": str})
    assert audit_csv.columns.tolist() == [
        "status",
        "source_file",
        "raw_copy_path",
        "symbol",
        "date",
        "previous_listing_status",
        "new_listing_status",
        "match_type",
    ]
    assert audit_json == audit_csv.to_dict(orient="records")
    assert {(row["symbol"], row["date"], row["new_listing_status"], row["match_type"]) for row in audit_json} == {
        ("000001", "2024-01-02", "admin", "exact_date"),
        ("000001", "2024-01-03", "suspended", "date_range"),
        ("000002", "2024-01-02", "delisted", "symbol"),
    }
    assert {row["previous_listing_status"] for row in audit_json} == {"listed"}


def test_collect_data_optionally_writes_generated_research_config(tmp_path):
    raw_path = Path("data/sample/raw/krx_ohlcv_sample.csv")
    config_path = _write_collection_config(
        tmp_path,
        raw_path=raw_path,
        output_extra={"research_config_filename": "generated_research.yaml"},
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    research_config_path = Path(manifest["research_config_file"]["path"])
    generated = yaml.safe_load(research_config_path.read_text(encoding="utf-8"))
    assert generated["data"]["path"] == str(tmp_path / "processed" / "collected_ohlcv.csv")
    assert generated["data"]["format"] == "csv"
    assert generated["data"]["date_column"] == "date"
    assert generated["data"]["symbol_column"] == "symbol"
    assert manifest["research_config_file"]["sha256"]


def test_generated_research_config_documents_split_guidance_when_sample_is_too_short(tmp_path):
    raw_path = Path("data/sample/raw/krx_ohlcv_sample.csv")
    config_path = _write_collection_config(
        tmp_path,
        raw_path=raw_path,
        output_extra={"research_config_filename": "generated_research.yaml"},
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.collect_data", "--config", str(config_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text(encoding="utf-8"))
    generated_path = Path(manifest["research_config_file"]["path"])
    generated = yaml.safe_load(generated_path.read_text(encoding="utf-8"))
    guidance = generated["generated_data_guidance"]
    assert guidance["unique_dates"] == 2
    assert guidance["split_status"] == "insufficient_unique_dates_for_safe_splits"
    assert "update splits before running full research" in guidance["split_guidance"]
    assert generated["research"]["allow_final_holdout_during_research"] is False

    research_result = subprocess.run(
        [sys.executable, "-m", "app.run_research", "--config", str(generated_path), "--output-dir", str(tmp_path / "outputs")],
        check=False,
        text=True,
        capture_output=True,
    )

    assert research_result.returncode != 0
    assert "Train, validation, and final_holdout splits must all contain rows" in research_result.stderr


def test_readme_documents_real_data_dry_run_workflow():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## Real-Data Dry Run" in readme
    assert "prepare local KRX CSV" in readme
    assert "status_files" in readme
    assert "app.collect_data" in readme
    assert "data_quality_report.json" in readme
    assert "status_merge_audit" in readme
    assert "generated_research.yaml" in readme
    assert "app.run_research" in readme
    assert "app.final_report" in readme
    assert "final_holdout" in readme


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
