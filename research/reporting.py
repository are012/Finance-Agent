from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research.data_loader import load_config, load_configured_data
from research.experiment import run_strategy_on_frame
from research.features import add_chart_features
from research.ledger import ExperimentLedger
from research.metrics import compute_metrics
from research.scoring import select_best_candidate
from research.strategy import StrategySpec
from research.validation import SplitConfig, split_by_date, validation_gates_pass


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
            "## Validation Metrics",
            "",
            "```json",
            json.dumps(selected.get("validation_metrics", selected.get("metrics")), indent=2, sort_keys=True, default=str),
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
    lines.append("")
    return "\n".join(lines)


def _split_ranges(split) -> dict[str, dict[str, str]]:
    return {
        "train": _range(split.train),
        "validation": _range(split.validation),
        "final_holdout": _range(split.holdout),
    }


def _range(frame) -> dict[str, str]:
    return {"start": str(frame["date"].min()), "end": str(frame["date"].max()), "rows": str(len(frame))}
