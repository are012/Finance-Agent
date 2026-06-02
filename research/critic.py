from __future__ import annotations

import re

from research.validation import validation_gates_pass

LEAKAGE_TERMS = ("future", "forward", "lead", "target")
FORBIDDEN_DATA_TERMS = (
    "pe",
    "eps",
    "revenue",
    "earnings",
    "analyst",
    "news",
    "disclosure",
    "macro",
    "foreign",
    "institutional",
    "retail",
)


def critique_experiment(
    *,
    hypothesis_id: str,
    feature_columns: list[str],
    metrics: dict,
    trades_count: int,
    gates: dict,
    validation_outputs: dict | None = None,
    config: dict | None = None,
) -> dict:
    validation_outputs = validation_outputs or {}
    config = config or {}
    flags = []
    leakage_columns = [column for column in feature_columns if any(term in column.lower() for term in LEAKAGE_TERMS)]
    if leakage_columns:
        flags.append(_flag("high", "LOOKAHEAD_RISK", f"Potential leakage columns detected: {leakage_columns}"))
    forbidden_columns = [column for column in feature_columns if _contains_forbidden_data_term(column)]
    if forbidden_columns:
        flags.append(_flag("high", "FORBIDDEN_DATA", f"Forbidden non-chart data columns detected: {forbidden_columns}"))

    backtest_config = config.get("backtest", {})
    if backtest_config.get("allow_same_bar_execution") or (
        backtest_config.get("signal_timing") == "close"
        and backtest_config.get("execution_timing") not in {None, "next_open", "next_available_open"}
    ):
        flags.append(_flag("high", "SAME_BAR_EXECUTION_RISK", "Close-based signals must execute no earlier than next open."))
    listing_status = validation_outputs.get("schema", {}).get("listing_status", {})
    if _has_survivorship_risk(config, validation_outputs, listing_status):
        flags.append(_flag("medium", "SURVIVORSHIP_BIAS_RISK", _survivorship_message(listing_status)))
    costs = config.get("costs", {})
    if config and any(key not in costs for key in ("commission_bps", "sell_tax_bps", "slippage_bps")):
        flags.append(_flag("medium", "MISSING_COST_ASSUMPTION", "Cost assumptions must include commission, sell tax, and slippage."))
    if config and costs and any(float(costs.get(key, 0.0) or 0.0) <= 0 for key in ("commission_bps", "slippage_bps")):
        flags.append(_flag("medium", "UNREALISTIC_EXECUTION", "Zero commission or slippage is unrealistic for conservative research."))
    schema_issues = validation_outputs.get("schema", {}).get("inconsistencies", [])
    if schema_issues:
        flags.append(_flag("medium", "SCHEMA_INCONSISTENCY", f"Schema normalization decisions require review: {schema_issues}"))
    liquidity = validation_outputs.get("liquidity", {})
    if liquidity.get("rejected_order_count", 0) or liquidity.get("partial_fill_count", 0):
        flags.append(_flag("medium", "ILLIQUID_EXECUTION", "Orders were constrained by liquidity caps."))

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
    if validation_outputs.get("walk_forward", {}).get("passed") is False:
        flags.append(_flag("medium", "WALK_FORWARD_FAIL", "Walk-forward validation did not pass across research windows."))
    concentration = validation_outputs.get("concentration", {})
    if max(
        concentration.get("max_symbol_pnl_share", 0.0),
        concentration.get("max_year_pnl_share", 0.0),
        concentration.get("top_trade_pnl_share", 0.0),
    ) > 0.8:
        flags.append(_flag("medium", "PROFIT_CONCENTRATION", "Profit is concentrated in a small subset of symbols, years, or trades."))
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


def _contains_forbidden_data_term(column: str) -> bool:
    tokens = [token for token in re.split(r"[^a-z0-9]+", column.lower()) if token]
    return any(term in tokens for term in FORBIDDEN_DATA_TERMS)


def _has_survivorship_risk(config: dict, validation_outputs: dict, listing_status: dict) -> bool:
    if config.get("universe", {}).get("survivorship_bias_risk") or validation_outputs.get("survivorship_bias_risk"):
        return True
    if listing_status.get("available") is False:
        return True
    counts = listing_status.get("counts", {})
    return any(int(counts.get(status, 0) or 0) > 0 for status in ("delisted", "suspended", "halted"))


def _survivorship_message(listing_status: dict) -> str:
    if listing_status.get("available") is False:
        return "listing_status is unavailable, so historical listing availability cannot be verified."
    counts = listing_status.get("counts", {})
    delisted = int(counts.get("delisted", 0) or 0)
    suspended = int(counts.get("suspended", 0) or 0) + int(counts.get("halted", 0) or 0)
    if delisted or suspended:
        return f"listing_status contains delisted={delisted} and suspended_or_halted={suspended} rows; survivorship handling requires review."
    return "Universe inputs may not represent historical listing availability."


def _summary(status: str, flags: list[dict]) -> str:
    if not flags:
        return "No critic flags."
    return f"{status.upper()} with {len(flags)} critic flag(s): " + ", ".join(flag["code"] for flag in flags)
