import pandas as pd
import pytest

from research.validation import SplitConfig, split_by_date


def test_validation_split_keeps_final_holdout_separate():
    data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "symbol": ["AAA"] * 10,
            "close": range(10),
        }
    )

    split = split_by_date(data, SplitConfig(train_fraction=0.5, validation_fraction=0.3, holdout_fraction=0.2))

    assert split.train["date"].max() < split.validation["date"].min()
    assert split.validation["date"].max() < split.holdout["date"].min()
    assert len(split.train) == 5
    assert len(split.validation) == 3
    assert len(split.holdout) == 2


def test_validation_split_rejects_invalid_fractions():
    with pytest.raises(ValueError, match="sum to 1.0"):
        SplitConfig(train_fraction=0.5, validation_fraction=0.5, holdout_fraction=0.5)
