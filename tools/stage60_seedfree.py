#!/usr/bin/env python3
"""Deterministic Stage 60 input recovery and bounded file helpers.

The committed Stage 60 snapshot did not preserve several historical files as
standalone artifacts.  It did preserve enough byte-level information to recover
five of them exactly.  This module performs that recovery without importing or
executing any historical solver and verifies every reconstructed byte stream
against the digest recorded by the historical manifests/runners.

Large pair bitsets are always copied as forward-only streams.  The equation and
per-source CSV members are explicitly bounded before they are parsed.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import struct
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, Mapping, Sequence


STAGE60 = "60-fin4-residual-284151591"
STAGE60_RELATIVE = Path("reproduction") / STAGE60
RAW_ARCHIVE_RELATIVE = Path("raw/fin4-residual-snapshot.tar.gz")
NORMALIZED_324_RELATIVE = Path("normalized/324M_remaining_pairs.bitset.gz")

RAW_ARCHIVE_SHA256 = (
    "589f3b272fb970c9b995e6d9433dc3deec66241a2cf061be230254445704d9d0"
)
NORMALIZED_324_GZIP_SHA256 = (
    "fdf831e78477f66074653427fb123b92655584577f405771dededbb1009ae7fc"
)
SOURCE_324_BYTES = 489_598_720
SOURCE_324_SHA256 = (
    "f3cce217528adee2305e618a81a1fdb7399c6732523bb60f055b1d5acf61f383"
)
FINAL_284_BYTES = 489_598_720
FINAL_284_SHA256 = (
    "03f4a7eccc7df811756fc5da361a647b49b9064f35b2b14730362fc3fb810756"
)

MODEL_MAGIC = b"FTMODL01"

EQUATION_COUNT = 62_576
OP_TOKEN = 255
EQUATION_MAGIC = b"FTEQN001"
MIRROR_MAGIC = b"FTMIRR01"
SIGNATURE_BYTES = (EQUATION_COUNT + 7) // 8

EQUATIONS_CSV_MEMBER = (
    "members/wubing/data/324M_remaining_pairs/order5_equations.csv"
)
SOURCE_ROWS_MEMBER = (
    "members/wubing/data/324M_remaining_pairs/"
    "324M_remaining_pairs_by_source.csv"
)
BITSLICE_ENGINE_MEMBER = (
    "members/wubing/artifacts/runs/"
    "d17-fin4-exhaustive-full-bitslice-opposite-20260818/"
    "fin4_bitslice_opposite_engine.c"
)
SCALAR_ENGINE_MEMBER = (
    "members/wubing/artifacts/runs/d17-fin4-exhaustive-full-20260818/"
    "fin4_exhaustive_engine.c"
)

EQUATIONS_CSV_BYTES = 3_594_508
EQUATIONS_CSV_SHA256 = (
    "62b9fa9d5b5fa0ef499e7a9b30ae3e244485e4cc62e996de99c39897a74bdc7c"
)
SOURCE_ROWS_BYTES = 2_440_134
SOURCE_ROWS_SHA256 = (
    "0e00485f6a0c6c2aa53a915c99f886f5d868d566d7f9f333106c9ebec996a882"
)
BITSLICE_ENGINE_BYTES = 65_659
BITSLICE_ENGINE_SHA256 = (
    "c1a1a761126d696ddd4fa2c3958042b71b2d8aa50e463448f57819757bacc189"
)
SCALAR_ENGINE_BYTES = 33_536
SCALAR_ENGINE_SHA256 = (
    "e2594b55d4f61c7ff6beafdf8068725664495777b673a9bf6e0ded9d2a89239c"
)

RECONSTRUCTED_INPUTS: Mapping[str, tuple[int, str]] = {
    "eq_size5.txt": (
        2_666_870,
        "7fb9c0e85bee412baa7030bafec311c65a75502a2c25bdd0b94171b324585b1d",
    ),
    "equations.bin": (
        928_334,
        "263b6d3fb1c6a84a4503742f11a4f2e6ac3a00a64e1f0a57fc002699ef7be7f9",
    ),
    "equation_mirror_map.bin": (
        250_316,
        "b3f3f577c986890fc4ab7eb594396cf246c6f855107c4ff02cdbd8795865a96a",
    ),
    "singleton_family_mask.u8": (
        62_576,
        "a237aefe72909539cf61e821a41117d33d1c7632da2303890cd03490226e64ec",
    ),
    "singleton_primary.u8": (
        62_576,
        "d159b628010fadd4a66bd4feb0e7278354247e265b988b4f773ce2d6b9a01fff",
    ),
}

RECONSTRUCTION_REPORT_SCHEMA = "stage60-seedfree-input-reconstruction-v1"
SYMBOLIC_FIXTURE_FILES: Mapping[str, tuple[int, str]] = {
    "models.bin": (
        63,
        "91cfe7bf669b51a35df15cab4a5ca343f1b358a61860c9026fa5d70884e8131f",
    ),
    "signatures.bin": (
        23_466,
        "529b454cc4996034d509cfe9a5c3bc1cce79cd2e7e0fff20e8caf41fede5ac56",
    ),
}
SYMBOLIC_FIXTURE_SATISFIED = (14_612, 14_612, 22_604)
CHUNK_SIZE = 1024 * 1024
MAX_EQUATIONS_CSV_BYTES = 4 * 1024 * 1024
MAX_SOURCE_ROWS_BYTES = 3 * 1024 * 1024


class Stage60SeedFreeError(RuntimeError):
    """Raised when a reconstructable input or runner prerequisite drifts."""


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def file_metadata(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": sha256_path(path)}


def verify_file(path: Path, *, expected_bytes: int, expected_sha256: str) -> dict[str, object]:
    if not path.is_file():
        raise Stage60SeedFreeError(f"missing required file: {path}")
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        raise Stage60SeedFreeError(
            f"byte-size mismatch for {path}: expected {expected_bytes}, found {actual_bytes}"
        )
    actual_sha256 = sha256_path(path)
    if actual_sha256 != expected_sha256:
        raise Stage60SeedFreeError(
            f"SHA-256 mismatch for {path}: expected {expected_sha256}, found {actual_sha256}"
        )
    return {"bytes": actual_bytes, "sha256": actual_sha256}


def _read_bounded_member(
    archive: tarfile.TarFile,
    member_name: str,
    *,
    expected_bytes: int,
    expected_sha256: str,
    size_limit: int,
) -> bytes:
    try:
        member = archive.getmember(member_name)
    except KeyError as exc:
        raise Stage60SeedFreeError(f"missing raw snapshot member: {member_name}") from exc
    if not member.isfile() or member.size != expected_bytes or member.size > size_limit:
        raise Stage60SeedFreeError(
            f"unexpected raw snapshot member metadata for {member_name}: "
            f"size={member.size}, is_file={member.isfile()}"
        )
    handle = archive.extractfile(member)
    if handle is None:
        raise Stage60SeedFreeError(f"cannot read raw snapshot member: {member_name}")
    payload = handle.read(size_limit + 1)
    if len(payload) != expected_bytes:
        raise Stage60SeedFreeError(f"truncated raw snapshot member: {member_name}")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise Stage60SeedFreeError(
            f"raw snapshot member hash drift for {member_name}: {digest}"
        )
    return payload


@contextmanager
def _atomic_binary_output(path: Path) -> Iterator[BinaryIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json_atomic(path: Path, value: object) -> None:
    with _atomic_binary_output(path) as handle:
        handle.write(
            (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        )


def _strip_outer_parentheses(text: str) -> str:
    text = text.strip()
    while len(text) >= 2 and text[0] == "(" and text[-1] == ")":
        depth = 0
        covers_all = True
        for index, character in enumerate(text):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth < 0:
                    raise Stage60SeedFreeError("unbalanced equation parentheses")
            if depth == 0 and index < len(text) - 1:
                covers_all = False
                break
        if not covers_all:
            break
        if depth != 0:
            raise Stage60SeedFreeError("unbalanced equation parentheses")
        text = text[1:-1].strip()
    return text


def _parse_term(text: str, variable_indices: Mapping[str, int]) -> object:
    text = _strip_outer_parentheses(text)
    depth = 0
    last_operation = -1
    for index, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise Stage60SeedFreeError("unbalanced equation parentheses")
        elif character == "◇" and depth == 0:
            last_operation = index
    if depth != 0:
        raise Stage60SeedFreeError("unbalanced equation parentheses")
    if last_operation >= 0:
        return (
            _parse_term(text[:last_operation], variable_indices),
            _parse_term(text[last_operation + 1 :], variable_indices),
        )
    if len(text) == 1 and text in variable_indices:
        return variable_indices[text]
    raise Stage60SeedFreeError(f"cannot parse historical term: {text!r}")


def _postfix(term: object) -> bytes:
    if type(term) is int:
        value = int(term)
        if not 0 <= value < OP_TOKEN:
            raise Stage60SeedFreeError(f"variable token outside uint8 range: {value}")
        return bytes([value])
    if not isinstance(term, tuple) or len(term) != 2:
        raise Stage60SeedFreeError("unexpected parsed term shape")
    return _postfix(term[0]) + _postfix(term[1]) + bytes([OP_TOKEN])


def _parse_historical_equation(text: str) -> tuple[int, bytes, bytes]:
    normalized = text.replace("*", "◇")
    if normalized.count("=") != 1 or "≠" in normalized:
        raise Stage60SeedFreeError(f"malformed historical equation: {text!r}")
    variables: list[str] = []
    for variable in re.findall(r"\b([a-z])\b", normalized):
        if variable not in variables:
            variables.append(variable)
    if not variables:
        raise Stage60SeedFreeError(f"equation has no variables: {text!r}")
    indices = {variable: index for index, variable in enumerate(variables)}
    left_text, right_text = normalized.split("=", 1)
    left = _postfix(_parse_term(left_text, indices))
    right = _postfix(_parse_term(right_text, indices))
    if len(variables) > 7 or not 1 <= len(left) <= 15 or not 1 <= len(right) <= 15:
        raise Stage60SeedFreeError("equation exceeds the frozen Fin4 engine limits")
    return len(variables), left, right


def _renumbered_orientation(left: bytes, right: bytes) -> bytes:
    remapping: dict[int, int] = {}
    normalized = bytearray()
    for token in left + right:
        if token == OP_TOKEN:
            normalized.append(token)
        else:
            if token not in remapping:
                remapping[token] = len(remapping)
            normalized.append(remapping[token])
    split = len(left)
    normalized_left = normalized[:split]
    normalized_right = normalized[split:]
    return bytes([len(normalized_left)]) + bytes(normalized_left) + bytes(
        [len(normalized_right)]
    ) + bytes(normalized_right)


def _equation_key(left: bytes, right: bytes) -> bytes:
    return min(
        _renumbered_orientation(left, right),
        _renumbered_orientation(right, left),
    )


def _mirror_postfix(tokens: bytes) -> bytes:
    stack: list[bytes] = []
    for token in tokens:
        if token != OP_TOKEN:
            stack.append(bytes([token]))
        else:
            if len(stack) < 2:
                raise Stage60SeedFreeError("invalid postfix term while building mirror map")
            right = stack.pop()
            left = stack.pop()
            stack.append(right + left + bytes([OP_TOKEN]))
    if len(stack) != 1:
        raise Stage60SeedFreeError("invalid postfix term final stack")
    return stack[0]


def _parse_equation_rows(payload: bytes) -> list[dict[str, str]]:
    text = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8", newline="")
    reader = csv.DictReader(text)
    expected = [
        "equation_id",
        "equation_text",
        "variable_count",
        "lhs_operation_count",
        "rhs_operation_count",
        "total_operation_count",
    ]
    if reader.fieldnames != expected:
        raise Stage60SeedFreeError("historical equation CSV header drift")
    rows = list(reader)
    if len(rows) != EQUATION_COUNT:
        raise Stage60SeedFreeError(
            f"historical equation CSV row count drift: {len(rows)}"
        )
    return rows


def _parse_source_rows(payload: bytes) -> list[dict[str, str]]:
    text = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8", newline="")
    reader = csv.DictReader(text)
    expected = [
        "source_equation_id",
        "bitmap_row_index",
        "bitmap_offset_bytes",
        "fin23_covered_target_count",
        "singleton_true_target_count",
        "remaining_target_count",
        "is_active_source",
        "singleton_family_mask",
        "singleton_primary_class",
    ]
    if reader.fieldnames != expected:
        raise Stage60SeedFreeError("historical per-source CSV header drift")
    rows = list(reader)
    if len(rows) != EQUATION_COUNT:
        raise Stage60SeedFreeError(
            f"historical per-source CSV row count drift: {len(rows)}"
        )
    return rows


def _build_reconstructed_inputs(
    equations_payload: bytes,
    source_rows_payload: bytes,
    output_dir: Path,
) -> dict[str, object]:
    equation_rows = _parse_equation_rows(equations_payload)
    source_rows = _parse_source_rows(source_rows_payload)
    equation_records: list[tuple[bytes, bytes]] = []

    with _atomic_binary_output(output_dir / "eq_size5.txt") as text_output, _atomic_binary_output(
        output_dir / "equations.bin"
    ) as binary_output:
        binary_output.write(EQUATION_MAGIC)
        binary_output.write(struct.pack("<I", EQUATION_COUNT))
        for index, row in enumerate(equation_rows, start=1):
            try:
                equation_id = int(row["equation_id"])
            except ValueError as exc:
                raise Stage60SeedFreeError("non-integer historical equation ID") from exc
            if equation_id != index:
                raise Stage60SeedFreeError(
                    f"historical equation ID drift at row {index}: {equation_id}"
                )
            equation_text = row["equation_text"]
            text_output.write(equation_text.encode("utf-8") + b"\n")
            variable_count, left, right = _parse_historical_equation(equation_text)
            if int(row["variable_count"]) != variable_count:
                raise Stage60SeedFreeError(
                    f"variable-count drift at Equation{equation_id}"
                )
            binary_output.write(bytes([variable_count, len(left), len(right)]))
            binary_output.write(left)
            binary_output.write(right)
            equation_records.append((left, right))

    key_to_index: dict[bytes, int] = {}
    for index, (left, right) in enumerate(equation_records):
        key = _equation_key(left, right)
        if key in key_to_index:
            raise Stage60SeedFreeError(
                f"duplicate normalized equation key at indexes {key_to_index[key]} and {index}"
            )
        key_to_index[key] = index
    mirror_mapping: list[int] = []
    for index, (left, right) in enumerate(equation_records):
        mirror_key = _equation_key(_mirror_postfix(left), _mirror_postfix(right))
        try:
            mirror_mapping.append(key_to_index[mirror_key])
        except KeyError as exc:
            raise Stage60SeedFreeError(
                f"mirror equation missing for zero-based equation index {index}"
            ) from exc
    if any(mirror_mapping[mirror_mapping[index]] != index for index in range(EQUATION_COUNT)):
        raise Stage60SeedFreeError("reconstructed mirror map is not an involution")
    if len(set(mirror_mapping)) != EQUATION_COUNT:
        raise Stage60SeedFreeError("reconstructed mirror map is not a permutation")
    fixed_points = sum(index == target for index, target in enumerate(mirror_mapping))
    two_cycles = sum(index < target for index, target in enumerate(mirror_mapping))
    if fixed_points != 202 or two_cycles != 31_187:
        raise Stage60SeedFreeError("reconstructed mirror-map orbit counts drift")
    with _atomic_binary_output(output_dir / "equation_mirror_map.bin") as handle:
        handle.write(MIRROR_MAGIC)
        handle.write(struct.pack("<I", EQUATION_COUNT))
        for target in mirror_mapping:
            handle.write(struct.pack("<I", target))

    family_counts: dict[int, int] = {}
    primary_counts: dict[int, int] = {}
    with _atomic_binary_output(output_dir / "singleton_family_mask.u8") as family, _atomic_binary_output(
        output_dir / "singleton_primary.u8"
    ) as primary:
        for index, row in enumerate(source_rows, start=1):
            if int(row["source_equation_id"]) != index or int(row["bitmap_row_index"]) != index - 1:
                raise Stage60SeedFreeError(
                    f"historical per-source identity drift at row {index}"
                )
            family_value = int(row["singleton_family_mask"])
            primary_value = int(row["singleton_primary_class"])
            if not 0 <= family_value <= 255 or not 0 <= primary_value <= 255:
                raise Stage60SeedFreeError(f"singleton byte outside range at row {index}")
            family.write(bytes([family_value]))
            primary.write(bytes([primary_value]))
            family_counts[family_value] = family_counts.get(family_value, 0) + 1
            primary_counts[primary_value] = primary_counts.get(primary_value, 0) + 1

    files: dict[str, dict[str, object]] = {}
    for name, (expected_bytes, expected_sha256) in RECONSTRUCTED_INPUTS.items():
        files[name] = verify_file(
            output_dir / name,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
        files[name]["historical_bytes_exact"] = True
    return {
        "files": files,
        "equations": EQUATION_COUNT,
        "mirror_fixed_points": fixed_points,
        "mirror_two_cycles": two_cycles,
        "singleton_family_counts": {
            str(key): family_counts[key] for key in sorted(family_counts)
        },
        "singleton_primary_counts": {
            str(key): primary_counts[key] for key in sorted(primary_counts)
        },
    }


def verify_reconstructed_inputs(output_dir: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, (expected_bytes, expected_sha256) in RECONSTRUCTED_INPUTS.items():
        result[name] = verify_file(
            output_dir / name,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
        result[name]["historical_bytes_exact"] = True
    return result


def reconstruct_stage60_inputs(
    repository_root: Path,
    output_dir: Path,
    *,
    report_path: Path | None = None,
    replace: bool = False,
) -> dict[str, object]:
    repository_root = repository_root.resolve()
    stage_dir = repository_root / STAGE60_RELATIVE
    archive_path = stage_dir / RAW_ARCHIVE_RELATIVE
    verify_file(
        archive_path,
        expected_bytes=18_269_359,
        expected_sha256=RAW_ARCHIVE_SHA256,
    )
    existing = [output_dir / name for name in RECONSTRUCTED_INPUTS if (output_dir / name).exists()]
    if existing and not replace:
        if len(existing) != len(RECONSTRUCTED_INPUTS):
            raise Stage60SeedFreeError(
                f"partial reconstructed input set in {output_dir}; use a clean directory"
            )
        files = verify_reconstructed_inputs(output_dir)
        result: dict[str, object] = {
            "files": files,
            "equations": EQUATION_COUNT,
            "mirror_fixed_points": 202,
            "mirror_two_cycles": 31_187,
            "singleton_family_counts": {
                "0": 41_697,
                "1": 569,
                "4": 2_663,
                "5": 2_858,
                "6": 8_874,
                "7": 5_915,
            },
            "singleton_primary_counts": {
                "0": 41_697,
                "1": 9_342,
                "2": 8_874,
                "3": 2_663,
            },
        }
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as archive:
            equations_payload = _read_bounded_member(
                archive,
                EQUATIONS_CSV_MEMBER,
                expected_bytes=EQUATIONS_CSV_BYTES,
                expected_sha256=EQUATIONS_CSV_SHA256,
                size_limit=MAX_EQUATIONS_CSV_BYTES,
            )
            source_rows_payload = _read_bounded_member(
                archive,
                SOURCE_ROWS_MEMBER,
                expected_bytes=SOURCE_ROWS_BYTES,
                expected_sha256=SOURCE_ROWS_SHA256,
                size_limit=MAX_SOURCE_ROWS_BYTES,
            )
        result = _build_reconstructed_inputs(
            equations_payload, source_rows_payload, output_dir
        )

    report = {
        "schema": RECONSTRUCTION_REPORT_SCHEMA,
        "status": "historical-bytes-exact",
        "source": {
            "archive": str(STAGE60_RELATIVE / RAW_ARCHIVE_RELATIVE),
            "archive_sha256": RAW_ARCHIVE_SHA256,
            "equations_member": EQUATIONS_CSV_MEMBER,
            "equations_member_sha256": EQUATIONS_CSV_SHA256,
            "source_rows_member": SOURCE_ROWS_MEMBER,
            "source_rows_member_sha256": SOURCE_ROWS_SHA256,
        },
        **result,
        "resource_boundary": {
            "large_bitsets_materialized": False,
            "maximum_bounded_csv_member_bytes": MAX_EQUATIONS_CSV_BYTES,
            "reconstructed_output_bytes": sum(
                expected_bytes for expected_bytes, _digest in RECONSTRUCTED_INPUTS.values()
            ),
        },
        "scope_boundary": (
            "These five files match the historical bytes. This does not recover or "
            "replay the historical 6,173-model seed-generation/provenance chain."
        ),
    }
    if report_path is not None:
        write_json_atomic(report_path, report)
    return report


def extract_engine_source(
    repository_root: Path,
    output_path: Path,
    *,
    bitslice: bool = True,
) -> dict[str, object]:
    stage_dir = repository_root.resolve() / STAGE60_RELATIVE
    archive_path = stage_dir / RAW_ARCHIVE_RELATIVE
    verify_file(
        archive_path,
        expected_bytes=18_269_359,
        expected_sha256=RAW_ARCHIVE_SHA256,
    )
    member_name = BITSLICE_ENGINE_MEMBER if bitslice else SCALAR_ENGINE_MEMBER
    expected_bytes = BITSLICE_ENGINE_BYTES if bitslice else SCALAR_ENGINE_BYTES
    expected_sha256 = BITSLICE_ENGINE_SHA256 if bitslice else SCALAR_ENGINE_SHA256
    with tarfile.open(archive_path, "r:gz") as archive:
        payload = _read_bounded_member(
            archive,
            member_name,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            size_limit=128 * 1024,
        )
    if output_path.exists():
        return verify_file(
            output_path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
    with _atomic_binary_output(output_path) as handle:
        handle.write(payload)
    return verify_file(
        output_path,
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha256,
    )


def materialize_source_324_bitset(
    repository_root: Path,
    output_path: Path,
) -> dict[str, object]:
    source_path = repository_root.resolve() / STAGE60_RELATIVE / NORMALIZED_324_RELATIVE
    verify_file(
        source_path,
        expected_bytes=7_217_176,
        expected_sha256=NORMALIZED_324_GZIP_SHA256,
    )
    if output_path.exists():
        return verify_file(
            output_path,
            expected_bytes=SOURCE_324_BYTES,
            expected_sha256=SOURCE_324_SHA256,
        )
    digest = hashlib.sha256()
    total = 0
    with gzip.open(source_path, "rb") as source, _atomic_binary_output(output_path) as output:
        for block in iter(lambda: source.read(CHUNK_SIZE), b""):
            output.write(block)
            digest.update(block)
            total += len(block)
    if total != SOURCE_324_BYTES or digest.hexdigest() != SOURCE_324_SHA256:
        raise Stage60SeedFreeError(
            "decompressed 324M source bitset does not match the committed raw hash"
        )
    return {"bytes": total, "sha256": digest.hexdigest()}


def copy_file_streaming(source: Path, destination: Path) -> dict[str, object]:
    if destination.exists():
        raise Stage60SeedFreeError(f"refusing to overwrite existing file: {destination}")
    digest = hashlib.sha256()
    total = 0
    with source.open("rb") as input_handle, _atomic_binary_output(destination) as output:
        for block in iter(lambda: input_handle.read(CHUNK_SIZE), b""):
            output.write(block)
            digest.update(block)
            total += len(block)
    return {"bytes": total, "sha256": digest.hexdigest()}


def default_work_dir(repository_root: Path) -> Path:
    identity = hashlib.sha256(str(repository_root.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"finite-countermodel-stage60-{identity}"


def reconstruction_report_for_repository(repository_root: Path) -> dict[str, object]:
    """Rebuild all five small inputs in a temporary directory and return the audit."""

    with tempfile.TemporaryDirectory(prefix="stage60-input-audit-") as temporary:
        return reconstruct_stage60_inputs(
            repository_root,
            Path(temporary) / "inputs",
        )


def build_symbolic_signature_fixture(
    input_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Build three independently-derived Fin4 signature fixtures.

    The expected laws are computed directly from ``eq_size5.txt`` using the
    semantics of left projection, right projection, and a constant-zero binary
    operation.  They do not evaluate the reconstructed postfix records, so both
    engine verification modes provide an independent check of ``equations.bin``.
    """

    verify_reconstructed_inputs(input_dir)
    model_tables = [
        (
            "left_projection",
            bytes(left for left in range(4) for _right in range(4)),
        ),
        (
            "right_projection",
            bytes(right for _left in range(4) for right in range(4)),
        ),
        ("constant_zero", bytes(16)),
    ]
    signatures = [bytearray(SIGNATURE_BYTES) for _name, _table in model_tables]
    satisfied = [0, 0, 0]
    equation_path = input_dir / "eq_size5.txt"
    equation_count = 0
    with equation_path.open("r", encoding="utf-8", newline="") as equations:
        for equation_count, raw_line in enumerate(equations, start=1):
            if not raw_line.endswith("\n"):
                raise Stage60SeedFreeError("eq_size5.txt lacks its historical final LF")
            text = raw_line[:-1]
            if text.count("=") != 1:
                raise Stage60SeedFreeError(
                    f"malformed equation text in symbolic fixture at row {equation_count}"
                )
            left, right = text.split("=", 1)
            left_variables = re.findall(r"\b([a-z])\b", left)
            right_variables = re.findall(r"\b([a-z])\b", right)
            if not left_variables or not right_variables:
                raise Stage60SeedFreeError(
                    f"equation side lacks variables at row {equation_count}"
                )
            projection_left_holds = left_variables[0] == right_variables[0]
            projection_right_holds = left_variables[-1] == right_variables[-1]
            left_compound = "◇" in left or "*" in left
            right_compound = "◇" in right or "*" in right
            if left_compound and right_compound:
                constant_zero_holds = True
            elif not left_compound and not right_compound:
                constant_zero_holds = left_variables[0] == right_variables[0]
            else:
                # On a four-element carrier a free variable is not identically 0.
                constant_zero_holds = False
            for model_index, holds in enumerate(
                (projection_left_holds, projection_right_holds, constant_zero_holds)
            ):
                if holds:
                    zero_based = equation_count - 1
                    signatures[model_index][zero_based >> 3] |= 1 << (zero_based & 7)
                    satisfied[model_index] += 1
    if equation_count != EQUATION_COUNT:
        raise Stage60SeedFreeError(
            f"symbolic fixture equation count drift: {equation_count}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    models_path = output_dir / "models.bin"
    with _atomic_binary_output(models_path) as models:
        models.write(MODEL_MAGIC)
        models.write(struct.pack("<I", len(model_tables)))
        for _name, table in model_tables:
            models.write(bytes([4]))
            models.write(table)
    signatures_path = output_dir / "signatures.bin"
    with _atomic_binary_output(signatures_path) as signature_output:
        for signature in signatures:
            signature_output.write(signature)
    if tuple(satisfied) != SYMBOLIC_FIXTURE_SATISFIED:
        raise Stage60SeedFreeError(
            f"symbolic fixture satisfaction-count drift: {tuple(satisfied)}"
        )
    fixture_files = {
        name: verify_file(
            output_dir / name,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
        for name, (expected_bytes, expected_sha256) in SYMBOLIC_FIXTURE_FILES.items()
    }
    return {
        "schema": "stage60-symbolic-signature-fixture-v1",
        "models": [
            {"name": name, "satisfied_equations": count}
            for (name, _table), count in zip(model_tables, satisfied)
        ],
        "equations": equation_count,
        "models_file": {"path": models_path.name, **fixture_files[models_path.name]},
        "signatures_file": {
            "path": signatures_path.name,
            **fixture_files[signatures_path.name],
        },
        "derivation": (
            "Expected signatures are derived from equation text using exact symbolic "
            "projection/constant rules, independently of equations.bin token evaluation."
        ),
    }


__all__: Sequence[str] = (
    "BITSLICE_ENGINE_SHA256",
    "FINAL_284_BYTES",
    "FINAL_284_SHA256",
    "RAW_ARCHIVE_SHA256",
    "RECONSTRUCTED_INPUTS",
    "RECONSTRUCTION_REPORT_SCHEMA",
    "SCALAR_ENGINE_SHA256",
    "SOURCE_324_BYTES",
    "SOURCE_324_SHA256",
    "SYMBOLIC_FIXTURE_FILES",
    "SYMBOLIC_FIXTURE_SATISFIED",
    "Stage60SeedFreeError",
    "copy_file_streaming",
    "build_symbolic_signature_fixture",
    "default_work_dir",
    "extract_engine_source",
    "file_metadata",
    "materialize_source_324_bitset",
    "reconstruct_stage60_inputs",
    "reconstruction_report_for_repository",
    "sha256_path",
    "verify_file",
    "verify_reconstructed_inputs",
    "write_json_atomic",
)
