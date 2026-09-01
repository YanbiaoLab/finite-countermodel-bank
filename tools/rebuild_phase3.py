#!/usr/bin/env python3
"""Rebuild Phase 3's portable Stage 81 evidence from committed inputs.

This maintained Phase-level entry delegates to the manifested, stage-local
bounded-memory builder. It does not run the historical high-memory Stage 80 rebuild
path, upstream graph extraction/build, or shortest-path discovery. The committed
Stage 81 companion snapshot is sufficient to validate every frozen path edge.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


MINIMUM_PYTHON = (3, 10)
STAGE80 = "80-finite149"
STAGE81 = "81-finite149-portable-verification"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: inferred from this script)",
    )
    return parser.parse_args(argv)


def rebuild_command(repository: Path, executable: str) -> list[str]:
    """Return the explicit Stage 81 command used by the Phase 3 entry point."""

    stage80 = repository / "reproduction" / STAGE80
    stage81 = repository / "reproduction" / STAGE81
    return [
        executable,
        str(stage81 / "scripts/rebuild.py"),
        "--repository-root",
        str(repository),
        "--output-stage",
        str(stage81),
        "--stage80",
        str(stage80),
        "--script-source-stage",
        str(stage81),
    ]


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    version_info: Any = None,
    runner: Any = None,
) -> int:
    current_version = sys.version_info if version_info is None else version_info
    if tuple(current_version[:2]) < MINIMUM_PYTHON:
        detected = ".".join(str(value) for value in current_version[:3])
        print(
            f"ERROR: Phase 3 requires Python 3.10+; detected {detected}. "
            "Python 3.11 matches the official sandbox",
            file=sys.stderr,
        )
        return 2

    args = parse_args(argv)
    repository = args.repository_root.resolve()
    command = rebuild_command(repository, sys.executable)
    builder = Path(command[1])
    if not builder.is_file():
        print(f"ERROR: missing Stage 81 builder: {builder}", file=sys.stderr)
        return 2

    run = subprocess.run if runner is None else runner
    completed = run(command, cwd=repository)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
