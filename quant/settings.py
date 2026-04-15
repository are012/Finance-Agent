from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class QuantFrameworkSettings(BaseModel):
    project_root: Path
    runtime_dir: Path
    lean_projects_dir: Path
    run_registry_file: Path
    market_data_cache_dir: Path
    kis_live_base_url: str = "https://openapi.koreainvestment.com:9443"
    kis_paper_base_url: str = "https://openapivts.koreainvestment.com:29443"
    kis_order_cash_path: str = "/uapi/domestic-stock/v1/trading/order-cash"

    def ensure_directories(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.lean_projects_dir.mkdir(parents=True, exist_ok=True)
        self.market_data_cache_dir.mkdir(parents=True, exist_ok=True)

    def kis_env_vars(self) -> list[str]:
        return [
            "KIS_APP_KEY",
            "KIS_APP_SECRET",
            "KIS_ACCOUNT_NO",
            "KIS_PRODUCT_CODE",
            "KIS_ACCESS_TOKEN",
            "KIS_PAPER_APP_KEY",
            "KIS_PAPER_APP_SECRET",
            "KIS_PAPER_ACCOUNT_NO",
            "KIS_PAPER_PRODUCT_CODE",
            "KIS_PAPER_ACCESS_TOKEN",
            "KIS_TR_ID_BUY",
            "KIS_TR_ID_SELL",
            "KIS_PAPER_TR_ID_BUY",
            "KIS_PAPER_TR_ID_SELL",
            "KIS_ORDER_CASH_PATH",
            "KIS_BASE_URL",
            "KIS_PAPER_BASE_URL",
        ]


def load_settings(project_root: Path | None = None) -> QuantFrameworkSettings:
    root = project_root or Path(__file__).resolve().parents[1]
    runtime_dir = root / "runtime"
    return QuantFrameworkSettings(
        project_root=root,
        runtime_dir=runtime_dir,
        lean_projects_dir=runtime_dir / "lean_projects",
        run_registry_file=runtime_dir / "runs.json",
        market_data_cache_dir=runtime_dir / "market_data_cache",
    )
