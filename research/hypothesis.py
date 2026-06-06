from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from research.formula import FormulaValidationError, validate_formula_spec
from research.strategy import StrategySpec

FORBIDDEN_FEATURE_TERMS = {
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
    "future",
    "forward",
    "target",
}

SUPPORTED_FAMILIES = {
    "momentum",
    "breakout",
    "reversal",
    "breakout_volume",
    "ma_trend",
    "short_reversal",
    "volatility_contraction_breakout",
    "gap_continuation",
    "gap_reversal",
    "rsi_mean_reversion",
    "price_volume_momentum",
    "high_traded_value_momentum",
    "traded_value_momentum",
    "formula_rank",
    "formula_rule",
}

FAMILY_ALIASES = {
    "reversal": "short_reversal",
    "high_traded_value_momentum": "traded_value_momentum",
}


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    name: str
    rationale: str
    signal_family: str
    lookback_bars: int
    holding_bars: int
    required_features: list[str]
    forbidden_features: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    universe: dict[str, Any] = field(default_factory=dict)
    entry_rule: dict[str, Any] = field(default_factory=dict)
    exit_rule: dict[str, Any] = field(default_factory=dict)
    position_sizing: dict[str, Any] = field(default_factory=dict)
    falsification: dict[str, Any] = field(default_factory=dict)
    notes: list[Any] = field(default_factory=list)
    formula: dict[str, Any] = field(default_factory=dict)
    formula_metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str = "agent_generated"
    paper_id: str | None = None
    paper_reference: dict[str, Any] = field(default_factory=dict)
    data_requirements: dict[str, Any] = field(default_factory=dict)
    implementation_notes: list[Any] = field(default_factory=list)
    implementation_caveats: list[Any] = field(default_factory=list)
    source_path: str | None = None

    def __post_init__(self) -> None:
        for feature in [*self.required_features, *self.forbidden_features]:
            lowered = str(feature).lower()
            if any(term in lowered for term in FORBIDDEN_FEATURE_TERMS):
                raise ValueError(f"Forbidden feature in chart-only research: {feature}")
        if self.signal_family not in SUPPORTED_FAMILIES:
            raise ValueError(f"Unsupported strategy family: {self.signal_family}")
        if self.lookback_bars <= 0 or self.holding_bars <= 0:
            raise ValueError("lookback_bars and holding_bars must be positive")
        if self.signal_family in {"formula_rank", "formula_rule"} and not self.formula:
            raise ValueError("Formula strategy families must define formula")
        if self.source_type == "paper_inspired":
            if not self.paper_id:
                raise ValueError("Paper-inspired hypotheses must define paper_id")
            if not self.paper_reference:
                raise ValueError("Paper-inspired hypotheses must define paper_reference")
            if not self.data_requirements.get("required"):
                raise ValueError("Paper-inspired hypotheses must define data_requirements.required")

    def to_strategy(self) -> StrategySpec:
        parameters = dict(self.parameters)
        parameters.setdefault("lookback_bars", self.lookback_bars)
        parameters.setdefault("holding_bars", self.holding_bars)
        return StrategySpec(
            hypothesis_id=self.hypothesis_id,
            name=self.name,
            signal_family=self.signal_family,
            lookback_bars=self.lookback_bars,
            holding_bars=self.holding_bars,
            required_features=self.required_features,
            parameters=parameters,
            max_position_pct=float(self.position_sizing.get("max_position_pct", 0.2) if self.position_sizing else 0.2),
            formula=dict(self.formula),
            formula_metadata=dict(self.formula_metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "name": self.name,
            "rationale": self.rationale,
            "signal_family": self.signal_family,
            "lookback_bars": self.lookback_bars,
            "holding_bars": self.holding_bars,
            "required_features": self.required_features,
            "forbidden_features": self.forbidden_features,
            "parameters": self.parameters,
            "universe": self.universe,
            "entry_rule": self.entry_rule,
            "exit_rule": self.exit_rule,
            "position_sizing": self.position_sizing,
            "falsification": self.falsification,
            "notes": self.notes,
            "formula": self.formula,
            "formula_metadata": self.formula_metadata,
            "source_type": self.source_type,
            "paper_id": self.paper_id,
            "paper_reference": self.paper_reference,
            "data_requirements": self.data_requirements,
            "implementation_notes": self.implementation_notes,
            "implementation_caveats": self.implementation_caveats,
            "source_path": self.source_path,
        }


@dataclass(frozen=True)
class InvalidHypothesis:
    hypothesis_id: str
    name: str
    rationale: str
    error: str
    source_path: str | None = None
    is_invalid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "name": self.name,
            "rationale": self.rationale,
            "error": self.error,
            "source_path": self.source_path,
            "invalid": True,
        }


def load_hypothesis_spec(path: str | Path) -> Hypothesis:
    spec_path = Path(path)
    raw = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        payload = json.loads(raw)
    else:
        payload = yaml.safe_load(raw) or {}
    return hypothesis_from_spec(payload, source_path=str(spec_path))


def hypothesis_from_spec(payload: dict[str, Any], *, source_path: str | None = None) -> Hypothesis:
    _reject_forbidden_spec_terms(payload)
    _validate_paper_inspired_payload(payload)
    parameters = dict(payload.get("parameters") or {})
    family = _canonical_family(str(payload.get("strategy_family", payload.get("family", payload.get("signal_family", "momentum")))))
    formula = dict(payload.get("formula") or {})
    exit_rule = dict(payload.get("exit_rule") or {})
    entry_rule = dict(payload.get("entry_rule") or {})
    if family in {"formula_rank", "formula_rule"}:
        entry_rule.setdefault("description", "Formula DSL entry rule.")
        entry_rule.setdefault("expression", formula.get("entry", ""))
        exit_rule.setdefault("description", "Formula DSL exit rule or configured holding period.")
        exit_rule.setdefault("holding_period_days", parameters.get("holding_bars", payload.get("holding_bars", 5)))
        if formula.get("exit"):
            exit_rule.setdefault("expression", formula["exit"])
    if not entry_rule:
        raise ValueError("Hypothesis must define entry_rule")
    if not exit_rule:
        raise ValueError("Hypothesis must define exit_rule")
    lookback = int(parameters.get("lookback_bars", payload.get("lookback_bars", 20)))
    holding = int(parameters.get("holding_bars", exit_rule.get("holding_period_days", payload.get("holding_bars", 5))))
    formula_metadata: dict[str, Any] = {}
    features = list(payload.get("features") or _required_features(family, lookback))
    if family in {"formula_rank", "formula_rule"}:
        try:
            formula_metadata = validate_formula_spec(
                formula,
                declared_features=features,
                require_score=family == "formula_rank",
            )
        except FormulaValidationError as exc:
            raise ValueError(str(exc)) from exc
        features = list(formula_metadata["features"])
    return Hypothesis(
        hypothesis_id=str(payload.get("id", payload.get("hypothesis_id", ""))).strip(),
        name=str(payload.get("name", payload.get("idea", "Unnamed chart-only hypothesis"))),
        rationale=str(payload.get("rationale", payload.get("idea", ""))),
        signal_family=family,
        lookback_bars=lookback,
        holding_bars=holding,
        required_features=features,
        forbidden_features=list(payload.get("forbidden_features") or []),
        parameters=parameters,
        universe=dict(payload.get("universe") or {}),
        entry_rule=entry_rule,
        exit_rule=exit_rule,
        position_sizing=dict(payload.get("position_sizing") or {}),
        falsification=dict(payload.get("falsification") or {}),
        notes=list(payload.get("notes") or []),
        formula=formula,
        formula_metadata=formula_metadata,
        source_type=str(payload.get("source_type", "agent_generated")),
        paper_id=payload.get("paper_id"),
        paper_reference=dict(payload.get("paper_reference") or {}),
        data_requirements=dict(payload.get("data_requirements") or {}),
        implementation_notes=list(payload.get("implementation_notes") or []),
        implementation_caveats=list(payload.get("implementation_caveats") or []),
        source_path=source_path,
    )


def load_hypotheses_from_config(config: dict[str, Any]) -> list[Hypothesis | InvalidHypothesis]:
    hypotheses = []
    seen_formula_hashes: dict[str, str] = {}
    for path in config.get("hypotheses", {}).get("paths", []) or []:
        try:
            hypothesis = load_hypothesis_spec(path)
            formula_hash = hypothesis.formula_metadata.get("hash")
            if formula_hash and formula_hash in seen_formula_hashes:
                raise ValueError(f"Duplicate formula matches {seen_formula_hashes[formula_hash]}")
            if formula_hash:
                seen_formula_hashes[formula_hash] = hypothesis.hypothesis_id
            hypotheses.append(hypothesis)
        except Exception as exc:
            hypotheses.append(
                InvalidHypothesis(
                    hypothesis_id=f"INVALID-{Path(path).stem}",
                    name=f"Invalid hypothesis spec: {path}",
                    rationale=str(exc),
                    error=str(exc),
                    source_path=str(path),
                )
            )
    include_builtin = config.get("hypotheses", {}).get("include_builtin", True)
    if include_builtin:
        budget = int(config.get("research", {}).get("max_hypotheses", config.get("research", {}).get("budget", 8)))
        hypotheses.extend(generate_hypotheses(budget))
    return hypotheses[: int(config.get("research", {}).get("max_hypotheses", len(hypotheses) or 1))]


def generate_hypotheses(budget: int) -> list[Hypothesis]:
    specs = [
        ("momentum_20", "Liquid 20-bar momentum continuation", "momentum", 20, {"min_momentum": 0.0}),
        ("breakout_20", "20-bar high breakout continuation", "breakout", 20, {}),
        ("short_reversal_5", "Short-term reversal after chart weakness", "short_reversal", 5, {}),
        ("breakout_volume_20", "20-bar breakout with volume confirmation", "breakout_volume", 20, {"volume_ratio_min": 1.0}),
        ("ma_trend_20", "Moving-average trend following", "ma_trend", 20, {}),
        (
            "volatility_contraction_breakout_20",
            "Volatility contraction breakout",
            "volatility_contraction_breakout",
            20,
            {"max_range_contraction": 1.0},
        ),
        ("gap_continuation_5", "Gap continuation", "gap_continuation", 5, {"min_gap": 0.005}),
        ("gap_reversal_5", "Gap reversal", "gap_reversal", 5, {"min_gap": 0.005}),
        ("rsi_mean_reversion_5", "RSI mean reversion", "rsi_mean_reversion", 5, {"max_rsi": 35}),
        ("price_volume_momentum_20", "Price-volume momentum", "price_volume_momentum", 20, {"volume_ratio_min": 1.0}),
        ("traded_value_momentum_20", "Traded-value momentum", "traded_value_momentum", 20, {}),
    ]
    candidates = [
        Hypothesis(
            hypothesis_id=hypothesis_id,
            name=name,
            rationale=f"{name} uses local chart-derived price, volume, and traded-value behavior.",
            signal_family=family,
            lookback_bars=lookback,
            holding_bars=3,
            required_features=_required_features(family, lookback),
            parameters=parameters,
            entry_rule={"description": name, "expression": _entry_expression(family, lookback)},
            exit_rule={"description": "Exit after the configured holding period.", "holding_period_days": 3},
            position_sizing={"method": "equal_weight", "max_positions": 3, "max_position_pct": 1.0},
            falsification={"min_trades": 1},
        )
        for hypothesis_id, name, family, lookback, parameters in specs
    ]
    return candidates[: max(0, budget)]


def _canonical_family(family: str) -> str:
    return FAMILY_ALIASES.get(family, family)


def _reject_forbidden_spec_terms(payload: dict[str, Any]) -> None:
    checked = {
        "features": payload.get("features"),
        "forbidden_features": payload.get("forbidden_features"),
        "entry_rule": payload.get("entry_rule"),
        "parameters": payload.get("parameters"),
        "notes": payload.get("notes"),
    }
    violations = _forbidden_spec_violations(checked)
    if violations:
        details = ", ".join(f"{item['path']}={item['value']}" for item in violations)
        raise ValueError(f"Forbidden non-chart data in hypothesis spec: {details}")


def _validate_paper_inspired_payload(payload: dict[str, Any]) -> None:
    source_type = payload.get("source_type", "agent_generated")
    has_paper_fields = any(payload.get(key) for key in ("paper_id", "paper_reference", "data_requirements"))
    if source_type != "paper_inspired":
        if has_paper_fields:
            raise ValueError("Paper metadata requires source_type=paper_inspired")
        return

    required_fields = {
        "paper_id": payload.get("paper_id"),
        "paper_reference": payload.get("paper_reference"),
        "data_requirements": payload.get("data_requirements"),
        "implementation_notes": payload.get("implementation_notes"),
        "implementation_caveats": payload.get("implementation_caveats"),
    }
    missing = [key for key, value in required_fields.items() if value in (None, "", [], {})]
    if missing:
        raise ValueError(f"Paper-inspired hypothesis is missing required metadata: {', '.join(missing)}")

    data_requirements = dict(payload.get("data_requirements") or {})
    required_data = data_requirements.get("required")
    if not isinstance(required_data, list) or not required_data:
        raise ValueError("Paper-inspired data_requirements.required must be a non-empty list")
    allowed_data = data_requirements.get("allowed", [])
    if not isinstance(allowed_data, list):
        raise ValueError("Paper-inspired data_requirements.allowed must be a list")
    violations = _forbidden_spec_violations({"required": required_data, "allowed": allowed_data}, "data_requirements")
    if violations:
        details = ", ".join(f"{item['path']}={item['value']}" for item in violations)
        raise ValueError(f"Forbidden non-chart data in paper-inspired required data: {details}")

    reference = dict(payload.get("paper_reference") or {})
    if not isinstance(reference.get("needs_verification"), bool):
        raise ValueError("Paper-inspired paper_reference.needs_verification must be true or false")


def _forbidden_spec_violations(value: Any, path: str = "spec") -> list[dict[str, str]]:
    violations = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{path}.{key}"
            if _contains_forbidden_term(str(key)):
                violations.append({"path": key_path, "value": str(key)})
            violations.extend(_forbidden_spec_violations(child, key_path))
        return violations
    if isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            violations.extend(_forbidden_spec_violations(child, f"{path}[{index}]"))
        return violations
    if value is not None and _contains_forbidden_term(str(value)):
        violations.append({"path": path, "value": str(value)})
    return violations


def _contains_forbidden_term(value: str) -> bool:
    lowered = value.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    return any(term in tokens for term in FORBIDDEN_FEATURE_TERMS)


def _required_features(family: str, lookback: int) -> list[str]:
    family = _canonical_family(family)
    common = [f"traded_value_ma_{lookback}"]
    mapping = {
        "momentum": [f"momentum_{lookback}", *common],
        "breakout": [f"prior_high_{lookback}", f"high_breakout_{lookback}", *common],
        "short_reversal": [f"reversal_{lookback}", *common],
        "breakout_volume": [f"prior_high_{lookback}", f"volume_ratio_{lookback}", *common],
        "ma_trend": [f"ma_{lookback}", f"ma_trend_{lookback}", *common],
        "volatility_contraction_breakout": [
            f"prior_high_{lookback}",
            f"range_contraction_{lookback}",
            f"volume_ratio_{lookback}",
            *common,
        ],
        "gap_continuation": ["gap_return", f"momentum_{lookback}", *common],
        "gap_reversal": ["gap_return", f"reversal_{lookback}", *common],
        "rsi_mean_reversion": [f"rsi_{lookback}", *common],
        "price_volume_momentum": [f"momentum_{lookback}", f"volume_ratio_{lookback}", *common],
        "traded_value_momentum": [f"momentum_{lookback}", *common],
    }
    return mapping.get(family, common)


def _entry_expression(family: str, lookback: int) -> str:
    family = _canonical_family(family)
    mapping = {
        "momentum": f"momentum_{lookback} > 0",
        "breakout": f"close > prior_high_{lookback}",
        "short_reversal": f"reversal_{lookback} > 0",
        "breakout_volume": f"close > prior_high_{lookback} and volume_ratio_{lookback} >= 1.0",
        "ma_trend": f"close > ma_{lookback}",
        "volatility_contraction_breakout": f"close > prior_high_{lookback} and range_contraction_{lookback} <= 1.0",
        "gap_continuation": "gap_return >= 0.005",
        "gap_reversal": "gap_return <= -0.005",
        "rsi_mean_reversion": f"rsi_{lookback} <= 35",
        "price_volume_momentum": f"momentum_{lookback} > 0 and volume_ratio_{lookback} >= 1.0",
        "traded_value_momentum": f"momentum_{lookback} > 0",
    }
    return mapping.get(family, "chart_only_signal")
