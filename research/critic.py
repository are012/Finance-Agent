from __future__ import annotations

from research.validation import validation_gates_pass

LEAKAGE_TERMS = ("future", "forward", "lead", "target")


def critique_experiment(
    *,
    hypothesis_id: str,
    feature_columns: list[str],
    metrics: dict[str, float],
    trades_count: int,
    gates: dict,
) -> tuple[str, list[str]]:
    findings = []
    leakage_columns = [column for column in feature_columns if any(term in column.lower() for term in LEAKAGE_TERMS)]
    if leakage_columns:
        findings.append(f"potential leakage columns detected: {leakage_columns}")

    gates_ok, gate_findings = validation_gates_pass(metrics, trades_count, gates)
    findings.extend(gate_findings)

    if metrics.get("periods", 0) < 3:
        findings.append("validation sample is too small to evaluate overfitting risk")
    if trades_count == 0:
        findings.append("strategy produced no validation trades; execution realism cannot be assessed")
    elif trades_count < 3:
        findings.append("validation trade sample is small; fragility and overfitting risk remain high")
    if metrics.get("max_drawdown", 0.0) < -0.5:
        findings.append("drawdown is too large for conservative research")
    if metrics.get("max_drawdown", 0.0) == 0.0 and metrics.get("periods", 0) < 20:
        findings.append("zero drawdown on a short validation window is not robust evidence")

    if leakage_columns or not gates_ok:
        return "FAIL", findings
    if metrics.get("periods", 0) < 20:
        return "NEEDS_MORE_RESEARCH", findings
    return "PASS", findings
