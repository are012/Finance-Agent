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

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Verify

```bash
.venv/bin/python -m pytest -q
```

## Run One YAML Hypothesis

```bash
.venv/bin/python -m app.run_one_hypothesis \
  --config configs/example.yaml \
  --hypothesis configs/sample_hypothesis.yaml \
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
- logs every experiment, including failures,
- never evaluates the final holdout.

Ledger path:

```text
outputs/ledger/experiments.jsonl
```

## Generate Final Report

```bash
.venv/bin/python -m app.final_report --config configs/example.yaml --output-dir outputs/reports
```

The final report selects the best validated candidate by risk-aware scoring and evaluates the final holdout exactly once. A `holdout_<key>.json` lock file is written in the report directory. Later report runs reuse the locked result and do not re-evaluate the holdout.

Report outputs:

- `outputs/reports/final_report.json`
- `outputs/reports/final_report.md`
- `outputs/reports/holdout_<key>.json`
- holdout equity, drawdown, order, and trade CSV artifacts

## Hypothesis Format

See `configs/sample_hypothesis.yaml`. Hypotheses must declare the strategy family, chart-only features, entry/exit rules, position sizing, cost assumptions, and falsification gates. Unsupported families and forbidden non-chart features are rejected before execution.

Built-in strategy families include breakout, breakout with volume confirmation, moving-average trend, short-term reversal, volatility contraction breakout, gap continuation/reversal, RSI mean reversion, price-volume momentum, and high traded-value momentum.

## Final Holdout Rule

Train and validation data can be used during research. Final holdout data is reserved for the selected candidate and evaluated only by `app.final_report`. After the lock file exists, the report command reuses the locked result. This avoids iterating on strategy design after seeing final-holdout performance.

## Known Limitations

- The included data is synthetic and only proves offline reproducibility.
- Deflated Sharpe, White Reality Check, and bootstrap inference are labeled placeholders.
- Risk rules such as stop loss and trailing ATR are represented in config/spec but not used as live order logic.
- A PASS result means paper-trading candidate only, not live-trading readiness.
