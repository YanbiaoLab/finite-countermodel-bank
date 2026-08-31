#!/usr/bin/env python3
"""Capture the historical finite149 source files into a deterministic archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


DEFAULT_CAPTURED_AT = "2026-08-31T18:00:00+08:00"
EXPECTED_FINITE_OUTCOMES_SHA256 = (
    "257f9e97bac460e3dcdb74469d95783a640c797d8d3423b8e9dbef95e5db52d5"
)
EXPERIMENT = PurePosixPath(
    "research_best/20260821_solo_v2_order4_full_generated"
)
FINITE149 = EXPERIMENT / "finite_not_generated_lean"
REFUTATION934 = PurePosixPath(
    "research_best/20260825_solo_v5_finite149_static_library"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_required(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"missing regular source file: {path}")
    return path.read_bytes()


def git_revision(source_root: Path) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={source_root.resolve()}",
            "rev-parse",
            "HEAD",
        ],
        cwd=source_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def canonical_json(data: object) -> bytes:
    return (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def collect_members(
    source_root: Path, captured_at: str, finite_outcomes_path: Path
) -> dict[str, bytes]:
    relative_sources = {
        "source/789/not_generated_labels.csv": EXPERIMENT
        / "not_generated_truth_db/not_generated_labels.csv",
        "source/789/not_generated_type_audit.json": EXPERIMENT
        / "not_generated_type_audit.json",
        "source/finite149/bundle_manifest.json": FINITE149 / "bundle_manifest.json",
        "source/finite149/manifest.csv": FINITE149 / "manifest.csv",
        "source/finite149/static_library_base_models.jsonl": FINITE149
        / "static_library_base_models.jsonl",
        "source/finite149/static_library_coverage.csv": FINITE149
        / "static_library_coverage.csv",
        "source/finite149/static_library_oriented_models.jsonl": FINITE149
        / "static_library_oriented_models.jsonl",
        "source/finite149/static_library_summary.json": FINITE149
        / "static_library_summary.json",
        "source/refutation934/order24_coverage_reductions.json": REFUTATION934
        / "order24_coverage_reductions.json",
    }
    members: dict[str, bytes] = {}
    source_ledger: list[dict[str, object]] = []
    for archive_name, source_relative in sorted(relative_sources.items()):
        body = read_required(source_root / Path(source_relative))
        members[archive_name] = body
        source_ledger.append(
            {
                "archive_path": archive_name,
                "bytes": len(body),
                "sha256": sha256_bytes(body),
                "source_path": source_relative.as_posix(),
            }
        )

    finite_outcomes = read_required(finite_outcomes_path)
    if sha256_bytes(finite_outcomes) != EXPECTED_FINITE_OUTCOMES_SHA256:
        raise RuntimeError("finite_outcomes.json.gz does not match the historical digest")
    finite_archive_name = "source/upstream/finite_outcomes.json.gz"
    members[finite_archive_name] = finite_outcomes
    source_ledger.append(
        {
            "archive_path": finite_archive_name,
            "bytes": len(finite_outcomes),
            "sha256": sha256_bytes(finite_outcomes),
            "source_path": (
                "https://teorth.github.io/equational_theories/"
                "raw_data/finite_outcomes.json.gz"
            ),
        }
    )

    base_rows = [
        json.loads(line)
        for line in members[
            "source/finite149/static_library_base_models.jsonl"
        ].decode("utf-8").splitlines()
        if line.strip()
    ]
    if len(base_rows) != 17:
        raise RuntimeError(f"expected 17 base-model records, got {len(base_rows)}")
    official_paths = [str(row["official_source"]) for row in base_rows]
    if len(set(official_paths)) != 17:
        raise RuntimeError("the base-model inventory does not name 17 unique sources")
    for official_path in sorted(official_paths):
        archive_name = f"source/official_sources/{official_path}"
        source_relative = FINITE149 / "official_sources" / PurePosixPath(
            official_path
        )
        body = read_required(source_root / Path(source_relative))
        members[archive_name] = body
        source_ledger.append(
            {
                "archive_path": archive_name,
                "bytes": len(body),
                "sha256": sha256_bytes(body),
                "source_path": source_relative.as_posix(),
            }
        )

    metadata = {
        "captured_at": captured_at,
        "member_count_excluding_metadata": len(members),
        "schema_version": "1.0.0",
        "source_files": sorted(source_ledger, key=lambda row: row["archive_path"]),
        "source_repository_revision": git_revision(source_root),
        "source_repository_root_hint": "math-distill-equational-stage2",
    }
    members["snapshot-metadata.json"] = canonical_json(metadata)
    return members


def write_archive(output: Path, members: dict[str, bytes]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw_output, mtime=0, compresslevel=9
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for name in sorted(members):
                    body = members[name]
                    info = tarfile.TarInfo(name)
                    info.size = len(body)
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mode = 0o644
                    archive.addfile(info, io.BytesIO(body))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--finite-outcomes",
        type=Path,
        required=True,
        help="historical finite_outcomes.json.gz with the frozen SHA-256",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "raw/finite149-source-snapshot.tar.gz",
    )
    parser.add_argument("--captured-at", default=DEFAULT_CAPTURED_AT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    members = collect_members(
        source_root, args.captured_at, args.finite_outcomes.resolve()
    )
    write_archive(args.output.resolve(), members)
    body = args.output.resolve().read_bytes()
    print(
        json.dumps(
            {
                "bytes": len(body),
                "members": len(members),
                "output": str(args.output.resolve()),
                "sha256": sha256_bytes(body),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
