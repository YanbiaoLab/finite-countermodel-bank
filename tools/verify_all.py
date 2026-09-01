#!/usr/bin/env python3
"""Run the complete maintained verification suite with one Python interpreter."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


MINIMUM_PYTHON = (3, 10)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: inferred from this script)",
    )
    return parser.parse_args(argv)


def verification_steps(repository: Path, executable: str) -> list[tuple[str, list[str]]]:
    """Return the ordered commands without capturing their potentially large output."""

    return [
        (
            "Verify manifests, artifacts, claims, and stage transitions",
            [executable, str(repository / "tools/verify_repository.py")],
        ),
        (
            "Regenerate and verify the portable Stage 81 correction",
            [
                executable,
                str(
                    repository
                    / "reproduction/81-finite149-portable-verification/scripts/verify.py"
                ),
                "--skip-repository-verifier",
            ],
        ),
        (
            "Regenerate and verify the exact Phase 4 stages",
            [
                executable,
                str(repository / "tools/verify_phase4.py"),
                "--skip-repository-verifier",
            ],
        ),
        (
            "Run unit tests",
            [executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
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
            f"ERROR: Python 3.10+ is required; detected {detected}. "
            "Python 3.11 matches the official sandbox",
            file=sys.stderr,
        )
        return 2

    args = parse_args(argv)
    repository = args.repository_root.resolve()
    run = subprocess.run if runner is None else runner

    for label, command in verification_steps(repository, sys.executable):
        print(f"\n==> {label}", flush=True)
        completed = run(command, cwd=repository)
        if completed.returncode != 0:
            print(
                f"ERROR: {label} failed with exit code {completed.returncode}",
                file=sys.stderr,
            )
            return completed.returncode

    print("\nAll maintained verification checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
