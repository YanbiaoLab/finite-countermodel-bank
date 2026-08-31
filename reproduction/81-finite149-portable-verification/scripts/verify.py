#!/usr/bin/env python3
"""Regenerate and verify the portable Stage 81 correction artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


SCRIPT_DIR = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPT_DIR))
import rebuild  # noqa: E402


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    stage = SCRIPT_DIR.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", type=Path, default=stage)
    parser.add_argument("--repository-root", type=Path, default=stage.parents[1])
    parser.add_argument(
        "--skip-repository-verifier",
        action="store_true",
        help="skip the final tools/verify_repository.py invocation",
    )
    return parser.parse_args()


def main() -> int:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            "Stage 81 requires Python 3.10+; Python 3.11 matches the official sandbox"
        )
    args = parse_args()
    stage = args.stage_dir.resolve()
    repository = args.repository_root.resolve()
    stage80 = repository / f"reproduction/{rebuild.STAGE80}"

    with tempfile.TemporaryDirectory(prefix="finite149-portable-verify-") as temporary:
        regenerated = Path(temporary) / rebuild.STAGE_ID
        artifact_paths = rebuild.build(regenerated, repository, stage80, stage)
        manifest = json.loads((regenerated / "stage.json").read_text(encoding="utf-8"))
        roles = {row["path"]: row["role"] for row in manifest["artifacts"]}
        compared: list[str] = []
        for relative in artifact_paths:
            if roles[relative] in {"rebuild-script", "verification-script"}:
                continue
            expected = stage / Path(PurePosixPath(relative))
            actual = regenerated / Path(PurePosixPath(relative))
            if expected.read_bytes() != actual.read_bytes():
                raise RuntimeError(f"nondeterministic correction artifact: {relative}")
            compared.append(relative)
        for relative in ("SHA256SUMS", "stage.json"):
            expected = stage / relative
            actual = regenerated / relative
            if expected.read_bytes() != actual.read_bytes():
                raise RuntimeError(f"nondeterministic correction metadata: {relative}")
            compared.append(relative)

    committed_manifest = json.loads((stage / "stage.json").read_text(encoding="utf-8"))
    for row in committed_manifest["artifacts"]:
        path = stage / Path(PurePosixPath(row["path"]))
        if path.stat().st_size != row["bytes"] or sha256_path(path) != row["sha256"]:
            raise RuntimeError(f"manifest integrity mismatch: {row['path']}")

    summary = json.loads((stage / "summary.json").read_text(encoding="utf-8"))
    matrix = summary["finite_outcomes_streaming"]["matrix"]
    if matrix["matrix_materialized"] or not matrix["full_json_syntax_scanned_to_eof"]:
        raise RuntimeError("finite-outcomes streaming contract was not satisfied")
    if matrix["max_buffer_bytes_observed"] > matrix["buffer_limit_bytes"]:
        raise RuntimeError("finite-outcomes application buffer exceeded its declared cap")
    if matrix["selected_cells_retained"] != 789 or matrix["row_count"] != 4694:
        raise RuntimeError("finite-outcomes projection count drift")
    if summary["lean_source_tables"] != {
        "captured_sources_parsed": 17,
        "exact_matches": 17,
    }:
        raise RuntimeError("Lean source-table audit drift")
    if summary["path_evidence_boundary"]["edge_replay_performed"]:
        raise RuntimeError("Stage 81 must not claim an unavailable ETP edge replay")
    if summary["correction_scope"]["changes_stage80_membership_or_counts"]:
        raise RuntimeError("corrective layer unexpectedly changes Stage 80 membership")
    semantics = summary["stage80_portable_semantics"]
    if not semantics["full_stage80_semantic_replacement"]:
        raise RuntimeError("portable verifier does not cover the full Stage 80 semantics")
    if (
        semantics["exhaustive_direction_exact_record_matches"] != 149
        or semantics["required_transpose_exact_records"] != 11
        or semantics["orientation_usage"] != {"direct": 129, "transpose": 20}
        or semantics["core_prefix_exact_records"] != 1470
        or semantics["suffix_exact_records"] != 17
    ):
        raise RuntimeError("portable Stage 80 semantic coverage drift")

    if not args.skip_repository_verifier:
        subprocess.run(
            [
                sys.executable,
                str(repository / "tools/verify_repository.py"),
                "--root",
                str(repository),
                "--stage",
                rebuild.STAGE_ID,
            ],
            check=True,
        )
    print(
        json.dumps(
            {
                "byte_identical_regenerated_files": len(compared),
                "manifested_artifacts": len(committed_manifest["artifacts"]),
                "max_application_buffer_bytes": matrix["max_buffer_bytes_observed"],
                "stage_id": rebuild.STAGE_ID,
                "status": "verified",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
