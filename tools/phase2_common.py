#!/usr/bin/env python3
"""Low-memory helpers for Phase 2's 10,059 -> 3,535 table pruning.

Historical solver files are treated strictly as data.  This module parses only
top-level literal assignments with :mod:`ast`; it never imports or executes a
historical solver.  Table banks use the repository's canonical binary record
format: one order byte followed by ``order * order`` row-major entry bytes.
"""

from __future__ import annotations

import ast
import base64
from dataclasses import dataclass
import gzip
import hashlib
import io
import lzma
import os
from pathlib import Path
import struct
import tempfile
from typing import BinaryIO, Iterable, Iterator, Mapping, Sequence


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_ENCODED_BYTES = 2 * 1024 * 1024
MAX_RAW_BYTES = 4 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024

PAIR_BITSET_MAGIC = b"O5RPAIR1" + b"\0" * 8
PAIR_BITSET_VERSION = 1
PAIR_BITSET_HEADER_BYTES = 4096
PAIR_BITSET_BIT_ORDER_CODE = 1
PAIR_BITSET_HEADER_STRUCT = struct.Struct("<16s6I3Q32s")
PAIR_BITSET_DEFAULT_ROWS_PER_CHUNK = 64

D15_SOURCE_PATH = (
    "members/wubing/experiments/solvers/false_solver/drafts/d15/solver.py"
)
D17_SOURCE_PATH = "solvers/false/20260812_d17/solver.py"
D17_REPORT_PATH = "solvers/false/20260812_d17/D17相对D15改动与实验报告.md"
D17_DIRECT_AFFINE_AUDIT_PATH = (
    "members/wubing/experiments/solvers/false_solver/drafts/d17/"
    "audit_static_affine_inventory.py"
)
D17_DIRECT_AFFINE_INVENTORY_PATH = (
    "members/wubing/experiments/solvers/false_solver/drafts/d17/"
    "static-affine-inventory.json"
)

EXPECTED_D15_FILE_SHA256 = (
    "c304fb47a14ecd0b3b8f966847f5e0149e41b0a520a97c38d9e2ebe315ba76a2"
)
EXPECTED_D17_FILE_SHA256 = (
    "edac3c959d912a51c6ee02b87ea3dce56b70738795c9102a284b1200a806145c"
)
EXPECTED_D15_MODEL_COUNT = 10_059
EXPECTED_D15_ENCODED_SHA256 = (
    "4ae818a64f8e2b1ca33770a1d1aa4e11642ef566e1b61c2fd439ea08e8ef3486"
)
EXPECTED_D15_XZ_SHA256 = (
    "865ac41a38f8ba71d372bae3aa0a04ea5b9f839ee48f84857608119a7a395f29"
)
EXPECTED_D15_RAW_SHA256 = (
    "fcb18adf3ff344e51a8f46d3e8eb92f7bb5487f4a3ee5ef74836076d51f3c3d4"
)
EXPECTED_D15_RAW_BYTES = 371_494

EXPECTED_DIRECT_AFFINE_COUNT = 227
EXPECTED_DIRECT_AFFINE_INDEX_SHA256 = (
    "5296c1235e5bfb4f5ebe06e6cf6b71280747f8f09146c1ad8c895042a88b1f8d"
)
EXPECTED_AFFINE_COUNT = 241
EXPECTED_AFFINE_INDEX_SHA256 = (
    "36e0eeef3e8c837512914078e21e91c2f268cb70de58185a10c369a1f107c49e"
)
EXPECTED_AFFINE_RAW_SHA256 = (
    "9668bf54568a49f348264525c8af12f175e295015c986cc689f687756ad0e98f"
)
EXPECTED_AFFINE_RAW_BYTES = 27_835

EXPECTED_NON_AFFINE_COUNT = 9_818
EXPECTED_NON_AFFINE_RAW_SHA256 = (
    "6cc78ed4596369784e331cc7a5dfae7992381bde7377aff2da65bc9c4da9426f"
)
EXPECTED_NON_AFFINE_RAW_BYTES = 343_659
EXPECTED_SMALL_COUNT = 6_283
EXPECTED_SMALL_RAW_SHA256 = (
    "ce1cc3b280cbc57a481fe17fa60fb5ba54b58fee31c3409a788cf9c4d669bca2"
)
EXPECTED_SMALL_RAW_BYTES = 106_028

EXPECTED_D17_MODEL_COUNT = 3_535
EXPECTED_D17_ENCODED_SHA256 = (
    "bf54704f2078603ed9076a0ab6c1d5a4d431f547154985f81a26ec7b6877ddea"
)
EXPECTED_D17_XZ_SHA256 = (
    "9fab4b2ac4ea94401084c26e44289845d42bd587a62e85c69a1d39ac4550c324"
)
EXPECTED_D17_RAW_SHA256 = (
    "7cb270a88641bb5ac6c43ddc22afd7395f54321afa3925454fe15f60d02de02b"
)
EXPECTED_D17_RAW_BYTES = 237_631

EXPECTED_DIRECT_AFFINE_ORDER_COUNTS = (
    (2, 6),
    (3, 6),
    (4, 6),
    (5, 17),
    (7, 31),
    (8, 6),
    (9, 31),
    (11, 92),
    (13, 15),
    (16, 1),
    (17, 13),
    (19, 1),
    (41, 1),
    (43, 1),
)
EXPECTED_AFFINE_ORDER_COUNTS = (
    (2, 6),
    (3, 6),
    (4, 6),
    (5, 20),
    (7, 32),
    (8, 6),
    (9, 37),
    (10, 4),
    (11, 92),
    (13, 15),
    (16, 1),
    (17, 13),
    (19, 1),
    (41, 1),
    (43, 1),
)
EXPECTED_SMALL_ORDER_COUNTS = ((2, 4), (3, 105), (4, 6_174))
EXPECTED_D17_ORDER_COUNTS = (
    (5, 187),
    (6, 1_256),
    (7, 31),
    (8, 803),
    (9, 735),
    (10, 142),
    (11, 12),
    (12, 359),
    (13, 1),
    (16, 3),
    (20, 3),
    (25, 2),
    (32, 1),
)


class Stage50Error(RuntimeError):
    """Raised when a frozen source or a reconstruction invariant drifts."""


class Stage60Error(RuntimeError):
    """Raised when a remaining-pairs bitset or stream invariant drifts."""


@dataclass(frozen=True)
class ScalarAffineWitness:
    """A deterministic affine description in a possibly relabelled carrier.

    ``mapping_to_zn[value]`` maps a stored carrier value to its coordinate in
    ``Z / order Z``.  An identity mapping denotes a table that is already
    scalar-affine in its stored coordinates.
    """

    source_index: int | None
    order: int
    table_id: str
    mapping_to_zn: tuple[int, ...]
    left_coefficient: int
    right_coefficient: int
    constant: int
    classification: str

    @property
    def parameters(self) -> tuple[int, int, int]:
        return self.left_coefficient, self.right_coefficient, self.constant

    @property
    def is_direct(self) -> bool:
        return self.classification == "direct"


@dataclass(frozen=True)
class RelabelledAffineWitness:
    """A carrier relabelling that turns one table into ``a*x+b*y+c mod n``."""

    source_index: int
    order: int
    table_id: str
    mapping_to_zn: tuple[int, ...]
    left_coefficient: int
    right_coefficient: int
    constant: int

    @property
    def parameters(self) -> tuple[int, int, int]:
        return self.left_coefficient, self.right_coefficient, self.constant


@dataclass(frozen=True)
class PairBitsetHeader:
    """Decoded canonical ``O5RPAIR1`` header."""

    version: int
    header_bytes: int
    equation_count: int
    word_count_per_row: int
    row_stride_bytes: int
    bit_order_code: int
    directed_nonreflexive_pair_universe: int
    remaining_pairs: int
    payload_bytes: int
    equations_sha256: str

    @property
    def expected_file_bytes(self) -> int:
        return self.header_bytes + self.payload_bytes

    @property
    def invalid_tail_bits(self) -> int:
        return self.word_count_per_row * 64 - self.equation_count


@dataclass(frozen=True)
class PairBitsetValidation:
    """Result of an exact, forward-only comparison of two pair bitsets."""

    original_header: PairBitsetHeader
    residual_header: PairBitsetHeader
    original_popcount: int
    residual_popcount: int
    removed_popcount: int
    original_active_sources: int
    residual_active_sources: int
    rows_checked: int
    residual_is_subset: bool
    diagonal_bits_all_zero: bool
    out_of_range_bits_all_zero: bool


@dataclass(frozen=True)
class DeterministicGzipCopy:
    """Integrity metadata returned by :func:`write_deterministic_gzip_copy`."""

    uncompressed_bytes: int
    uncompressed_sha256: str
    gzip_bytes: int
    gzip_sha256: str


# These are the fourteen non-direct tables removed between d15 and d17.  The
# mapping is oriented from the stored carrier label to Z/nZ, so every witness
# is checked with m[table[x,y]] = a*m[x] + b*m[y] + c (mod n).
RELABELLED_AFFINE_WITNESSES = (
    RelabelledAffineWitness(
        6353,
        5,
        "sha256:d66a4bc39490d65f495f8ff92124646b878b1769ef7d1110569a1df8cc9793a0",
        (0, 1, 4, 2, 3),
        2,
        1,
        2,
    ),
    RelabelledAffineWitness(
        6384,
        5,
        "sha256:cdd61b0b8a68d54e03185fd31c17b69768257fdded7016321f51e816138a71df",
        (0, 1, 2, 4, 3),
        1,
        2,
        4,
    ),
    RelabelledAffineWitness(
        6411,
        5,
        "sha256:84aa5d51ec4e35a14ffbc1ed72df65336be067f85128dbad3645064eef1a7475",
        (0, 1, 4, 3, 2),
        2,
        4,
        0,
    ),
    RelabelledAffineWitness(
        7733,
        7,
        "sha256:0b117a237ed82b9ae099e306b10ac6e72d70f736598831e84464154d618892fe",
        (0, 1, 6, 2, 5, 3, 4),
        2,
        6,
        0,
    ),
    RelabelledAffineWitness(
        8973,
        9,
        "sha256:22f6c2be257e6196e413314dba2484581cb2464adeecf129347c9c8326ad8435",
        (0, 1, 5, 3, 4, 8, 6, 7, 2),
        1,
        4,
        0,
    ),
    RelabelledAffineWitness(
        8994,
        9,
        "sha256:ba6f870a036cb13a92b93e15726081f42b630302c6b155a1ad082c12b4806d49",
        (0, 1, 5, 3, 4, 8, 6, 7, 2),
        2,
        4,
        0,
    ),
    RelabelledAffineWitness(
        9095,
        9,
        "sha256:924e1055cec973a3c13617e9098e3cbed06d2df64959ed959a850c5a9b472008",
        (0, 1, 5, 3, 4, 8, 6, 7, 2),
        2,
        7,
        0,
    ),
    RelabelledAffineWitness(
        9203,
        9,
        "sha256:9e3f1e9436a2f85282d3c74de1d38f48ae60258d4e95bc2aa1c616861f852901",
        (0, 1, 5, 3, 4, 8, 6, 7, 2),
        1,
        5,
        0,
    ),
    RelabelledAffineWitness(
        9226,
        9,
        "sha256:4f8a5c64a3e48971166959d852d1e9d4e4d9768266abf7e10c31edcb759f3a4d",
        (0, 1, 5, 3, 4, 8, 6, 7, 2),
        4,
        5,
        0,
    ),
    RelabelledAffineWitness(
        9230,
        9,
        "sha256:d0218fcd5ff3609a98f92c55fe09ba15ed0558338fd7dbcfa8c864058e6c8b1a",
        (0, 1, 5, 3, 4, 8, 6, 7, 2),
        5,
        1,
        0,
    ),
    RelabelledAffineWitness(
        9380,
        10,
        "sha256:3df2e7fa8dd142e1ff9b7c6a782ef8ec12154b467a2d5bd5f3e1924a745aecde",
        (0, 2, 4, 6, 8, 1, 3, 5, 7, 9),
        8,
        3,
        1,
    ),
    RelabelledAffineWitness(
        9412,
        10,
        "sha256:616b5d4e25c3d161ae0a3653647cf341a617fb6daab3c3813165504a52cb5837",
        (0, 2, 4, 6, 8, 5, 7, 9, 1, 3),
        9,
        8,
        4,
    ),
    RelabelledAffineWitness(
        9414,
        10,
        "sha256:89553159869b9ee255992b515cfb58a69ceb21527968e93f9febb3d9ff570f04",
        (0, 5, 2, 7, 4, 9, 6, 1, 8, 3),
        8,
        8,
        9,
    ),
    RelabelledAffineWitness(
        9430,
        10,
        "sha256:f20bfb41d3a9629e0b61a8c5a2bf947993195e92c9325e38b12bb5866c4b6088",
        (0, 5, 2, 7, 4, 9, 6, 1, 8, 3),
        4,
        3,
        5,
    ),
)


@dataclass(frozen=True)
class SolverTablePayload:
    """Statically extracted and fully validated table payload."""

    source_sha256: str
    model_count: int
    declared_raw_bytes: int
    encoded: bytes
    compressed: bytes
    raw: bytes
    records: tuple[bytes, ...]

    @property
    def encoded_sha256(self) -> str:
        return sha256_bytes(self.encoded)

    @property
    def compressed_sha256(self) -> str:
        return sha256_bytes(self.compressed)

    @property
    def raw_sha256(self) -> str:
        return sha256_bytes(self.raw)


@dataclass(frozen=True)
class Stage50Reconstruction:
    """Stable-filter outputs; record tuples share the original immutable bytes."""

    input_records: tuple[bytes, ...]
    direct_affine_indices: tuple[int, ...]
    relabelled_affine_indices: tuple[int, ...]
    affine_indices: tuple[int, ...]
    affine_witnesses: tuple[ScalarAffineWitness, ...]
    removed_affine_records: tuple[bytes, ...]
    non_affine_records: tuple[bytes, ...]
    removed_order_le4_records: tuple[bytes, ...]
    final_records: tuple[bytes, ...]

    def summary(self) -> dict[str, object]:
        return {
            "input_count": len(self.input_records),
            "direct_affine_count": len(self.direct_affine_indices),
            "relabelled_affine_count": len(self.relabelled_affine_indices),
            "affine_count": len(self.affine_indices),
            "non_affine_count": len(self.non_affine_records),
            "order_le4_count": len(self.removed_order_le4_records),
            "final_count": len(self.final_records),
            "input_raw_sha256": records_raw_sha256(self.input_records),
            "affine_raw_sha256": records_raw_sha256(
                self.removed_affine_records
            ),
            "non_affine_raw_sha256": records_raw_sha256(
                self.non_affine_records
            ),
            "order_le4_raw_sha256": records_raw_sha256(
                self.removed_order_le4_records
            ),
            "final_raw_sha256": records_raw_sha256(self.final_records),
            "final_order_counts": dict(order_counts(self.final_records)),
        }


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise Stage50Error(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_bounded_file(path: Path, *, limit: int = MAX_SOURCE_BYTES) -> bytes:
    """Read one regular nonsymlink file after enforcing a byte bound."""

    if path.is_symlink() or not path.is_file():
        raise Stage50Error(f"not a regular nonsymlink file: {path}")
    size = path.stat().st_size
    if size > limit:
        raise Stage50Error(f"{path}: {size} bytes exceeds {limit}-byte bound")
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) != size:
        raise Stage50Error(
            f"{path}: size changed while reading (stat={size}, read={len(payload)})"
        )
    return payload


def extract_top_level_literals(
    source: bytes, names: Iterable[str], *, context: str = "<solver>"
) -> dict[str, object]:
    """Extract exactly one literal assignment for each requested top-level name."""

    if len(source) > MAX_SOURCE_BYTES:
        raise Stage50Error(
            f"{context}: source exceeds {MAX_SOURCE_BYTES}-byte AST bound"
        )
    try:
        text = source.decode("utf-8")
        tree = ast.parse(text, filename=context)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise Stage50Error(f"{context}: invalid UTF-8 Python source") from exc

    requested = set(names)
    matches: dict[str, list[ast.expr]] = {name: [] for name in requested}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in requested:
                matches[target.id].append(value)

    result: dict[str, object] = {}
    for name in sorted(requested):
        values = matches[name]
        if len(values) != 1:
            raise Stage50Error(
                f"{context}: expected one top-level assignment to {name}, "
                f"found {len(values)}"
            )
        try:
            result[name] = ast.literal_eval(values[0])
        except (ValueError, TypeError) as exc:
            raise Stage50Error(
                f"{context}: assignment to {name} is not a literal"
            ) from exc
    return result


def _decode_lzma_bounded(
    compressed: bytes, *, expected_size: int, limit: int, context: str
) -> bytes:
    if expected_size < 0 or expected_size > limit:
        raise Stage50Error(
            f"{context}: declared raw size {expected_size} exceeds bound {limit}"
        )
    decompressor = lzma.LZMADecompressor()
    try:
        raw = decompressor.decompress(compressed, max_length=expected_size + 1)
    except lzma.LZMAError as exc:
        raise Stage50Error(f"{context}: invalid XZ/LZMA payload") from exc
    if len(raw) > expected_size:
        raise Stage50Error(f"{context}: decompressed payload exceeds declared size")
    if not decompressor.eof:
        raise Stage50Error(f"{context}: compressed payload is truncated or exceeds bound")
    if decompressor.unused_data:
        raise Stage50Error(f"{context}: trailing data after compressed payload")
    if len(raw) != expected_size:
        raise Stage50Error(
            f"{context}: raw size is {len(raw)}, expected {expected_size}"
        )
    return raw


def extract_solver_table_payload(
    source: bytes,
    *,
    context: str = "<solver>",
    raw_limit: int = MAX_RAW_BYTES,
) -> SolverTablePayload:
    """Safely extract a solver's literal Base85/XZ table bank."""

    literals = extract_top_level_literals(
        source,
        ("_MODEL_COUNT", "_TABLE_RAW_BYTES", "_TABLES_XZ_B85"),
        context=context,
    )
    model_count = literals["_MODEL_COUNT"]
    declared_raw_bytes = literals["_TABLE_RAW_BYTES"]
    encoded_value = literals["_TABLES_XZ_B85"]
    if (
        isinstance(model_count, bool)
        or not isinstance(model_count, int)
        or model_count < 0
    ):
        raise Stage50Error(f"{context}: invalid _MODEL_COUNT")
    if (
        isinstance(declared_raw_bytes, bool)
        or not isinstance(declared_raw_bytes, int)
        or declared_raw_bytes < 0
    ):
        raise Stage50Error(f"{context}: invalid _TABLE_RAW_BYTES")
    if isinstance(encoded_value, str) and encoded_value.isascii():
        encoded = encoded_value.encode("ascii")
    elif isinstance(encoded_value, bytes) and encoded_value.isascii():
        encoded = encoded_value
    else:
        raise Stage50Error(f"{context}: _TABLES_XZ_B85 must be ASCII text or bytes")
    if len(encoded) > MAX_ENCODED_BYTES:
        raise Stage50Error(
            f"{context}: Base85 payload exceeds {MAX_ENCODED_BYTES}-byte bound"
        )
    try:
        compressed = base64.b85decode(encoded)
    except (ValueError, TypeError) as exc:
        raise Stage50Error(f"{context}: invalid Base85 payload") from exc
    if base64.b85encode(compressed) != encoded:
        raise Stage50Error(f"{context}: noncanonical Base85 payload")
    raw = _decode_lzma_bounded(
        compressed,
        expected_size=declared_raw_bytes,
        limit=raw_limit,
        context=context,
    )
    records = parse_canonical_table_records(
        raw, model_count=model_count, context=context
    )
    return SolverTablePayload(
        source_sha256=sha256_bytes(source),
        model_count=model_count,
        declared_raw_bytes=declared_raw_bytes,
        encoded=encoded,
        compressed=compressed,
        raw=raw,
        records=records,
    )


def extract_embedded_false_solver_table_payload(
    launcher_source: bytes,
    *,
    context: str = "<submission launcher>",
    engine_source_limit: int = MAX_SOURCE_BYTES,
    table_raw_limit: int = MAX_RAW_BYTES,
) -> SolverTablePayload:
    """Statically decode a submitted launcher's embedded false-engine tables.

    The final submission wraps the false solver's UTF-8 source in a literal
    Base85/LZMA2 raw stream.  This helper mirrors only that data transform: it
    parses literals with :func:`ast.literal_eval`, verifies the declared engine
    digest, and then applies :func:`extract_solver_table_payload` to the decoded
    source.  No submitted or historical Python is imported, compiled, or run.
    """

    literals = extract_top_level_literals(
        launcher_source,
        (
            "_ENGINE_PAYLOAD_B85",
            "_ENGINE_PAYLOAD_SHA256",
            "_ENGINE_PAYLOAD_FORMAT",
            "_ENGINE_LZMA_DICT_SIZE",
        ),
        context=context,
    )
    encoded_by_side = literals["_ENGINE_PAYLOAD_B85"]
    sha_by_side = literals["_ENGINE_PAYLOAD_SHA256"]
    format_by_side = literals["_ENGINE_PAYLOAD_FORMAT"]
    dictionary_size = literals["_ENGINE_LZMA_DICT_SIZE"]
    if not isinstance(encoded_by_side, dict) or not isinstance(sha_by_side, dict):
        raise Stage50Error(f"{context}: invalid embedded engine dictionaries")
    if not isinstance(format_by_side, dict):
        raise Stage50Error(f"{context}: invalid embedded engine format dictionary")
    encoded = encoded_by_side.get("false")
    expected_sha256 = sha_by_side.get("false")
    payload_format = format_by_side.get("false")
    if not isinstance(encoded, bytes) or len(encoded) > MAX_ENCODED_BYTES:
        raise Stage50Error(f"{context}: invalid false engine Base85 payload")
    if not isinstance(expected_sha256, str) or not _is_canonical_sha256(expected_sha256):
        raise Stage50Error(f"{context}: invalid false engine SHA-256")
    if payload_format != "utf8_source":
        raise Stage50Error(f"{context}: false engine is not declared UTF-8 source")
    if (
        isinstance(dictionary_size, bool)
        or not isinstance(dictionary_size, int)
        or dictionary_size <= 0
        or dictionary_size > 64 * 1024 * 1024
    ):
        raise Stage50Error(f"{context}: invalid LZMA dictionary size")
    try:
        compressed = base64.b85decode(encoded)
    except (ValueError, TypeError) as exc:
        raise Stage50Error(f"{context}: invalid false engine Base85 payload") from exc
    if base64.b85encode(compressed) != encoded:
        raise Stage50Error(f"{context}: noncanonical false engine Base85 payload")
    filters = [{
        "id": lzma.FILTER_LZMA2,
        "dict_size": dictionary_size,
        "lc": 0,
        "lp": 0,
        "pb": 0,
        "mode": lzma.MODE_NORMAL,
        "nice_len": 273,
        "mf": lzma.MF_BT4,
        "depth": 0,
    }]
    decompressor = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=filters,
    )
    try:
        engine_source = decompressor.decompress(
            compressed,
            max_length=engine_source_limit + 1,
        )
    except lzma.LZMAError as exc:
        raise Stage50Error(f"{context}: invalid false engine LZMA payload") from exc
    if len(engine_source) > engine_source_limit:
        raise Stage50Error(f"{context}: false engine source exceeds bounded size")
    if not decompressor.eof or decompressor.unused_data:
        raise Stage50Error(f"{context}: truncated or trailing false engine payload")
    if sha256_bytes(engine_source) != expected_sha256:
        raise Stage50Error(f"{context}: false engine SHA-256 mismatch")
    return extract_solver_table_payload(
        engine_source,
        context=f"{context}#false-engine",
        raw_limit=table_raw_limit,
    )


def _is_canonical_sha256(value: str) -> bool:
    """Return whether ``value`` is one canonical lowercase SHA-256 digest."""

    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def read_solver_table_payload(
    path: Path,
    *,
    expected_file_sha256: str | None = None,
    source_limit: int = MAX_SOURCE_BYTES,
    raw_limit: int = MAX_RAW_BYTES,
) -> SolverTablePayload:
    """Boundedly read and statically extract a historical solver file."""

    source = read_bounded_file(path, limit=source_limit)
    actual_sha256 = sha256_bytes(source)
    if expected_file_sha256 is not None and actual_sha256 != expected_file_sha256:
        raise Stage50Error(
            f"{path}: file SHA-256 drift: expected {expected_file_sha256}, "
            f"got {actual_sha256}"
        )
    return extract_solver_table_payload(source, context=str(path), raw_limit=raw_limit)


def _read_exact(
    handle: BinaryIO,
    size: int,
    *,
    context: str,
    allow_eof: bool = False,
) -> bytes:
    """Read exactly ``size`` bytes from a possibly short-reading stream."""

    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError(f"{context}: invalid read size {size!r}")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = handle.read(remaining)
        if not chunk:
            if allow_eof and remaining == size:
                return b""
            observed = size - remaining
            raise EOFError(
                f"{context}: short stream read ({observed} of {size} bytes)"
            )
        if not isinstance(chunk, bytes):
            chunk = bytes(chunk)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def validate_canonical_table_record(
    record: bytes, *, context: str = "table record"
) -> tuple[int, memoryview]:
    """Validate and return ``(order, row-major entries view)``."""

    if not isinstance(record, bytes) or not record:
        raise Stage50Error(f"{context}: record must be nonempty bytes")
    order = record[0]
    if order == 0:
        raise Stage50Error(f"{context}: zero table order")
    expected = 1 + order * order
    if len(record) != expected:
        raise Stage50Error(
            f"{context}: record has {len(record)} bytes, expected {expected}"
        )
    entries = memoryview(record)[1:]
    if any(value >= order for value in entries):
        raise Stage50Error(f"{context}: entry outside carrier")
    return order, entries


def iter_canonical_table_records(
    handle: BinaryIO,
    *,
    model_count: int | None = None,
    context: str = "table payload",
    require_unique: bool = False,
) -> Iterator[bytes]:
    """Iterate canonical records from a forward-only binary stream.

    When ``model_count`` is supplied, the iterator requires exactly that many
    records and rejects trailing bytes.  Exhausting the returned iterator is
    therefore part of validation.  With ``require_unique=True`` only record
    identities, not the complete bank, are retained in memory.
    """

    if model_count is not None and (
        isinstance(model_count, bool)
        or not isinstance(model_count, int)
        or model_count < 0
    ):
        raise Stage50Error(f"{context}: invalid model count")
    seen: set[bytes] | None = set() if require_unique else None
    index = 0
    while model_count is None or index < model_count:
        try:
            order_raw = _read_exact(
                handle,
                1,
                context=f"{context} record {index} order",
                allow_eof=model_count is None,
            )
        except EOFError as exc:
            raise Stage50Error(str(exc)) from exc
        if not order_raw:
            break
        order = order_raw[0]
        if order == 0:
            raise Stage50Error(f"{context}: zero table order at record {index}")
        try:
            entries = _read_exact(
                handle,
                order * order,
                context=f"{context} record {index} entries",
            )
        except EOFError as exc:
            raise Stage50Error(str(exc)) from exc
        record = order_raw + entries
        validate_canonical_table_record(
            record, context=f"{context} record {index}"
        )
        if seen is not None:
            if record in seen:
                raise Stage50Error(f"{context}: duplicate record {index}")
            seen.add(record)
        yield record
        index += 1

    if model_count is not None:
        trailing = handle.read(1)
        if trailing:
            raise Stage50Error(f"{context}: trailing payload bytes")


def iter_canonical_table_path(
    path: Path,
    *,
    model_count: int | None = None,
    require_unique: bool = False,
) -> Iterator[bytes]:
    """Open ``path`` and stream its canonical table records."""

    if path.is_symlink() or not path.is_file():
        raise Stage50Error(f"not a regular nonsymlink file: {path}")
    with path.open("rb") as handle:
        yield from iter_canonical_table_records(
            handle,
            model_count=model_count,
            context=str(path),
            require_unique=require_unique,
        )


def parse_canonical_table_records(
    raw: bytes,
    *,
    model_count: int,
    context: str = "table payload",
    require_unique: bool = True,
) -> tuple[bytes, ...]:
    """Parse an exact number of canonical records and reject trailing bytes."""

    if not isinstance(raw, bytes):
        raise Stage50Error(f"{context}: raw payload must be bytes")
    return tuple(
        iter_canonical_table_records(
            io.BytesIO(raw),
            model_count=model_count,
            context=context,
            require_unique=require_unique,
        )
    )


def canonical_table_id(record: bytes) -> str:
    validate_canonical_table_record(record)
    return "sha256:" + sha256_bytes(record)


def direct_scalar_affine_parameters(
    record: bytes,
) -> tuple[int, int, int] | None:
    """Recognize ``a*x+b*y+c mod n`` in the record's stored coordinates."""

    order, entries = validate_canonical_table_record(record)
    constant = entries[0]
    if order == 1:
        left = right = 0
    else:
        left = (entries[order] - constant) % order
        right = (entries[1] - constant) % order
    for row in range(order):
        row_offset = row * order
        for column in range(order):
            expected = (left * row + right * column + constant) % order
            if entries[row_offset + column] != expected:
                return None
    return left, right, constant


def verify_relabelled_affine_witness(
    record: bytes,
    witness: RelabelledAffineWitness,
    *,
    require_non_direct: bool = True,
) -> None:
    """Exhaustively verify one explicit carrier-relabelled affine witness."""

    order, entries = validate_canonical_table_record(
        record, context=f"d15 record {witness.source_index}"
    )
    ensure(order == witness.order, f"record {witness.source_index}: order drift")
    ensure(
        canonical_table_id(record) == witness.table_id,
        f"record {witness.source_index}: canonical table ID drift",
    )
    mapping = witness.mapping_to_zn
    ensure(
        len(mapping) == order and tuple(sorted(mapping)) == tuple(range(order)),
        f"record {witness.source_index}: mapping is not a carrier permutation",
    )
    left, right, constant = witness.parameters
    ensure(
        all(0 <= value < order for value in witness.parameters),
        f"record {witness.source_index}: coefficient outside Z/{order}Z",
    )
    for row in range(order):
        row_offset = row * order
        for column in range(order):
            actual = mapping[entries[row_offset + column]]
            expected = (
                left * mapping[row] + right * mapping[column] + constant
            ) % order
            ensure(
                actual == expected,
                f"record {witness.source_index}: relabelled affine cell "
                f"({row}, {column}) failed",
            )
    if require_non_direct:
        ensure(
            direct_scalar_affine_parameters(record) is None,
            f"record {witness.source_index}: expected a non-direct witness",
        )


def verify_scalar_affine_witness(
    record: bytes, witness: ScalarAffineWitness
) -> None:
    """Exhaustively check a direct or carrier-relabelled affine witness."""

    order, entries = validate_canonical_table_record(record)
    ensure(order == witness.order, "scalar-affine witness order drift")
    ensure(
        canonical_table_id(record) == witness.table_id,
        "scalar-affine witness table ID drift",
    )
    mapping = witness.mapping_to_zn
    ensure(
        len(mapping) == order and tuple(sorted(mapping)) == tuple(range(order)),
        "scalar-affine witness mapping is not a carrier permutation",
    )
    ensure(
        witness.classification in ("direct", "carrier-relabelled"),
        "invalid scalar-affine witness classification",
    )
    if witness.classification == "direct":
        ensure(mapping == tuple(range(order)), "direct witness mapping is not identity")
    left, right, constant = witness.parameters
    ensure(
        all(0 <= value < order for value in witness.parameters),
        f"scalar-affine coefficient outside Z/{order}Z",
    )
    for row in range(order):
        row_offset = row * order
        for column in range(order):
            actual = mapping[entries[row_offset + column]]
            expected = (
                left * mapping[row] + right * mapping[column] + constant
            ) % order
            ensure(
                actual == expected,
                f"scalar-affine witness cell ({row}, {column}) failed",
            )


def stage50_scalar_affine_witness(
    record: bytes, *, source_index: int | None = None
) -> ScalarAffineWitness | None:
    """Classify one record under Stage 50's complete frozen affine inventory.

    The direct test is formulaic.  The only additional affine records in the
    frozen 10,059-table bank are the fourteen byte-identified, exhaustively
    checked carrier relabellings in :data:`RELABELLED_AFFINE_WITNESSES`.
    Their mappings are frozen to make the witness deterministic rather than
    depending on permutation-search order.
    """

    order, _entries = validate_canonical_table_record(record)
    parameters = direct_scalar_affine_parameters(record)
    if parameters is not None:
        witness = ScalarAffineWitness(
            source_index=source_index,
            order=order,
            table_id=canonical_table_id(record),
            mapping_to_zn=tuple(range(order)),
            left_coefficient=parameters[0],
            right_coefficient=parameters[1],
            constant=parameters[2],
            classification="direct",
        )
        verify_scalar_affine_witness(record, witness)
        return witness

    table_id = canonical_table_id(record)
    matches = tuple(
        item for item in RELABELLED_AFFINE_WITNESSES if item.table_id == table_id
    )
    if not matches:
        return None
    ensure(len(matches) == 1, f"duplicate frozen witness for {table_id}")
    frozen = matches[0]
    if source_index is not None:
        ensure(
            source_index == frozen.source_index,
            f"carrier-relabelled affine source-index drift for {table_id}",
        )
    verify_relabelled_affine_witness(record, frozen)
    witness = ScalarAffineWitness(
        source_index=frozen.source_index if source_index is None else source_index,
        order=frozen.order,
        table_id=frozen.table_id,
        mapping_to_zn=frozen.mapping_to_zn,
        left_coefficient=frozen.left_coefficient,
        right_coefficient=frozen.right_coefficient,
        constant=frozen.constant,
        classification="carrier-relabelled",
    )
    verify_scalar_affine_witness(record, witness)
    return witness


def records_raw_sha256(records: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for record in records:
        validate_canonical_table_record(record)
        digest.update(record)
    return digest.hexdigest()


def records_raw_size(records: Iterable[bytes]) -> int:
    total = 0
    for record in records:
        validate_canonical_table_record(record)
        total += len(record)
    return total


def write_canonical_table_records(records: Iterable[bytes], handle: BinaryIO) -> int:
    """Write records without assembling another in-memory bank; return byte count."""

    total = 0
    for record in records:
        validate_canonical_table_record(record)
        handle.write(record)
        total += len(record)
    return total


def order_counts(records: Iterable[bytes]) -> tuple[tuple[int, int], ...]:
    counts: dict[int, int] = {}
    for record in records:
        order, _entries = validate_canonical_table_record(record)
        counts[order] = counts.get(order, 0) + 1
    return tuple(sorted(counts.items()))


def index_lines_sha256(indices: Iterable[int]) -> str:
    digest = hashlib.sha256()
    for index in indices:
        digest.update(str(index).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _verify_record_collection(
    records: Sequence[bytes],
    *,
    label: str,
    expected_count: int,
    expected_bytes: int,
    expected_sha256: str,
    expected_order_counts: tuple[tuple[int, int], ...] | None = None,
) -> None:
    ensure(len(records) == expected_count, f"{label}: count drift")
    ensure(records_raw_size(records) == expected_bytes, f"{label}: byte-size drift")
    ensure(
        records_raw_sha256(records) == expected_sha256,
        f"{label}: raw SHA-256 drift",
    )
    if expected_order_counts is not None:
        ensure(
            order_counts(records) == expected_order_counts,
            f"{label}: order distribution drift",
        )


def prune_stage50_records(records: Sequence[bytes]) -> Stage50Reconstruction:
    """Perform the historical stable 10,059 -> 9,818 -> 3,535 filtering."""

    input_records = tuple(records)
    _verify_record_collection(
        input_records,
        label="d15 input",
        expected_count=EXPECTED_D15_MODEL_COUNT,
        expected_bytes=EXPECTED_D15_RAW_BYTES,
        expected_sha256=EXPECTED_D15_RAW_SHA256,
    )

    direct_indices = tuple(
        index
        for index, record in enumerate(input_records)
        if direct_scalar_affine_parameters(record) is not None
    )
    ensure(
        len(direct_indices) == EXPECTED_DIRECT_AFFINE_COUNT,
        "direct affine count drift",
    )
    ensure(
        index_lines_sha256(direct_indices) == EXPECTED_DIRECT_AFFINE_INDEX_SHA256,
        "direct affine index vector drift",
    )
    direct_records = tuple(input_records[index] for index in direct_indices)
    ensure(
        order_counts(direct_records) == EXPECTED_DIRECT_AFFINE_ORDER_COUNTS,
        "direct affine order distribution drift",
    )

    relabelled_indices: list[int] = []
    for witness in RELABELLED_AFFINE_WITNESSES:
        ensure(
            0 <= witness.source_index < len(input_records),
            f"relabelled witness index outside d15: {witness.source_index}",
        )
        verify_relabelled_affine_witness(
            input_records[witness.source_index], witness
        )
        relabelled_indices.append(witness.source_index)
    ensure(
        len(set(relabelled_indices)) == len(RELABELLED_AFFINE_WITNESSES),
        "duplicate relabelled affine witness index",
    )
    ensure(
        not set(direct_indices).intersection(relabelled_indices),
        "direct and relabelled affine classifications overlap",
    )
    affine_indices = tuple(sorted((*direct_indices, *relabelled_indices)))
    ensure(len(affine_indices) == EXPECTED_AFFINE_COUNT, "affine count drift")
    ensure(
        index_lines_sha256(affine_indices) == EXPECTED_AFFINE_INDEX_SHA256,
        "affine index vector drift",
    )

    affine_set = set(affine_indices)
    removed_affine = tuple(input_records[index] for index in affine_indices)
    non_affine = tuple(
        record for index, record in enumerate(input_records) if index not in affine_set
    )
    _verify_record_collection(
        removed_affine,
        label="removed scalar-affine records",
        expected_count=EXPECTED_AFFINE_COUNT,
        expected_bytes=EXPECTED_AFFINE_RAW_BYTES,
        expected_sha256=EXPECTED_AFFINE_RAW_SHA256,
        expected_order_counts=EXPECTED_AFFINE_ORDER_COUNTS,
    )
    _verify_record_collection(
        non_affine,
        label="non-affine 9,818 bank",
        expected_count=EXPECTED_NON_AFFINE_COUNT,
        expected_bytes=EXPECTED_NON_AFFINE_RAW_BYTES,
        expected_sha256=EXPECTED_NON_AFFINE_RAW_SHA256,
    )

    removed_small = tuple(record for record in non_affine if record[0] <= 4)
    final_records = tuple(record for record in non_affine if record[0] > 4)
    _verify_record_collection(
        removed_small,
        label="removed order-at-most-4 records",
        expected_count=EXPECTED_SMALL_COUNT,
        expected_bytes=EXPECTED_SMALL_RAW_BYTES,
        expected_sha256=EXPECTED_SMALL_RAW_SHA256,
        expected_order_counts=EXPECTED_SMALL_ORDER_COUNTS,
    )
    _verify_record_collection(
        final_records,
        label="final 3,535 bank",
        expected_count=EXPECTED_D17_MODEL_COUNT,
        expected_bytes=EXPECTED_D17_RAW_BYTES,
        expected_sha256=EXPECTED_D17_RAW_SHA256,
        expected_order_counts=EXPECTED_D17_ORDER_COUNTS,
    )
    return Stage50Reconstruction(
        input_records=input_records,
        direct_affine_indices=direct_indices,
        relabelled_affine_indices=tuple(relabelled_indices),
        affine_indices=affine_indices,
        affine_witnesses=tuple(
            witness
            for index, record in enumerate(input_records)
            if (witness := stage50_scalar_affine_witness(record, source_index=index))
            is not None
        ),
        removed_affine_records=removed_affine,
        non_affine_records=non_affine,
        removed_order_le4_records=removed_small,
        final_records=final_records,
    )


def verify_expected_d15_payload(payload: SolverTablePayload) -> None:
    ensure(payload.model_count == EXPECTED_D15_MODEL_COUNT, "d15 model count drift")
    ensure(
        payload.declared_raw_bytes == EXPECTED_D15_RAW_BYTES,
        "d15 declared raw byte count drift",
    )
    ensure(
        payload.encoded_sha256 == EXPECTED_D15_ENCODED_SHA256,
        "d15 Base85 SHA-256 drift",
    )
    ensure(
        payload.compressed_sha256 == EXPECTED_D15_XZ_SHA256,
        "d15 XZ SHA-256 drift",
    )
    ensure(payload.raw_sha256 == EXPECTED_D15_RAW_SHA256, "d15 raw SHA-256 drift")


def verify_expected_d17_payload(payload: SolverTablePayload) -> None:
    ensure(payload.model_count == EXPECTED_D17_MODEL_COUNT, "d17 model count drift")
    ensure(
        payload.declared_raw_bytes == EXPECTED_D17_RAW_BYTES,
        "d17 declared raw byte count drift",
    )
    ensure(
        payload.encoded_sha256 == EXPECTED_D17_ENCODED_SHA256,
        "d17 Base85 SHA-256 drift",
    )
    ensure(
        payload.compressed_sha256 == EXPECTED_D17_XZ_SHA256,
        "d17 XZ SHA-256 drift",
    )
    ensure(payload.raw_sha256 == EXPECTED_D17_RAW_SHA256, "d17 raw SHA-256 drift")


def reconstruct_stage50(
    d15_payload: SolverTablePayload,
    d17_payload: SolverTablePayload | None = None,
) -> Stage50Reconstruction:
    """Strictly rebuild Stage 50 and optionally compare the published d17 bank."""

    verify_expected_d15_payload(d15_payload)
    result = prune_stage50_records(d15_payload.records)
    if d17_payload is not None:
        verify_expected_d17_payload(d17_payload)
        ensure(
            result.final_records == d17_payload.records,
            "stable-filter result differs from the published d17 record sequence",
        )
    return result


def reconstruct_stage50_sources(
    d15_source: bytes,
    d17_source: bytes | None = None,
    *,
    enforce_file_hashes: bool = True,
) -> Stage50Reconstruction:
    """Convenience entry point for captured source-member bytes."""

    if enforce_file_hashes:
        ensure(
            sha256_bytes(d15_source) == EXPECTED_D15_FILE_SHA256,
            "d15 source file SHA-256 drift",
        )
        if d17_source is not None:
            ensure(
                sha256_bytes(d17_source) == EXPECTED_D17_FILE_SHA256,
                "d17 source file SHA-256 drift",
            )
    d15_payload = extract_solver_table_payload(d15_source, context=D15_SOURCE_PATH)
    d17_payload = (
        None
        if d17_source is None
        else extract_solver_table_payload(d17_source, context=D17_SOURCE_PATH)
    )
    return reconstruct_stage50(d15_payload, d17_payload)


def load_and_reconstruct_stage50(
    d15_path: Path, d17_path: Path | None = None
) -> Stage50Reconstruction:
    """Convenience entry point for a capture command operating on local paths."""

    d15_payload = read_solver_table_payload(
        d15_path, expected_file_sha256=EXPECTED_D15_FILE_SHA256
    )
    d17_payload = (
        None
        if d17_path is None
        else read_solver_table_payload(
            d17_path, expected_file_sha256=EXPECTED_D17_FILE_SHA256
        )
    )
    return reconstruct_stage50(d15_payload, d17_payload)


def _ensure60(condition: bool, message: str) -> None:
    if not condition:
        raise Stage60Error(message)


def sha256_path(path: Path) -> str:
    """Hash a file in bounded chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(STREAM_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_deterministic_gzip_copy(
    source: BinaryIO, output: Path
) -> DeterministicGzipCopy:
    """Copy a stream to deterministic gzip while hashing the source and result."""

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=output.name + ".", dir=output.parent
    )
    temporary = Path(temporary_name)
    source_digest = hashlib.sha256()
    source_bytes = 0
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
            ) as compressed:
                while True:
                    chunk = source.read(STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        chunk = bytes(chunk)
                    source_digest.update(chunk)
                    source_bytes += len(chunk)
                    compressed.write(chunk)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return DeterministicGzipCopy(
        uncompressed_bytes=source_bytes,
        uncompressed_sha256=source_digest.hexdigest(),
        gzip_bytes=output.stat().st_size,
        gzip_sha256=sha256_path(output),
    )


def parse_pair_bitset_header(
    block: bytes, *, context: str = "remaining-pairs bitset"
) -> PairBitsetHeader:
    """Parse and strictly validate a complete 4,096-byte ``O5RPAIR1`` header."""

    _ensure60(
        len(block) == PAIR_BITSET_HEADER_BYTES,
        f"{context}: header is {len(block)} bytes, expected {PAIR_BITSET_HEADER_BYTES}",
    )
    try:
        values = PAIR_BITSET_HEADER_STRUCT.unpack_from(block)
    except struct.error as exc:
        raise Stage60Error(f"{context}: truncated header structure") from exc
    (
        magic,
        version,
        header_bytes,
        equation_count,
        word_count,
        row_stride,
        bit_order,
        pair_universe,
        remaining_pairs,
        payload_bytes,
        equations_sha,
    ) = values
    _ensure60(magic == PAIR_BITSET_MAGIC, f"{context}: magic drift")
    _ensure60(version == PAIR_BITSET_VERSION, f"{context}: version drift")
    _ensure60(
        header_bytes == PAIR_BITSET_HEADER_BYTES,
        f"{context}: header-size drift",
    )
    _ensure60(equation_count == 62_576, f"{context}: equation-count drift")
    _ensure60(word_count == 978, f"{context}: word-count drift")
    _ensure60(row_stride == word_count * 8, f"{context}: row-stride drift")
    _ensure60(bit_order == PAIR_BITSET_BIT_ORDER_CODE, f"{context}: bit order drift")
    _ensure60(
        pair_universe == equation_count * (equation_count - 1),
        f"{context}: directed-pair universe drift",
    )
    _ensure60(
        payload_bytes == equation_count * row_stride,
        f"{context}: payload-size drift",
    )
    _ensure60(
        equations_sha.hex()
        == "7fb9c0e85bee412baa7030bafec311c65a75502a2c25bdd0b94171b324585b1d",
        f"{context}: equation digest drift",
    )
    _ensure60(
        not any(block[PAIR_BITSET_HEADER_STRUCT.size :]),
        f"{context}: nonzero reserved header bytes",
    )
    return PairBitsetHeader(
        version=version,
        header_bytes=header_bytes,
        equation_count=equation_count,
        word_count_per_row=word_count,
        row_stride_bytes=row_stride,
        bit_order_code=bit_order,
        directed_nonreflexive_pair_universe=pair_universe,
        remaining_pairs=remaining_pairs,
        payload_bytes=payload_bytes,
        equations_sha256=equations_sha.hex(),
    )


def _read_exact60(handle: BinaryIO, size: int, context: str) -> bytes:
    try:
        return _read_exact(handle, size, context=context)
    except EOFError as exc:
        raise Stage60Error(str(exc)) from exc


def validate_pair_bitset_streams(
    original: BinaryIO,
    residual: BinaryIO,
    *,
    expected_rows: Iterable[tuple[int, int, int, int]] | None = None,
    context: str = "324M/284M pair bitsets",
) -> PairBitsetValidation:
    """Validate the two bitsets in one bounded, forward-only pass.

    ``expected_rows``, when supplied, contains
    ``(source_id, original_count, removed_count, residual_count)``.  This lets
    the caller bind the bit-level evidence to a separately parsed row ledger
    without retaining either 467 MiB payload.
    """

    original_header = parse_pair_bitset_header(
        _read_exact60(original, PAIR_BITSET_HEADER_BYTES, f"{context} original header"),
        context=f"{context} original",
    )
    residual_header = parse_pair_bitset_header(
        _read_exact60(residual, PAIR_BITSET_HEADER_BYTES, f"{context} residual header"),
        context=f"{context} residual",
    )
    comparable = (
        "version",
        "header_bytes",
        "equation_count",
        "word_count_per_row",
        "row_stride_bytes",
        "bit_order_code",
        "directed_nonreflexive_pair_universe",
        "payload_bytes",
        "equations_sha256",
    )
    for field in comparable:
        _ensure60(
            getattr(original_header, field) == getattr(residual_header, field),
            f"{context}: header field {field} differs",
        )

    expected_iterator = iter(expected_rows) if expected_rows is not None else None
    original_total = 0
    residual_total = 0
    original_active = 0
    residual_active = 0
    invalid_bits = original_header.invalid_tail_bits
    invalid_mask = (
        ((1 << invalid_bits) - 1) << (64 - invalid_bits)
        if invalid_bits
        else 0
    )

    for row_index in range(original_header.equation_count):
        original_row = _read_exact60(
            original,
            original_header.row_stride_bytes,
            f"{context} original row {row_index + 1}",
        )
        residual_row = _read_exact60(
            residual,
            residual_header.row_stride_bytes,
            f"{context} residual row {row_index + 1}",
        )
        # One 7,824-byte row becomes one bounded Python integer.  The bin/count
        # fallback keeps the verifier compatible with Python 3.9, where
        # int.bit_count is unavailable, while doing the heavy scan in C rather
        # than issuing 978 Python-level word operations per row.
        original_value = int.from_bytes(original_row, "little")
        residual_value = int.from_bytes(residual_row, "little")
        _ensure60(
            residual_value & ~original_value == 0,
            f"{context}: residual is not a subset at Equation{row_index + 1}",
        )
        original_count = bin(original_value).count("1")
        residual_count = bin(residual_value).count("1")
        if invalid_mask:
            original_last = int.from_bytes(original_row[-8:], "little")
            residual_last = int.from_bytes(residual_row[-8:], "little")
            _ensure60(
                not (original_last & invalid_mask)
                and not (residual_last & invalid_mask),
                f"{context}: out-of-range tail bit set at Equation{row_index + 1}",
            )

        original_diagonal = original_value & (1 << row_index)
        residual_diagonal = residual_value & (1 << row_index)
        _ensure60(
            not original_diagonal and not residual_diagonal,
            f"{context}: diagonal bit set at Equation{row_index + 1}",
        )

        removed_count = original_count - residual_count
        if expected_iterator is not None:
            try:
                expected = next(expected_iterator)
            except StopIteration as exc:
                raise Stage60Error(
                    f"{context}: row ledger ended before Equation{row_index + 1}"
                ) from exc
            _ensure60(
                expected
                == (row_index + 1, original_count, removed_count, residual_count),
                f"{context}: row ledger drift at Equation{row_index + 1}",
            )

        original_total += original_count
        residual_total += residual_count
        original_active += original_count > 0
        residual_active += residual_count > 0

    if expected_iterator is not None:
        try:
            extra = next(expected_iterator)
        except StopIteration:
            extra = None
        _ensure60(extra is None, f"{context}: row ledger has trailing rows")
    _ensure60(not original.read(1), f"{context}: original stream has trailing bytes")
    _ensure60(not residual.read(1), f"{context}: residual stream has trailing bytes")
    _ensure60(
        original_total == original_header.remaining_pairs,
        f"{context}: original payload/header popcount drift",
    )
    _ensure60(
        residual_total == residual_header.remaining_pairs,
        f"{context}: residual payload/header popcount drift",
    )
    return PairBitsetValidation(
        original_header=original_header,
        residual_header=residual_header,
        original_popcount=original_total,
        residual_popcount=residual_total,
        removed_popcount=original_total - residual_total,
        original_active_sources=original_active,
        residual_active_sources=residual_active,
        rows_checked=original_header.equation_count,
        residual_is_subset=True,
        diagonal_bits_all_zero=True,
        out_of_range_bits_all_zero=True,
    )
