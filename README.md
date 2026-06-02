# Chart-Only Korean Market Research Framework

This repository is an offline, reproducible research framework for Korean-market systematic trading ideas that use only OHLCV/chart-derived data.

It is research-only. It does not include live trading, broker integration, account login, order placement, or real-money execution.

## Data Scope

Allowed local input columns:

- `date`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `adjusted_close`, optional and filled from `close` when absent
- `volume`
- `traded_value`
- `market`
- `listing_status`, optional

The collection pipeline may also preserve `name` and `security_type` as local metadata for filtering and traceability. These are not chart-derived signal features.

Forbidden data includes fundamentals, financial statements, news, disclosures, macro data, analyst data, investor-flow data, future returns in signal generation, and any feature unavailable at the decision timestamp.

## Korean OHLCV Input

Provide a local CSV or Parquet file and point `configs/example.yaml` at it:

```yaml
data:
  path: data/sample/synthetic_ohlcv.csv
  format: csv
  date_column: date
  symbol_column: symbol
```

The loader validates required columns, rejects impossible OHLC rows, deduplicates duplicate `date`/`symbol` rows deterministically, and applies configured universe filters such as market, listing status, low price, and traded-value filters.

## Offline Data Collection

Use the collection CLI to normalize local KRX CSV exports into the canonical OHLCV schema:

```bash
.venv/bin/python -m app.collect_data --config configs/data_collection.yaml
```

The default config reads the small sample raw file under `data/sample/raw/`, writes raw/staging/processed outputs under ignored `data/raw/`, `data/staging/`, and `data/processed/` directories, and creates a JSON manifest with input/output hashes, row counts, schema decisions, filters, source metadata, listing-status counts, and data-quality report paths.

Optional `status_files` can merge separate local CSV or Parquet files for suspended, delisted, and admin-issue symbols into `listing_status`. Status files require `symbol` and may include `date` or `start_date`/`end_date`; dated rows update only matching `date`/`symbol` observations, ranged rows update observations inside the effective range, and symbol-only rows update every observation for that symbol. Status files are copied into `raw_dir` and recorded in the manifest with hashes.

Set `output.processed_filename` to `.csv` or `.parquet`, or set `output.processed_format`, to choose the processed output format. The manifest records the processed format and hash.

The preferred reproducible source is `krx_csv`, because it works fully offline. Optional `pykrx` and `fdr` source modules are available for research convenience through lazy imports, but tests and CI do not require internet access or those packages.

For optional `pykrx` and `fdr` convenience sources, configure `source.retry.attempts`, `source.retry.backoff_seconds`, and `source.rate_limit.sleep_seconds`. The manifest records requested, successful, empty, and failed symbols so partial remote collection does not hide missing data. Remote sources default to `zero_row_policy: write_empty`, which is useful for audit runs and fixtures because it writes canonical empty OHLCV outputs and a manifest when every requested symbol is empty or failed. Use `zero_row_policy: error` for production refresh jobs so a zero-row collection fails fast. The manifest also records provider metadata, adjusted-close policy notes, and FDR traded-value estimation warnings.

Each collection writes JSON and CSV data-quality reports with row counts by symbol, date coverage, missing required columns, OHLC anomaly counts, listing-status counts, market counts, and duplicate-removal summary. Set `output.research_config_filename` to emit a generated research config whose `data.path` points at the processed output.

The processed CSV can be used by setting `configs/example.yaml`:

```yaml
data:
  path: data/processed/collected_ohlcv.csv
  format: csv
  date_column: date
  symbol_column: symbol
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Verify

```bash
.venv/bin/python -m pytest -q
```

## Completion Audit

Run the local completion audit from a clean generated-output state:

```bash
rm -rf outputs/ledger outputs/artifacts outputs/reports
mkdir -p outputs/ledger outputs/artifacts outputs/reports
python -m pytest -q
python -m app.run_research --config configs/example.yaml --output-dir outputs
python -m app.run_one_hypothesis --config configs/example.yaml --hypothesis configs/hypotheses/momentum_20.yaml --output-dir outputs
python -m app.final_report --config configs/example.yaml --ledger outputs/ledger/experiments.jsonl --output-dir outputs/reports
python -m app.final_report --config configs/example.yaml --ledger outputs/ledger/experiments.jsonl --output-dir outputs/reports
```

The second final-report command must reuse the locked final-holdout result rather than evaluating the final holdout again.

## Run One YAML Hypothesis

```bash
.venv/bin/python -m app.run_one_hypothesis \
  --config configs/example.yaml \
  --hypothesis configs/hypotheses/momentum_20.yaml \
  --output-dir outputs
```

This validates the YAML hypothesis, runs train and validation backtests only, applies gates and critic checks, writes ledger rows, and saves artifacts.

## Run Research Loop

```bash
.venv/bin/python -m app.run_research --config configs/example.yaml --output-dir outputs
```

The research loop:

- loads local chart data,
- computes chart-derived features per symbol,
- splits data into train, validation, and final holdout,
- generates or loads one explicit hypothesis at a time,
- executes close-based signals at the next available open,
- applies commission, sell tax, slippage, liquidity caps, and partial-fill or rejection behavior,
- records walk-forward validation and base-relative parameter-sensitivity summaries,
- records listing-status availability and delisted/suspended counts for survivorship-bias review,
- logs every experiment, including failures,
- never evaluates the final holdout.

Ledger path:

```text
outputs/ledger/experiments.jsonl
```

## Generate Final Report

```bash
.venv/bin/python -m app.final_report \
  --config configs/example.yaml \
  --ledger outputs/ledger/experiments.jsonl \
  --output-dir outputs/reports
```

The final report selects the best validated candidate by risk-aware scoring and evaluates the final holdout exactly once. A `holdout_<key>.json` lock file is written in the report directory. Later report runs reuse the locked result and do not re-evaluate the holdout.

Report outputs:

- `outputs/reports/final_report.json`
- `outputs/reports/final_report.md`
- `outputs/reports/holdout_<key>.json`
- holdout equity, drawdown, order, and trade CSV artifacts

## Hypothesis Format

See `configs/hypotheses/`. Hypotheses must declare the strategy family, chart-only features, entry/exit rules, position sizing, cost assumptions, and falsification gates. Unsupported families, missing entry/exit rules, and forbidden non-chart features are rejected before execution. Invalid hypotheses loaded by the research loop are written to the ledger with a rejection reason.

Forbidden-data validation checks the full hypothesis spec fields that can affect research decisions, including feature lists, `entry_rule`, `parameters`, and `notes`.

Built-in strategy families include breakout, breakout with volume confirmation, moving-average trend, short-term reversal, volatility contraction breakout, gap continuation/reversal, RSI mean reversion, price-volume momentum, and traded-value momentum.

## Final Holdout Rule

Train and validation data can be used during research. Final holdout data is reserved for the selected candidate and evaluated only by `app.final_report`. After the lock file exists, the report command reuses the locked result. This avoids iterating on strategy design after seeing final-holdout performance.

## Known Limitations

- The included data is synthetic and only proves offline reproducibility.
- Deflated Sharpe, White Reality Check, and bootstrap inference are labeled placeholders.
- Risk rules such as stop loss and trailing ATR are represented in config/spec but not used as live order logic.
- A PASS result means paper-trading candidate only, not live-trading readiness.
