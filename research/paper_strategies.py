from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from research.hypothesis import Hypothesis, hypothesis_from_spec


def load_paper_strategy_template(path: str | Path) -> Hypothesis:
    spec_path = Path(path)
    payload = _load_payload(spec_path)
    hypothesis = hypothesis_from_spec(payload, source_path=str(spec_path))
    if hypothesis.source_type != "paper_inspired":
        raise ValueError(f"Paper strategy template must set source_type=paper_inspired: {spec_path}")
    return hypothesis


def load_paper_strategy_templates(directory: str | Path) -> list[Hypothesis]:
    template_dir = Path(directory)
    if not template_dir.exists():
        raise FileNotFoundError(f"Paper strategy template directory does not exist: {template_dir}")
    templates = []
    for path in sorted([*template_dir.glob("*.yaml"), *template_dir.glob("*.yml"), *template_dir.glob("*.json")]):
        templates.append(load_paper_strategy_template(path))
    return templates


def _load_payload(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(raw)
    else:
        payload = yaml.safe_load(raw) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Paper strategy template must be a mapping: {path}")
    return payload
