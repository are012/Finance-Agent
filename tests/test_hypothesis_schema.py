import pytest

from research.hypothesis import Hypothesis, generate_hypotheses


def test_hypothesis_requires_explicit_chart_only_fields():
    hypothesis = Hypothesis(
        hypothesis_id="h001",
        name="Liquid momentum continuation",
        rationale="Recent chart momentum may persist in liquid names.",
        signal_family="momentum",
        lookback_bars=20,
        holding_bars=3,
        required_features=["momentum_20", "traded_value_ma_20"],
        forbidden_features=[],
    )

    assert hypothesis.to_strategy().hypothesis_id == "h001"


def test_hypothesis_rejects_forbidden_non_chart_features():
    with pytest.raises(ValueError, match="Forbidden feature"):
        Hypothesis(
            hypothesis_id="bad",
            name="Fundamental value",
            rationale="Uses valuation.",
            signal_family="value",
            lookback_bars=20,
            holding_bars=3,
            required_features=["pe_ratio"],
            forbidden_features=[],
        )


def test_generate_hypotheses_is_deterministic_and_budget_limited():
    hypotheses = generate_hypotheses(budget=2)

    assert [h.hypothesis_id for h in hypotheses] == ["momentum_20", "breakout_20"]
