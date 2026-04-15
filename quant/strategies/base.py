from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import StrategyMetadata, StrategyParameter, StrategyRequest


class StrategySpec(ABC):
    key: str = ""
    name: str = ""
    description: str = ""
    lean_class_name: str = ""
    parameter_definitions: tuple[StrategyParameter, ...] = tuple()

    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            key=self.key,
            name=self.name,
            description=self.description,
            lean_class_name=self.lean_class_name,
            parameters=list(self.parameter_definitions),
        )

    def default_parameters(self) -> dict[str, str]:
        return {item.name: item.default for item in self.parameter_definitions}

    def resolve_parameters(self, request: StrategyRequest) -> dict[str, str]:
        params = self.default_parameters()
        for key, value in request.parameters.items():
            params[key] = str(value)
        return params

    def render_project_config(self, request: StrategyRequest) -> dict[str, Any]:
        parameters = {
            "ticker": request.ticker,
            "resolution": request.resolution,
            "market": request.market,
            **self.resolve_parameters(request),
        }
        return {
            "description": f"{self.name} generated for {request.ticker}",
            "algorithm-language": "Python",
            "parameters": parameters,
        }

    def render_live_manifest(self, request: StrategyRequest) -> dict[str, Any]:
        return {
            "broker": "kis",
            "strategy_key": self.key,
            "ticker": request.ticker,
            "market": request.market,
            "parameters": self.resolve_parameters(request),
            "notes": [
                "Lean handles the research/backtest leg via main.py + config.json.",
                "KIS handles the live execution leg through quant.brokers.kis_adapter.KisBrokerAdapter.",
                "Default KIS mapper targets domestic cash equity orders only.",
            ],
        }

    @abstractmethod
    def render_lean_algorithm(self, request: StrategyRequest) -> str:
        raise NotImplementedError
