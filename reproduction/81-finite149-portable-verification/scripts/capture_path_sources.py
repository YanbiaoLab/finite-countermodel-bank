#!/usr/bin/env python3
"""Capture the hash-pinned finite149 graph inputs and missing Lean path sources.

The Stage 80 bundle manifest is the authority for every URL, byte count, and
SHA-256 value.  Downloads are copied in bounded chunks and rejected before the
deterministic archive is written if any declared identity has drifted.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath


CAPTURED_AT = "2026-09-01T12:00:00+08:00"
CHUNK_BYTES = 64 * 1024
MAX_MEMBER_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
STAGE80_BUNDLE_MEMBER = "source/finite149/bundle_manifest.json"
STAGE80_SOURCE_PREFIX = "source/official_sources/"
UPSTREAM_NAMES = ("finite_graph", "implications_js", "full_entries")
DUALS_RE = re.compile(rb"\bvar\s+duals\s*=\s*")
EXPECTED_STAGE80_RAW_SHA256 = "15dcc1152d014e4a18996d160f0471e85e3c47f7227450c1c2ed2b8bf1dbc237"
EXPECTED_BUNDLE_SHA256 = "03f148e135fbb7a3c548d7aedc3a09b6a1f5bbfacad7afdf2de8401f43f07514"
LICENSE_SPEC = {
    "bytes": 11_377,
    "sha256": "c6be243aa954228fc83b68a08e769bf3c561a64fb515cbbd470046d006c18bbf",
    "url": (
        "https://raw.githubusercontent.com/teorth/equational_theories/"
        "730c20724c9f076eec1c1a98eec232a0ea8f4c5c/LICENSE"
    ),
}
SHOW_PROOF_SPEC = {
    "bytes": 10_132,
    "sha256": "0117a9a3c1d8aa5188b263b2d8aa40394b20e26f380d98718058ce6d392190f2",
    "url": (
        "https://raw.githubusercontent.com/teorth/equational_theories/"
        "730c20724c9f076eec1c1a98eec232a0ea8f4c5c/"
        "home_page/implications/show_proof.html"
    ),
}
MISSING_SOURCE_ALLOWLIST = frozenset(
    {
        "equational_theories/Generated/MagmaEgg/small/_000.lean",
        "equational_theories/Generated/MagmaEgg/small/_001.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_wz_yx_zy.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_wz_zx.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_yx.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_yx_zy.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_zx.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_zy.lean",
        "equational_theories/Generated/TrivialBruteforce/theorems/Apply.lean",
        "equational_theories/Generated/TrivialBruteforce/theorems/RewriteCombinations.lean",
        "equational_theories/Generated/TrivialBruteforce/theorems/RewriteHypothesis.lean",
        "equational_theories/Generated/VampireProven/Proofs2.lean",
        "equational_theories/Generated/VampireProven/Proofs4.lean",
    }
)


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def compact_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def safe_member(name: str) -> None:
    pure = PurePosixPath(name)
    ensure(name and not name.startswith("/"), f"unsafe archive member: {name!r}")
    ensure(".." not in pure.parts and str(pure) == name, f"unsafe archive member: {name!r}")


def validate_member_headers(
    members: list[tarfile.TarInfo],
    *,
    max_member_bytes: int = MAX_MEMBER_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> None:
    names = [member.name for member in members]
    ensure(len(names) == len(set(names)), "duplicate archive member")
    total = 0
    for member in members:
        safe_member(member.name)
        ensure(member.isfile(), f"non-file archive member: {member.name}")
        ensure(member.size <= max_member_bytes, f"archive member exceeds cap: {member.name}")
        total += member.size
    ensure(total <= max_total_bytes, "archive total-size cap exceeded")


def resolve_local_source(source_root: Path, relative: str) -> Path:
    safe_member(relative)
    root = source_root.resolve()
    source = root / Path(PurePosixPath(relative))
    current = source
    while current != root:
        ensure(not current.is_symlink(), f"symlinked local source rejected: {current}")
        current = current.parent
    try:
        resolved = source.resolve(strict=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"missing local source: {source}") from error
    ensure(resolved.is_relative_to(root), f"local source escapes root: {relative}")
    ensure(resolved.is_file(), f"local source is not a file: {source}")
    return resolved


def read_stage80_authority(path: Path) -> tuple[dict[str, object], set[str], str]:
    ensure(sha256_path(path) == EXPECTED_STAGE80_RAW_SHA256, "Stage 80 raw archive hash drift")
    captured: set[str] = set()
    bundle_body: bytes | None = None
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        validate_member_headers(members)
        names = [member.name for member in members]
        ensure("snapshot-metadata.json" in names, "Stage 80 snapshot metadata is absent")
        metadata_file = archive.extractfile("snapshot-metadata.json")
        ensure(metadata_file is not None, "cannot read Stage 80 snapshot metadata")
        metadata = json.load(metadata_file)
        declared = {row["archive_path"]: row for row in metadata["source_files"]}
        ensure(
            len(declared) == len(metadata["source_files"]),
            "duplicate Stage 80 metadata declaration",
        )
        ensure(set(names) == {"snapshot-metadata.json", *declared}, "Stage 80 metadata/member set drift")
        ensure(metadata["member_count_excluding_metadata"] == len(declared), "Stage 80 member-count drift")
        for name, row in declared.items():
            member = archive.getmember(name)
            ensure(member.size == row["bytes"], f"Stage 80 member size drift: {name}")
            extracted = archive.extractfile(member)
            ensure(extracted is not None, f"cannot read Stage 80 member: {name}")
            digest = hashlib.sha256()
            total = 0
            chunks: list[bytes] | None = [] if name == STAGE80_BUNDLE_MEMBER else None
            while chunk := extracted.read(CHUNK_BYTES):
                total += len(chunk)
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
            ensure(total == row["bytes"] and digest.hexdigest() == row["sha256"], f"Stage 80 member identity drift: {name}")
            if member.name.startswith(STAGE80_SOURCE_PREFIX):
                captured.add(member.name[len(STAGE80_SOURCE_PREFIX) :])
            if member.name == STAGE80_BUNDLE_MEMBER:
                ensure(chunks is not None, "internal bundle capture error")
                bundle_body = b"".join(chunks)
    ensure(bundle_body is not None, "Stage 80 bundle manifest is absent")
    bundle_sha = hashlib.sha256(bundle_body).hexdigest()
    ensure(bundle_sha == EXPECTED_BUNDLE_SHA256, "Stage 80 bundle raw-byte hash drift")
    return json.loads(bundle_body), captured, bundle_sha


def copy_url(url: str, destination: Path, expected_bytes: int) -> None:
    ensure(expected_bytes <= MAX_MEMBER_BYTES, f"declared member exceeds cap: {url}")
    written = 0
    request = urllib.request.Request(url, headers={"User-Agent": "finite149-capture/1"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as out:
        while chunk := response.read(CHUNK_BYTES):
            written += len(chunk)
            ensure(written <= expected_bytes, f"download exceeds declared size: {url}")
            out.write(chunk)
    ensure(written == expected_bytes, f"download size drift for {url}: {written}")


def copy_local(source: Path, destination: Path, expected_bytes: int) -> None:
    ensure(source.is_file(), f"missing Lean source: {source}")
    ensure(expected_bytes <= MAX_MEMBER_BYTES, f"declared member exceeds cap: {source}")
    written = 0
    with source.open("rb") as inp, destination.open("wb") as out:
        while chunk := inp.read(CHUNK_BYTES):
            written += len(chunk)
            ensure(written <= expected_bytes, f"source exceeds declared size: {source}")
            out.write(chunk)
    ensure(written == expected_bytes, f"source size drift for {source}: {written}")


def parse_duals(implications_js: bytes) -> list[list[int]]:
    match = DUALS_RE.search(implications_js)
    ensure(match is not None, "implications.js has no `var duals =` assignment")
    text = implications_js[match.end() :].decode("utf-8")
    value, _ = json.JSONDecoder().raw_decode(text.lstrip())
    ensure(isinstance(value, list), "duals assignment is not an array")
    pairs: list[list[int]] = []
    seen: set[int] = set()
    for pair in value:
        ensure(
            isinstance(pair, list)
            and len(pair) == 2
            and all(isinstance(item, int) for item in pair),
            "malformed dual pair",
        )
        left, right = pair
        ensure(left != right, f"self-dual equation listed explicitly: {left}")
        ensure(left not in seen and right not in seen, f"duplicate dual endpoint: {pair}")
        seen.update(pair)
        pairs.append([left, right])
    ensure(pairs == sorted(pairs), "duals array ordering drift")
    return pairs


def add_tar_bytes(archive: tarfile.TarFile, name: str, body: bytes) -> None:
    safe_member(name)
    ensure(len(body) <= MAX_MEMBER_BYTES, f"member exceeds cap: {name}")
    info = tarfile.TarInfo(name)
    info.size = len(body)
    info.mode = 0o644
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    archive.addfile(info, io.BytesIO(body))


def add_tar_path(archive: tarfile.TarFile, name: str, path: Path) -> None:
    safe_member(name)
    size = path.stat().st_size
    ensure(size <= MAX_MEMBER_BYTES, f"member exceeds cap: {name}")
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    with path.open("rb") as handle:
        archive.addfile(info, handle)


def write_archive(output: Path, members: dict[str, Path | bytes], metadata: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    ordered = {"snapshot-metadata.json": compact_json_bytes(metadata), **members}
    total = sum(len(value) if isinstance(value, bytes) else value.stat().st_size for value in ordered.values())
    ensure(total <= MAX_TOTAL_BYTES, f"archive content exceeds {MAX_TOTAL_BYTES} byte cap")
    temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|") as archive:
                    for name in sorted(ordered):
                        value = ordered[name]
                        if isinstance(value, bytes):
                            add_tar_bytes(archive, name, value)
                        else:
                            add_tar_path(archive, name, value)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args() -> argparse.Namespace:
    stage = Path(__file__).resolve().parent.parent
    repository = stage.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage80-raw",
        type=Path,
        default=repository / "reproduction/80-finite149/raw/finite149-source-snapshot.tar.gz",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="checkout root containing equational_theories/ at the pinned commit",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=stage / "raw/finite149-path-source-snapshot.tar.gz",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle, captured, bundle_sha = read_stage80_authority(args.stage80_raw.resolve())
    upstream = bundle["upstream"]
    official = bundle["official_sources"]
    missing = sorted(set(official) - captured)
    ensure(len(official) == 30 and len(captured) == 17 and len(missing) == 13, "path-source closure drift")
    ensure(set(missing) == MISSING_SOURCE_ALLOWLIST, "missing path-source allowlist drift")

    members: dict[str, Path | bytes] = {}
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="finite149-capture-") as temporary_name:
        temporary = Path(temporary_name)
        specs = {
            "finite_graph": "finite_graph.json",
            "implications_js": "implications.js",
            "full_entries": "full_entries.json",
        }
        for key in UPSTREAM_NAMES:
            filename = specs[key]
            destination = temporary / filename
            expected_bytes = int(upstream[f"{key}_bytes"])
            expected_sha = str(upstream[f"{key}_sha256"])
            url = str(upstream[f"{key}_url"])
            copy_url(url, destination, expected_bytes)
            ensure(sha256_path(destination) == expected_sha, f"download hash drift: {url}")
            archive_path = f"source/upstream/{filename}"
            members[archive_path] = destination
            rows.append(
                {
                    "archive_path": archive_path,
                    "bytes": expected_bytes,
                    "purpose": "graph-edge-replay" if key != "full_entries" else "identity-only",
                    "sha256": expected_sha,
                    "source_url": url,
                    "source_revision": (
                        upstream["github_main_commit_at_collection"]
                        if key == "full_entries"
                        else upstream["commit"]
                    ),
                }
            )

        license_path = temporary / "LICENSE"
        copy_url(str(LICENSE_SPEC["url"]), license_path, int(LICENSE_SPEC["bytes"]))
        ensure(sha256_path(license_path) == LICENSE_SPEC["sha256"], "upstream LICENSE hash drift")
        members["source/license/LICENSE"] = license_path
        rows.append(
            {
                "archive_path": "source/license/LICENSE",
                "bytes": LICENSE_SPEC["bytes"],
                "license": "Apache-2.0",
                "purpose": "license-text",
                "sha256": LICENSE_SPEC["sha256"],
                "source_revision": upstream["commit"],
                "source_url": LICENSE_SPEC["url"],
            }
        )

        show_proof_path = temporary / "show_proof.html"
        copy_url(
            str(SHOW_PROOF_SPEC["url"]),
            show_proof_path,
            int(SHOW_PROOF_SPEC["bytes"]),
        )
        ensure(
            sha256_path(show_proof_path) == SHOW_PROOF_SPEC["sha256"],
            "show_proof.html hash drift",
        )
        members["source/upstream/show_proof.html"] = show_proof_path
        rows.append(
            {
                "archive_path": "source/upstream/show_proof.html",
                "bytes": SHOW_PROOF_SPEC["bytes"],
                "purpose": "graph-construction-algorithm",
                "sha256": SHOW_PROOF_SPEC["sha256"],
                "source_revision": upstream["commit"],
                "source_url": SHOW_PROOF_SPEC["url"],
            }
        )

        implications = (temporary / "implications.js").read_bytes()
        duals_body = compact_json_bytes(parse_duals(implications))
        duals_path = "data/duals.json"
        members[duals_path] = duals_body
        rows.append(
            {
                "archive_path": duals_path,
                "bytes": len(duals_body),
                "derived_from": "source/upstream/implications.js",
                "purpose": "dual-mapping-replay",
                "sha256": hashlib.sha256(duals_body).hexdigest(),
            }
        )

        for relative in missing:
            spec = official[relative]
            source = resolve_local_source(args.source_root, relative)
            destination = temporary / "lean" / Path(PurePosixPath(relative))
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy_local(source, destination, int(spec["bytes"]))
            ensure(sha256_path(destination) == spec["sha256"], f"Lean source hash drift: {relative}")
            archive_path = f"source/path_sources/{relative}"
            members[archive_path] = destination
            rows.append(
                {
                    "archive_path": archive_path,
                    "bytes": int(spec["bytes"]),
                    "purpose": "path-source-closure",
                    "sha256": spec["sha256"],
                    "source_url": spec["url"],
                    "source_revision": upstream["commit"],
                }
            )

        rows.sort(key=lambda row: str(row["archive_path"]))
        metadata = {
            "captured_at": CAPTURED_AT,
            "limits": {
                "copy_chunk_bytes": CHUNK_BYTES,
                "max_member_bytes": MAX_MEMBER_BYTES,
                "max_total_uncompressed_bytes": MAX_TOTAL_BYTES,
            },
            "member_count_excluding_metadata": len(rows),
            "schema_version": "1.0.0",
            "source_files": rows,
            "license_notice": {
                "license": "Apache-2.0",
                "notice_file_present_upstream": False,
                "text_member": "source/license/LICENSE",
            },
            "source_revisions": {
                "finite_graph_and_implications_site_snapshot": upstream["commit"],
                "full_entries_github_snapshot": upstream["github_main_commit_at_collection"],
                "lean_path_sources": upstream["commit"],
            },
            "stage80_bundle_manifest_raw_sha256": bundle_sha,
        }
        write_archive(args.output.resolve(), members, metadata)

    print(
        json.dumps(
            {
                "archive": str(args.output.resolve()),
                "members": len(rows) + 1,
                "missing_lean_sources_captured": len(missing),
                "sha256": sha256_path(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
