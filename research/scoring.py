from __future__ import annotations


def score_candidate(metrics: dict[str, float], *, gates: dict | None = None) -> float:
    gates = gates or {}
    score = 0.0
    score += metrics.get("total_return", 0.0) * 100.0
    score += metrics.get("sharpe", 0.0) * 3.0
    score += metrics.get("sortino", 0.0) * 2.0
    score += metrics.get("calmar", 0.0) * 0.5
    score += metrics.get("max_drawdown", 0.0) * 50.0
    if score < float(gates.get("min_score", -10**9)):
        return score
    return float(score)


def select_best_candidate(rows: list[dict]) -> dict | None:
    eligible = [row for row in rows if row.get("status") in {"PASS", "NEEDS_MORE_RESEARCH"}]
    if not eligible:
        eligible = rows
    if not eligible:
        return None
    return max(eligible, key=lambda row: float(row.get("score", float("-inf"))))
