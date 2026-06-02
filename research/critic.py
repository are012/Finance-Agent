from __future__ import annotations

from research.validation import validation_gates_pass

LEAKAGE_TERMS = ("future", "forward", "lead", "target")


def critique_experiment(
    *,
    hypothesis_id: str,
    feature_columns: list[str],
    metrics: dict,
    trades_count: int,
    gates: dict,
    validation_outputs: dict | None = None,
) -> dict:
    validation_outputs = validation_outputs or {}
    flags = []
    leakage_columns = [column for column in feature_columns if any(term in column.lower() for term in LEAKAGE_TERMS)]
    if leakage_columns:
        flags.append(_flag("high", "LOOKAHEAD_RISK", f"Potential leakage columns detected: {leakage_columns}"))

    gates_ok, gate_findings = validation_gates_pass(metrics, trades_count, gates)
    for finding in gate_findings:
        flags.append(_flag("medium", "VALIDATION_GATE_FAILURE", finding))

    if validation_outputs.get("used_final_holdout"):
        flags.append(_flag("high", "FINAL_HOLDOUT_CONTAMINATION", "Final holdout was used before final report evaluation."))
    if metrics.get("periods", 0) < 20:
        flags.append(_flag("medium", "OVERFITTING_RISK", "Validation sample is too small to evaluate robustness."))
    if trades_count == 0:
        flags.append(_flag("high", "NO_TRADES", "Strategy produced no validation trades."))
    elif trades_count < int(gates.get("min_trade_count", gates.get("min_trades", 3))):
        flags.append(_flag("medium", "TOO_FEW_TRADES", "Validation trade sample is below the configured gate."))
    if metrics.get("max_drawdown", 0.0) < -float(gates.get("max_mdd", 0.5)):
        flags.append(_flag("high", "EXCESSIVE_DRAWDOWN", "Drawdown is too large for conservative research."))
    if metrics.get("turnover", 0.0) > 20:
        flags.append(_flag("medium", "EXCESSIVE_TURNOVER", "Turnover is high relative to portfolio equity."))
    if validation_outputs.get("cost_sensitivity", {}).get("passed") is False:
        flags.append(_flag("medium", "COST_SENSITIVITY_FAIL", "Strategy weakens under higher cost assumptions."))
    if validation_outputs.get("parameter_sensitivity", {}).get("passed") is False:
        flags.append(_flag("medium", "PARAMETER_FRAGILITY", "Parameter sensitivity check did not pass."))
    concentration = validation_outputs.get("concentration", {})
    if concentration.get("max_symbol_pnl_share", 0.0) > 0.8:
        flags.append(_flag("medium", "PROFIT_CONCENTRATION", "Profit is concentrated in a small subset of symbols."))
    if metrics.get("sharpe", 0.0) > 5 and trades_count < 20:
        flags.append(_flag("medium", "SUSPICIOUSLY_HIGH_PERFORMANCE", "High Sharpe on a small sample is suspicious."))

    if any(flag["severity"] == "high" for flag in flags) or not gates_ok:
        status = "reject"
    elif flags:
        status = "warn"
    else:
        status = "pass"
    return {
        "status": status,
        "flags": flags,
        "summary": _summary(status, flags),
        "hypothesis_id": hypothesis_id,
    }


def _flag(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _summary(status: str, flags: list[dict]) -> str:
    if not flags:
        return "No critic flags."
    return f"{status.upper()} with {len(flags)} critic flag(s): " + ", ".join(flag["code"] for flag in flags)
