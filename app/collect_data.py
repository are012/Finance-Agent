from __future__ import annotations

import argparse
import sys

from research.data_collection import collect_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect or ingest chart-only Korean OHLCV data.")
    parser.add_argument("--config", default="configs/data_collection.yaml")
    args = parser.parse_args(argv)

    try:
        manifest = collect_data(config_path=args.config)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"processed={manifest['processed_file']['path']}")
    print(f"manifest={manifest['manifest_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
