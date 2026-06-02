from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    name: str
    rationale: str
    signal_family: str
    lookback_bars: int
    holding_bars: int
    required_features: list[str]
    forbidden_features: list[str]

    def __post_init__(self) -> None:
        for feature in [*self.required_features, *self.forbidden_features]:
            lowered = feature.lower()
            if any(term in lowered for term in FORBIDDEN_FEATURE_TERMS):
                raise ValueError(f"Forbidden feature in chart-only research: {feature}")
        if self.lookback_bars <= 0 or self.holding_bars <= 0:
            raise ValueError("lookback_bars and holding_bars must be positive")

    def to_strategy(self) -> StrategySpec:
        return StrategySpec(
            hypothesis_id=self.hypothesis_id,
            name=self.name,
            signal_family=self.signal_family,
            lookback_bars=self.lookback_bars,
            holding_bars=self.holding_bars,
            required_features=self.required_features,
        )


def generate_hypotheses(budget: int) -> list[Hypothesis]:
    candidates = [
        Hypothesis(
            hypothesis_id="momentum_20",
            name="Liquid 20-bar momentum continuation",
            rationale="Positive chart momentum in sufficiently traded names may persist.",
            signal_family="momentum",
            lookback_bars=20,
            holding_bars=3,
            required_features=["momentum_20", "traded_value_ma_20"],
            forbidden_features=[],
        ),
        Hypothesis(
            hypothesis_id="breakout_20",
            name="20-bar high breakout continuation",
            rationale="Breaks above prior chart highs may indicate demand imbalance.",
            signal_family="breakout",
            lookback_bars=20,
            holding_bars=3,
            required_features=["high_breakout_20", "prior_high_20", "traded_value_ma_20"],
            forbidden_features=[],
        ),
        Hypothesis(
            hypothesis_id="reversal_5",
            name="Short-term reversal after chart weakness",
            rationale="Liquid names with short-term chart weakness may mean-revert.",
            signal_family="reversal",
            lookback_bars=5,
            holding_bars=3,
            required_features=["reversal_5", "traded_value_ma_5"],
            forbidden_features=[],
        ),
    ]
    return candidates[: max(0, budget)]
