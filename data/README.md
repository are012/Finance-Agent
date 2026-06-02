# Data

This framework uses local chart-derived data only. Runtime commands must not fetch internet data.

Required CSV columns:

- `date`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `adjusted_close`
- `volume`
- `traded_value`
- `market`

Optional chart-data column:

- `listing_status`

Optional local metadata columns for filtering and traceability only:

- `name`
- `security_type`

Use `python -m app.collect_data --config configs/data_collection.yaml` to normalize local KRX CSV exports into the canonical schema. The default config ingests `data/sample/raw/krx_ohlcv_sample.csv` and writes generated raw, staging, processed, and manifest outputs under ignored `data/raw/`, `data/staging/`, and `data/processed/` directories.

Separate local status files may be supplied for `suspended`, `delisted`, and `admin` rows. Each status file must contain `symbol` and may contain `date` or `start_date`/`end_date`; no fundamentals, disclosures, news, investor-flow, macro, broker, or live-trading data is allowed.

The collector also writes ignored data-quality JSON/CSV reports. They summarize local OHLCV quality only and are not trading signals. When status files change `listing_status`, the collector also writes ignored `status_merge_audit.json` and `.csv` files with the affected symbol/date rows.

The sample file under `data/sample/synthetic_ohlcv.csv` is synthetic and exists only to make tests, examples, ledgers, validation, critic checks, and report generation reproducible. It contains multiple Korean-market-style symbols across train, validation, and final-holdout date ranges.
