from __future__ import annotations


def score_candidate(metrics: dict, *, validation_outputs: dict | None = None, gates: dict | None = None) -> float:
    validation_outputs = validation_outputs or {}
    gates = gates or {}
    score = 0.0
    score += 20.0 * _clip(metrics.get("cagr", 0.0), -0.5, 0.5)
    score += 20.0 * _clip(metrics.get("sharpe", 0.0) / 3.0, -1.0, 1.0)
    score += 15.0 * _clip(metrics.get("calmar", 0.0) / 3.0, -1.0, 1.0)
    score += 10.0 * _stability(metrics.get("yearly_returns", {}))
    score += 10.0 if validation_outputs.get("walk_forward", {}).get("passed", True) else -10.0
    score += 10.0 if validation_outputs.get("cost_sensitivity", {}).get("passed", True) else -10.0
    score += 10.0 if validation_outputs.get("parameter_sensitivity", {}).get("passed", True) else -10.0
    score += 5.0 * _clip(metrics.get("exposure", 0.0), 0.0, 1.0)
    score -= 10.0 * _clip(abs(metrics.get("max_drawdown", 0.0)), 0.0, 1.0)
    score -= 0.5 * _clip(metrics.get("turnover", 0.0), 0.0, 50.0)
    min_trades = float(gates.get("min_trade_count", gates.get("min_trades", 1)))
    if metrics.get("trade_count", 0.0) < min_trades:
        score -= (min_trades - metrics.get("trade_count", 0.0)) * 2.0
    concentration = validation_outputs.get("concentration", {})
    score -= 10.0 * _clip(concentration.get("max_symbol_pnl_share", 0.0), 0.0, 1.0)
    return float(score)


def select_best_candidate(rows: list[dict]) -> dict | None:
    eligible = [row for row in rows if row.get("status") in {"PASS", "WARN", "pass", "warn"}]
    if not eligible:
        eligible = [row for row in rows if row.get("status") in {"NEEDS_MORE_RESEARCH"}]
    if not eligible:
        eligible = rows
    if not eligible:
        return None
    return max(eligible, key=lambda row: float(row.get("score", float("-inf"))))


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _stability(yearly: dict) -> float:
    if not yearly:
        return 0.0
    positives = sum(1 for value in yearly.values() if value >= 0)
    return positives / len(yearly)
