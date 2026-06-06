from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from functools import reduce
from typing import Any

import pandas as pd


class FormulaValidationError(ValueError):
    """Raised when a formula cannot be safely validated or compiled."""


FORBIDDEN_FORMULA_TERMS = {
    "pe",
    "pbr",
    "eps",
    "revenue",
    "earnings",
    "profit",
    "margin",
    "debt",
    "assets",
    "valuation",
    "analyst",
    "news",
    "disclosure",
    "macro",
    "foreign",
    "institutional",
    "retail",
    "orderbook",
    "order_book",
    "broker",
    "account",
    "future",
    "forward",
    "lead",
    "target",
    "holdout",
    "final_holdout",
}

ALLOWED_FUNCTIONS = {"rank", "zscore", "clip", "abs"}
ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
ALLOWED_UNARYOPS = (ast.UAdd, ast.USub, ast.Not)
ALLOWED_CMPOPS = (ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq)


@dataclass(frozen=True)
class FormulaEvaluation:
    score: pd.Series
    entry: pd.Series
    exit: pd.Series


def validate_formula_spec(
    formula: dict[str, Any],
    *,
    declared_features: list[str],
    require_score: bool = False,
    max_depth: int = 8,
    max_features: int = 8,
    max_constants: int = 12,
) -> dict[str, Any]:
    if not isinstance(formula, dict):
        raise FormulaValidationError("Formula must be a mapping")
    if "entry" not in formula:
        raise FormulaValidationError("Formula must define entry")
    if require_score and "score" not in formula:
        raise FormulaValidationError("Formula rank strategies must define score")

    declared = {str(feature) for feature in declared_features}
    if not declared:
        raise FormulaValidationError("Formula hypotheses must declare chart-derived features")
    for feature in declared:
        _reject_forbidden_text(feature, context="feature")

    parsed: dict[str, ast.Expression] = {}
    used_features: set[str] = set()
    constants = 0
    node_count = 0
    max_seen_depth = 0
    functions: set[str] = set()
    for field in ("score", "entry", "exit"):
        expression = formula.get(field)
        if expression in (None, ""):
            continue
        if not isinstance(expression, str):
            raise FormulaValidationError(f"Formula {field} must be a string")
        _reject_forbidden_text(expression, context=field)
        tree = _parse_expression(expression)
        parsed[field] = tree
        stats = _validate_node(
            tree.body,
            declared_features=declared,
            depth=1,
            max_depth=max_depth,
        )
        used_features.update(stats["features"])
        constants += stats["constants"]
        node_count += stats["nodes"]
        max_seen_depth = max(max_seen_depth, stats["depth"])
        functions.update(stats["functions"])

    if len(used_features) > max_features:
        raise FormulaValidationError(f"Formula uses too many features: {len(used_features)} > {max_features}")
    if constants > max_constants:
        raise FormulaValidationError(f"Formula uses too many constants: {constants} > {max_constants}")

    normalized = _normalized_formula(formula)
    return {
        "features": sorted(used_features),
        "declared_features": sorted(declared),
        "complexity_score": int(node_count + len(used_features) + constants + (2 * len(functions))),
        "depth": int(max_seen_depth),
        "constant_count": int(constants),
        "function_count": int(len(functions)),
        "operators": sorted(functions),
        "normalized": normalized,
        "hash": formula_fingerprint(formula),
    }


def formula_fingerprint(formula: dict[str, Any]) -> str:
    payload = _normalized_formula(formula)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def evaluate_formula_frame(
    frame: pd.DataFrame,
    formula: dict[str, Any],
    *,
    declared_features: list[str] | None = None,
) -> FormulaEvaluation:
    if not isinstance(formula, dict):
        raise FormulaValidationError("Formula must be a mapping")
    validate_formula_spec(formula, declared_features=declared_features or list(frame.columns))
    index = frame.index
    score = _as_series(_evaluate_ast(_parse_expression(str(formula.get("score", "0"))).body, frame), index=index).astype(float)
    entry = _as_series(_evaluate_ast(_parse_expression(str(formula["entry"])).body, frame), index=index).fillna(False).astype(bool)
    if formula.get("exit"):
        exit_signal = _as_series(_evaluate_ast(_parse_expression(str(formula["exit"])).body, frame), index=index).fillna(False).astype(bool)
    else:
        exit_signal = pd.Series(False, index=index)
    return FormulaEvaluation(score=score, entry=entry, exit=exit_signal)


def _parse_expression(expression: str) -> ast.Expression:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FormulaValidationError(f"Unsupported formula syntax: {expression}") from exc
    return tree


def _validate_node(node: ast.AST, *, declared_features: set[str], depth: int, max_depth: int) -> dict[str, Any]:
    if depth > max_depth:
        raise FormulaValidationError(f"Formula depth exceeds limit: {depth} > {max_depth}")
    stats = {"features": set(), "constants": 0, "nodes": 1, "depth": depth, "functions": set()}

    if isinstance(node, ast.Name):
        _reject_forbidden_text(node.id, context="feature")
        if node.id not in declared_features:
            raise FormulaValidationError(f"Unsupported feature in formula: {node.id}")
        stats["features"].add(node.id)
        return stats

    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, bool)):
            raise FormulaValidationError("Formula constants must be numeric or boolean")
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            stats["constants"] += 1
        return stats

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, ALLOWED_BINOPS):
            raise FormulaValidationError("Unsupported formula syntax: unsupported arithmetic operator")
        return _merge_stats(stats, _validate_node(node.left, declared_features=declared_features, depth=depth + 1, max_depth=max_depth), _validate_node(node.right, declared_features=declared_features, depth=depth + 1, max_depth=max_depth))

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ALLOWED_UNARYOPS):
            raise FormulaValidationError("Unsupported formula syntax: unsupported unary operator")
        return _merge_stats(stats, _validate_node(node.operand, declared_features=declared_features, depth=depth + 1, max_depth=max_depth))

    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise FormulaValidationError("Unsupported formula syntax: unsupported boolean operator")
        child_stats = [_validate_node(child, declared_features=declared_features, depth=depth + 1, max_depth=max_depth) for child in node.values]
        return _merge_stats(stats, *child_stats)

    if isinstance(node, ast.Compare):
        if not all(isinstance(op, ALLOWED_CMPOPS) for op in node.ops):
            raise FormulaValidationError("Unsupported formula syntax: unsupported comparison operator")
        child_stats = [_validate_node(node.left, declared_features=declared_features, depth=depth + 1, max_depth=max_depth)]
        child_stats.extend(
            _validate_node(child, declared_features=declared_features, depth=depth + 1, max_depth=max_depth)
            for child in node.comparators
        )
        return _merge_stats(stats, *child_stats)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
            raise FormulaValidationError("Unsupported formula syntax: unsupported function")
        _validate_call_shape(node)
        stats["functions"].add(node.func.id)
        child_stats = [_validate_node(child, declared_features=declared_features, depth=depth + 1, max_depth=max_depth) for child in node.args]
        return _merge_stats(stats, *child_stats)

    raise FormulaValidationError(f"Unsupported formula syntax: {type(node).__name__}")


def _validate_call_shape(node: ast.Call) -> None:
    if node.keywords:
        raise FormulaValidationError("Unsupported formula syntax: keyword arguments are not allowed")
    name = node.func.id
    counts = {"rank": 1, "abs": 1, "zscore": 2, "clip": 3}
    if len(node.args) != counts[name]:
        raise FormulaValidationError(f"Formula function {name} expects {counts[name]} argument(s)")
    if name == "zscore" and not _numeric_constant(node.args[1]):
        raise FormulaValidationError("zscore window must be a numeric constant")
    if name == "clip" and (not _numeric_constant(node.args[1]) or not _numeric_constant(node.args[2])):
        raise FormulaValidationError("clip bounds must be numeric constants")


def _numeric_constant(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
        and not isinstance(node.operand.value, bool)
    )


def _merge_stats(base: dict[str, Any], *children: dict[str, Any]) -> dict[str, Any]:
    result = {
        "features": set(base["features"]),
        "constants": int(base["constants"]),
        "nodes": int(base["nodes"]),
        "depth": int(base["depth"]),
        "functions": set(base["functions"]),
    }
    for child in children:
        result["features"].update(child["features"])
        result["constants"] += int(child["constants"])
        result["nodes"] += int(child["nodes"])
        result["depth"] = max(result["depth"], int(child["depth"]))
        result["functions"].update(child["functions"])
    return result


def _evaluate_ast(node: ast.AST, frame: pd.DataFrame) -> Any:
    if isinstance(node, ast.Name):
        if node.id not in frame.columns:
            raise FormulaValidationError(f"Formula feature is unavailable in feature matrix: {node.id}")
        return frame[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        left = _evaluate_ast(node.left, frame)
        right = _evaluate_ast(node.right, frame)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate_ast(node.operand, frame)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.Not):
            return ~_as_series(operand, index=frame.index).fillna(False).astype(bool)
    if isinstance(node, ast.BoolOp):
        values = [_as_series(_evaluate_ast(child, frame), index=frame.index).fillna(False).astype(bool) for child in node.values]
        return reduce(lambda left, right: left & right, values) if isinstance(node.op, ast.And) else reduce(lambda left, right: left | right, values)
    if isinstance(node, ast.Compare):
        left = _evaluate_ast(node.left, frame)
        comparisons = []
        for op, comparator in zip(node.ops, node.comparators):
            right = _evaluate_ast(comparator, frame)
            comparisons.append(_compare(left, op, right, frame.index))
            left = right
        return reduce(lambda current, next_item: current & next_item, comparisons)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = [_evaluate_ast(arg, frame) for arg in node.args]
        if node.func.id == "rank":
            series = _as_series(args[0], index=frame.index)
            return series.groupby(frame["date"]).rank(method="first", pct=True)
        if node.func.id == "zscore":
            series = _as_series(args[0], index=frame.index).astype(float)
            window = int(args[1])
            mean = series.groupby(frame["symbol"]).transform(lambda values: values.rolling(window, min_periods=window).mean())
            std = series.groupby(frame["symbol"]).transform(lambda values: values.rolling(window, min_periods=window).std(ddof=0))
            return (series - mean) / std.replace(0, pd.NA)
        if node.func.id == "clip":
            return _as_series(args[0], index=frame.index).clip(lower=float(args[1]), upper=float(args[2]))
        if node.func.id == "abs":
            return _as_series(args[0], index=frame.index).abs()
    raise FormulaValidationError(f"Unsupported formula syntax: {type(node).__name__}")


def _compare(left: Any, op: ast.cmpop, right: Any, index: pd.Index) -> pd.Series:
    left_value = _as_series(left, index=index) if not isinstance(left, (int, float, bool)) else left
    right_value = _as_series(right, index=index) if not isinstance(right, (int, float, bool)) else right
    if isinstance(op, ast.Gt):
        return left_value > right_value
    if isinstance(op, ast.GtE):
        return left_value >= right_value
    if isinstance(op, ast.Lt):
        return left_value < right_value
    if isinstance(op, ast.LtE):
        return left_value <= right_value
    if isinstance(op, ast.Eq):
        return left_value == right_value
    if isinstance(op, ast.NotEq):
        return left_value != right_value
    raise FormulaValidationError("Unsupported formula syntax: unsupported comparison operator")


def _as_series(value: Any, *, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(index)
    return pd.Series(value, index=index)


def _normalized_formula(formula: dict[str, Any]) -> dict[str, str]:
    normalized = {}
    for field in ("score", "entry", "exit"):
        expression = formula.get(field)
        if expression in (None, ""):
            continue
        tree = _parse_expression(str(expression))
        normalized[field] = ast.dump(tree, annotate_fields=False, include_attributes=False)
    return normalized


def _reject_forbidden_text(value: str, *, context: str) -> None:
    lowered = value.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    if any(term in tokens for term in FORBIDDEN_FORMULA_TERMS):
        raise FormulaValidationError(f"Forbidden non-chart term in formula {context}: {value}")
