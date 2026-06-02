from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research.backtester import backtest_signals
from research.costs import CostModel
from research.data_loader import load_config, load_configured_data
from research.features import add_chart_features
from research.hypothesis import generate_hypotheses
from research.ledger import ExperimentLedger
from research.metrics import compute_metrics
from research.scoring import select_best_candidate
from research.strategy import build_signals
from research.validation import SplitConfig, split_by_date, validation_gates_pass


def write_final_report(
    *,
    ledger_path: str | Path,
    output_dir: str | Path,
    config_path: str | Path = "configs/example.yaml",
) -> dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    ledger = ExperimentLedger(ledger_path)
    rows = ledger.read_all()
    selected = select_best_candidate(rows)

    summary: dict[str, Any] = {
        "decision": "FAIL",
        "selected_experiment": selected,
        "experiment_count": len(rows),
        "holdout_evaluated": False,
        "holdout_metrics": None,
        "critic_findings": [],
    }

    if selected is None:
        summary["critic_findings"].append("no experiments were found in the ledger")
        return _persist_report(summary, output_path)

    holdout_key = _holdout_key(config_path, selected)
    holdout_file = output_path / f"holdout_{holdout_key}.json"
    if holdout_file.exists():
        holdout_payload = json.loads(holdout_file.read_text(encoding="utf-8"))
        summary.update(holdout_payload)
        summary["holdout_evaluated"] = False
        summary["critic_findings"].append("final holdout was already evaluated; reused locked result")
        return _persist_report(summary, output_path)

    config = load_config(config_path)
    data = load_configured_data(config)
    featured = add_chart_features(data, windows=list(config["research"].get("feature_windows", [5, 20])))
    split = split_by_date(featured, SplitConfig.from_config(config["split"]))
    cost_model = CostModel.from_config(config.get("costs", {}))
    hypotheses = {hypothesis.hypothesis_id: hypothesis for hypothesis in generate_hypotheses(config["research"]["budget"])}
    hypothesis_id = selected.get("hypothesis_id")
    if hypothesis_id not in hypotheses:
        summary["decision"] = "FAIL"
        summary["critic_findings"].append(f"selected hypothesis is unavailable: {hypothesis_id}")
        return _persist_report(summary, output_path)

    strategy = hypotheses[hypothesis_id].to_strategy()
    signals = build_signals(split.holdout, strategy, max_positions=int(config["research"].get("max_positions", 3)))
    result = backtest_signals(
        split.holdout,
        signals,
        initial_cash=float(config["research"].get("initial_cash", 1000000)),
        cost_model=cost_model,
    )
    holdout_metrics = compute_metrics(result.equity_curve)
    gates_ok, gate_findings = validation_gates_pass(holdout_metrics, len(result.trades), config.get("validation_gates", {}))
    validation_status = selected.get("status")
    if gates_ok and validation_status == "PASS":
        decision = "PASS"
    elif gates_ok:
        decision = "NEEDS_MORE_RESEARCH"
    else:
        decision = "FAIL"

    holdout_payload = {
        "decision": decision,
        "selected_experiment": selected,
        "experiment_count": len(rows),
        "holdout_evaluated": True,
        "holdout_metrics": holdout_metrics,
        "holdout_trades": len(result.trades),
        "critic_findings": gate_findings,
    }
    holdout_file.write_text(json.dumps(holdout_payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    summary.update(holdout_payload)
    return _persist_report(summary, output_path)


def _holdout_key(config_path: str | Path, selected: dict[str, Any]) -> str:
    config = load_config(config_path)
    configured = config.get("research", {}).get("final_holdout_key", "holdout")
    return f"{configured}-{selected.get('hypothesis_id', 'unknown')}"


def _persist_report(summary: dict[str, Any], output_path: Path) -> dict[str, Any]:
    json_path = output_path / "final_report.json"
    md_path = output_path / "final_report.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    md_path.write_text(_markdown(summary), encoding="utf-8")
    return summary


def _markdown(summary: dict[str, Any]) -> str:
    selected = summary.get("selected_experiment") or {}
    lines = [
        "# Final Research Report",
        "",
        f"Decision: **{summary.get('decision')}**",
        "",
        f"Experiment count: {summary.get('experiment_count', 0)}",
        f"Selected hypothesis: {selected.get('hypothesis_id', 'none')}",
        f"Holdout evaluated in this run: {summary.get('holdout_evaluated')}",
        "",
        "## Holdout Metrics",
        "",
        "```json",
        json.dumps(summary.get("holdout_metrics"), indent=2, sort_keys=True, default=str),
        "```",
        "",
        "## Critic Findings",
        "",
    ]
    findings = summary.get("critic_findings") or []
    if findings:
        lines.extend(f"- {finding}" for finding in findings)
    else:
        lines.append("- No blocking critic findings.")
    lines.append("")
    return "\n".join(lines)
