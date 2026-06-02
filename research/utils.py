from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def ensure_output_dirs(output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    paths = {
        "root": root,
        "ledger": root / "ledger",
        "reports": root / "reports",
        "artifacts": root / "artifacts",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
