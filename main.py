from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import uvicorn

from quant.models import AccountMode, BacktestRequest, OrderIntent, OrderSide, StrategyRequest
from quant.runtime.service import QuantFrameworkService


def _parse_key_value_pairs(items: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"Invalid parameter '{item}'. Use key=value format.")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SystemExit(f"Invalid parameter '{item}'. Empty keys are not allowed.")
        pairs[key] = value
    return pairs


def _print_json(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    elif isinstance(payload, list):
        payload = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in payload
        ]
    elif isinstance(payload, dict):
        payload = {
            key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            for key, value in payload.items()
        }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lean + KIS quant framework CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve-api", help="Run the FastAPI server.")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")

    subparsers.add_parser("framework-info", help="Print framework metadata.")
    subparsers.add_parser("list-strategies", help="List available strategy templates.")
    subparsers.add_parser("list-runs", help="List generated Lean runs.")

    backtest_parser = subparsers.add_parser("run-backtest", help="Run the interactive local backtest engine.")
    backtest_parser.add_argument("--strategy-key", default="sma_cross")
    backtest_parser.add_argument("--ticker", required=True)
    backtest_parser.add_argument("--market", default="usa_equity")
    backtest_parser.add_argument("--start-date", default="2023-01-01")
    backtest_parser.add_argument("--end-date")
    backtest_parser.add_argument("--resolution", default="DAILY")
    backtest_parser.add_argument("--initial-cash", type=float, default=100000.0)
    backtest_parser.add_argument("--max-points", type=int, default=220)
    backtest_parser.add_argument("--param", action="append", default=[])

    project_parser = subparsers.add_parser("create-project", help="Generate a Lean project scaffold.")
    project_parser.add_argument("--strategy-key", default="sma_cross")
    project_parser.add_argument("--ticker", required=True)
    project_parser.add_argument("--market", default="usa_equity")
    project_parser.add_argument("--start-date", default="2023-01-01")
    project_parser.add_argument("--end-date")
    project_parser.add_argument("--resolution", default="DAILY")
    project_parser.add_argument("--initial-cash", type=float, default=100000.0)
    project_parser.add_argument("--tag", action="append", default=[])
    project_parser.add_argument("--param", action="append", default=[])

    preview_parser = subparsers.add_parser("preview-order", help="Preview a KIS order payload.")
    preview_parser.add_argument("--ticker", required=True)
    preview_parser.add_argument("--side", choices=["buy", "sell"], required=True)
    preview_parser.add_argument("--quantity", type=int, required=True)
    preview_parser.add_argument("--order-type", choices=["market", "limit"], default="market")
    preview_parser.add_argument("--price", type=float)
    preview_parser.add_argument("--account-mode", choices=["paper", "live"], default="paper")
    preview_parser.add_argument("--strategy-key")

    submit_parser = subparsers.add_parser("submit-order", help="Submit or dry-run a KIS order.")
    submit_parser.add_argument("--ticker", required=True)
    submit_parser.add_argument("--side", choices=["buy", "sell"], required=True)
    submit_parser.add_argument("--quantity", type=int, required=True)
    submit_parser.add_argument("--order-type", choices=["market", "limit"], default="market")
    submit_parser.add_argument("--price", type=float)
    submit_parser.add_argument("--account-mode", choices=["paper", "live"], default="paper")
    submit_parser.add_argument("--strategy-key")
    submit_parser.add_argument("--execute", action="store_true", help="Actually call the KIS order endpoint.")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "serve-api":
        uvicorn.run("api.server:app", host=args.host, port=args.port, reload=args.reload)
        return

    service = QuantFrameworkService(project_root=Path.cwd())

    if args.command == "framework-info":
        _print_json(service.framework_info())
        return

    if args.command == "list-strategies":
        _print_json(service.list_strategies())
        return

    if args.command == "list-runs":
        _print_json(service.list_runs())
        return

    if args.command == "run-backtest":
        request = BacktestRequest(
            strategy_key=args.strategy_key,
            ticker=args.ticker,
            market=args.market,
            start_date=args.start_date,
            end_date=args.end_date,
            resolution=args.resolution,
            initial_cash=args.initial_cash,
            max_points=args.max_points,
            parameters=_parse_key_value_pairs(args.param),
        )
        _print_json(service.run_backtest(request))
        return

    if args.command == "create-project":
        request = StrategyRequest(
            strategy_key=args.strategy_key,
            ticker=args.ticker,
            market=args.market,
            start_date=args.start_date,
            end_date=args.end_date,
            resolution=args.resolution,
            initial_cash=args.initial_cash,
            parameters=_parse_key_value_pairs(args.param),
            tags=args.tag,
        )
        _print_json(service.create_lean_project(request))
        return

    if args.command in {"preview-order", "submit-order"}:
        intent = OrderIntent(
            ticker=args.ticker,
            side=OrderSide(args.side),
            quantity=args.quantity,
            order_type=args.order_type,
            price=args.price,
            strategy_key=args.strategy_key,
            account_mode=AccountMode(args.account_mode),
        )
        if args.command == "preview-order":
            _print_json(service.preview_kis_order(intent))
        else:
            _print_json(service.submit_kis_order(intent, dry_run=not args.execute))
        return


if __name__ == "__main__":
    main()
