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

The default config reads the small sample raw file under `data/sample/raw/`, writes raw/staging/processed outputs under ignored `data/raw/`, `data/staging/`, and `data/processed/` directories, and creates a JSON manifest with input/output hashes, row counts, schema decisions, filters, source metadata, listing-status counts, data-quality report paths, status-merge audit paths when status files change rows, and the generated research config path when configured.

Optional `status_files` can merge separate local CSV or Parquet files for suspended, delisted, and admin-issue symbols into `listing_status`. Status files require `symbol` and may include `date` or `start_date`/`end_date`; dated rows update only matching `date`/`symbol` observations, ranged rows update observations inside the effective range, and symbol-only rows update every observation for that symbol. Status files are copied into `raw_dir` and recorded in the manifest with hashes.

Set `output.processed_filename` to `.csv` or `.parquet`, or set `output.processed_format`, to choose the processed output format. The manifest records the processed format and hash.

The preferred reproducible source is `krx_csv`, because it works fully offline. Optional `pykrx` and `fdr` source modules are available for research convenience through lazy imports, but tests and CI do not require internet access or those packages.

For optional `pykrx` and `fdr` convenience sources, configure `source.retry.attempts`, `source.retry.backoff_seconds`, and `source.rate_limit.sleep_seconds`. The manifest records requested, successful, empty, and failed symbols so partial remote collection does not hide missing data. Remote sources default to `zero_row_policy: write_empty`, which is useful for audit runs and fixtures because it writes canonical empty OHLCV outputs and a manifest when every requested symbol is empty or failed. Use `zero_row_policy: error` for production refresh jobs so a zero-row collection fails fast. The manifest also records provider metadata, adjusted-close policy notes, and FDR traded-value estimation warnings.

Each collection writes JSON and CSV data-quality reports with symbol-level first/last dates, row counts by symbol, zero-volume and zero-traded-value counts, market/listing-status counts by symbol, adjusted-close divergence, daily universe size, date coverage, missing required columns, OHLC anomaly counts, and duplicate-removal summary. Set `output.research_config_filename` to emit a generated research config whose `data.path` points at the processed output. If the processed file is too short to create non-empty train, validation, and final-holdout splits, the generated config records split guidance instead of silently producing a runnable research setup.

## Real-Data Dry Run

1. To prepare local KRX CSV files, keep only chart/local metadata columns: `date`, `symbol`, `open`, `high`, `low`, `close`, optional `adjusted_close`, `volume`, `traded_value`, `market`, optional `listing_status`, optional `name`, and optional `security_type`.
2. Configure `configs/data_collection.yaml` with your local `source.input_paths`. Add local `status_files` for suspended, delisted, or admin symbols when available; do not add fundamentals, news, disclosures, analyst, macro, investor-flow, broker, account, or live-trading data.
3. Run collection:

```bash
.venv/bin/python -m app.collect_data --config configs/data_collection.yaml
```

4. Inspect generated artifacts before research:
   - `data/processed/manifest.json`
   - `data/processed/data_quality_report.json`
   - `data/processed/data_quality_report.csv`
   - `data/processed/status_merge_audit.json` and `.csv` when status files changed `listing_status`
   - `data/processed/generated_research.yaml` when `output.research_config_filename` is configured
5. If `generated_research.yaml` reports that the processed sample is too short, update its `splits` for your real dataset before running full research. Keep `research.allow_final_holdout_during_research: false`; final_holdout is reserved for `app.final_report`.
6. Run research and reporting:

```bash
.venv/bin/python -m app.run_research --config data/processed/generated_research.yaml --output-dir outputs
.venv/bin/python -m app.final_report --config data/processed/generated_research.yaml --ledger outputs/ledger/experiments.jsonl --output-dir outputs/reports
```

The processed CSV can be used by setting `configs/example.yaml`:

```yaml
data:
  path: data/processed/collected_ohlcv.csv
  format: csv
  date_column: date
  symbol_column: symbol
```

## KRX Open API Collection

Use `source.type: krx_openapi` when collecting official KRX Open API daily stock data. This source is research-only and currently supports the KOSPI and KOSDAQ daily trading-information APIs. Tests use mocked responses, so CI remains offline and does not require a KRX account.

Keep the API key out of all files. Export it in your shell and point the config at the environment variable name:

```bash
export KRX_AUTH_KEY='replace-with-your-issued-key'
```

Example collection config:

```yaml
zero_row_policy: error

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
  cache:
    enabled: true
    dir: data/raw/krx_openapi_cache
    refresh: false
  retry:
    attempts: 2
    backoff_seconds: 1
  rate_limit:
    sleep_seconds: 0.2

output:
  raw_dir: data/raw
  staging_dir: data/staging
  processed_dir: data/processed
  staging_filename: staging_ohlcv.csv
  processed_filename: collected_ohlcv.csv
  manifest_filename: manifest.json
  research_config_filename: generated_research.yaml

filters:
  markets: ["KOSPI", "KOSDAQ"]
  exclude_listing_statuses: []
```

Run collection with the same CLI:

```bash
.venv/bin/python -m app.collect_data --config configs/data_collection_krx_openapi.yaml
```

The manifest records the provider, requested dates and markets, retry/rate-limit settings, empty or failed requests, and data-quality artifacts. It stores only `auth_key_env`, never the API key value. For production refresh jobs, keep `zero_row_policy: error` so missing approval, expired keys, or empty remote responses fail fast instead of producing a misleading empty dataset.

`market_endpoints` and `field_map` are configurable so the collector can adapt if KRX changes endpoint IDs or response field names. Keep mapped fields inside the allowed OHLCV/local-metadata schema. The optional cache stores provider response JSON under `source.cache.dir`; it does not store request headers or the API key. Set `source.cache.refresh: true` only when you intentionally want to replace cached responses with fresh KRX responses.

When `output.research_config_filename` is set, the generated config keeps `research.allow_final_holdout_during_research: false`. Inspect `data/processed/manifest.json`, `data/processed/data_quality_report.json`, and generated split guidance before running research.

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

A safe chart-only formula hypothesis can be run the same way:

```bash
.venv/bin/python -m app.run_one_hypothesis \
  --config configs/example.yaml \
  --hypothesis configs/hypotheses/formula_rank_sample.yaml \
  --output-dir outputs
```

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

Formula strategy families are also supported for controlled research:

- `formula_rank`: ranks eligible symbols by a safe chart-only `formula.score`.
- `formula_rule`: enters eligible symbols from a boolean `formula.entry`.

Formula hypotheses must declare every referenced feature in `features`. The engine validates expressions before backtesting and rejects forbidden terms, undeclared or unavailable features, unsupported operators, excessive depth, excessive features, excessive constants, and duplicate formulas loaded in the same research config.

Allowed DSL syntax is intentionally small:

- arithmetic: `+`, `-`, `*`, `/`
- comparisons: `>`, `>=`, `<`, `<=`, `==`, `!=`
- boolean logic: `and`, `or`, `not`
- functions: `rank(x)`, `zscore(x, window)`, `clip(x, low, high)`, `abs(x)`

Example:

```yaml
id: formula_rank_sample
name: Simple formula rank momentum and liquidity
strategy_family: formula_rank
features:
  - momentum_5
  - volume_ratio_5
  - traded_value_ma_5
formula:
  score: "rank(momentum_5) + rank(volume_ratio_5)"
  entry: "momentum_5 > 0 and traded_value_ma_5 >= 100000"
  exit: "momentum_5 < 0"
parameters:
  lookback_bars: 5
  holding_bars: 3
position_sizing:
  method: equal_weight
  max_positions: 3
  max_position_pct: 0.34
```

The formula DSL never evaluates arbitrary Python. It does not allow imports, attribute access, file or network access, broker/account data, final-holdout access, or non-chart data such as fundamentals, news, disclosures, macro data, investor-flow data, or order-book data. Formula search increases overfitting risk; keep formulas simple, require walk-forward/cost/parameter checks, and treat high-scoring formulas as research candidates only.

## Final Holdout Rule

Train and validation data can be used during research. Final holdout data is reserved for the selected candidate and evaluated only by `app.final_report`. After the lock file exists, the report command reuses the locked result. This avoids iterating on strategy design after seeing final-holdout performance.

## Known Limitations

- The included data is synthetic and only proves offline reproducibility.
- Deflated Sharpe, White Reality Check, and bootstrap inference are labeled placeholders.
- Risk rules such as stop loss and trailing ATR are represented in config/spec but not used as live order logic.
- A PASS result means paper-trading candidate only, not live-trading readiness.
