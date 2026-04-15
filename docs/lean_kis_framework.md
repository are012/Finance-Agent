# Lean + KIS Framework

This project now includes a dedicated quant framework layer that separates research/backtests from broker execution.

## Layout

```text
quant/
  brokers/
    kis_adapter.py
  lean/
    project_builder.py
  runtime/
    service.py
    store.py
  strategies/
    base.py
    moving_average_cross.py
    registry.py
  models.py
  settings.py
```

## Design

- Lean owns strategy scaffolding and backtests.
- KIS owns live order routing, credentials, and account-specific behavior.
- `QuantFrameworkService` is the single application entry point for API or CLI integrations.
- Run metadata is persisted to `runtime/runs.json`.
- The initial strategy registry includes `sma_cross`, `ema_cross`, and `rsi_reversion`.

## Environment

Use a fresh Anaconda environment for this project.

```bash
conda env create -f environment.yml
conda activate finance-agent
```

If you prefer a manual setup:

```bash
conda create -n finance-agent python=3.12 -y
conda activate finance-agent
pip install -r requirements.txt
```

## Default workflow

1. Run `python3 main.py create-project --strategy-key sma_cross --ticker AAPL`.
2. Or call `POST /api/quant/lean/projects` with a strategy request.
3. Run the generated Lean project locally with the suggested command.
4. Preview or submit approved live orders through the KIS adapter endpoints.

## Extension points

- Add more strategies in `quant/strategies/`.
- Add product-specific KIS mappers in `quant/brokers/kis_adapter.py`.
- Add persistent run storage in `quant/runtime/store.py`.
