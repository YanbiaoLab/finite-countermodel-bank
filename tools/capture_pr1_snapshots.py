#!/usr/bin/env python3
"""Capture the ignored local PR 1 sources into deterministic tar.gz snapshots.

This is the only PR 1 command that reads the sibling development checkout.  The
reconstruction command reads only the committed archives produced here.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.pr1_common import sha256_path, write_deterministic_tar_gz


STAGES = (
    "10-primary-9450",
    "20-registered-9852",
    "30-early-deltas-9957",
    "40-delivery-10059",
)

FALSE_ROOT = Path(
    "members/wubing/data/processed/rulebooks/order5_rule_registry/false"
)
PRIMARY_ROOT = FALSE_ROOT / "selected_false_finmodel_rule_scripts"
DRAFT_ROOT = Path("members/wubing/experiments/solvers/false_solver/drafts")


def require(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def paths_for_stage(source: Path, stage: str) -> tuple[str, list[Path]]:
    if stage == "10-primary-9450":
        base = source / PRIMARY_ROOT
        names = (
            "README.md",
            "SELF_CONTAINED_NOTE.md",
            "false_model_coverage_9722317.csv",
            "false_model_primary_coverage_9722317.csv",
            "primary_nonzero_model_generation_summary.json",
            "primary_nonzero_model_index.csv",
        )
        paths = [require(base / name) for name in names]
        paths.extend(sorted((base / "primary_nonzero_model_scripts").glob("*.py")))
        paths.append(
            require(source / "members/wubing/data/324M_remaining_pairs/order5_equations.csv")
        )
        return "primary-recovery-snapshot.tar.gz", paths

    if stage == "20-registered-9852":
        false_root = source / FALSE_ROOT
        paths = sorted(false_root.glob("*/*.manifest.json"))
        paths.extend(sorted(false_root.glob("*/*_rule.py")))
        paths.extend(
            sorted(
                (false_root / "selected_false_finmodel_rule_scripts").glob(
                    "false_finmodel_setcheck_*.py"
                )
            )
        )
        d3 = source / DRAFT_ROOT / "d3"
        paths.extend(
            require(d3 / name)
            for name in (
                "README.md",
                "build_solver.py",
                "false9852_model_audit.json",
                "manifest.json",
            )
        )
        return "registry-and-d3-snapshot.tar.gz", paths

    if stage == "30-early-deltas-9957":
        selected = {
            "d1": ("README.md", "build_solver.py", "manifest.json", "solver.py"),
            "d2": (
                "README.md",
                "build_solver.py",
                "manifest.json",
                "offline_false244_model_audit.json",
                "solver.py",
            ),
            "d4": ("README.md", "build_solver.py", "solver.py"),
            "d6": (
                "README.md",
                "build_formula_solver.py",
                "formula_solver.py",
                "model_audit.json",
                "runtime.py",
            ),
            "d8": (
                "README.md",
                "build_formula_solver.py",
                "formula_solver.py",
                "model_audit.json",
            ),
        }
        paths = []
        for draft, names in selected.items():
            base = source / DRAFT_ROOT / draft
            paths.extend(require(base / name) for name in names)
        return "d1-d2-d4-d6-d8-snapshot.tar.gz", paths

    if stage == "40-delivery-10059":
        jiaming = source / "members/wubing/data/processed/jiaming"
        paths = [require(jiaming / "交付.md"), require(jiaming / "剩余252题_false挖掘交付_52题.md")]
        d11 = source / DRAFT_ROOT / "d11"
        paths.extend(
            require(d11 / name)
            for name in (
                "README.md",
                "build_formula_solver.py",
                "evaluate_d11.py",
                "evaluation.json",
                "formula_solver.py",
            )
        )
        return "jiaming-d11-snapshot.tar.gz", paths

    raise ValueError(f"unsupported stage: {stage}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--stage", choices=STAGES, action="append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source_root.resolve()
    repository = args.repository_root.resolve()
    selected = args.stage or list(STAGES)
    for stage in selected:
        archive_name, paths = paths_for_stage(source, stage)
        output = repository / "reproduction" / stage / "raw" / archive_name
        count, source_bytes = write_deterministic_tar_gz(source, paths, output)
        print(
            f"{stage}: {count} files, {source_bytes} source bytes -> "
            f"{output.relative_to(repository)} ({output.stat().st_size} bytes, "
            f"sha256:{sha256_path(output)})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
