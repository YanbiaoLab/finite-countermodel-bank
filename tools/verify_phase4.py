#!/usr/bin/env python3
"""Regenerate and verify both Phase 4 stages without executing submitted code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rebuild_phase4  # noqa: E402
from tools.phase4_common import (  # noqa: E402
    DERIVED_TRANSPOSE_COUNT,
    EMBEDDED_COUNT,
    HISTORICAL_REINTRODUCTION_COUNT,
    HISTORICAL_STAGE10_COUNT,
    HISTORICAL_STAGE80_COUNT,
    NEW_RUNTIME_TABLE_COUNT,
    RUNTIME_COUNT,
    STAGE90,
    STAGE100,
    sha256_path,
)


def files_equal(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_handle, right.open("rb") as right_handle:
        while True:
            left_chunk = left_handle.read(1024 * 1024)
            right_chunk = right_handle.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def parse_args() -> argparse.Namespace:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=repository)
    parser.add_argument(
        "--skip-repository-verifier",
        action="store_true",
        help="skip the final tools/verify_repository.py invocation",
    )
    return parser.parse_args()


def main() -> int:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            "Phase 4 requires Python 3.10+; Python 3.11 matches the official sandbox"
        )
    args = parse_args()
    repository = args.repository_root.resolve()
    compared = 0
    with tempfile.TemporaryDirectory(prefix="finite-bank-phase4-") as temporary:
        generated_root = Path(temporary) / "reproduction"
        generated = rebuild_phase4.build(generated_root, repository)
        for stage_id in (STAGE90, STAGE100):
            committed_stage = repository / "reproduction" / stage_id
            generated_stage = generated_root / stage_id
            committed_manifest = json.loads(
                (committed_stage / "stage.json").read_text(encoding="utf-8")
            )
            generated_manifest = json.loads(
                (generated_stage / "stage.json").read_text(encoding="utf-8")
            )
            if committed_manifest != generated_manifest:
                raise RuntimeError(f"nondeterministic stage manifest: {stage_id}")
            committed_paths = {
                str(row["path"]) for row in committed_manifest["artifacts"]
            }
            if committed_paths != set(generated[stage_id]):
                raise RuntimeError(f"generated artifact set drift: {stage_id}")
            for relative in sorted(committed_paths):
                expected = committed_stage / Path(PurePosixPath(relative))
                actual = generated_stage / Path(PurePosixPath(relative))
                if not files_equal(expected, actual):
                    raise RuntimeError(
                        f"nondeterministic Phase 4 artifact: {stage_id}/{relative}"
                    )
                compared += 1
            for relative in ("SHA256SUMS", "stage.json"):
                if not files_equal(
                    committed_stage / relative, generated_stage / relative
                ):
                    raise RuntimeError(
                        f"nondeterministic Phase 4 metadata: {stage_id}/{relative}"
                    )
                compared += 1
            for artifact in committed_manifest["artifacts"]:
                path = committed_stage / Path(PurePosixPath(artifact["path"]))
                if (
                    path.stat().st_size != artifact["bytes"]
                    or sha256_path(path) != artifact["sha256"]
                ):
                    raise RuntimeError(
                        f"manifest integrity drift: {stage_id}/{artifact['path']}"
                    )

    stage90_summary = json.loads(
        (repository / f"reproduction/{STAGE90}/summary.json").read_text(
            encoding="utf-8"
        )
    )
    if stage90_summary["metrics"] != {
        "payload.declared_embedded": EMBEDDED_COUNT,
        "payload.decoded_embedded": EMBEDDED_COUNT,
        "payload.embedded": EMBEDDED_COUNT,
    }:
        raise RuntimeError("Stage 90 claim metrics drift")
    if not (
        stage90_summary["payload_bundle"]["exact_submitted_base85_match"]
        and stage90_summary["payload_bundle"]["exact_submitted_xz_match"]
        and stage90_summary["composition"][
            "finite149_uses_stage81_effective_provenance"
        ]
    ):
        raise RuntimeError("Stage 90 payload/provenance gate drift")

    stage100_summary = json.loads(
        (repository / f"reproduction/{STAGE100}/summary.json").read_text(
            encoding="utf-8"
        )
    )
    if stage100_summary["metrics"] != {
        "closure.added": DERIVED_TRANSPOSE_COUNT,
        "closure.runtime": RUNTIME_COUNT,
    }:
        raise RuntimeError("Stage 100 claim metrics drift")
    closure = stage100_summary["closure"]
    if (
        closure["self_transpose_sources"] != 9
        or closure["embedded_nontrivial_transpose_sources"] != 64
        or closure["stage80_required_transposes_in_derived_set"] != 11
        or closure["historical_exact_record_reintroductions"]
        != HISTORICAL_REINTRODUCTION_COUNT
        or closure["historical_first_seen_stage_counts"]
        != {
            "10-primary-9450": HISTORICAL_STAGE10_COUNT,
            "80-finite149": HISTORICAL_STAGE80_COUNT,
        }
        or closure["new_exact_records_first_seen_here"]
        != NEW_RUNTIME_TABLE_COUNT
    ):
        raise RuntimeError("Stage 100 closure partition drift")

    if not args.skip_repository_verifier:
        subprocess.run(
            [
                sys.executable,
                str(repository / "tools/verify_repository.py"),
                "--root",
                str(repository),
                "--stage",
                STAGE100,
            ],
            check=True,
        )
    print(
        json.dumps(
            {
                "byte_identical_files": compared,
                "embedded_records": EMBEDDED_COUNT,
                "runtime_records": RUNTIME_COUNT,
                "stages": [STAGE90, STAGE100],
                "status": "verified",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
