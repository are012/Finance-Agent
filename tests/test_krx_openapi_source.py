import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from research.data_sources.krx_openapi import collect_krx_openapi_ohlcv


class FakeResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload


def test_collect_krx_openapi_maps_daily_kospi_and_kosdaq_rows(monkeypatch):
    monkeypatch.setenv("KRX_TEST_AUTH_KEY", "test-secret-key")
    requests: list[dict] = []

    def fake_transport(url, *, params, headers, timeout):
        requests.append({"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout})
        assert headers == {"AUTH_KEY": "test-secret-key"}
        if url.endswith("stk_bydd_trd.json"):
            return FakeResponse(
                {
                    "OutBlock_1": [
                        {
                            "BAS_DD": "20240102",
                            "ISU_CD": "005930",
                            "ISU_NM": "삼성전자",
                            "MKT_NM": "KOSPI",
                            "SECT_TP_NM": "보통주",
                            "TDD_OPNPRC": "70,000",
                            "TDD_HGPRC": "71,000",
                            "TDD_LWPRC": "69,500",
                            "TDD_CLSPRC": "70,500",
                            "ACC_TRDVOL": "1,234",
                            "ACC_TRDVAL": "86,973,000",
                        }
                    ]
                }
            )
        if url.endswith("ksq_bydd_trd.json"):
            return FakeResponse(
                {
                    "OutBlock_1": [
                        {
                            "BAS_DD": "20240102",
                            "ISU_CD": "035720",
                            "ISU_NM": "카카오",
                            "MKT_NM": "KOSDAQ",
                            "SECT_TP_NM": "우량기업부",
                            "TDD_OPNPRC": "50,000",
                            "TDD_HGPRC": "51,000",
                            "TDD_LWPRC": "49,500",
                            "TDD_CLSPRC": "50,500",
                            "ACC_TRDVOL": "100",
                            "ACC_TRDVAL": "5,050,000",
                        }
                    ]
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    frame = collect_krx_openapi_ohlcv(
        start="2024-01-02",
        end="2024-01-02",
        markets=["KOSPI", "KOSDAQ"],
        auth_key_env="KRX_TEST_AUTH_KEY",
        transport=fake_transport,
        timeout_seconds=7,
    )

    assert requests == [
        {
            "url": "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd.json",
            "params": {"basDd": "20240102"},
            "headers": {"AUTH_KEY": "test-secret-key"},
            "timeout": 7,
        },
        {
            "url": "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd.json",
            "params": {"basDd": "20240102"},
            "headers": {"AUTH_KEY": "test-secret-key"},
            "timeout": 7,
        },
    ]
    assert frame.to_dict(orient="records") == [
        {
            "date": "2024-01-02",
            "symbol": "005930",
            "open": 70000.0,
            "high": 71000.0,
            "low": 69500.0,
            "close": 70500.0,
            "adjusted_close": 70500.0,
            "volume": 1234.0,
            "traded_value": 86973000.0,
            "market": "KOSPI",
            "listing_status": "listed",
            "name": "삼성전자",
            "security_type": "보통주",
        },
        {
            "date": "2024-01-02",
            "symbol": "035720",
            "open": 50000.0,
            "high": 51000.0,
            "low": 49500.0,
            "close": 50500.0,
            "adjusted_close": 50500.0,
            "volume": 100.0,
            "traded_value": 5050000.0,
            "market": "KOSDAQ",
            "listing_status": "listed",
            "name": "카카오",
            "security_type": "우량기업부",
        },
    ]
    assert frame.attrs["krx_openapi"]["requested_dates"] == ["2024-01-02"]
    assert frame.attrs["krx_openapi"]["successful_requests"] == [
        {"date": "2024-01-02", "market": "KOSPI", "rows": 1},
        {"date": "2024-01-02", "market": "KOSDAQ", "rows": 1},
    ]


def test_collect_krx_openapi_requires_configured_environment_key(monkeypatch):
    monkeypatch.delenv("KRX_MISSING_AUTH_KEY", raising=False)

    with pytest.raises(ValueError, match="KRX_MISSING_AUTH_KEY"):
        collect_krx_openapi_ohlcv(
            start="2024-01-02",
            end="2024-01-02",
            markets=["KOSPI"],
            auth_key_env="KRX_MISSING_AUTH_KEY",
            transport=lambda *args, **kwargs: FakeResponse({"OutBlock_1": []}),
        )


def test_collect_krx_openapi_uses_custom_endpoint_and_field_mapping(monkeypatch):
    monkeypatch.setenv("KRX_TEST_AUTH_KEY", "test-secret-key")
    requests: list[str] = []

    def fake_transport(url, *, params, headers, timeout):
        requests.append(url)
        return FakeResponse(
            {
                "OutBlock_1": [
                    {
                        "D": "20240102",
                        "CODE": "5930",
                        "NAME": "삼성전자",
                        "MARKET": "유가증권",
                        "TYPE": "보통주",
                        "OPEN": "70,000",
                        "HIGH": "71,000",
                        "LOW": "69,500",
                        "CLOSE": "70,500",
                        "VOL": "1,234",
                        "VALUE": "86,973,000",
                    }
                ]
            }
        )

    frame = collect_krx_openapi_ohlcv(
        start="2024-01-02",
        end="2024-01-02",
        markets=["KOSPI"],
        auth_key_env="KRX_TEST_AUTH_KEY",
        endpoint_base_url="https://example.invalid/apis",
        market_endpoints={"KOSPI": "custom_kospi_daily"},
        field_map={
            "date": "D",
            "symbol": "CODE",
            "name": "NAME",
            "market": "MARKET",
            "security_type": "TYPE",
            "open": "OPEN",
            "high": "HIGH",
            "low": "LOW",
            "close": "CLOSE",
            "volume": "VOL",
            "traded_value": "VALUE",
        },
        transport=fake_transport,
    )

    assert requests == ["https://example.invalid/apis/custom_kospi_daily.json"]
    assert frame.to_dict(orient="records") == [
        {
            "date": "2024-01-02",
            "symbol": "005930",
            "open": 70000.0,
            "high": 71000.0,
            "low": 69500.0,
            "close": 70500.0,
            "adjusted_close": 70500.0,
            "volume": 1234.0,
            "traded_value": 86973000.0,
            "market": "KOSPI",
            "listing_status": "listed",
            "name": "삼성전자",
            "security_type": "보통주",
        }
    ]
    assert frame.attrs["krx_openapi"]["market_endpoints"]["KOSPI"] == "custom_kospi_daily"
    assert frame.attrs["krx_openapi"]["field_map"]["symbol"] == "CODE"


def test_collect_krx_openapi_reuses_cache_without_second_transport_call(tmp_path, monkeypatch):
    monkeypatch.setenv("KRX_TEST_AUTH_KEY", "test-secret-key")
    cache_dir = tmp_path / "cache"
    calls = 0

    def fake_transport(url, *, params, headers, timeout):
        nonlocal calls
        calls += 1
        return FakeResponse(
            {
                "OutBlock_1": [
                    {
                        "BAS_DD": "20240102",
                        "ISU_CD": "005930",
                        "ISU_NM": "삼성전자",
                        "MKT_NM": "KOSPI",
                        "SECT_TP_NM": "보통주",
                        "TDD_OPNPRC": "70,000",
                        "TDD_HGPRC": "71,000",
                        "TDD_LWPRC": "69,500",
                        "TDD_CLSPRC": "70,500",
                        "ACC_TRDVOL": "1,234",
                        "ACC_TRDVAL": "86,973,000",
                    }
                ]
            }
        )

    first = collect_krx_openapi_ohlcv(
        start="2024-01-02",
        end="2024-01-02",
        markets=["KOSPI"],
        auth_key_env="KRX_TEST_AUTH_KEY",
        cache_dir=cache_dir,
        transport=fake_transport,
    )

    second = collect_krx_openapi_ohlcv(
        start="2024-01-02",
        end="2024-01-02",
        markets=["KOSPI"],
        auth_key_env="KRX_TEST_AUTH_KEY",
        cache_dir=cache_dir,
        transport=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert calls == 1
    assert first.to_dict(orient="records") == second.to_dict(orient="records")
    assert first.attrs["krx_openapi"]["cache_writes"] == [{"date": "2024-01-02", "market": "KOSPI"}]
    assert second.attrs["krx_openapi"]["cache_hits"] == [{"date": "2024-01-02", "market": "KOSPI"}]
    cache_files = list(cache_dir.glob("*.json"))
    assert len(cache_files) == 1
    assert "test-secret-key" not in cache_files[0].read_text(encoding="utf-8")


def test_collect_data_integrates_krx_openapi_without_manifest_secret_leak(tmp_path, monkeypatch):
    import research.data_collection as data_collection

    monkeypatch.setenv("KRX_TEST_AUTH_KEY", "do-not-store-this-secret")

    def fake_collect_krx_openapi_ohlcv(**kwargs):
        assert kwargs["start"] == "2024-01-02"
        assert kwargs["end"] == "2024-01-02"
        assert kwargs["markets"] == ["KOSPI", "KOSDAQ"]
        assert kwargs["auth_key_env"] == "KRX_TEST_AUTH_KEY"
        assert kwargs["market_endpoints"] == {"KOSPI": "custom_kospi_daily"}
        assert kwargs["field_map"] == {"symbol": "ISU_CD"}
        assert kwargs["cache_dir"] == str(tmp_path / "cache")
        assert kwargs["cache_refresh"] is True
        frame = pd.DataFrame(
            [
                {
                    "date": "2024-01-02",
                    "symbol": "005930",
                    "open": 70000,
                    "high": 71000,
                    "low": 69500,
                    "close": 70500,
                    "adjusted_close": 70500,
                    "volume": 1000,
                    "traded_value": 70500000,
                    "market": "KOSPI",
                    "listing_status": "listed",
                    "name": "삼성전자",
                    "security_type": "보통주",
                },
                {
                    "date": "2024-01-02",
                    "symbol": "035720",
                    "open": 50000,
                    "high": 51000,
                    "low": 49500,
                    "close": 50500,
                    "adjusted_close": 50500,
                    "volume": 100,
                    "traded_value": 5050000,
                    "market": "KOSDAQ",
                    "listing_status": "listed",
                    "name": "카카오",
                    "security_type": "우량기업부",
                },
            ]
        )
        frame.attrs["krx_openapi"] = {
            "requested_dates": ["2024-01-02"],
            "requested_markets": ["KOSPI", "KOSDAQ"],
            "successful_requests": [
                {"date": "2024-01-02", "market": "KOSPI", "rows": 1},
                {"date": "2024-01-02", "market": "KOSDAQ", "rows": 1},
            ],
            "empty_requests": [],
            "failed_requests": [],
            "skipped_rows": 0,
            "cache_hits": [{"date": "2024-01-02", "market": "KOSPI"}],
            "cache_writes": [{"date": "2024-01-02", "market": "KOSDAQ"}],
        }
        return frame

    monkeypatch.setattr(data_collection, "collect_krx_openapi_ohlcv", fake_collect_krx_openapi_ohlcv)
    config = {
        "source": {
            "type": "krx_openapi",
            "start": "2024-01-02",
            "end": "2024-01-02",
            "markets": ["KOSPI", "KOSDAQ"],
            "auth_key_env": "KRX_TEST_AUTH_KEY",
            "market_endpoints": {"KOSPI": "custom_kospi_daily"},
            "field_map": {"symbol": "ISU_CD"},
            "cache": {"enabled": True, "dir": str(tmp_path / "cache"), "refresh": True},
            "rate_limit": {"sleep_seconds": 0},
        },
        "output": {
            "raw_dir": str(tmp_path / "raw"),
            "staging_dir": str(tmp_path / "staging"),
            "processed_dir": str(tmp_path / "processed"),
            "processed_filename": "krx_openapi.csv",
            "manifest_filename": "manifest.json",
        },
        "filters": {"markets": ["KOSPI", "KOSDAQ"]},
        "metadata": {"dataset_id": "krx-openapi-fixture"},
    }
    config_path = tmp_path / "krx_openapi.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    manifest = data_collection.collect_data(config_path=config_path)

    processed = pd.read_csv(tmp_path / "processed" / "krx_openapi.csv", dtype={"symbol": str})
    assert processed["symbol"].tolist() == ["005930", "035720"]
    assert manifest["source"]["type"] == "krx_openapi"
    assert manifest["source"]["provider_name"] == "KRX Open API"
    assert manifest["source"]["provider_mode"] == "official_remote_research_data"
    assert manifest["source"]["auth_key_env"] == "KRX_TEST_AUTH_KEY"
    assert manifest["source"]["market_endpoints"] == {"KOSPI": "custom_kospi_daily"}
    assert manifest["source"]["field_map"] == {"symbol": "ISU_CD"}
    assert manifest["source"]["cache"] == {"enabled": True, "dir": str(tmp_path / "cache"), "refresh": True}
    assert manifest["collection_results"]["requested_dates"] == ["2024-01-02"]
    assert manifest["collection_results"]["requested_markets"] == ["KOSPI", "KOSDAQ"]
    assert manifest["collection_results"]["cache_hits"] == [{"date": "2024-01-02", "market": "KOSPI"}]
    assert manifest["collection_results"]["cache_writes"] == [{"date": "2024-01-02", "market": "KOSDAQ"}]
    assert manifest["collection_constraints"]["chart_allowed_only"] is True
    manifest_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    assert "do-not-store-this-secret" not in manifest_text
    assert "AUTH_KEY:" not in manifest_text
    assert "api_key" not in manifest_text.lower()


def test_collect_data_rejects_inline_krx_openapi_keys(tmp_path):
    from research.data_collection import load_collection_config

    config = {
        "source": {
            "type": "krx_openapi",
            "start": "2024-01-02",
            "end": "2024-01-02",
            "markets": ["KOSPI"],
            "auth_key": "must-not-be-stored",
        },
        "output": {
            "raw_dir": str(tmp_path / "raw"),
            "staging_dir": str(tmp_path / "staging"),
            "processed_dir": str(tmp_path / "processed"),
            "processed_filename": "krx_openapi.csv",
            "manifest_filename": "manifest.json",
        },
    }
    config_path = tmp_path / "bad_krx_openapi.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="auth_key_env"):
        load_collection_config(config_path)


def test_readme_documents_safe_krx_openapi_workflow():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## KRX Open API Collection" in readme
    assert "source.type: krx_openapi" in readme
    assert "KRX_AUTH_KEY" in readme
    krx_section = readme.partition("## KRX Open API Collection")[2].partition("## Setup")[0]
    assert "AUTH_KEY:" not in krx_section
    assert "auth_key:" not in krx_section
    assert "market_endpoints" in krx_section
    assert "field_map" in krx_section
    assert "cache:" in krx_section
    assert "source.cache.refresh: true" in krx_section
    assert "zero_row_policy: error" in readme
    assert "research.allow_final_holdout_during_research: false" in readme
