from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from quant import QuantFrameworkService
from quant.models import (
    BacktestRequest,
    BacktestResponse,
    ChartContext,
    ChartHistoryResponse,
    FrameworkInfo,
    OrderExecutionResult,
    OrderIntent,
    OrderPreview,
    QuantRun,
    StrategyMetadata,
    StrategyRequest,
)

app = FastAPI(title="Lean + KIS Quant Framework")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

quant_framework = QuantFrameworkService(project_root=Path(__file__).resolve().parents[1])


@app.get("/api/healthz")
async def healthcheck():
    return {"status": "ok"}


@app.get("/api/quant/framework", response_model=FrameworkInfo)
async def get_quant_framework():
    return quant_framework.framework_info()


@app.get("/api/quant/strategies", response_model=list[StrategyMetadata])
async def get_quant_strategies():
    return quant_framework.list_strategies()


@app.get("/api/quant/chart-context", response_model=ChartContext)
async def get_chart_context(ticker: str, market: str = "usa_equity"):
    try:
        return quant_framework.resolve_chart_context(ticker=ticker, market=market)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/quant/chart-history", response_model=ChartHistoryResponse)
async def get_chart_history(
    ticker: str,
    market: str = "usa_equity",
    start_date: str | None = None,
    end_date: str | None = None,
    max_points: int = 220,
):
    try:
        from datetime import date, timedelta

        resolved_end = date.fromisoformat(end_date) if end_date else date.today()
        resolved_start = date.fromisoformat(start_date) if start_date else resolved_end - timedelta(days=365)
        return quant_framework.get_chart_history(
            ticker=ticker,
            market=market,
            start_date=resolved_start,
            end_date=resolved_end,
            max_points=max_points,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/quant/runs", response_model=list[QuantRun])
async def list_quant_runs():
    return quant_framework.list_runs()


@app.post("/api/quant/backtests", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest):
    try:
        return quant_framework.run_backtest(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/quant/lean/projects", response_model=QuantRun)
async def create_lean_project(req: StrategyRequest):
    try:
        return quant_framework.create_lean_project(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/quant/runs/{run_id}", response_model=QuantRun)
async def get_quant_run(run_id: str):
    run = quant_framework.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/api/quant/kis/orders/preview", response_model=OrderPreview)
async def preview_kis_order(req: OrderIntent):
    try:
        return quant_framework.preview_kis_order(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/quant/kis/orders/submit", response_model=OrderExecutionResult)
async def submit_kis_order(req: OrderIntent, dry_run: bool = True):
    try:
        return quant_framework.submit_kis_order(req, dry_run=dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    frontend_path = Path(__file__).resolve().parents[1] / "index.html"
    with frontend_path.open("r", encoding="utf-8") as file:
        return file.read()
