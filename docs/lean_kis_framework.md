# Lean + KIS Framework

This project now includes a dedicated quant framework layer that separates research/backtests from broker execution, while exposing an interactive web UI for chart exploration and local backtests.

## Layout

```text
quant/
  research/
    backtester.py
    market_data.py
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
- The web UI adds a fast local backtest loop powered by `yfinance` daily bars.
- KIS owns live order routing, credentials, and account-specific behavior.
- `QuantFrameworkService` is the single application entry point for API or CLI integrations.
- Run metadata is persisted to `runtime/runs.json`.
- The initial strategy registry includes `buy_hold`, `sma_cross`, `ema_cross`, `rsi_reversion`, and `bollinger_reversion`.

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

1. Start the server with `python3 main.py serve-api --reload`.
2. Open `http://127.0.0.1:8000/` and switch between US/KR symbols in the chart view.
3. Pick a strategy card, adjust parameters, and run a local backtest from the UI or `python3 main.py run-backtest ...`.
4. Export the approved setup through `POST /api/quant/lean/projects` or the `Lean 프로젝트 생성` button.
5. Run the generated Lean project locally with the suggested command.
6. Preview or submit approved live orders through the KIS adapter endpoints.

## API surface

- `GET /api/quant/chart-context`: resolve the yfinance ticker and TradingView symbol for a market/ticker pair.
- `POST /api/quant/backtests`: run a local daily-bar backtest and return metrics, equity curve points, and trades.
- `POST /api/quant/lean/projects`: generate a Lean scaffold for the selected strategy.

## Extension points

- Add more strategies in `quant/strategies/`.
- Replace `yfinance` with a dedicated market data service when you need lower latency or richer fundamentals.
- Add product-specific KIS mappers in `quant/brokers/kis_adapter.py`.
- Add persistent run storage in `quant/runtime/store.py`.
