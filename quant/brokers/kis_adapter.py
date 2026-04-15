from __future__ import annotations

import os
from typing import Any

import requests

from ..models import (
    AccountMode,
    KisCredentials,
    OrderExecutionResult,
    OrderIntent,
    OrderPreview,
    OrderSide,
)
from ..settings import QuantFrameworkSettings
from .base import BrokerAdapter


class KisBrokerAdapter(BrokerAdapter):
    name = "kis"

    def __init__(self, settings: QuantFrameworkSettings) -> None:
        self.settings = settings

    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        request = self._build_domestic_cash_order(intent)
        return OrderPreview(
            broker=self.name,
            account_mode=intent.account_mode,
            endpoint=request["url"],
            headers=request["redacted_headers"],
            payload=request["payload"],
            dry_run=True,
            notes=request["notes"],
        )

    def submit_order(self, intent: OrderIntent, dry_run: bool = True) -> OrderExecutionResult:
        request = self._build_domestic_cash_order(intent)

        if dry_run:
            return OrderExecutionResult(
                broker=self.name,
                account_mode=intent.account_mode,
                submitted=False,
                dry_run=True,
                endpoint=request["url"],
                payload=request["payload"],
                response={},
                notes=request["notes"],
            )

        if request["missing_runtime"]:
            raise ValueError("KIS live submission is not ready: " + "; ".join(request["missing_runtime"]))

        response = requests.post(
            request["url"],
            headers=request["headers"],
            json=request["payload"],
            timeout=10,
        )

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {"raw": response.text}

        return OrderExecutionResult(
            broker=self.name,
            account_mode=intent.account_mode,
            submitted=response.ok,
            dry_run=False,
            endpoint=request["url"],
            status_code=response.status_code,
            payload=request["payload"],
            response=response_payload,
            notes=request["notes"],
        )

    def _build_domestic_cash_order(self, intent: OrderIntent) -> dict[str, Any]:
        credentials = self._load_credentials(intent.account_mode)
        endpoint = os.getenv("KIS_ORDER_CASH_PATH", self.settings.kis_order_cash_path)
        url = credentials.base_url.rstrip("/") + endpoint
        tr_id = self._resolve_tr_id(intent.side, intent.account_mode)
        order_division = "01" if intent.order_type == "market" else "00"

        payload = {
            "CANO": credentials.account_no or "",
            "ACNT_PRDT_CD": credentials.product_code or "",
            "PDNO": intent.ticker,
            "ORD_DVSN": order_division,
            "ORD_QTY": str(intent.quantity),
            "ORD_UNPR": "0" if order_division == "01" else self._format_price(intent.price),
        }
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {credentials.access_token}" if credentials.access_token else "",
            "appkey": credentials.app_key or "",
            "appsecret": credentials.app_secret or "",
            "tr_id": tr_id or "",
            "custtype": "P",
        }

        notes = [
            "Default mapper targets domestic cash equity orders only.",
            "Extend this adapter for overseas stocks, ETF, futures, or account-specific payload shapes.",
            "Access token refresh is intentionally left outside the scaffold so you can plug in your preferred KIS auth flow.",
        ]
        missing_runtime = []

        if not credentials.is_configured():
            missing_runtime.append("missing KIS app/account environment variables")
        if not credentials.access_token:
            missing_runtime.append("missing access token environment variable")
        if not tr_id:
            missing_runtime.append("missing KIS TR_ID environment variable")

        if intent.account_mode == AccountMode.PAPER:
            notes.append("Paper mode selected; using the KIS virtual trading base URL.")
        else:
            notes.append("Live mode selected; confirm order routing and guardrails before use.")

        if missing_runtime:
            notes.append("Runtime is incomplete: " + "; ".join(missing_runtime))

        return {
            "url": url,
            "headers": headers,
            "redacted_headers": self._redact_headers(headers),
            "payload": payload,
            "notes": notes,
            "missing_runtime": missing_runtime,
        }

    def _load_credentials(self, account_mode: AccountMode) -> KisCredentials:
        if account_mode == AccountMode.PAPER:
            base_url = os.getenv("KIS_PAPER_BASE_URL", self.settings.kis_paper_base_url)
            prefix = "KIS_PAPER_"
        else:
            base_url = os.getenv("KIS_BASE_URL", self.settings.kis_live_base_url)
            prefix = "KIS_"

        return KisCredentials(
            app_key=self._read_env(prefix + "APP_KEY", "KIS_APP_KEY"),
            app_secret=self._read_env(prefix + "APP_SECRET", "KIS_APP_SECRET"),
            account_no=self._read_env(prefix + "ACCOUNT_NO", "KIS_ACCOUNT_NO"),
            product_code=self._read_env(prefix + "PRODUCT_CODE", "KIS_PRODUCT_CODE"),
            access_token=self._read_env(prefix + "ACCESS_TOKEN", "KIS_ACCESS_TOKEN"),
            base_url=base_url,
        )

    def _resolve_tr_id(self, side: OrderSide, account_mode: AccountMode) -> str | None:
        if account_mode == AccountMode.PAPER:
            env_name = "KIS_PAPER_TR_ID_BUY" if side == OrderSide.BUY else "KIS_PAPER_TR_ID_SELL"
            fallback = "KIS_TR_ID_BUY" if side == OrderSide.BUY else "KIS_TR_ID_SELL"
            return self._read_env(env_name, fallback)

        env_name = "KIS_TR_ID_BUY" if side == OrderSide.BUY else "KIS_TR_ID_SELL"
        return os.getenv(env_name)

    @staticmethod
    def _read_env(primary: str, fallback: str | None = None) -> str | None:
        value = os.getenv(primary)
        if value:
            return value
        if fallback:
            return os.getenv(fallback)
        return None

    @staticmethod
    def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
        redacted = dict(headers)
        for key in ("authorization", "appkey", "appsecret"):
            value = redacted.get(key, "")
            if value:
                redacted[key] = value[:6] + "..." if len(value) > 6 else "***"
        return redacted

    @staticmethod
    def _format_price(price: float | None) -> str:
        if price is None:
            return "0"
        return f"{price:.2f}"
