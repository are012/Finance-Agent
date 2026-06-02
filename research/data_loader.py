from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from research.schema import validate_ohlcv_frame


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if "data" not in config or "path" not in config["data"]:
        raise ValueError("Config must define data.path")
    return config


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    return validate_ohlcv_frame(frame)


def load_configured_data(config: dict[str, Any]) -> pd.DataFrame:
    return load_ohlcv_csv(config["data"]["path"])
