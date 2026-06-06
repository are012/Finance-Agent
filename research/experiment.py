from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from research.backtester import BacktestResult, backtest_signals
from research.costs import CostModel
from research.critic import critique_experiment
from research.metrics import compute_metrics
from research.scoring import score_candidate
from research.strategy import StrategySpec, build_signals
from research.utils import file_hash, git_hash, stable_json_hash, utc_stamp
from research.validation import concentration_summary, validation_gates_pass, walk_forward_splits


def evaluate_hypothesis(
    *,
    hypothesis,
    split,
    featured,
    config: dict[str, Any],
    output_paths: dict[str, Path] | None = None,
    sequence: int = 1,
) -> dict[str, Any]:
    strategy = hypothesis.to_strategy()
    backtest_config = config.get("backtest", config.get("research", {}))
    initial_cash = float(backtest_config.get("initial_cash", config.get("research", {}).get("initial_cash", 1000000)))
    max_positions = int(backtest_config.get("max_positions", config.get("research", {}).get("max_positions", 3)))
    force_liquidate_at_end = bool(backtest_config.get("force_liquidate_at_end", True))
    cost_model = CostModel.from_config(config.get("costs", {}))
    liquidity_config = config.get("liquidity", {})

    train_result = _evaluate(split.train, strategy, initial_cash, cost_model, max_positions, liquidity_config, force_liquidate_at_end)
    validation_result = _evaluate(
        split.validation,
        strategy,
        initial_cash,
        cost_model,
        max_positions,
        liquidity_config,
        force_liquidate_at_end,
    )
    train_metrics = compute_metrics(train_result.equity_curve, trades=train_result.trades, orders=train_result.orders)
    validation_metrics = compute_metrics(
        validation_result.equity_curve,
        trades=validation_result.trades,
        orders=validation_result.orders,
    )
    validation_outputs = {
        "used_final_holdout": False,
        "cost_sensitivity": _cost_sensitivity(
            split.validation,
            strategy,
            initial_cash,
            cost_model,
            max_positions,
            liquidity_config,
            force_liquidate_at_end,
            config.get("costs", {}).get("cost_sensitivity_multipliers", [1, 2, 3]),
        ),
        "parameter_sensitivity": _parameter_sensitivity(
            split.validation,
            strategy,
            validation_metrics,
            initial_cash,
            cost_model,
            max_positions,
            liquidity_config,
            force_liquidate_at_end,
            config.get("parameter_sensitivity", {}),
            config.get("validation_gates", {}),
        ),
        "concentration": concentration_summary(validation_result.trades, validation_result.equity_curve),
        "liquidity": _liquidity_summary(validation_result.orders),
        "schema": {
            "inconsistencies": list(getattr(featured, "attrs", {}).get("schema_decisions", [])),
            "listing_status": getattr(featured, "attrs", {}).get("listing_status_profile", {}),
        },
        "walk_forward": _walk_forward_validation(
            split=split,
            strategy=strategy,
            initial_cash=initial_cash,
            cost_model=cost_model,
            max_positions=max_positions,
            liquidity_config=liquidity_config,
            force_liquidate_at_end=force_liquidate_at_end,
            walk_forward_config=config.get("walk_forward", {}),
            gates=config.get("validation_gates", {}),
        ),
    }
    formula_outputs = _formula_outputs(strategy)
    if formula_outputs:
        validation_outputs["formula"] = formula_outputs
    critic = critique_experiment(
        hypothesis_id=hypothesis.hypothesis_id,
        feature_columns=list(featured.columns),
        metrics=validation_metrics,
        trades_count=len(validation_result.trades),
        gates=config.get("validation_gates", {}),
        validation_outputs=validation_outputs,
        config=config,
    )
    score = score_candidate(validation_metrics, validation_outputs=validation_outputs, gates=config.get("validation_gates", {}))
    status = {"pass": "PASS", "warn": "WARN", "reject": "FAIL"}[critic["status"]]
    experiment_id = f"{utc_stamp()}-{sequence:03d}"
    artifacts = {}
    if output_paths:
        artifacts = _write_artifacts(
            output_paths=output_paths,
            experiment_id=experiment_id,
            train_result=train_result,
            validation_result=validation_result,
            validation_outputs=validation_outputs,
        )

    return {
        "experiment_id": experiment_id,
        "hypothesis_id": hypothesis.hypothesis_id,
        "hypothesis": hypothesis.to_dict(),
        "status": status,
        "score": score,
        "strategy_family": strategy.signal_family,
        "strategy": _strategy_dict(strategy),
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
        "metrics": validation_metrics,
        "validation_trades": len(validation_result.trades),
        "critic": critic,
        "critic_findings": [flag["message"] for flag in critic["flags"]],
        "validation_outputs": validation_outputs,
        "tested_formula_count": 1 if formula_outputs else 0,
        "config_snapshot": _public_config(config),
        "config_hash": stable_json_hash(_public_config(config)),
        "data_hash": file_hash(config["data"]["path"]),
        "git_hash": git_hash(),
        "artifact_paths": artifacts,
        "artifacts": artifacts,
        "cost_assumptions": config.get("costs", {}),
        "universe_filters": config.get("universe", {}),
        "final_holdout_access": {"used_during_research": False, "evaluated": False},
        "execution_model": "close_signal_executes_next_available_open; same_bar_execution_forbidden",
    }


def rejected_hypothesis_row(
    *,
    hypothesis,
    config: dict[str, Any],
    sequence: int = 1,
) -> dict[str, Any]:
    reason = str(getattr(hypothesis, "error", None) or getattr(hypothesis, "rationale", "Invalid hypothesis"))
    experiment_id = f"{utc_stamp()}-{sequence:03d}"
    critic = {
        "status": "reject",
        "flags": [
            {
                "severity": "high",
                "code": "INVALID_HYPOTHESIS",
                "message": reason,
            }
        ],
    }
    return {
        "experiment_id": experiment_id,
        "hypothesis_id": getattr(hypothesis, "hypothesis_id", f"INVALID-{sequence:03d}"),
        "hypothesis": hypothesis.to_dict() if hasattr(hypothesis, "to_dict") else {"error": reason},
        "status": "FAIL",
        "status_reason": reason,
        "score": -1000000000000.0,
        "strategy_family": None,
        "strategy": None,
        "train_metrics": {},
        "validation_metrics": {},
        "metrics": {},
        "validation_trades": 0,
        "critic": critic,
        "critic_findings": [reason],
        "validation_outputs": {"used_final_holdout": False},
        "config_snapshot": _public_config(config),
        "config_hash": stable_json_hash(_public_config(config)),
        "data_hash": file_hash(config["data"]["path"]),
        "git_hash": git_hash(),
        "artifact_paths": {},
        "artifacts": {},
        "cost_assumptions": config.get("costs", {}),
        "universe_filters": config.get("universe", {}),
        "final_holdout_access": {"used_during_research": False, "evaluated": False},
        "execution_model": "not_executed_invalid_hypothesis",
    }


def run_strategy_on_frame(frame, strategy: StrategySpec, config: dict[str, Any], *, cost_model: CostModel | None = None) -> BacktestResult:
    backtest_config = config.get("backtest", config.get("research", {}))
    return _evaluate(
        frame,
        strategy,
        float(backtest_config.get("initial_cash", config.get("research", {}).get("initial_cash", 1000000))),
        cost_model or CostModel.from_config(config.get("costs", {})),
        int(backtest_config.get("max_positions", config.get("research", {}).get("max_positions", 3))),
        config.get("liquidity", {}),
        bool(backtest_config.get("force_liquidate_at_end", True)),
    )


def _evaluate(data, strategy, initial_cash, cost_model, max_positions, liquidity_config, force_liquidate_at_end=True):
    signals = build_signals(data, strategy, max_positions=max_positions)
    return backtest_signals(
        data,
        signals,
        initial_cash=initial_cash,
        cost_model=cost_model,
        liquidity_config=liquidity_config,
        force_liquidate_at_end=force_liquidate_at_end,
    )


def _cost_sensitivity(data, strategy, initial_cash, cost_model, max_positions, liquidity_config, force_liquidate_at_end, multipliers):
    rows = []
    for multiplier in multipliers:
        result = _evaluate(
            data,
            strategy,
            initial_cash,
            cost_model.scaled(float(multiplier)),
            max_positions,
            liquidity_config,
            force_liquidate_at_end,
        )
        rows.append(
            {
                "multiplier": float(multiplier),
                "metrics": compute_metrics(result.equity_curve, trades=result.trades, orders=result.orders),
            }
        )
    return {
        "rows": rows,
        "passed": all(row["metrics"].get("total_return", 0.0) >= 0 for row in rows if row["multiplier"] >= 2.0),
    }


def _walk_forward_validation(
    *,
    split,
    strategy: StrategySpec,
    initial_cash: float,
    cost_model: CostModel,
    max_positions: int,
    liquidity_config: dict[str, Any],
    force_liquidate_at_end: bool,
    walk_forward_config: dict[str, Any],
    gates: dict[str, Any],
) -> dict[str, Any]:
    research_frame = pd.concat([split.train, split.validation], ignore_index=True).sort_values(["date", "symbol"])
    train_size = int(walk_forward_config.get("train_size", 0) or 0)
    validation_size = int(walk_forward_config.get("validation_size", 0) or 0)
    if train_size <= 0 or validation_size <= 0:
        return {"window_count": 0, "rows": [], "passed": False, "reason": "walk_forward train_size and validation_size must be positive"}

    windows = walk_forward_splits(
        research_frame,
        train_size=train_size,
        validation_size=validation_size,
        step_size=walk_forward_config.get("step_size"),
    )
    rows = []
    for index, window in enumerate(windows, start=1):
        train_result = _evaluate(
            window.train,
            strategy,
            initial_cash,
            cost_model,
            max_positions,
            liquidity_config,
            force_liquidate_at_end,
        )
        validation_result = _evaluate(
            window.validation,
            strategy,
            initial_cash,
            cost_model,
            max_positions,
            liquidity_config,
            force_liquidate_at_end,
        )
        train_metrics = compute_metrics(train_result.equity_curve, trades=train_result.trades, orders=train_result.orders)
        validation_metrics = compute_metrics(validation_result.equity_curve, trades=validation_result.trades, orders=validation_result.orders)
        gates_ok, findings = validation_gates_pass(validation_metrics, len(validation_result.trades), gates)
        rows.append(
            {
                "window": index,
                "train_range": _date_range(window.train),
                "validation_range": _date_range(window.validation),
                "train_metrics": train_metrics,
                "validation_metrics": validation_metrics,
                "validation_trades": len(validation_result.trades),
                "passed": gates_ok,
                "findings": findings,
            }
        )
    return {"window_count": len(rows), "rows": rows, "passed": bool(rows) and all(row["passed"] for row in rows)}


def _parameter_sensitivity(
    data,
    strategy: StrategySpec,
    base_metrics: dict[str, Any],
    initial_cash: float,
    cost_model: CostModel,
    max_positions: int,
    liquidity_config: dict[str, Any],
    force_liquidate_at_end: bool,
    sensitivity_config: dict[str, Any],
    gates: dict[str, Any],
) -> dict[str, Any]:
    rows = []
    seen: set[tuple[str, str]] = set()
    base_lookback = int(strategy.lookback_bars)
    for multiplier in sensitivity_config.get("lookback_multipliers", []):
        lookback = max(1, int(round(base_lookback * float(multiplier))))
        variant = _lookback_variant(strategy, lookback)
        key = ("lookback", json.dumps(_strategy_dict(variant), sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            _evaluate_variant(
                data,
                variant,
                initial_cash,
                cost_model,
                max_positions,
                liquidity_config,
                force_liquidate_at_end,
                gates,
                base_metrics,
                variant_type="lookback",
                variant_value=lookback,
            )
        )

    threshold_params = _threshold_parameters(strategy.parameters)
    for parameter, value in threshold_params.items():
        for multiplier in sensitivity_config.get("threshold_multipliers", [0.8, 1.2]):
            parameters = dict(strategy.parameters)
            parameters[parameter] = float(value) * float(multiplier)
            variant = replace(strategy, parameters=parameters)
            key = ("threshold", json.dumps(_strategy_dict(variant), sort_keys=True, default=str))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                _evaluate_variant(
                    data,
                    variant,
                    initial_cash,
                    cost_model,
                    max_positions,
                    liquidity_config,
                    force_liquidate_at_end,
                    gates,
                    base_metrics,
                    variant_type=f"threshold:{parameter}",
                    variant_value=parameters[parameter],
                )
            )

    evaluated = [row for row in rows if row["status"] == "evaluated"]
    pass_rate = sum(1 for row in evaluated if row["passed"]) / len(evaluated) if evaluated else 0.0
    return {
        "base_parameters": strategy.parameters,
        "base_metrics": base_metrics,
        "variant_count": len(rows),
        "rows": rows,
        "pass_rate": pass_rate,
        "worst_case": _worst_case_metrics(evaluated),
        "median_metrics": _median_metrics(evaluated),
        "degradation": _max_degradation(evaluated),
        "passed": bool(evaluated) and all(row["passed"] for row in evaluated),
    }


def _evaluate_variant(
    data,
    strategy: StrategySpec,
    initial_cash: float,
    cost_model: CostModel,
    max_positions: int,
    liquidity_config: dict[str, Any],
    force_liquidate_at_end: bool,
    gates: dict[str, Any],
    base_metrics: dict[str, Any],
    *,
    variant_type: str,
    variant_value: Any,
) -> dict[str, Any]:
    try:
        result = _evaluate(data, strategy, initial_cash, cost_model, max_positions, liquidity_config, force_liquidate_at_end)
    except ValueError as exc:
        return {
            "variant_type": variant_type,
            "variant_value": variant_value,
            "parameters": strategy.parameters,
            "lookback_bars": strategy.lookback_bars,
            "status": "skipped",
            "reason": str(exc),
            "metrics": {},
            "base_metrics": base_metrics,
            "degradation": {},
            "trade_count": 0,
            "passed": False,
        }
    metrics = compute_metrics(result.equity_curve, trades=result.trades, orders=result.orders)
    gates_ok, findings = validation_gates_pass(metrics, len(result.trades), gates)
    return {
        "variant_type": variant_type,
        "variant_value": variant_value,
        "parameters": strategy.parameters,
        "lookback_bars": strategy.lookback_bars,
        "status": "evaluated",
        "metrics": metrics,
        "base_metrics": base_metrics,
        "degradation": _metric_degradation(base_metrics, metrics),
        "trade_count": len(result.trades),
        "passed": gates_ok,
        "findings": findings,
    }


def _lookback_variant(strategy: StrategySpec, lookback: int) -> StrategySpec:
    old = int(strategy.lookback_bars)
    parameters = dict(strategy.parameters)
    parameters["lookback_bars"] = lookback
    required_features = [_replace_feature_lookback(feature, old, lookback) for feature in strategy.required_features]
    return replace(strategy, lookback_bars=lookback, required_features=required_features, parameters=parameters)


def _replace_feature_lookback(feature: str, old: int, new: int) -> str:
    suffix = f"_{old}"
    if feature.endswith(suffix):
        return f"{feature[: -len(suffix)]}_{new}"
    return feature


def _threshold_parameters(parameters: dict[str, Any]) -> dict[str, float]:
    result = {}
    for key, value in parameters.items():
        if not isinstance(value, (int, float)):
            continue
        lowered = key.lower()
        if any(marker in lowered for marker in ("threshold", "min_", "max_", "_min", "_max", "rsi", "gap")):
            result[key] = float(value)
    return result


_SENSITIVITY_METRICS = (
    "total_return",
    "cagr",
    "sharpe",
    "calmar",
    "max_drawdown",
    "turnover",
    "trade_count",
)


def _metric_degradation(base_metrics: dict[str, Any], variant_metrics: dict[str, Any]) -> dict[str, float]:
    degradation = {}
    for key in _SENSITIVITY_METRICS:
        if key not in base_metrics or key not in variant_metrics:
            continue
        base_value = float(base_metrics.get(key, 0.0) or 0.0)
        variant_value = float(variant_metrics.get(key, 0.0) or 0.0)
        if key == "turnover":
            degradation[key] = max(0.0, variant_value - base_value)
        else:
            degradation[key] = max(0.0, base_value - variant_value)
    return degradation


def _median_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    result = {}
    for key in _SENSITIVITY_METRICS:
        values = [float(row["metrics"].get(key, 0.0) or 0.0) for row in rows if key in row.get("metrics", {})]
        if values:
            result[key] = float(median(values))
    return result


def _worst_case_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    result = {}
    for key in _SENSITIVITY_METRICS:
        values = [float(row["metrics"].get(key, 0.0) or 0.0) for row in rows if key in row.get("metrics", {})]
        if not values:
            continue
        result[key] = max(values) if key == "turnover" else min(values)
    return result


def _max_degradation(rows: list[dict[str, Any]]) -> dict[str, float]:
    result = {}
    for key in _SENSITIVITY_METRICS:
        values = [float(row.get("degradation", {}).get(key, 0.0) or 0.0) for row in rows]
        if values:
            result[key] = max(values)
    return result


def _liquidity_summary(orders) -> dict[str, int]:
    if orders.empty or "status" not in orders.columns:
        return {"rejected_order_count": 0, "partial_fill_count": 0}
    liquidity_orders = orders[orders.get("reason", "").eq("liquidity_cap")] if "reason" in orders.columns else orders.iloc[0:0]
    return {
        "rejected_order_count": int((liquidity_orders["status"] == "rejected").sum()) if not liquidity_orders.empty else 0,
        "partial_fill_count": int((liquidity_orders["status"] == "partial").sum()) if not liquidity_orders.empty else 0,
    }


def _date_range(frame) -> dict[str, str]:
    return {"start": str(frame["date"].min()), "end": str(frame["date"].max()), "rows": str(len(frame))}


def _write_artifacts(*, output_paths, experiment_id, train_result, validation_result, validation_outputs):
    artifact_dir = output_paths["artifacts"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "train_equity": train_result.equity_curve,
        "validation_equity": validation_result.equity_curve,
        "validation_orders": validation_result.orders,
        "validation_trades": validation_result.trades,
    }
    paths = {}
    for name, frame in payloads.items():
        path = artifact_dir / f"{experiment_id}_{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = str(path)
    validation_path = artifact_dir / f"{experiment_id}_validation_outputs.json"
    validation_path.write_text(json.dumps(validation_outputs, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths["validation_outputs"] = str(validation_path)
    return paths


def _strategy_dict(strategy: StrategySpec) -> dict[str, Any]:
    payload = {
        "hypothesis_id": strategy.hypothesis_id,
        "name": strategy.name,
        "signal_family": strategy.signal_family,
        "lookback_bars": strategy.lookback_bars,
        "holding_bars": strategy.holding_bars,
        "required_features": strategy.required_features,
        "parameters": strategy.parameters,
        "max_position_pct": strategy.max_position_pct,
    }
    if strategy.formula:
        payload["formula"] = {
            **strategy.formula_metadata,
            "expressions": strategy.formula,
        }
    return payload


def _formula_outputs(strategy: StrategySpec) -> dict[str, Any]:
    if not strategy.formula:
        return {}
    return {
        **strategy.formula_metadata,
        "strategy_family": strategy.signal_family,
        "expressions": strategy.formula,
    }


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if not key.startswith("_")}
