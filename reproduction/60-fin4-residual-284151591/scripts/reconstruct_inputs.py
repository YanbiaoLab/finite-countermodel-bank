#!/usr/bin/env python3
"""Recover the five byte-exact standalone inputs needed by Stage 60 tooling."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.stage60_seedfree import (  # noqa: E402
    Stage60SeedFreeError,
    default_work_dir,
    reconstruct_stage60_inputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository root (default: inferred from this script)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "generated input directory; defaults to a checkout-specific directory "
            "under the system temporary directory"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="optional JSON report path (defaults to OUTPUT_DIR/reconstruction.json)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace only the five known generated files after reconstructing them",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = args.repository_root.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else default_work_dir(repository) / "inputs"
    )
    report_path = args.report.resolve() if args.report else output_dir / "reconstruction.json"
    try:
        report = reconstruct_stage60_inputs(
            repository,
            output_dir,
            report_path=report_path,
            replace=args.replace,
        )
    except Stage60SeedFreeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"generated_inputs={output_dir}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
