from __future__ import annotations

import argparse

from research.reporting import write_final_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate final report and one-time holdout evaluation.")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--output-dir", default="outputs/reports")
    parser.add_argument("--config", default="configs/example.yaml")
    args = parser.parse_args(argv)

    summary = write_final_report(ledger_path=args.ledger, output_dir=args.output_dir, config_path=args.config)
    print(f"decision={summary['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
