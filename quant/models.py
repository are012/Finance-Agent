from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator, field_validator


class RunMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class RunStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    PREVIEW = "preview"
    SUBMITTED = "submitted"
    FAILED = "failed"


class AccountMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class StrategyParameter(BaseModel):
    name: str
    default: str
    description: str


class StrategyMetadata(BaseModel):
    key: str
    name: str
    description: str
    lean_class_name: str
    parameters: list[StrategyParameter]
    supports_live_trading: bool = True
    family: str = "general"


class StrategyRequest(BaseModel):
    strategy_key: str = "sma_cross"
    ticker: str
    market: str = "usa_equity"
    start_date: date = Field(default_factory=lambda: date(2023, 1, 1))
    end_date: date | None = None
    resolution: str = "DAILY"
    initial_cash: float = 100000.0
    parameters: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("ticker must not be empty")
        return value

    @field_validator("resolution")
    @classmethod
    def normalize_resolution(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("resolution must not be empty")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "StrategyRequest":
        if self.end_date is None:
            self.end_date = date.today()
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class LeanProjectArtifact(BaseModel):
    project_name: str
    project_dir: Path
    main_file: Path
    config_file: Path
    kis_live_file: Path
    manifest_file: Path
    readme_file: Path
    suggested_command: str


class QuantRun(BaseModel):
    run_id: str
    mode: RunMode
    status: RunStatus
    created_at: datetime
    strategy: StrategyMetadata
    ticker: str
    artifact: LeanProjectArtifact | None = None
    notes: list[str] = Field(default_factory=list)


class KisCredentials(BaseModel):
    app_key: str | None = None
    app_secret: str | None = None
    account_no: str | None = None
    product_code: str | None = None
    access_token: str | None = None
    base_url: str

    def is_configured(self) -> bool:
        return all(
            [
                bool(self.app_key),
                bool(self.app_secret),
                bool(self.account_no),
                bool(self.product_code),
            ]
        )


class OrderIntent(BaseModel):
    ticker: str
    side: OrderSide
    quantity: int = Field(gt=0)
    order_type: str = "market"
    price: float | None = None
    strategy_key: str | None = None
    account_mode: AccountMode = AccountMode.PAPER
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def normalize_order_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("ticker must not be empty")
        return value

    @field_validator("order_type")
    @classmethod
    def normalize_order_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"market", "limit"}:
            raise ValueError("order_type must be either market or limit")
        return value

    @model_validator(mode="after")
    def validate_price(self) -> "OrderIntent":
        if self.order_type == "limit" and self.price is None:
            raise ValueError("limit orders require price")
        return self


class OrderPreview(BaseModel):
    broker: str
    account_mode: AccountMode
    endpoint: str
    headers: dict[str, str]
    payload: dict[str, Any]
    dry_run: bool = True
    notes: list[str] = Field(default_factory=list)


class OrderExecutionResult(BaseModel):
    broker: str
    account_mode: AccountMode
    submitted: bool
    dry_run: bool
    endpoint: str
    status_code: int | None = None
    payload: dict[str, Any]
    response: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class FrameworkInfo(BaseModel):
    name: str
    description: str
    default_projects_dir: Path
    strategies: list[StrategyMetadata]
    kis_env_vars: list[str]
    notes: list[str]


class ChartContext(BaseModel):
    ticker: str
    market: str
    data_ticker: str
    tradingview_symbol: str
    notes: list[str] = Field(default_factory=list)


class ChartHistoryPoint(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class ChartHistoryResponse(BaseModel):
    ticker: str
    market: str
    data_ticker: str
    tradingview_symbol: str
    start_date: date
    end_date: date
    points: list[ChartHistoryPoint]
    notes: list[str] = Field(default_factory=list)


class BacktestRequest(StrategyRequest):
    max_points: int = 220

    @field_validator("max_points")
    @classmethod
    def validate_max_points(cls, value: int) -> int:
        if value < 50:
            raise ValueError("max_points must be at least 50")
        if value > 1000:
            raise ValueError("max_points must be 1000 or less")
        return value


class BacktestMetrics(BaseModel):
    total_return: float
    annual_return: float
    benchmark_return: float
    max_drawdown: float
    sharpe_ratio: float
    volatility: float
    win_rate: float
    exposure: float
    trade_count: int


class BacktestPoint(BaseModel):
    date: date
    close: float
    strategy_equity: float
    benchmark_equity: float
    position: float


class BacktestTrade(BaseModel):
    entered_at: date
    exited_at: date | None = None
    entry_price: float
    exit_price: float | None = None
    return_pct: float | None = None


class BacktestResponse(BaseModel):
    strategy: StrategyMetadata
    ticker: str
    market: str
    data_ticker: str
    tradingview_symbol: str
    start_date: date
    end_date: date
    initial_cash: float
    parameters: dict[str, str]
    metrics: BacktestMetrics
    equity_curve: list[BacktestPoint]
    trades: list[BacktestTrade]
    notes: list[str] = Field(default_factory=list)
