# KRX OpenAPI Data Source Spec

Status: implementation contract

## Scope

Add a research-only `krx_openapi` source to the existing collection pipeline. The source collects official KRX daily stock trading information for:

- KOSPI daily trading information: `stk_bydd_trd`
- KOSDAQ daily trading information: `ksq_bydd_trd`

The source is for offline research data preparation only. It must not implement live trading, broker integration, account login, order placement, or real-money execution.

## Authentication

- Read the KRX OpenAPI key only from the environment variable named by `source.auth_key_env`.
- Default `source.auth_key_env` is `KRX_AUTH_KEY`.
- Reject configs that include inline key fields such as `auth_key` or `api_key`.
- Do not print, log, persist, or include the key value in manifests, generated configs, or reports.
- It is acceptable to record the environment variable name for auditability.

## Request Shape

Each request is date and market based:

```yaml
source:
  type: krx_openapi
  start: "2024-01-02"
  end: "2024-12-30"
  markets: ["KOSPI", "KOSDAQ"]
  auth_key_env: KRX_AUTH_KEY
  endpoint_base_url: https://data-dbg.krx.co.kr/svc/apis/sto
  response_format: json
  market_endpoints:
    KOSPI: stk_bydd_trd
    KOSDAQ: ksq_bydd_trd
```

The source must support retry and rate-limit config through the existing collection config keys:

```yaml
source:
  retry:
    attempts: 2
    backoff_seconds: 1
  rate_limit:
    sleep_seconds: 0.2
```

The source may use a local response cache for repeatable refresh jobs:

```yaml
source:
  cache:
    enabled: true
    dir: data/raw/krx_openapi_cache
    refresh: false
```

Cache files must contain only provider response JSON, never request headers or the API key.

## Canonical Output

Map KRX response rows to the existing canonical OHLCV schema:

| KRX field | Canonical field |
| --- | --- |
| `BAS_DD` | `date` |
| `ISU_CD` | `symbol` |
| `TDD_OPNPRC` | `open` |
| `TDD_HGPRC` | `high` |
| `TDD_LWPRC` | `low` |
| `TDD_CLSPRC` | `close` |
| `TDD_CLSPRC` | `adjusted_close` |
| `ACC_TRDVOL` | `volume` |
| `ACC_TRDVAL` | `traded_value` |
| `MKT_NM` | `market` |
| `ISU_NM` | `name` |
| `SECT_TP_NM` | `security_type` |

Set `listing_status` to `listed` unless local `status_files` are configured and merged by the existing pipeline.

Do not use KRX market cap, listed shares, fundamentals, disclosures, investor-flow data, or order-book data as research features.

The default field map can be overridden by `source.field_map` when KRX field names change:

```yaml
source:
  field_map:
    date: BAS_DD
    symbol: ISU_CD
    name: ISU_NM
    market: MKT_NM
    security_type: SECT_TP_NM
    open: TDD_OPNPRC
    high: TDD_HGPRC
    low: TDD_LWPRC
    close: TDD_CLSPRC
    volume: ACC_TRDVOL
    traded_value: ACC_TRDVAL
```

## Manifest and Data Quality

The existing manifest and data-quality outputs must remain active for `krx_openapi`. The manifest should include:

- provider name and mode,
- requested dates and markets,
- successful, empty, failed, and skipped request counts or rows,
- retry and rate-limit settings,
- endpoint, field-map, and cache settings,
- processed file metadata,
- data-quality report paths,
- generated research config path when requested.

The manifest must not include the API key value.

## Tests

Tests must be offline and use mocked KRX responses. Required coverage:

- canonical row mapping from KRX `OutBlock_1`,
- environment-variable-only key handling,
- inline key rejection,
- no key value leakage into manifest output,
- configurable endpoint and field mapping,
- cache reuse without a second remote call,
- existing `krx_csv`, `pykrx`, and `fdr` behavior remains unchanged,
- sample local collection continues to work,
- README documents the safe KRX OpenAPI workflow.
