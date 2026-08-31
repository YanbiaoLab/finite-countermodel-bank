#!/usr/bin/env python3
"""Independently rebuild and verify the committed Stage 80 artifacts."""

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
        help="skip the final root tools/verify_repository.py invocation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stage = args.stage_dir.resolve()
    repository = args.repository_root.resolve()
    raw_snapshot = stage / "raw/finite149-source-snapshot.tar.gz"
    with tempfile.TemporaryDirectory(prefix="finite149-verify-") as temporary:
        regenerated = Path(temporary) / "80-finite149"
        artifact_paths = rebuild.build(
            regenerated,
            repository,
            raw_snapshot,
            stage,
        )
        manifest = json.loads((regenerated / "stage.json").read_text(encoding="utf-8"))
        roles = {row["path"]: row["role"] for row in manifest["artifacts"]}
        compared = []
        for relative in artifact_paths:
            if roles[relative] in {
                "raw-snapshot",
                "capture-script",
                "rebuild-script",
                "verification-script",
            }:
                continue
            expected = stage / Path(PurePosixPath(relative))
            actual = regenerated / Path(PurePosixPath(relative))
            if expected.read_bytes() != actual.read_bytes():
                raise RuntimeError(f"nondeterministic regenerated artifact: {relative}")
            compared.append(relative)
        for relative in ("SHA256SUMS", "stage.json"):
            expected = stage / relative
            actual = regenerated / relative
            if expected.read_bytes() != actual.read_bytes():
                raise RuntimeError(f"nondeterministic regenerated metadata: {relative}")
            compared.append(relative)

    committed_manifest = json.loads((stage / "stage.json").read_text(encoding="utf-8"))
    for row in committed_manifest["artifacts"]:
        path = stage / Path(PurePosixPath(row["path"]))
        if path.stat().st_size != row["bytes"] or sha256_path(path) != row["sha256"]:
            raise RuntimeError(f"manifest integrity mismatch: {row['path']}")
    summary = json.loads((stage / "summary.json").read_text(encoding="utf-8"))
    if summary["evidence_boundary"]["includes_full_1487_payload"]:
        raise RuntimeError("Stage 80 unexpectedly includes the cumulative payload")
    if summary["evidence_boundary"]["includes_opposite_closure_2901"]:
        raise RuntimeError("Stage 80 unexpectedly includes the opposite closure")

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
                "stage_id": rebuild.STAGE_ID,
                "status": "verified",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
