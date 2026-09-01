#!/usr/bin/env python3
"""Shared, standard-library helpers for the Phase 1 bank reconstruction."""

from __future__ import annotations

import ast
import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator


CHUNK_SIZE = 1024 * 1024
SCHEMA_VERSION = "1.0.0"
TABLE_ENCODING = "uint8-order-row-major-v1"
HISTORICAL_ID_SCHEME = "sha256-compact-json-table-v1"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_table_bytes(order: int, entries: Iterable[int]) -> bytes:
    values = tuple(entries)
    if isinstance(order, bool) or not isinstance(order, int) or not 1 <= order <= 255:
        raise ValueError(f"invalid table order: {order!r}")
    if len(values) != order * order:
        raise ValueError(
            f"order {order} table has {len(values)} entries, expected {order * order}"
        )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("table entries must be integers")
    if any(value < 0 or value >= order for value in values):
        raise ValueError("table entry outside carrier")
    return bytes((order, *values))


def flatten_table(table: object) -> tuple[int, tuple[int, ...]]:
    if not isinstance(table, (list, tuple)) or not table:
        raise ValueError("table must be a nonempty list or tuple of rows")
    order = len(table)
    rows: list[tuple[int, ...]] = []
    for row in table:
        if not isinstance(row, (list, tuple)):
            raise ValueError("table row must be a list or tuple")
        rows.append(tuple(row))
    if any(len(row) != order for row in rows):
        raise ValueError("table must be square")
    entries = tuple(value for row in rows for value in row)
    canonical_table_bytes(order, entries)
    return order, entries


def nested_table(order: int, entries: Iterable[int]) -> list[list[int]]:
    values = tuple(entries)
    canonical_table_bytes(order, values)
    return [list(values[start : start + order]) for start in range(0, len(values), order)]


def canonical_table_id(order: int, entries: Iterable[int]) -> str:
    return "sha256:" + sha256_bytes(canonical_table_bytes(order, entries))


def historical_table_id(order: int, entries: Iterable[int]) -> str:
    compact = json.dumps(
        nested_table(order, entries),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256_bytes(compact)


def json_line(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


@contextmanager
def deterministic_gzip_writer(path: Path) -> Iterator[BinaryIO]:
    """Write gzip bytes with no filename or wall-clock timestamp."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
            ) as compressed:
                yield compressed
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_deterministic_tar_gz(
    source_root: Path, paths: Iterable[Path], output: Path
) -> tuple[int, int]:
    """Archive regular files in path order with normalized tar/gzip metadata."""

    source_root = source_root.resolve()
    candidates: dict[str, Path] = {}
    for original in paths:
        if original.is_symlink() or not original.is_file():
            raise ValueError(f"archive input is not a regular nonsymlink file: {original}")
        resolved = original.resolve()
        try:
            relative = resolved.relative_to(source_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"archive input escapes source root: {original}") from exc
        if relative in candidates:
            raise ValueError(f"duplicate archive input: {relative}")
        candidates[relative] = resolved
    ordered = [candidates[name] for name in sorted(candidates)]
    if not ordered:
        raise ValueError(f"refusing to create empty archive: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=output.name + ".", dir=output.parent
    )
    temporary = Path(temporary_name)
    source_bytes = 0
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w|", format=tarfile.GNU_FORMAT
                ) as archive:
                    for path in ordered:
                        try:
                            relative = path.relative_to(source_root).as_posix()
                        except ValueError as exc:
                            raise ValueError(f"archive input escapes source root: {path}") from exc
                        size = path.stat().st_size
                        info = tarfile.TarInfo(relative)
                        info.size = size
                        info.mode = 0o644
                        info.mtime = 0
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
                        source_bytes += size
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return len(ordered), source_bytes


def iter_archive_members(path: Path) -> Iterator[tuple[str, tarfile.TarInfo, BinaryIO]]:
    """Yield safe regular members from a tar.gz in one forward-only pass."""

    seen: set[str] = set()
    previous_name: str | None = None
    with tarfile.open(path, mode="r|gz") as archive:
        for member in archive:
            name = member.name
            parts = Path(name).parts
            if (
                not name
                or name.startswith("/")
                or ".." in parts
                or name in seen
                or not member.isfile()
            ):
                raise ValueError(f"unsafe or duplicate archive member in {path}: {name!r}")
            if previous_name is not None and name <= previous_name:
                raise ValueError(f"archive members are not strictly sorted in {path}: {name}")
            if (
                member.mtime != 0
                or member.uid != 0
                or member.gid != 0
                or member.mode != 0o644
            ):
                raise ValueError(f"noncanonical tar metadata in {path}: {name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"cannot read archive member in {path}: {name}")
            seen.add(name)
            previous_name = name
            yield name, member, extracted


def read_bounded(handle: BinaryIO, expected_size: int, *, limit: int) -> bytes:
    if expected_size > limit:
        raise ValueError(f"archive member exceeds {limit} byte bound")
    payload = handle.read(limit + 1)
    if len(payload) != expected_size:
        raise ValueError(
            f"archive member size mismatch: header={expected_size}, read={len(payload)}"
        )
    return payload


def literal_assignment(source: str, name: str) -> object:
    """Return one top-level literal assignment without executing source code."""

    tree = ast.parse(source)
    matches: list[ast.expr] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                matches.append(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                matches.append(node.value)
    if len(matches) != 1:
        raise ValueError(f"expected one literal assignment to {name}, found {len(matches)}")
    try:
        return ast.literal_eval(matches[0])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"assignment to {name} is not a literal") from exc


def extract_chunked_ascii_constant(source: str, name: str) -> bytes:
    """Extract NAME = (\n 'ascii chunks' \n) without importing the source."""

    chunks: list[str] = []
    active = False
    for line in io.StringIO(source):
        if not active:
            if line.startswith(f"{name} = ("):
                active = True
            continue
        if line.strip() == ")":
            break
        try:
            value = ast.literal_eval(line.strip())
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"invalid string chunk in {name}") from exc
        if not isinstance(value, str) or not value.isascii():
            raise ValueError(f"non-ASCII string chunk in {name}")
        chunks.append(value)
    if not active:
        raise ValueError(f"missing chunked constant {name}")
    return "".join(chunks).encode("ascii")


@contextmanager
def atomic_text_writer(path: Path) -> Iterator[io.TextIOWrapper]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            yield handle
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
