from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import OrderExecutionResult, OrderIntent, OrderPreview


class BrokerAdapter(ABC):
    name: str = "broker"

    @abstractmethod
    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, intent: OrderIntent, dry_run: bool = True) -> OrderExecutionResult:
        raise NotImplementedError
