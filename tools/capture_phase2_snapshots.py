#!/usr/bin/env python3
"""Capture the ignored local Phase 2 sources as deterministic tar.gz snapshots.

This is the only Phase 2 command that reads the sibling development checkout.
The portable rebuild reads only the archives produced here and earlier committed
reproduction stages.  Large bitsets are copied into the tar stream in bounded
chunks; they are never materialized in memory.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase1_common import sha256_path, write_deterministic_tar_gz


STAGE50 = "50-generator-prune-3535"
STAGE60 = "60-fin4-residual-284151591"
STAGE70 = "70-positive-marginal-core-1470"
STAGES = (STAGE50, STAGE60, STAGE70)

DRAFT_ROOT = Path("members/wubing/experiments/solvers/false_solver/drafts")
RUN_ROOT = Path("members/wubing/artifacts/runs")
DATA_ROOT = Path("members/wubing/data")


def require(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def required_files(base: Path, names: tuple[str, ...]) -> list[Path]:
    return [require(base / name) for name in names]


def paths_for_stage(source: Path, stage: str) -> tuple[str, list[Path]]:
    if stage == STAGE50:
        d15 = source / DRAFT_ROOT / "d15"
        d17 = source / DRAFT_ROOT / "d17"
        published = source / "solvers/false/20260812_d17"
        paths = [require(d15 / "solver.py")]
        paths.extend(
            required_files(
                d17,
                (
                    "audit_static_affine_inventory.py",
                    "static-affine-inventory.json",
                ),
            )
        )
        paths.extend(
            required_files(
                published,
                ("D17相对D15改动与实验报告.md", "solver.py"),
            )
        )
        return "d15-d17-prune-snapshot.tar.gz", paths

    if stage == STAGE60:
        package324 = source / DATA_ROOT / "324M_remaining_pairs"
        package284 = source / DATA_ROOT / "284M_remaining_pairs"
        scalar = source / RUN_ROOT / "d17-fin4-exhaustive-full-20260818"
        bitslice = (
            source
            / RUN_ROOT
            / "d17-fin4-exhaustive-full-bitslice-opposite-20260818"
        )

        # order5_equations.csv is captured once from the 324M package.  The 284M
        # copy is byte-identical and its digest remains checked through its
        # historical manifest.
        paths = required_files(
            package324,
            (
                "README.md",
                "manifest.json",
                "build_324M_remaining_pairs.py",
                "generate_324M_remaining_pairs.c",
                "query_324M_remaining_pairs.py",
                "validate_324M_remaining_pairs.py",
                "324M_remaining_pairs.bitset",
                "324M_remaining_pairs.bitset.zst",
                "324M_remaining_pairs_by_source.csv",
                "order5_equations.csv",
            ),
        )
        paths.extend(
            required_files(
                package284,
                (
                    "README.md",
                    "manifest.json",
                    "build_284M_remaining_pairs.py",
                    "query_284M_remaining_pairs.py",
                    "validate_284M_remaining_pairs.py",
                    "284M_remaining_pairs.bitset",
                    "284M_remaining_pairs.bitset.zst",
                    "284M_remaining_pairs_by_source.csv",
                ),
            )
        )

        # Six scalar shards were completed before the run resumed with the
        # bit-sliced opposite-algebra engine.  Together these JSON files cover
        # all 256 contiguous [0, 2^32) labeled-table ranges.
        paths.extend(
            required_files(
                scalar,
                ("run_full_fin4.py", "fin4_exhaustive_engine.c", "progress.json"),
            )
        )
        paths.extend(require(scalar / "shards" / f"shard_{index:03d}.json") for index in range(6))

        paths.extend(
            required_files(
                bitslice,
                (
                    "README.md",
                    "manifest.json",
                    "full_summary.json",
                    "progress.json",
                    "run_remaining_bitslice_opposite.py",
                    "finalize_and_validate.py",
                    "fin4_bitslice_opposite_engine.c",
                    "fin4_coverage_by_source.csv",
                ),
            )
        )
        paths.extend(
            require(bitslice / "shards" / f"shard_{index:03d}.json")
            for index in range(6, 256)
        )
        return "fin4-residual-snapshot.tar.gz", paths

    if stage == STAGE70:
        coverage = (
            source
            / RUN_ROOT
            / "d17-finite-model-284m-pair-coverage-20260818"
        )
        law_counts = (
            source / RUN_ROOT / "d17-finite-model-order5-law-counts-20260817"
        )
        paths = required_files(
            coverage,
            (
                "README.md",
                "manifest.json",
                "deduplicated_manifest.json",
                "compute_284m_model_pair_coverage.py",
                "compute_284m_deduplicated_pair_coverage.py",
                "model_284m_pair_coverage.csv",
                "model_284m_pair_coverage_deduplicated.csv",
                "d17-finite-model-284m-pair-coverage-20260818-share.zip",
            ),
        )
        paths.extend(
            required_files(
                law_counts,
                (
                    "README.md",
                    "manifest.json",
                    "compute_counts.py",
                    "evaluator.c",
                    "model_order5_law_counts.csv",
                ),
            )
        )
        return "d17-284m-coverage-snapshot.tar.gz", paths

    raise ValueError(f"unsupported stage: {stage}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--stage", choices=STAGES, action="append")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
