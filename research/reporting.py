from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research.data_loader import load_config, load_configured_data
from research.experiment import run_strategy_on_frame
from research.features import add_chart_features
from research.ledger import ExperimentLedger
from research.metrics import compute_metrics
from research.schema import OPTIONAL_COLUMNS, REQUIRED_COLUMNS
from research.scoring import select_best_candidate
from research.strategy import StrategySpec
from research.validation import SplitConfig, split_by_date, validation_gates_pass

ALLOWED_DATA = [
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "traded_value",
    "market",
    "listing_status",
    "chart-derived indicators from allowed fields",
]
FORBIDDEN_DATA = [
    "fundamentals",
    "financial statements",
    "earnings",
    "analyst reports",
    "news",
    "disclosures",
    "macroeconomic indicators",
    "investor-flow data",
    "future signal data",
    "live market data during tests",
]


def write_final_report(
    *,
    ledger_path: str | Path | None = None,
    output_dir: str | Path,
    config_path: str | Path = "configs/example.yaml",
) -> dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    config = load_config(config_path)
    if ledger_path is None:
        ledger_path = _default_ledger_path(output_path)
    ledger = ExperimentLedger(ledger_path)
    rows = ledger.read_all()
    selected = select_best_candidate(rows)

    summary: dict[str, Any] = {
        "decision": "FAIL",
        "selected_experiment": selected,
        "experiment_count": len(rows),
        "rejected_experiment_count": sum(1 for row in rows if row.get("status") == "FAIL"),
        "holdout_evaluated": False,
        "holdout_metrics": None,
        "holdout_trades": 0,
        "critic_findings": [],
        "limitations": [
            "Research-only output; PASS means paper-trading candidate, not live-trading readiness.",
            "Deflated Sharpe, White Reality Check, and bootstrap inference are placeholders unless explicitly implemented.",
        ],
    }

    if selected is None:
        summary["critic_findings"].append("no experiments were found in the ledger")
        return _persist_report(summary, output_path, reused_lock=False)
    if not selected.get("strategy"):
        summary["critic_findings"].append("no executable validated strategy was found in the ledger")
        return _persist_report(summary, output_path, reused_lock=False)

    holdout_key = _holdout_key(config, selected)
    holdout_file = output_path / f"holdout_{holdout_key}.json"
    if holdout_file.exists():
        holdout_payload = json.loads(holdout_file.read_text(encoding="utf-8"))
        summary.update(holdout_payload)
        summary["holdout_evaluated"] = False
        summary["critic_findings"] = list(summary.get("critic_findings") or [])
        summary["critic_findings"].append("reused locked result; final holdout was not evaluated again")
        return _persist_report(summary, output_path, reused_lock=True)

    data = load_configured_data(config)
    featured = add_chart_features(data, windows=list(config["research"].get("feature_windows", [5, 20])))
    split = split_by_date(featured, SplitConfig.from_config(config.get("splits", config.get("split"))))
    strategy = _strategy_from_row(selected)
    result = run_strategy_on_frame(split.holdout, strategy, config)
    holdout_metrics = compute_metrics(result.equity_curve, trades=result.trades, orders=result.orders)
    gates_ok, gate_findings = validation_gates_pass(holdout_metrics, len(result.trades), config.get("validation_gates", {}))
    validation_status = selected.get("status")
    if gates_ok and validation_status == "PASS":
        decision = "PASS"
    elif gates_ok:
        decision = "NEEDS_MORE_RESEARCH"
    else:
        decision = "FAIL"

    equity_path = output_path / f"holdout_{holdout_key}_equity.csv"
    drawdown_path = output_path / f"holdout_{holdout_key}_drawdown.csv"
    orders_path = output_path / f"holdout_{holdout_key}_orders.csv"
    trades_path = output_path / f"holdout_{holdout_key}_trades.csv"
    result.equity_curve.to_csv(equity_path, index=False)
    result.drawdown_curve.to_csv(drawdown_path, index=False)
    result.orders.to_csv(orders_path, index=False)
    result.trades.to_csv(trades_path, index=False)

    holdout_payload = {
        "decision": decision,
        "selected_experiment": selected,
        "experiment_count": len(rows),
        "rejected_experiment_count": summary["rejected_experiment_count"],
        "holdout_evaluated": True,
        "holdout_metrics": holdout_metrics,
        "holdout_trades": len(result.trades),
        "critic_findings": gate_findings,
        "holdout_artifacts": {
            "equity_curve": str(equity_path),
            "drawdown_curve": str(drawdown_path),
            "orders": str(orders_path),
            "trades": str(trades_path),
        },
        "split_ranges": _split_ranges(split),
        "overfitting_controls": {
            "tested_hypotheses": len(rows),
            "rejected_hypotheses": summary["rejected_experiment_count"],
            "deflated_sharpe": "placeholder",
            "white_reality_check": "placeholder",
            "bootstrap_confidence": "placeholder",
        },
        "limitations": summary["limitations"],
        **_research_report_sections(config=config, selected=selected, split=split, holdout_metrics=holdout_metrics, decision=decision),
    }
    holdout_file.write_text(json.dumps(holdout_payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    summary.update(holdout_payload)
    return _persist_report(summary, output_path, reused_lock=False)


def _default_ledger_path(output_path: Path) -> Path:
    if output_path.name == "reports":
        return output_path.parent / "ledger" / "experiments.jsonl"
    return output_path / "ledger" / "experiments.jsonl"


def _holdout_key(config: dict, selected: dict[str, Any]) -> str:
    configured = config.get("research", {}).get("final_holdout_key", "holdout")
    return f"{configured}-{selected.get('hypothesis_id', 'unknown')}"


def _strategy_from_row(row: dict[str, Any]) -> StrategySpec:
    strategy = dict(row.get("strategy") or {})
    return StrategySpec(
        hypothesis_id=strategy["hypothesis_id"],
        name=strategy["name"],
        signal_family=strategy["signal_family"],
        lookback_bars=int(strategy["lookback_bars"]),
        holding_bars=int(strategy["holding_bars"]),
        required_features=list(strategy["required_features"]),
        parameters=dict(strategy.get("parameters") or {}),
        max_position_pct=float(strategy.get("max_position_pct", 0.2)),
        formula=dict((strategy.get("formula") or {}).get("expressions") or {}),
        formula_metadata={key: value for key, value in dict(strategy.get("formula") or {}).items() if key != "expressions"},
    )


def _persist_report(summary: dict[str, Any], output_path: Path, *, reused_lock: bool) -> dict[str, Any]:
    json_path = output_path / "final_report.json"
    md_path = output_path / "final_report.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    md_path.write_text(_markdown(summary, reused_lock=reused_lock), encoding="utf-8")
    return summary


def _markdown(summary: dict[str, Any], *, reused_lock: bool) -> str:
    selected = summary.get("selected_experiment") or {}
    selected_hypothesis = selected.get("hypothesis") or {}
    lines = [
        "# Final Research Report",
        "",
        f"Decision: **{summary.get('decision')}**",
        "",
        "This is a research report only. A PASS means the strategy is a candidate for paper trading, not live deployment.",
        "",
        "## Research Summary",
        "",
        f"- Experiment count: {summary.get('experiment_count', 0)}",
        f"- Rejected experiment count: {summary.get('rejected_experiment_count', 0)}",
        f"- Selected hypothesis: {selected.get('hypothesis_id', 'none')}",
        f"- Strategy family: {selected.get('strategy_family', 'none')}",
        f"- Holdout evaluated in this run: {summary.get('holdout_evaluated')}",
        "",
        "## Research Objective",
        "",
        str(summary.get("research_objective", "")),
        "",
        "## Data Assumptions",
        "",
        "```json",
        json.dumps(summary.get("data_assumptions", {}), indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Allowed Data",
        "",
        "```json",
        json.dumps(summary.get("allowed_data", []), indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Forbidden Data",
        "",
        "```json",
        json.dumps(summary.get("forbidden_data", []), indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Schema Summary",
        "",
        "```json",
        json.dumps(summary.get("schema_summary", {}), indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Split Ranges",
        "",
        "```json",
        json.dumps(summary.get("split_ranges", {}), indent=2, sort_keys=True, default=str),
        "```",
    ]
    if reused_lock:
        lines.append("- Final holdout status: reused locked result; final holdout was not evaluated again")
    lines.extend(
        [
            "",
            "## Strategy",
            "",
            "```json",
            json.dumps(selected_hypothesis, indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Selected Strategy Parameters",
            "",
            "```json",
            json.dumps(summary.get("selected_strategy_parameters", {}), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Train Metrics",
            "",
            "```json",
            json.dumps(summary.get("train_metrics"), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Validation Metrics",
            "",
            "```json",
            json.dumps(summary.get("validation_metrics", selected.get("validation_metrics", selected.get("metrics"))), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Yearly Results",
            "",
            "```json",
            json.dumps(summary.get("yearly_results", {}), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Cost Sensitivity",
            "",
            "```json",
            json.dumps(summary.get("cost_sensitivity", {}), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Parameter Sensitivity",
            "",
            "```json",
            json.dumps(summary.get("parameter_sensitivity", {}), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Concentration Analysis",
            "",
            "```json",
            json.dumps(summary.get("concentration_analysis", {}), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Walk-Forward Summary",
            "",
            "```json",
            json.dumps(summary.get("walk_forward_summary", {}), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Holdout Metrics",
            "",
            "```json",
            json.dumps(summary.get("holdout_metrics"), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Artifacts",
            "",
            "```json",
            json.dumps(summary.get("holdout_artifacts", {}), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Critic Findings",
            "",
        ]
    )
    findings = summary.get("critic_findings") or []
    lines.extend(f"- {finding}" for finding in findings) if findings else lines.append("- No blocking critic findings.")
    lines.extend(
        [
            "",
            "## Critic Flags",
            "",
            "```json",
            json.dumps(summary.get("critic_flags", []), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Overfitting Controls",
            "",
            "```json",
            json.dumps(summary.get("overfitting_controls", {}), indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in summary.get("limitations", []))
    lines.extend(
        [
            "",
            "## Final Conclusion",
            "",
            str(summary.get("final_conclusion", summary.get("decision"))),
            "",
        ]
    )
    return "\n".join(lines)


def _split_ranges(split) -> dict[str, dict[str, str]]:
    return {
        "train": _range(split.train),
        "validation": _range(split.validation),
        "final_holdout": _range(split.holdout),
    }


def _range(frame) -> dict[str, str]:
    return {"start": str(frame["date"].min()), "end": str(frame["date"].max()), "rows": str(len(frame))}


def _research_report_sections(
    *,
    config: dict[str, Any],
    selected: dict[str, Any],
    split,
    holdout_metrics: dict[str, Any],
    decision: str,
) -> dict[str, Any]:
    validation_outputs = selected.get("validation_outputs") or {}
    train_metrics = selected.get("train_metrics", {})
    validation_metrics = selected.get("validation_metrics", selected.get("metrics", {}))
    return {
        "research_objective": "Evaluate chart-only Korean-market systematic trading hypotheses offline, with final holdout reserved for one locked report evaluation.",
        "data_assumptions": {
            "research_only": True,
            "offline_local_data_only": True,
            "chart_only": True,
            "no_live_trading": True,
            "data_path": config.get("data", {}).get("path"),
            "data_format": config.get("data", {}).get("format", "csv"),
            "execution_model": selected.get("execution_model"),
        },
        "allowed_data": ALLOWED_DATA,
        "forbidden_data": FORBIDDEN_DATA,
        "schema_summary": {
            "required_columns": sorted(REQUIRED_COLUMNS),
            "optional_columns": sorted(OPTIONAL_COLUMNS),
            "data_columns": ALLOWED_DATA[:-1],
            "schema_decisions": validation_outputs.get("schema", {}).get("inconsistencies", []),
        },
        "split_ranges": _split_ranges(split),
        "selected_strategy_parameters": (selected.get("strategy") or {}).get("parameters", {}),
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
        "yearly_results": {
            "train": train_metrics.get("yearly_returns", {}),
            "validation": validation_metrics.get("yearly_returns", {}),
            "final_holdout": holdout_metrics.get("yearly_returns", {}),
        },
        "trade_count": {
            "train": train_metrics.get("trade_count", 0),
            "validation": validation_metrics.get("trade_count", 0),
            "final_holdout": holdout_metrics.get("trade_count", 0),
        },
        "turnover": {
            "train": train_metrics.get("turnover", 0),
            "validation": validation_metrics.get("turnover", 0),
            "final_holdout": holdout_metrics.get("turnover", 0),
        },
        "exposure": {
            "train": train_metrics.get("exposure", 0),
            "validation": validation_metrics.get("exposure", 0),
            "final_holdout": holdout_metrics.get("exposure", 0),
        },
        "cost_sensitivity": validation_outputs.get("cost_sensitivity", {}),
        "parameter_sensitivity": validation_outputs.get("parameter_sensitivity", {}),
        "concentration_analysis": validation_outputs.get("concentration", {}),
        "walk_forward_summary": validation_outputs.get("walk_forward", {}),
        "critic_flags": selected.get("critic", {}).get("flags", []),
        "final_conclusion": decision,
    }
