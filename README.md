# Chart-Only Korean Market Research Framework

This repository implements a reproducible Python framework for systematic trading research using only chart-derived Korean market data.

It is research-only. It does not contain live trading, broker integration, account login, order placement, or real-money execution.

## Scope

Allowed input data:

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
- `listing_status`, when available
- indicators derived from those fields only

Forbidden data includes fundamentals, news, disclosures, macro data, investor-flow data, analyst data, order-book data unless explicitly present as local chart data, and any feature unavailable at the decision timestamp.

## Setup

Use a local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Verify

```bash
.venv/bin/python -m pytest -q
```

## Run Example Research

```bash
.venv/bin/python -m app.run_research --config configs/example.yaml --output-dir outputs
```

This command:

- loads local CSV chart data,
- generates one explicit hypothesis at a time,
- converts each hypothesis into a strategy,
- backtests with next-bar execution and configured costs,
- validates out-of-sample without using the final holdout,
- critiques leakage, execution realism, fragility, and validation gates,
- logs every experiment to `outputs/ledger/experiments.jsonl`,
- writes per-experiment artifacts to `outputs/artifacts`.

## Generate Final Report

```bash
.venv/bin/python -m app.final_report --ledger outputs/ledger/experiments.jsonl --output-dir outputs/reports --config configs/example.yaml
```

The final report command selects the best ledger candidate by predefined scoring rules and evaluates the final holdout once. A holdout lock file is written under `outputs/reports`; later report runs reuse the locked result instead of evaluating the holdout again.

Report outputs:

- `outputs/reports/final_report.json`
- `outputs/reports/final_report.md`
- `outputs/reports/holdout_<key>.json`

## Run One Hypothesis

```bash
.venv/bin/python -m app.run_one_hypothesis --config configs/example.yaml --hypothesis-id momentum_20
```

## Project Layout

```text
app/          CLI entry points
configs/      local reproducible configs
data/         local chart-only sample data
research/     schema, features, hypotheses, strategy, backtest, validation, critic, scoring, ledger, reporting
tests/        pytest coverage for core research invariants
outputs/      generated ledgers, reports, and artifacts
```

## Current Example Result

The bundled synthetic data is intentionally small. The example run can return `NEEDS_MORE_RESEARCH` even when validation and holdout returns are positive, because the critic treats very small samples as inconclusive.
