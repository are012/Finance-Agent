from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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
    "volatility_contraction_breakout",
    "gap_continuation",
    "gap_reversal",
    "rsi_mean_reversion",
    "price_volume_momentum",
    "high_traded_value_momentum",
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
            "parameters": self.parameters,
            "universe": self.universe,
            "entry_rule": self.entry_rule,
            "exit_rule": self.exit_rule,
            "position_sizing": self.position_sizing,
            "falsification": self.falsification,
            "source_path": self.source_path,
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
    parameters = dict(payload.get("parameters") or {})
    exit_rule = dict(payload.get("exit_rule") or {})
    lookback = int(parameters.get("lookback_bars", payload.get("lookback_bars", 20)))
    holding = int(parameters.get("holding_bars", exit_rule.get("holding_period_days", payload.get("holding_bars", 5))))
    features = list(payload.get("features") or _required_features(str(payload.get("family", payload.get("signal_family", "momentum"))), lookback))
    return Hypothesis(
        hypothesis_id=str(payload.get("id", payload.get("hypothesis_id", ""))).strip(),
        name=str(payload.get("name", payload.get("idea", "Unnamed chart-only hypothesis"))),
        rationale=str(payload.get("rationale", payload.get("idea", ""))),
        signal_family=str(payload.get("family", payload.get("signal_family", "momentum"))),
        lookback_bars=lookback,
        holding_bars=holding,
        required_features=features,
        forbidden_features=list(payload.get("forbidden_features") or []),
        parameters=parameters,
        universe=dict(payload.get("universe") or {}),
        entry_rule=dict(payload.get("entry_rule") or {}),
        exit_rule=exit_rule,
        position_sizing=dict(payload.get("position_sizing") or {}),
        falsification=dict(payload.get("falsification") or {}),
        source_path=source_path,
    )


def load_hypotheses_from_config(config: dict[str, Any]) -> list[Hypothesis]:
    hypotheses = []
    for path in config.get("hypotheses", {}).get("paths", []) or []:
        try:
            hypotheses.append(load_hypothesis_spec(path))
        except Exception as exc:
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=f"INVALID-{Path(path).stem}",
                    name=f"Invalid hypothesis spec: {path}",
                    rationale=str(exc),
                    signal_family="momentum",
                    lookback_bars=1,
                    holding_bars=1,
                    required_features=["momentum_1"],
                    parameters={"invalid_reason": str(exc)},
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
        ("reversal_5", "Short-term reversal after chart weakness", "reversal", 5, {}),
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
        ("rsi_mean_reversion_14", "RSI mean reversion", "rsi_mean_reversion", 14, {"max_rsi": 35}),
        ("price_volume_momentum_20", "Price-volume momentum", "price_volume_momentum", 20, {"volume_ratio_min": 1.0}),
        ("high_traded_value_momentum_20", "High traded-value momentum", "high_traded_value_momentum", 20, {}),
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
            position_sizing={"method": "equal_weight", "max_positions": 3, "max_position_pct": 1.0},
            falsification={"min_trades": 1},
        )
        for hypothesis_id, name, family, lookback, parameters in specs
    ]
    return candidates[: max(0, budget)]


def _required_features(family: str, lookback: int) -> list[str]:
    common = [f"traded_value_ma_{lookback}"]
    mapping = {
        "momentum": [f"momentum_{lookback}", *common],
        "breakout": [f"prior_high_{lookback}", f"high_breakout_{lookback}", *common],
        "reversal": [f"reversal_{lookback}", *common],
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
        "high_traded_value_momentum": [f"momentum_{lookback}", *common],
    }
    return mapping.get(family, common)
