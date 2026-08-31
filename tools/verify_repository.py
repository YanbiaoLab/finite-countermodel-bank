#!/usr/bin/env python3
"""Verify committed reproduction metadata and immutable artifacts.

The verifier intentionally uses only the Python standard library and hashes files
in fixed-size chunks so that later large stages do not require loading whole files
into memory.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import gzip
import hashlib
import json
import re
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO
from urllib.parse import urlparse


SCHEMA_VERSION = "1.0.0"
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
STAGE_RE = re.compile(r"^[0-9]{2,3}-[a-z0-9-]+$")
CLAIM_RE = re.compile(r"^[a-z0-9_.-]+$")
ROLE_RE = re.compile(r"^[a-z0-9-]+$")
SUBMISSION_ID_RE = re.compile(r"^[a-z0-9-]+$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
CLAIM_STATUSES = {"planned", "captured", "reproduced", "verified", "blocked"}
STAGE_STATUSES = {"captured", "reproduced", "verified", "blocked"}
SOURCE_KINDS = {
    "authenticated-web-download",
    "local-filesystem-snapshot",
    "repository-snapshot",
    "generated",
    "third-party",
}
TRACKS = {"solo", "marathon"}
CHUNK_SIZE = 1024 * 1024
MAX_TEXT_LINE_CHARS = 1024 * 1024


class VerificationError(RuntimeError):
    """Raised when committed evidence violates the repository contract."""


def iter_bounded_text_lines(
    handle: TextIO, context: str, *, limit: int = MAX_TEXT_LINE_CHARS
) -> Iterator[str]:
    """Yield physical text lines without allowing an unbounded readline."""

    while True:
        line = handle.readline(limit + 1)
        if not line:
            return
        if len(line) > limit:
            raise VerificationError(f"text line exceeds {limit} characters in {context}")
        yield line


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_table_bytes(order: int, entries: Iterable[int]) -> bytes:
    values = list(entries)
    if isinstance(order, bool) or not isinstance(order, int) or not 1 <= order <= 255:
        raise VerificationError(
            f"table order {order!r} must be an integer in 1..255"
        )
    if len(values) != order * order:
        raise VerificationError(
            f"order {order} table has {len(values)} entries; expected {order * order}"
        )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise VerificationError(f"order {order} table contains a non-integer entry")
    if any(value < 0 or value >= order for value in values):
        raise VerificationError(f"order {order} table contains an out-of-range entry")
    return bytes([order, *values])


def canonical_table_id(order: int, entries: Iterable[int]) -> str:
    return "sha256:" + hashlib.sha256(canonical_table_bytes(order, entries)).hexdigest()


def historical_table_id(order: int, entries: Iterable[int]) -> str:
    values = list(entries)
    canonical_table_bytes(order, values)
    nested = [values[index : index + order] for index in range(0, len(values), order)]
    payload = json.dumps(
        nested, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"expected a JSON object in {path}")
    return value


def safe_stage_path(stage_dir: Path, relative: str) -> Path:
    rel = Path(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts:
        raise VerificationError(f"unsafe stage-relative path: {relative!r}")
    unresolved = stage_dir / rel
    if unresolved.is_symlink():
        raise VerificationError(f"artifact path must not be a symlink: {relative}")
    candidate = unresolved.resolve()
    root = stage_dir.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise VerificationError(f"path escapes stage directory: {relative!r}") from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise VerificationError(f"artifact is not a regular file: {relative}")
    return candidate


def require_fields(record: dict[str, Any], fields: Iterable[str], context: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise VerificationError(f"{context} is missing fields: {', '.join(missing)}")


def require_exact_fields(
    record: dict[str, Any],
    required: Iterable[str],
    optional: Iterable[str],
    context: str,
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    require_fields(record, required_set, context)
    extra = sorted(set(record) - allowed)
    if extra:
        raise VerificationError(f"{context} has unsupported fields: {', '.join(extra)}")


def require_nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise VerificationError(f"{context} must be a non-empty string")
    return value


def require_integer(value: Any, context: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise VerificationError(f"{context} must be an integer >= {minimum}")
    return value


def require_string_list(
    value: Any,
    context: str,
    *,
    minimum_items: int = 0,
    pattern: re.Pattern[str] | None = None,
    unique: bool = False,
) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum_items:
        raise VerificationError(
            f"{context} must be a list with at least {minimum_items} item(s)"
        )
    if any(not isinstance(item, str) for item in value):
        raise VerificationError(f"{context} must contain only strings")
    if pattern is not None and any(not pattern.fullmatch(item) for item in value):
        raise VerificationError(f"{context} contains an invalid identifier")
    if unique and len(set(value)) != len(value):
        raise VerificationError(f"{context} must not contain duplicates")
    return value


def require_datetime(value: Any, context: str) -> str:
    text = require_nonempty_string(value, context)
    if not DATETIME_RE.fullmatch(text):
        raise VerificationError(f"{context} is not an RFC 3339 date-time with timezone")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError(f"{context} is not a valid date-time") from exc
    if parsed.utcoffset() is None:
        raise VerificationError(f"{context} must include a timezone")
    return text


def require_http_url(value: Any, context: str) -> str:
    text = require_nonempty_string(value, context)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise VerificationError(f"{context} must be an absolute HTTP(S) URL")
    return text


def validate_stage_manifest_structure(manifest: dict[str, Any], context: str) -> None:
    required = [
        "$schema",
        "schema_version",
        "stage_id",
        "title",
        "pipeline_order",
        "status",
        "captured_at",
        "depends_on",
        "claims",
        "sources",
        "artifacts",
        "verification",
    ]
    require_exact_fields(manifest, required, ["notes"], context)
    if manifest["$schema"] != "../../schemas/stage-manifest.schema.json":
        raise VerificationError(f"unexpected $schema reference in {context}")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise VerificationError(f"unsupported stage schema in {context}")
    if not isinstance(manifest["stage_id"], str) or not STAGE_RE.fullmatch(
        manifest["stage_id"]
    ):
        raise VerificationError(f"invalid stage_id in {context}")
    require_nonempty_string(manifest["title"], f"{context}.title")
    require_integer(manifest["pipeline_order"], f"{context}.pipeline_order")
    if manifest["status"] not in STAGE_STATUSES:
        raise VerificationError(f"invalid stage status in {context}")
    require_datetime(manifest["captured_at"], f"{context}.captured_at")
    require_string_list(
        manifest["depends_on"],
        f"{context}.depends_on",
        pattern=STAGE_RE,
        unique=True,
    )
    require_string_list(
        manifest["claims"],
        f"{context}.claims",
        pattern=CLAIM_RE,
        unique=True,
    )
    if "notes" in manifest:
        require_string_list(manifest["notes"], f"{context}.notes")

    sources = manifest["sources"]
    if not isinstance(sources, list) or not sources:
        raise VerificationError(f"{context}.sources must be a non-empty list")
    for index, source in enumerate(sources):
        source_context = f"{context}.sources[{index}]"
        if not isinstance(source, dict):
            raise VerificationError(f"{source_context} must be an object")
        require_exact_fields(
            source,
            ["source_id", "kind", "locator", "captured_at", "license_status"],
            ["revision", "notes"],
            source_context,
        )
        source_id = require_nonempty_string(source["source_id"], f"{source_context}.source_id")
        if not CLAIM_RE.fullmatch(source_id):
            raise VerificationError(f"invalid source_id in {source_context}")
        if source["kind"] not in SOURCE_KINDS:
            raise VerificationError(f"invalid source kind in {source_context}")
        require_nonempty_string(source["locator"], f"{source_context}.locator")
        require_datetime(source["captured_at"], f"{source_context}.captured_at")
        require_nonempty_string(
            source["license_status"], f"{source_context}.license_status"
        )
        if "revision" in source and not isinstance(source["revision"], str):
            raise VerificationError(f"{source_context}.revision must be a string")
        if "notes" in source:
            require_string_list(source["notes"], f"{source_context}.notes")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise VerificationError(f"{context}.artifacts must be a non-empty list")
    for index, artifact in enumerate(artifacts):
        artifact_context = f"{context}.artifacts[{index}]"
        if not isinstance(artifact, dict):
            raise VerificationError(f"{artifact_context} must be an object")
        require_exact_fields(
            artifact,
            ["path", "role", "media_type", "bytes", "sha256", "source_ids"],
            ["record_count", "attributes"],
            artifact_context,
        )
        require_nonempty_string(artifact["path"], f"{artifact_context}.path")
        role = require_nonempty_string(artifact["role"], f"{artifact_context}.role")
        if not ROLE_RE.fullmatch(role):
            raise VerificationError(f"invalid role in {artifact_context}")
        require_nonempty_string(artifact["media_type"], f"{artifact_context}.media_type")
        require_integer(artifact["bytes"], f"{artifact_context}.bytes")
        if not isinstance(artifact["sha256"], str) or not HASH_RE.fullmatch(
            artifact["sha256"]
        ):
            raise VerificationError(f"invalid SHA-256 in {artifact_context}")
        require_string_list(
            artifact["source_ids"],
            f"{artifact_context}.source_ids",
            minimum_items=1,
            pattern=CLAIM_RE,
            unique=True,
        )
        if "record_count" in artifact:
            require_integer(
                artifact["record_count"], f"{artifact_context}.record_count"
            )
        if "attributes" in artifact and not isinstance(artifact["attributes"], dict):
            raise VerificationError(f"{artifact_context}.attributes must be an object")

    verification = manifest["verification"]
    if not isinstance(verification, dict):
        raise VerificationError(f"{context}.verification must be an object")
    require_exact_fields(
        verification,
        ["checksum_file", "command"],
        ["notes"],
        f"{context}.verification",
    )
    require_nonempty_string(
        verification["checksum_file"], f"{context}.verification.checksum_file"
    )
    require_nonempty_string(
        verification["command"], f"{context}.verification.command"
    )
    if "notes" in verification:
        require_string_list(
            verification["notes"], f"{context}.verification.notes"
        )


def validate_submission_record(record: dict[str, Any], context: str) -> None:
    require_exact_fields(
        record,
        [
            "schema_version",
            "submission_id",
            "competition",
            "track",
            "model",
            "submitted_at_display",
            "display_timezone_context",
            "source_url",
            "captured_at",
            "reported_size_bytes",
            "artifact",
        ],
        [],
        context,
    )
    if record["schema_version"] != SCHEMA_VERSION:
        raise VerificationError(f"unsupported submission schema in {context}")
    if not isinstance(record["submission_id"], str) or not SUBMISSION_ID_RE.fullmatch(
        record["submission_id"]
    ):
        raise VerificationError(f"invalid submission_id in {context}")
    require_nonempty_string(record["competition"], f"{context}.competition")
    if record["track"] not in TRACKS:
        raise VerificationError(f"invalid track in {context}")
    model = record["model"]
    if not isinstance(model, dict):
        raise VerificationError(f"{context}.model must be an object")
    require_exact_fields(model, ["provider", "name"], [], f"{context}.model")
    require_nonempty_string(model["provider"], f"{context}.model.provider")
    require_nonempty_string(model["name"], f"{context}.model.name")
    require_nonempty_string(
        record["submitted_at_display"], f"{context}.submitted_at_display"
    )
    require_nonempty_string(
        record["display_timezone_context"], f"{context}.display_timezone_context"
    )
    require_http_url(record["source_url"], f"{context}.source_url")
    require_datetime(record["captured_at"], f"{context}.captured_at")
    require_integer(record["reported_size_bytes"], f"{context}.reported_size_bytes")
    artifact = record["artifact"]
    if not isinstance(artifact, dict):
        raise VerificationError(f"{context}.artifact must be an object")
    require_exact_fields(
        artifact, ["path", "bytes", "sha256"], [], f"{context}.artifact"
    )
    require_nonempty_string(artifact["path"], f"{context}.artifact.path")
    require_integer(artifact["bytes"], f"{context}.artifact.bytes")
    if not isinstance(artifact["sha256"], str) or not HASH_RE.fullmatch(
        artifact["sha256"]
    ):
        raise VerificationError(f"invalid artifact SHA-256 in {context}")


def parse_checksums(path: Path, stage_dir: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(
            iter_bounded_text_lines(handle, str(path)), start=1
        ):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
            if not match:
                raise VerificationError(f"invalid checksum line {path}:{line_number}")
            digest, relative = match.groups()
            safe_stage_path(stage_dir, relative)
            if relative in entries:
                raise VerificationError(f"duplicate checksum path in {path}: {relative}")
            entries[relative] = digest
    return entries


def verify_submission_index(
    stage_dir: Path,
    index_artifact: dict[str, Any],
    artifact_by_path: dict[str, dict[str, Any]],
    source_locators: set[str],
) -> dict[str, Any]:
    index_path = safe_stage_path(stage_dir, index_artifact["path"])
    seen_ids: set[str] = set()
    referenced_paths: set[str] = set()
    participation_keys: set[tuple[str, str, str]] = set()
    digests: set[str] = set()
    track_sizes: dict[str, set[int]] = {track: set() for track in TRACKS}
    count = 0

    with index_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(
            iter_bounded_text_lines(handle, str(index_path)), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise VerificationError(
                    f"invalid JSONL record {index_path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise VerificationError(f"non-object record {index_path}:{line_number}")
            record_context = f"submission record {line_number}"
            validate_submission_record(record, record_context)
            if record["source_url"] not in source_locators:
                raise VerificationError(
                    f"submission source URL is not declared by the stage at line {line_number}"
                )
            submission_id = record["submission_id"]
            if submission_id in seen_ids:
                raise VerificationError(f"duplicate submission_id: {submission_id}")
            seen_ids.add(submission_id)

            artifact_ref = record["artifact"]
            relative = artifact_ref["path"]
            manifest_artifact = artifact_by_path.get(relative)
            if manifest_artifact is None or manifest_artifact["role"] != "submitted-solver":
                raise VerificationError(
                    f"unmanifested submitted solver at line {line_number}: {relative}"
                )
            if artifact_ref["bytes"] != manifest_artifact["bytes"]:
                raise VerificationError(f"size mismatch in submission index for {relative}")
            if artifact_ref["sha256"] != manifest_artifact["sha256"]:
                raise VerificationError(f"hash mismatch in submission index for {relative}")
            if record.get("reported_size_bytes") != manifest_artifact["bytes"]:
                raise VerificationError(f"reported size mismatch for {relative}")
            if relative in referenced_paths:
                raise VerificationError(
                    f"submitted solver is referenced more than once: {relative}"
                )
            attributes = manifest_artifact.get("attributes", {})
            model = record.get("model")
            if (
                record.get("track") != attributes.get("track")
                or model.get("provider") != attributes.get("model_provider")
                or model.get("name") != attributes.get("model_name")
                or record.get("submitted_at_display")
                != attributes.get("submitted_at_display")
            ):
                raise VerificationError(
                    f"submission metadata disagrees with manifest for {relative}"
                )
            participation_key = (
                record["track"],
                model["provider"],
                model["name"],
            )
            if participation_key in participation_keys:
                raise VerificationError(
                    f"duplicate track/model participation at line {line_number}"
                )
            participation_keys.add(participation_key)
            digests.add(artifact_ref["sha256"])
            track_sizes[record["track"]].add(artifact_ref["bytes"])
            referenced_paths.add(relative)
            count += 1

    declared_count = index_artifact.get("record_count")
    if declared_count != count:
        raise VerificationError(
            f"submission index has {count} records; manifest declares {declared_count}"
        )
    solver_paths = {
        path
        for path, artifact in artifact_by_path.items()
        if artifact["role"] == "submitted-solver"
    }
    if referenced_paths != solver_paths:
        raise VerificationError(
            "submission index does not reference every submitted solver exactly once"
        )
    return {
        "participations": count,
        "unique_blobs": len(digests),
        "track_sizes": track_sizes,
    }


def validate_table_record(record: dict[str, Any], context: str) -> bytes:
    require_exact_fields(
        record,
        [
            "schema_version",
            "table_id",
            "encoding",
            "order",
            "entries",
            "first_seen_stage",
            "record_kind",
            "provenance",
        ],
        ["identifiers", "verification", "notes"],
        context,
    )
    if record["schema_version"] != SCHEMA_VERSION:
        raise VerificationError(f"unsupported table schema in {context}")
    if record["encoding"] != "uint8-order-row-major-v1":
        raise VerificationError(f"unexpected table encoding in {context}")
    order = require_integer(record["order"], f"{context}.order", minimum=1)
    if order > 255:
        raise VerificationError(f"{context}.order exceeds 255")
    entries = record["entries"]
    if not isinstance(entries, list):
        raise VerificationError(f"{context}.entries must be a list")
    encoded = canonical_table_bytes(order, entries)
    expected_id = "sha256:" + hashlib.sha256(encoded).hexdigest()
    if record["table_id"] != expected_id:
        raise VerificationError(f"canonical table_id mismatch in {context}")
    if not isinstance(record["first_seen_stage"], str) or not STAGE_RE.fullmatch(
        record["first_seen_stage"]
    ):
        raise VerificationError(f"invalid first_seen_stage in {context}")
    if record["record_kind"] not in {
        "exact-explicit",
        "derived-transpose",
        "verified-substitute",
    }:
        raise VerificationError(f"invalid record_kind in {context}")

    provenance = record["provenance"]
    if not isinstance(provenance, list) or not provenance:
        raise VerificationError(f"{context}.provenance must be nonempty")
    for index, source in enumerate(provenance):
        source_context = f"{context}.provenance[{index}]"
        if not isinstance(source, dict):
            raise VerificationError(f"{source_context} must be an object")
        require_exact_fields(
            source,
            ["source_id", "source_path"],
            ["source_record", "notes"],
            source_context,
        )
        source_id = require_nonempty_string(source["source_id"], f"{source_context}.source_id")
        if not CLAIM_RE.fullmatch(source_id):
            raise VerificationError(f"invalid source_id in {source_context}")
        require_nonempty_string(source["source_path"], f"{source_context}.source_path")
        if "source_record" in source and not isinstance(
            source["source_record"], (str, int)
        ):
            raise VerificationError(f"invalid source_record in {source_context}")
        if "notes" in source and not isinstance(source["notes"], str):
            raise VerificationError(f"invalid notes in {source_context}")

    identifiers = record.get("identifiers", [])
    if not isinstance(identifiers, list):
        raise VerificationError(f"{context}.identifiers must be a list")
    seen_schemes: set[str] = set()
    for index, identifier in enumerate(identifiers):
        identifier_context = f"{context}.identifiers[{index}]"
        if not isinstance(identifier, dict):
            raise VerificationError(f"{identifier_context} must be an object")
        require_exact_fields(identifier, ["scheme", "value"], [], identifier_context)
        if identifier["scheme"] != "sha256-compact-json-table-v1":
            raise VerificationError(f"unsupported identifier scheme in {identifier_context}")
        if identifier["scheme"] in seen_schemes:
            raise VerificationError(f"duplicate identifier scheme in {context}")
        seen_schemes.add(identifier["scheme"])
        expected_alias = historical_table_id(order, entries)
        if identifier["value"] != expected_alias:
            raise VerificationError(f"historical table alias mismatch in {context}")

    verification = record.get("verification")
    if verification is not None:
        if not isinstance(verification, dict):
            raise VerificationError(f"{context}.verification must be an object")
        require_exact_fields(
            verification,
            [],
            ["shape_checked", "entry_range_checked", "task_check_paths"],
            f"{context}.verification",
        )
        for field in ("shape_checked", "entry_range_checked"):
            if field in verification and not isinstance(verification[field], bool):
                raise VerificationError(f"{context}.verification.{field} must be boolean")
        if "task_check_paths" in verification:
            require_string_list(
                verification["task_check_paths"],
                f"{context}.verification.task_check_paths",
            )
    if "notes" in record:
        require_string_list(record["notes"], f"{context}.notes")
    return encoded


def validate_delta_record(record: dict[str, Any], context: str) -> None:
    require_exact_fields(
        record,
        [
            "schema_version",
            "stage_id",
            "sequence",
            "action",
            "table_id",
            "reason_code",
            "evidence_paths",
        ],
        ["source_stage_id", "source_table_id", "notes"],
        context,
    )
    if record["schema_version"] != SCHEMA_VERSION:
        raise VerificationError(f"unsupported delta schema in {context}")
    if not isinstance(record["stage_id"], str) or not STAGE_RE.fullmatch(record["stage_id"]):
        raise VerificationError(f"invalid delta stage_id in {context}")
    require_integer(record["sequence"], f"{context}.sequence")
    if record["action"] not in {"add", "duplicate", "retain", "remove", "replace", "derive"}:
        raise VerificationError(f"invalid delta action in {context}")
    if not isinstance(record["table_id"], str) or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", record["table_id"]
    ):
        raise VerificationError(f"invalid delta table_id in {context}")
    if not isinstance(record["reason_code"], str) or not CLAIM_RE.fullmatch(
        record["reason_code"]
    ):
        raise VerificationError(f"invalid reason_code in {context}")
    require_string_list(record["evidence_paths"], f"{context}.evidence_paths", minimum_items=1)
    if "source_stage_id" in record:
        if not isinstance(record["source_stage_id"], str) or not STAGE_RE.fullmatch(
            record["source_stage_id"]
        ):
            raise VerificationError(f"invalid source_stage_id in {context}")
    if "source_table_id" in record:
        if not isinstance(record["source_table_id"], str) or not re.fullmatch(
            r"sha256:[a-f0-9]{64}", record["source_table_id"]
        ):
            raise VerificationError(f"invalid source_table_id in {context}")
    if ("source_stage_id" in record) != ("source_table_id" in record):
        raise VerificationError(f"source stage/table fields must occur together in {context}")
    if "notes" in record and not isinstance(record["notes"], str):
        raise VerificationError(f"delta notes must be a string in {context}")


def open_text_artifact(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def count_nonempty_lines(path: Path) -> int:
    count = 0
    with open_text_artifact(path) as handle:
        for line in iter_bounded_text_lines(handle, str(path)):
            if line.strip():
                count += 1
    return count


def verify_raw_snapshot(path: Path, declared_count: int) -> None:
    count = 0
    seen: set[str] = set()
    previous_name: str | None = None
    try:
        with tarfile.open(path, mode="r|gz") as archive:
            for member in archive:
                name = member.name
                if (
                    not name
                    or name.startswith("/")
                    or ".." in Path(name).parts
                    or name in seen
                    or not member.isfile()
                ):
                    raise VerificationError(f"unsafe raw archive member: {path}#{name}")
                if previous_name is not None and name <= previous_name:
                    raise VerificationError(
                        f"raw archive members are not strictly sorted: {path}#{name}"
                    )
                if (
                    member.mtime != 0
                    or member.uid != 0
                    or member.gid != 0
                    or member.mode != 0o644
                ):
                    raise VerificationError(f"noncanonical raw archive metadata: {path}#{name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise VerificationError(f"cannot read raw archive member: {path}#{name}")
                remaining = member.size
                while remaining:
                    chunk = extracted.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise VerificationError(f"truncated raw archive member: {path}#{name}")
                    remaining -= len(chunk)
                if extracted.read(1):
                    raise VerificationError(f"oversized raw archive member: {path}#{name}")
                seen.add(name)
                previous_name = name
                count += 1
    except (tarfile.TarError, OSError) as exc:
        raise VerificationError(f"cannot read raw snapshot {path}: {exc}") from exc
    if count != declared_count:
        raise VerificationError(
            f"raw snapshot has {count} members; manifest declares {declared_count}"
        )


def normalized_equation_text(text: str) -> str:
    return "".join(text.replace("◇", "*").split())


def load_official_equations(root: Path, wanted_ids: set[int]) -> dict[int, str]:
    stage10_dir = root / "reproduction" / "10-primary-9450"
    manifest = load_json(stage10_dir / "stage.json")
    candidates = [
        artifact
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
        and artifact.get("path") == "raw/primary-recovery-snapshot.tar.gz"
    ]
    if len(candidates) != 1:
        raise VerificationError("Stage10 manifest lacks a unique equation snapshot")
    declared = candidates[0]
    archive_path = safe_stage_path(stage10_dir, declared["path"])
    if (
        archive_path.stat().st_size != declared.get("bytes")
        or sha256_file(archive_path) != declared.get("sha256")
    ):
        raise VerificationError("Stage10 equation snapshot disagrees with its manifest")
    found: dict[int, str] = {}
    member_count = 0
    row_count = 0
    try:
        with tarfile.open(archive_path, mode="r|gz") as archive:
            for member in archive:
                if not member.name.endswith("/order5_equations.csv"):
                    continue
                member_count += 1
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise VerificationError(
                        f"cannot read official equation index: {archive_path}#{member.name}"
                    )
                text = codecs.getreader("utf-8")(extracted)
                reader = csv.DictReader(
                    iter_bounded_text_lines(text, f"{archive_path}#{member.name}")
                )
                expected_header = [
                    "equation_id",
                    "equation_text",
                    "variable_count",
                    "lhs_operation_count",
                    "rhs_operation_count",
                    "total_operation_count",
                ]
                if reader.fieldnames != expected_header:
                    raise VerificationError("official equation index header drift")
                for row_count, row in enumerate(reader, start=1):
                    equation_id = int(row["equation_id"])
                    if equation_id != row_count:
                        raise VerificationError(
                            "official equation IDs are not contiguous"
                        )
                    if equation_id in wanted_ids:
                        found[equation_id] = row["equation_text"]
    except (OSError, tarfile.TarError, UnicodeError, ValueError, csv.Error) as exc:
        raise VerificationError(f"cannot read official equation snapshot: {exc}") from exc
    if member_count != 1 or row_count != 62_576:
        raise VerificationError(
            f"official equation index shape drift: members={member_count}, rows={row_count}"
        )
    if set(found) != wanted_ids:
        raise VerificationError("task evidence references an unknown official equation ID")
    return found


def verify_task_evidence(stage_dir: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    path = safe_stage_path(stage_dir, artifact["path"])
    rows: list[dict[str, Any]] = []
    references: list[tuple[int, str, str]] = []
    problem_ids: set[str] = set()
    directions: set[tuple[int, int]] = set()
    table_ids: set[str] = set()
    with open_text_artifact(path) as handle:
        for line_number, raw_line in enumerate(
            iter_bounded_text_lines(handle, str(path)), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise VerificationError(
                    f"invalid task evidence {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise VerificationError(f"non-object task evidence {path}:{line_number}")
            problem_id = row.get("problem_id")
            table_id = row.get("table_id")
            if not isinstance(problem_id, str) or not problem_id:
                raise VerificationError(f"invalid problem ID at {path}:{line_number}")
            if not isinstance(table_id, str) or not re.fullmatch(
                r"sha256:[a-f0-9]{64}", table_id
            ):
                raise VerificationError(f"invalid table ID at {path}:{line_number}")
            problem_ids.add(problem_id)
            table_ids.add(table_id)
            for side in ("source", "target"):
                equation_id = row.get(f"{side}_equation_id")
                formula = row.get(f"{side}_formula")
                if (
                    isinstance(equation_id, bool)
                    or not isinstance(equation_id, int)
                    or not 1 <= equation_id <= 62_576
                    or not isinstance(formula, str)
                    or not formula
                    or row.get(f"official_{side}_formula_match") is not True
                ):
                    raise VerificationError(
                        f"invalid official equation reference at {path}:{line_number}"
                    )
                references.append((equation_id, formula, side))
            directions.add((row["source_equation_id"], row["target_equation_id"]))
            rows.append(row)
    if artifact.get("record_count") != len(rows):
        raise VerificationError(f"task evidence record_count drift in {stage_dir.name}")
    wanted_ids = {equation_id for equation_id, _formula, _side in references}
    official = load_official_equations(stage_dir.parents[1], wanted_ids)
    mismatches = [
        (equation_id, side)
        for equation_id, formula, side in references
        if normalized_equation_text(formula)
        != normalized_equation_text(official[equation_id])
    ]
    if mismatches:
        raise VerificationError(
            f"task formulas disagree with official equation IDs: {mismatches[:5]}"
        )
    if len(references) != 204 or len(wanted_ids) != 195:
        raise VerificationError(
            "unexpected delivery equation-reference cardinality: "
            f"references={len(references)}, distinct={len(wanted_ids)}"
        )
    if len(problem_ids) != 102 or len(directions) != 102 or len(table_ids) != 102:
        raise VerificationError(
            "delivery task identities are not unique: "
            f"problems={len(problem_ids)}, directions={len(directions)}, "
            f"tables={len(table_ids)}"
        )
    return {
        "official_equation_mapping": {
            "reference_count": len(references),
            "distinct_equation_count": len(wanted_ids),
            "mismatch_count": 0,
            "normalization": "diamond-to-asterisk-and-remove-whitespace",
        },
        "table_ids": [row["table_id"] for row in rows],
    }


def verify_table_index(
    stage_dir: Path,
    index_artifact: dict[str, Any],
    binary_artifact: dict[str, Any],
) -> dict[str, Any]:
    index_path = safe_stage_path(stage_dir, index_artifact["path"])
    binary_path = safe_stage_path(stage_dir, binary_artifact["path"])
    table_ids: list[str] = []
    table_set: set[str] = set()
    historical_ids: list[str] = []
    first_seen: dict[str, str] = {}
    provenance_source_ids: set[str] = set()
    order_counts: dict[str, int] = {}
    raw_digest = hashlib.sha256()
    raw_bytes = 0
    with open_text_artifact(index_path) as index_handle, binary_path.open("rb") as binary:
        for line_number, raw_line in enumerate(
            iter_bounded_text_lines(index_handle, str(index_path)), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise VerificationError(
                    f"invalid table JSONL {index_path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise VerificationError(f"non-object table record {index_path}:{line_number}")
            encoded = validate_table_record(record, f"{index_path}:{line_number}")
            table_id = record["table_id"]
            if table_id in table_set:
                raise VerificationError(f"duplicate canonical table_id in {index_path}: {table_id}")
            table_set.add(table_id)
            table_ids.append(table_id)
            first_seen[table_id] = record["first_seen_stage"]
            provenance_source_ids.update(
                source["source_id"] for source in record["provenance"]
            )
            aliases = record.get("identifiers", [])
            historical = next(
                (
                    item["value"]
                    for item in aliases
                    if item["scheme"] == "sha256-compact-json-table-v1"
                ),
                None,
            )
            if historical is None:
                raise VerificationError(f"PR 1 table lacks historical alias: {index_path}:{line_number}")
            historical_ids.append(historical)
            order_key = str(record["order"])
            order_counts[order_key] = order_counts.get(order_key, 0) + 1
            actual = binary.read(len(encoded))
            if actual != encoded:
                raise VerificationError(
                    f"table binary disagrees with JSONL at record {len(table_ids) - 1}"
                )
            raw_digest.update(encoded)
            raw_bytes += len(encoded)
        if binary.read(1):
            raise VerificationError(f"table binary has trailing bytes: {binary_path}")
    declared = index_artifact.get("record_count")
    if declared != len(table_ids) or binary_artifact.get("record_count") != len(table_ids):
        raise VerificationError(f"table artifact record_count drift in {stage_dir.name}")
    return {
        "ids": table_ids,
        "id_set": table_set,
        "historical_ids": historical_ids,
        "first_seen": first_seen,
        "provenance_source_ids": provenance_source_ids,
        "count": len(table_ids),
        "raw_bytes": raw_bytes,
        "raw_sha256": raw_digest.hexdigest(),
        "canonical_id_vector_sha256": hashlib.sha256(
            "".join(f"{value.removeprefix('sha256:')}\n" for value in table_ids).encode("ascii")
        ).hexdigest(),
        "historical_id_vector_sha256": hashlib.sha256(
            "".join(f"{value.removeprefix('sha256:')}\n" for value in historical_ids).encode("ascii")
        ).hexdigest(),
        "order_distribution": {
            key: order_counts[key] for key in sorted(order_counts, key=int)
        },
    }


def verify_delta_index(stage_dir: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    path = safe_stage_path(stage_dir, artifact["path"])
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    with open_text_artifact(path) as handle:
        for line_number, raw_line in enumerate(
            iter_bounded_text_lines(handle, str(path)), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise VerificationError(f"invalid delta JSONL {path}:{line_number}: {exc}") from exc
            if not isinstance(record, dict):
                raise VerificationError(f"non-object delta record {path}:{line_number}")
            validate_delta_record(record, f"{path}:{line_number}")
            if record["stage_id"] != stage_dir.name:
                raise VerificationError(f"delta stage mismatch at {path}:{line_number}")
            if record["sequence"] != len(rows):
                raise VerificationError(f"noncontiguous delta sequence at {path}:{line_number}")
            rows.append(record)
            counts[record["action"]] = counts.get(record["action"], 0) + 1
    if artifact.get("record_count") != len(rows):
        raise VerificationError(f"delta record_count drift in {stage_dir.name}")
    return {"rows": rows, "action_counts": counts}


def verify_stage_summary(
    stage_dir: Path,
    artifact: dict[str, Any],
    manifest_claims: set[str],
    claims_by_id: dict[str, dict[str, str]],
    bank: dict[str, Any] | None,
    delta: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = load_json(safe_stage_path(stage_dir, artifact["path"]))
    require_fields(
        summary,
        ["schema_version", "stage_id", "metrics", "action_counts", "bank"],
        f"summary in {stage_dir.name}",
    )
    if summary["schema_version"] != SCHEMA_VERSION or summary["stage_id"] != stage_dir.name:
        raise VerificationError(f"summary identity drift in {stage_dir.name}")
    metrics = summary["metrics"]
    if not isinstance(metrics, dict) or set(metrics) != manifest_claims:
        raise VerificationError(f"summary metrics do not match manifest claims in {stage_dir.name}")
    for claim_id, actual in metrics.items():
        if isinstance(actual, bool) or not isinstance(actual, int):
            raise VerificationError(f"summary metric is not integer: {claim_id}")
        expected = claim_expected_integer(claims_by_id, claim_id, stage_dir.name)
        if actual != expected:
            raise VerificationError(f"claim {claim_id} says {expected}; summary computed {actual}")
    if bank is not None:
        bank_summary = summary["bank"]
        if not isinstance(bank_summary, dict):
            raise VerificationError(f"summary bank must be an object in {stage_dir.name}")
        for field in (
            "table_count",
            "raw_bytes",
            "raw_sha256",
            "canonical_id_vector_sha256",
            "historical_id_vector_sha256",
            "order_distribution",
        ):
            if bank_summary.get(field) != bank[field if field != "table_count" else "count"]:
                raise VerificationError(f"summary bank.{field} drift in {stage_dir.name}")
    if delta is not None and summary["action_counts"] != delta["action_counts"]:
        raise VerificationError(f"summary action counts drift in {stage_dir.name}")
    return summary


def verify_identity_map(
    stage_dir: Path, artifact: dict[str, Any], bank: dict[str, Any]
) -> None:
    path = safe_stage_path(stage_dir, artifact["path"])
    with open_text_artifact(path) as handle:
        reader = csv.DictReader(iter_bounded_text_lines(handle, str(path)))
        if reader.fieldnames != [
            "position",
            "table_id",
            "historical_json_table_id",
            "first_seen_stage",
        ]:
            raise VerificationError(f"identity-map header drift in {stage_dir.name}")
        count = 0
        for count, row in enumerate(reader, start=1):
            position = count - 1
            if int(row["position"]) != position:
                raise VerificationError(f"identity-map position drift at {path}:{count + 1}")
            if row["table_id"] != bank["ids"][position]:
                raise VerificationError(f"identity-map canonical ID drift at {path}:{count + 1}")
            if row["historical_json_table_id"] != bank["historical_ids"][position]:
                raise VerificationError(f"identity-map historical ID drift at {path}:{count + 1}")
            if row["first_seen_stage"] != bank["first_seen"][row["table_id"]]:
                raise VerificationError(
                    f"identity-map first_seen_stage drift at {path}:{count + 1}"
                )
    if count != bank["count"] or artifact.get("record_count") != count:
        raise VerificationError(f"identity-map count drift in {stage_dir.name}")


def table_binary_ids(path: Path) -> list[str]:
    table_ids: list[str] = []
    with path.open("rb") as handle:
        while True:
            first = handle.read(1)
            if not first:
                break
            order = first[0]
            if order == 0:
                raise VerificationError(f"zero-order table in {path}")
            entries = handle.read(order * order)
            if len(entries) != order * order:
                raise VerificationError(f"truncated table binary in {path}")
            if any(value >= order for value in entries):
                raise VerificationError(f"out-of-range table entry in {path}")
            table_ids.append("sha256:" + hashlib.sha256(first + entries).hexdigest())
    return table_ids


def count_table_binary(path: Path) -> int:
    return len(table_binary_ids(path))


def claim_expected_integer(
    claims_by_id: dict[str, dict[str, str]],
    claim_id: str,
    stage_id: str,
) -> int:
    claim = claims_by_id.get(claim_id)
    if claim is None or claim["stage_id"] != stage_id:
        raise VerificationError(f"missing or misrouted claim: {claim_id}")
    if claim["status"] == "planned":
        raise VerificationError(f"captured stage still has a planned claim: {claim_id}")
    try:
        return int(claim["expected_value"])
    except ValueError as exc:
        raise VerificationError(f"claim is not an integer: {claim_id}") from exc


def verify_submission_claims(
    stage_id: str,
    manifest_claims: set[str],
    claims_by_id: dict[str, dict[str, str]],
    summary: dict[str, Any],
) -> None:
    actual = {
        "submission.participations": summary["participations"],
        "submission.unique_blobs": summary["unique_blobs"],
    }
    for track, claim_id in (
        ("solo", "submission.solo_bytes"),
        ("marathon", "submission.marathon_bytes"),
    ):
        sizes = summary["track_sizes"][track]
        if len(sizes) != 1:
            raise VerificationError(
                f"submission anchor must have one consistent {track} byte size"
            )
        actual[claim_id] = next(iter(sizes))

    if not set(actual).issubset(manifest_claims):
        raise VerificationError("submission anchor manifest omits a computed claim")
    for claim_id, actual_value in actual.items():
        expected_value = claim_expected_integer(claims_by_id, claim_id, stage_id)
        if expected_value != actual_value:
            raise VerificationError(
                f"claim {claim_id} says {expected_value}; computed {actual_value}"
            )


def verify_stage(
    stage_dir: Path, claims_by_id: dict[str, dict[str, str]]
) -> tuple[int, int, set[str], dict[str, Any]]:
    manifest_path = stage_dir / "stage.json"
    manifest = load_json(manifest_path)
    validate_stage_manifest_structure(manifest, str(manifest_path))
    if manifest["stage_id"] != stage_dir.name or not STAGE_RE.fullmatch(stage_dir.name):
        raise VerificationError(f"stage_id does not match directory: {stage_dir}")

    manifest_claims = set(manifest["claims"])
    for claim_id in manifest_claims:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            raise VerificationError(f"manifest references unknown claim: {claim_id}")
        if claim["stage_id"] != stage_dir.name:
            raise VerificationError(
                f"manifest claim {claim_id} belongs to {claim['stage_id']}"
            )

    sources = manifest["sources"]
    if not isinstance(sources, list) or not sources:
        raise VerificationError(f"stage must declare at least one source: {stage_dir.name}")
    source_ids = {
        source.get("source_id") for source in sources if isinstance(source, dict)
    }
    if None in source_ids or len(source_ids) != len(sources):
        raise VerificationError(f"source IDs must be present and unique: {stage_dir.name}")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise VerificationError(f"stage must declare at least one artifact: {stage_dir.name}")
    artifact_by_path: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise VerificationError(f"invalid artifact object in {stage_dir.name}")
        require_fields(
            artifact,
            ["path", "role", "media_type", "bytes", "sha256", "source_ids"],
            f"artifact in {stage_dir.name}",
        )
        relative = artifact["path"]
        if relative in artifact_by_path:
            raise VerificationError(f"duplicate artifact path: {relative}")
        if not HASH_RE.fullmatch(str(artifact["sha256"])):
            raise VerificationError(f"invalid SHA-256 in manifest for {relative}")
        if not set(artifact["source_ids"]).issubset(source_ids):
            raise VerificationError(f"artifact references an unknown source: {relative}")
        path = safe_stage_path(stage_dir, relative)
        actual_size = path.stat().st_size
        if actual_size != artifact["bytes"]:
            raise VerificationError(
                f"size mismatch for {relative}: {actual_size} != {artifact['bytes']}"
            )
        actual_hash = sha256_file(path)
        if actual_hash != artifact["sha256"]:
            raise VerificationError(f"SHA-256 mismatch for {relative}")
        artifact_by_path[relative] = artifact

    verification = manifest["verification"]
    require_fields(
        verification,
        ["checksum_file", "command"],
        f"verification in {stage_dir.name}",
    )
    checksum_path = safe_stage_path(stage_dir, verification["checksum_file"])
    checksum_entries = parse_checksums(checksum_path, stage_dir)
    manifest_entries = {
        path: artifact["sha256"] for path, artifact in artifact_by_path.items()
    }
    if checksum_entries != manifest_entries:
        raise VerificationError(f"SHA256SUMS and manifest disagree in {stage_dir.name}")

    raw_snapshots = [artifact for artifact in artifacts if artifact["role"] == "raw-snapshot"]
    for artifact in raw_snapshots:
        if "record_count" not in artifact:
            raise VerificationError(f"raw snapshot lacks record_count in {stage_dir.name}")
        verify_raw_snapshot(
            safe_stage_path(stage_dir, artifact["path"]), artifact["record_count"]
        )

    table_indexes = [artifact for artifact in artifacts if artifact["role"] == "table-index"]
    table_binaries = [artifact for artifact in artifacts if artifact["role"] == "table-binary"]
    bank = None
    if table_indexes or table_binaries:
        if len(table_indexes) != 1 or len(table_binaries) != 1:
            raise VerificationError(
                f"stage must pair one table-index with one table-binary: {stage_dir.name}"
            )
        bank = verify_table_index(stage_dir, table_indexes[0], table_binaries[0])
        attributes = table_binaries[0].get("attributes", {})
        for field, value in (
            ("table_count", bank["count"]),
            ("raw_bytes", bank["raw_bytes"]),
            ("raw_sha256", bank["raw_sha256"]),
            ("canonical_id_vector_sha256", bank["canonical_id_vector_sha256"]),
            ("historical_id_vector_sha256", bank["historical_id_vector_sha256"]),
            ("order_distribution", bank["order_distribution"]),
        ):
            if attributes.get(field) != value:
                raise VerificationError(
                    f"table-binary attribute {field} drift in {stage_dir.name}"
                )

    delta_artifacts = [
        artifact for artifact in artifacts if artifact["role"] == "membership-delta"
    ]
    delta = None
    if delta_artifacts:
        if len(delta_artifacts) != 1:
            raise VerificationError(f"expected one membership delta in {stage_dir.name}")
        delta = verify_delta_index(stage_dir, delta_artifacts[0])

    identity_maps = [artifact for artifact in artifacts if artifact["role"] == "identity-map"]
    if identity_maps:
        if len(identity_maps) != 1 or bank is None:
            raise VerificationError(f"identity map lacks a unique table bank in {stage_dir.name}")
        verify_identity_map(stage_dir, identity_maps[0], bank)

    line_count_roles = {
        "primary-model-index",
        "skipped-model-index",
        "input-classification",
    }
    delivery_binaries: dict[str, list[str]] = {}
    for artifact in artifacts:
        if artifact["role"] in line_count_roles:
            actual_count = count_nonempty_lines(safe_stage_path(stage_dir, artifact["path"]))
            if artifact.get("record_count") != actual_count:
                raise VerificationError(
                    f"record_count drift for {artifact['path']} in {stage_dir.name}"
                )
        if artifact["role"] == "delivery-binary":
            ids = table_binary_ids(safe_stage_path(stage_dir, artifact["path"]))
            delivery_binaries[artifact["path"]] = ids
            if artifact.get("record_count") != len(ids):
                raise VerificationError(
                    f"delivery binary count drift for {artifact['path']}"
                )

    task_artifacts = [
        artifact for artifact in artifacts if artifact["role"] == "task-verification"
    ]
    task_verification = None
    if task_artifacts:
        if stage_dir.name != "40-delivery-10059" or len(task_artifacts) != 1:
            raise VerificationError(
                f"unexpected task-verification artifacts in {stage_dir.name}"
            )
        task_verification = verify_task_evidence(stage_dir, task_artifacts[0])
        delivery_ids = delivery_binaries.get("normalized/delivery-102.bin")
        if delivery_ids != task_verification["table_ids"]:
            raise VerificationError(
                "task evidence table order disagrees with delivery-102.bin"
            )
        if bank is None or bank["ids"][-len(delivery_ids) :] != delivery_ids:
            raise VerificationError(
                "delivery-102.bin does not match the Stage40 bank suffix"
            )

    summary_artifacts = [artifact for artifact in artifacts if artifact["role"] == "stage-summary"]
    summary = None
    if summary_artifacts:
        if len(summary_artifacts) != 1:
            raise VerificationError(f"expected one stage summary in {stage_dir.name}")
        summary = verify_stage_summary(
            stage_dir,
            summary_artifacts[0],
            manifest_claims,
            claims_by_id,
            bank,
            delta,
        )
        if (
            task_verification is not None
            and summary.get("official_equation_mapping")
            != task_verification["official_equation_mapping"]
        ):
            raise VerificationError(
                f"official equation mapping summary drift in {stage_dir.name}"
            )

    submission_indexes = [
        artifact for artifact in artifacts if artifact["role"] == "submission-index"
    ]
    submission_count = 0
    if submission_indexes:
        if len(submission_indexes) != 1:
            raise VerificationError(f"expected one submission index in {stage_dir.name}")
        source_locators = {source["locator"] for source in sources}
        submission_summary = verify_submission_index(
            stage_dir,
            submission_indexes[0],
            artifact_by_path,
            source_locators,
        )
        submission_count = submission_summary["participations"]
        verify_submission_claims(
            stage_dir.name,
            manifest_claims,
            claims_by_id,
            submission_summary,
        )

    return len(artifacts), submission_count, manifest_claims, {
        "manifest": manifest,
        "bank": bank,
        "delta": delta,
        "summary": summary,
    }


def verify_claims(root: Path) -> dict[str, dict[str, str]]:
    path = root / "CLAIMS.csv"
    required_headers = [
        "claim_id",
        "stage_id",
        "metric",
        "expected_value",
        "unit",
        "derivation",
        "status",
        "evidence_path",
    ]
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(iter_bounded_text_lines(handle, str(path)))
        if reader.fieldnames != required_headers:
            raise VerificationError(f"unexpected CLAIMS.csv header: {reader.fieldnames}")
        claims_by_id: dict[str, dict[str, str]] = {}
        for line_number, row in enumerate(reader, start=2):
            claim_id = row["claim_id"]
            if not CLAIM_RE.fullmatch(claim_id or "") or claim_id in claims_by_id:
                raise VerificationError(
                    f"missing or duplicate claim_id at CLAIMS.csv:{line_number}"
                )
            if not STAGE_RE.fullmatch(row["stage_id"]):
                raise VerificationError(f"invalid stage_id at CLAIMS.csv:{line_number}")
            for field in ("metric", "expected_value", "unit", "derivation"):
                if not row[field]:
                    raise VerificationError(
                        f"empty {field} at CLAIMS.csv:{line_number}"
                    )
            if row["status"] not in CLAIM_STATUSES:
                raise VerificationError(f"invalid status at CLAIMS.csv:{line_number}")
            evidence = row["evidence_path"]
            if row["status"] != "planned":
                if not evidence:
                    raise VerificationError(
                        f"non-planned claim lacks evidence at line {line_number}"
                    )
                evidence_path = (root / evidence).resolve()
                try:
                    evidence_path.relative_to(root.resolve())
                except ValueError as exc:
                    raise VerificationError(
                        f"claim evidence escapes repository at line {line_number}"
                    ) from exc
                if not evidence_path.is_file():
                    raise VerificationError(
                        f"claim evidence does not exist at line {line_number}"
                    )
            claims_by_id[claim_id] = row
    return claims_by_id


def verify_schema_documents(root: Path) -> int:
    schema_dir = root / "schemas"
    expected = {
        "stage-manifest.schema.json",
        "submission-anchor.schema.json",
        "table-record.schema.json",
        "delta-record.schema.json",
    }
    found = {path.name for path in schema_dir.glob("*.schema.json")}
    if found != expected:
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        raise VerificationError(
            f"schema set mismatch; missing={missing or 'none'}, extra={extra or 'none'}"
        )
    for name in sorted(expected):
        document = load_json(schema_dir / name)
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise VerificationError(f"unexpected JSON Schema draft in {name}")
        require_http_url(document.get("$id"), f"{name}.$id")
        if document.get("type") != "object":
            raise VerificationError(f"top-level schema type must be object in {name}")
    return len(expected)


def verify_stage_transitions(
    results: dict[str, dict[str, Any]], *, allow_missing_dependencies: bool = False
) -> None:
    pipeline_orders: dict[int, str] = {}
    global_source_ids: set[str] = set()
    for stage_id, result in results.items():
        manifest = result["manifest"]
        for source in manifest["sources"]:
            source_id = source["source_id"]
            if source_id in global_source_ids:
                raise VerificationError(f"source_id is not globally unique: {source_id}")
            global_source_ids.add(source_id)
        order = manifest["pipeline_order"]
        if order in pipeline_orders:
            raise VerificationError(
                f"duplicate pipeline_order {order}: {pipeline_orders[order]} and {stage_id}"
            )
        pipeline_orders[order] = stage_id
        for dependency in manifest["depends_on"]:
            if dependency not in results:
                if allow_missing_dependencies:
                    continue
                raise VerificationError(
                    f"stage dependency is missing from full verification: "
                    f"{dependency} -> {stage_id}"
                )
            dependency_order = results[dependency]["manifest"]["pipeline_order"]
            if dependency_order >= order:
                raise VerificationError(
                    f"dependency does not precede stage: {dependency} -> {stage_id}"
                )

    for stage_id, result in results.items():
        bank = result["bank"]
        if bank is None:
            continue
        if set(bank["first_seen"].values()).issubset(results):
            unknown_provenance = bank["provenance_source_ids"] - global_source_ids
            if unknown_provenance:
                raise VerificationError(
                    f"table provenance references unknown sources in {stage_id}: "
                    f"{', '.join(sorted(unknown_provenance))}"
                )
        delta = result["delta"]
        if delta is None:
            raise VerificationError(f"table stage lacks membership delta: {stage_id}")
        dependencies = result["manifest"]["depends_on"]
        available_dependencies = [value for value in dependencies if value in results]
        if dependencies and len(available_dependencies) != len(dependencies):
            if allow_missing_dependencies:
                # A --stage selection intentionally verifies one stage in isolation.
                continue
            raise VerificationError(f"cannot reconstruct missing dependency for {stage_id}")
        if len(dependencies) > 1:
            raise VerificationError(f"table stage has multiple bank dependencies: {stage_id}")
        previous = results[dependencies[0]]["bank"] if dependencies else None
        if dependencies and previous is None:
            raise VerificationError(f"bank dependency has no table bank: {stage_id}")
        working = set(previous["id_set"] if previous is not None else set())
        previous_first_seen = previous["first_seen"] if previous is not None else {}
        for row in delta["rows"]:
            table_id = row["table_id"]
            action = row["action"]
            if action in {"add", "derive"}:
                if table_id in working:
                    raise VerificationError(
                        f"delta {action} targets an existing table in {stage_id}: {table_id}"
                    )
                working.add(table_id)
            elif action in {"duplicate", "retain"}:
                if table_id not in working:
                    raise VerificationError(
                        f"delta {action} targets a missing table in {stage_id}: {table_id}"
                    )
            elif action == "remove":
                if table_id not in working:
                    raise VerificationError(
                        f"delta remove targets a missing table in {stage_id}: {table_id}"
                    )
                working.remove(table_id)
            elif action == "replace":
                source_table_id = row.get("source_table_id")
                if source_table_id not in working or table_id in working:
                    raise VerificationError(f"invalid replace transition in {stage_id}")
                working.remove(source_table_id)
                working.add(table_id)
        if working != bank["id_set"]:
            raise VerificationError(f"delta does not reconstruct table membership in {stage_id}")
        for table_id, first_stage in bank["first_seen"].items():
            if table_id in previous_first_seen:
                if first_stage != previous_first_seen[table_id]:
                    raise VerificationError(
                        f"first_seen_stage changed for {table_id} in {stage_id}"
                    )
            elif first_stage != stage_id:
                raise VerificationError(
                    f"new table has wrong first_seen_stage in {stage_id}: {table_id}"
                )


def verify_repository(
    root: Path, selected_stages: list[str] | None = None
) -> tuple[int, int]:
    schema_count = verify_schema_documents(root)
    claims_by_id = verify_claims(root)
    reproduction_root = root / "reproduction"
    if selected_stages:
        stage_dirs = [reproduction_root / stage for stage in selected_stages]
    else:
        stage_dirs = sorted(path.parent for path in reproduction_root.glob("*/stage.json"))
    if not stage_dirs:
        raise VerificationError("no reproduction stages found")

    total_artifacts = 0
    manifested_claims: set[str] = set()
    stage_results: dict[str, dict[str, Any]] = {}
    selected_stage_ids = {stage_dir.name for stage_dir in stage_dirs}
    for stage_dir in stage_dirs:
        if not stage_dir.is_dir():
            raise VerificationError(f"stage directory does not exist: {stage_dir.name}")
        artifact_count, submission_count, stage_claims, stage_result = verify_stage(
            stage_dir, claims_by_id
        )
        total_artifacts += artifact_count
        manifested_claims.update(stage_claims)
        stage_results[stage_dir.name] = stage_result
        suffix = f", {submission_count} submission records" if submission_count else ""
        print(f"OK {stage_dir.name}: {artifact_count} artifacts{suffix}")

    for claim_id, claim in claims_by_id.items():
        if (
            claim["stage_id"] in selected_stage_ids
            and claim["status"] != "planned"
            and claim_id not in manifested_claims
        ):
            raise VerificationError(
                f"non-planned claim is missing from its stage manifest: {claim_id}"
            )

    verify_stage_transitions(
        stage_results, allow_missing_dependencies=bool(selected_stages)
    )

    print(f"OK schemas: {schema_count} documents")
    print(f"OK CLAIMS.csv: {len(claims_by_id)} claims")
    return len(stage_dirs), total_artifacts


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: inferred from this script)",
    )
    parser.add_argument(
        "--stage",
        action="append",
        dest="stages",
        help="verify only this stage; repeat for multiple stages",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        stage_count, artifact_count = verify_repository(args.root.resolve(), args.stages)
    except (OSError, VerificationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"Repository verification passed: {stage_count} stage(s), "
        f"{artifact_count} artifacts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
