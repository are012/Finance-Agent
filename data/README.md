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

The sample file under `data/sample/synthetic_ohlcv.csv` is synthetic and exists only to make tests, examples, ledgers, validation, critic checks, and report generation reproducible.
