#!/usr/bin/env python3
"""Shared, bounded helpers for Phase 4 payload and opposite-closure replay."""

from __future__ import annotations

import ast
import base64
import csv
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import lzma
from pathlib import Path
from typing import Iterable, Sequence

from tools.phase2_common import (
    canonical_table_id,
    extract_top_level_literals,
    parse_canonical_table_records,
    validate_canonical_table_record,
)


SCHEMA_VERSION = "1.0.0"
STAGE70 = "70-positive-marginal-core-1470"
STAGE80 = "80-finite149"
STAGE81 = "81-finite149-portable-verification"
STAGE90 = "90-payload-1487"
STAGE100 = "100-opposite-closure-2901"

CORE_COUNT = 1_470
FINITE149_COUNT = 17
EMBEDDED_COUNT = 1_487
EMBEDDED_RAW_BYTES = 111_009
EMBEDDED_RAW_SHA256 = (
    "17240427976219ef8da8b2ecb1bd14731b6c11d3be052711911443539e92a680"
)
EMBEDDED_CANONICAL_ID_VECTOR_SHA256 = (
    "75596a4b3a08e651cf1c152923092b955a7f5cd6a81b65c2978a9cbfd091cd07"
)
EMBEDDED_XZ_BYTES = 28_808
EMBEDDED_XZ_SHA256 = (
    "a9b757ea978411ff982f0a1c0404e0b505be74b8c29481d7eeb81d97a6cd79cc"
)
EMBEDDED_B85_BYTES = 36_010
EMBEDDED_B85_SHA256 = (
    "2b34894f2da26c12476f88473cd4cb2dae77ddbfeeedb2c2d7147d6caf8abb42"
)

SELF_TRANSPOSE_COUNT = 9
EMBEDDED_NONTRIVIAL_TRANSPOSE_SOURCE_COUNT = 64
EMBEDDED_NONTRIVIAL_TRANSPOSE_PAIR_COUNT = 32
DERIVED_TRANSPOSE_COUNT = 1_414
HISTORICAL_REINTRODUCTION_COUNT = 17
HISTORICAL_STAGE10_COUNT = 6
HISTORICAL_STAGE80_COUNT = 11
NEW_RUNTIME_TABLE_COUNT = 1_397
RUNTIME_COUNT = 2_901
DERIVED_RAW_BYTES = 104_424
DERIVED_RAW_SHA256 = (
    "992318b8e336cc8cd232b4012d02a43d906d18d8397b2d67880a533406377f9e"
)
RUNTIME_RAW_BYTES = 215_433
RUNTIME_RAW_SHA256 = (
    "b38ffe73f45ae8780c6cbcbd7904bcc1a5b2947b15789d6c9972394fe695afb7"
)
DERIVED_CANONICAL_ID_VECTOR_SHA256 = (
    "bfe0723f93ad8bedf715814c2608adeae240b5af6027f3a6cedcee06bc72b5bb"
)
RUNTIME_CANONICAL_ID_VECTOR_SHA256 = (
    "42c21dfecfaca35451ad1bc7f1216456ef682aadc6eb7edbf498417d81ae530e"
)

SUBMISSION_RELATIVE = (
    "reproduction/00-submission-anchor/raw/"
    "2026-08-31_marathon_openai-gpt-oss-120b_solver.py"
)
SUBMISSION_SHA256 = (
    "e301cbd091df1376c21ac297e1afb05decb70c34879cd6e485744d09e017c809"
)
FALSE_ENGINE_SHA256 = (
    "f2cc2d09479dff78761c3c34e288b8300105fe95d733e1232def43e9f3bec197"
)
FALSE_ENGINE_SOURCE_LIMIT = 2 * 1024 * 1024
FALSE_ENGINE_FUNCTION_SHA256 = {
    "_table_bytes": "873f934b7ea996a482cca9b437dae9751142580d3496f7fa78169fb47e2e4310",
    "_tables": "1d6e1c4b762e20f3d733d802c3083543eb0309d0cb67d1f053a6724571e75291",
    "_v5_table_key": "ab6d27ad36ef53bf560feca87a2cf1dfba53a883514efb1b6856db0b659b0980",
    "_v5_transpose_table": "092a12af26920432d4a1d9075e375b182d09a8d541a4e030f64bed4fad54042a",
    "_v5_tables_with_all_duals": "0bd86e168bfe481111abac70d3a000dfed75981c0370e3fc7107fbbe065108d9",
}


class Phase4Error(RuntimeError):
    """Raised when a Phase 4 reconstruction invariant drifts."""


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise Phase4Error(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def jsonl_bytes(rows: Iterable[dict[str, object]]) -> bytes:
    return b"".join(compact_json_bytes(row) + b"\n" for row in rows)


def deterministic_gzip(data: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=output, mtime=0, compresslevel=9
    ) as handle:
        handle.write(data)
    return output.getvalue()


def csv_bytes(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def load_gzip_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            ensure(isinstance(value, dict), f"non-object JSONL row: {path}:{line_number}")
            rows.append(value)
    return rows


def table_record_from_row(row: dict[str, object], context: str) -> bytes:
    order = row.get("order")
    entries = row.get("entries")
    ensure(
        isinstance(order, int) and not isinstance(order, bool) and 1 <= order <= 255,
        f"invalid table order: {context}",
    )
    ensure(isinstance(entries, list), f"missing table entries: {context}")
    ensure(
        len(entries) == order * order
        and all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value < order
            for value in entries
        ),
        f"invalid row-major entries: {context}",
    )
    record = bytes([order, *entries])
    ensure(
        row.get("table_id") == canonical_table_id(record),
        f"canonical table ID drift: {context}",
    )
    return record


def compact_json_table_id(record: bytes) -> str:
    order, entries = validate_canonical_table_record(record)
    table = [
        list(entries[row * order : (row + 1) * order]) for row in range(order)
    ]
    return "sha256:" + sha256_bytes(
        json.dumps(table, separators=(",", ":")).encode("utf-8")
    )


def canonical_id_vector_sha256(records: Sequence[bytes]) -> str:
    payload = "".join(
        f"{canonical_table_id(record).removeprefix('sha256:')}\n"
        for record in records
    ).encode("ascii")
    return sha256_bytes(payload)


def historical_id_vector_sha256(records: Sequence[bytes]) -> str:
    payload = "".join(
        f"{compact_json_table_id(record).removeprefix('sha256:')}\n"
        for record in records
    ).encode("ascii")
    return sha256_bytes(payload)


def order_distribution(records: Sequence[bytes]) -> dict[str, int]:
    result: dict[str, int] = {}
    for record in records:
        order = str(record[0])
        result[order] = result.get(order, 0) + 1
    return {key: result[key] for key in sorted(result, key=int)}


def bank_summary(records: Sequence[bytes]) -> dict[str, object]:
    raw = b"".join(records)
    return {
        "canonical_id_vector_sha256": canonical_id_vector_sha256(records),
        "historical_id_vector_sha256": historical_id_vector_sha256(records),
        "order_distribution": order_distribution(records),
        "raw_bytes": len(raw),
        "raw_sha256": sha256_bytes(raw),
        "table_count": len(records),
    }


def transpose_record(record: bytes) -> bytes:
    order, entries = validate_canonical_table_record(record)
    transposed = bytes(
        entries[column * order + row]
        for row in range(order)
        for column in range(order)
    )
    return bytes([order]) + transposed


@dataclass(frozen=True)
class ClosureReplay:
    classifications: tuple[dict[str, object], ...]
    derived_records: tuple[bytes, ...]
    runtime_records: tuple[bytes, ...]
    runtime_scan_rows: tuple[tuple[object, ...], ...]


def replay_runtime_closure(records: Sequence[bytes]) -> ClosureReplay:
    ensure(len(records) == EMBEDDED_COUNT, "embedded record count drift")
    ensure(len(set(records)) == len(records), "embedded payload contains duplicates")
    originals = tuple(records)
    initial_index = {record: index for index, record in enumerate(originals)}
    seen = set(originals)
    derived: list[bytes] = []
    derived_sources: list[int] = []
    classifications: list[dict[str, object]] = []

    for source_index, record in enumerate(originals):
        opposite = transpose_record(record)
        row: dict[str, object] = {
            "order": record[0],
            "schema_version": SCHEMA_VERSION,
            "source_payload_index": source_index,
            "source_table_id": canonical_table_id(record),
            "transpose_table_id": canonical_table_id(opposite),
        }
        if opposite == record:
            row["classification"] = "self-transpose"
            row["existing_payload_index"] = source_index
        elif opposite in initial_index:
            row["classification"] = "nontrivial-transpose-embedded"
            row["existing_payload_index"] = initial_index[opposite]
        else:
            ensure(opposite not in seen, "transpose collided with an earlier derivation")
            runtime_index = EMBEDDED_COUNT + len(derived)
            row["classification"] = "derived-runtime-transpose"
            row["runtime_index"] = runtime_index
            seen.add(opposite)
            derived.append(opposite)
            derived_sources.append(source_index)
        classifications.append(row)

    runtime = originals + tuple(derived)
    scan_rows: list[tuple[object, ...]] = []
    for runtime_index, record in enumerate(originals):
        scan_rows.append(
            (
                runtime_index,
                "embedded",
                runtime_index,
                canonical_table_id(record),
                record[0],
                canonical_table_id(record),
            )
        )
    for offset, record in enumerate(derived):
        runtime_index = EMBEDDED_COUNT + offset
        source_index = derived_sources[offset]
        scan_rows.append(
            (
                runtime_index,
                "derived-transpose",
                source_index,
                canonical_table_id(originals[source_index]),
                record[0],
                canonical_table_id(record),
            )
        )

    counts: dict[str, int] = {}
    for row in classifications:
        key = str(row["classification"])
        counts[key] = counts.get(key, 0) + 1
    ensure(counts.get("self-transpose") == SELF_TRANSPOSE_COUNT, "self-transpose count drift")
    ensure(
        counts.get("nontrivial-transpose-embedded")
        == EMBEDDED_NONTRIVIAL_TRANSPOSE_SOURCE_COUNT,
        "embedded nontrivial-transpose count drift",
    )
    ensure(
        counts.get("derived-runtime-transpose") == DERIVED_TRANSPOSE_COUNT,
        "derived transpose count drift",
    )
    ensure(len(runtime) == RUNTIME_COUNT and len(set(runtime)) == RUNTIME_COUNT, "runtime closure drift")
    return ClosureReplay(
        classifications=tuple(classifications),
        derived_records=tuple(derived),
        runtime_records=runtime,
        runtime_scan_rows=tuple(scan_rows),
    )


def parse_exact_records(raw: bytes, count: int, context: str) -> tuple[bytes, ...]:
    try:
        return parse_canonical_table_records(
            raw, model_count=count, context=context, require_unique=True
        )
    except Exception as exc:
        raise Phase4Error(f"cannot parse {context}: {exc}") from exc


def decode_false_engine_source(launcher_source: bytes) -> bytes:
    """Statically decode the launcher's literal false-engine source bundle."""

    literals = extract_top_level_literals(
        launcher_source,
        (
            "_ENGINE_PAYLOAD_B85",
            "_ENGINE_PAYLOAD_SHA256",
            "_ENGINE_PAYLOAD_FORMAT",
            "_ENGINE_LZMA_DICT_SIZE",
        ),
        context="submitted launcher",
    )
    encoded = literals["_ENGINE_PAYLOAD_B85"]["false"]
    expected = literals["_ENGINE_PAYLOAD_SHA256"]["false"]
    payload_format = literals["_ENGINE_PAYLOAD_FORMAT"]["false"]
    dictionary_size = literals["_ENGINE_LZMA_DICT_SIZE"]
    ensure(isinstance(encoded, bytes), "false engine Base85 literal is not bytes")
    ensure(expected == FALSE_ENGINE_SHA256, "false engine declared SHA-256 drift")
    ensure(payload_format == "utf8_source", "false engine format drift")
    ensure(dictionary_size == 1_048_576, "false engine dictionary-size drift")
    compressed = base64.b85decode(encoded)
    ensure(base64.b85encode(compressed) == encoded, "noncanonical false engine Base85")
    filters = [
        {
            "id": lzma.FILTER_LZMA2,
            "dict_size": dictionary_size,
            "lc": 0,
            "lp": 0,
            "pb": 0,
            "mode": lzma.MODE_NORMAL,
            "nice_len": 273,
            "mf": lzma.MF_BT4,
            "depth": 0,
        }
    ]
    decompressor = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW, filters=filters
    )
    try:
        source = decompressor.decompress(
            compressed, max_length=FALSE_ENGINE_SOURCE_LIMIT + 1
        )
    except lzma.LZMAError as exc:
        raise Phase4Error(f"invalid false engine LZMA payload: {exc}") from exc
    ensure(
        len(source) <= FALSE_ENGINE_SOURCE_LIMIT,
        "false engine source exceeds bound",
    )
    ensure(
        decompressor.eof and not decompressor.unused_data,
        "false engine source is truncated or has trailing data",
    )
    ensure(sha256_bytes(source) == expected, "false engine source SHA-256 drift")
    source.decode("utf-8")
    return source


def audit_false_engine_functions(engine_source: bytes) -> dict[str, object]:
    """Hash the exact submitted functions that decode and close the table bank."""

    text = engine_source.decode("utf-8")
    tree = ast.parse(text)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    rows: list[dict[str, object]] = []
    for name, expected_sha256 in FALSE_ENGINE_FUNCTION_SHA256.items():
        node = functions.get(name)
        ensure(node is not None, f"submitted false engine lacks {name}")
        segment = ast.get_source_segment(text, node)
        ensure(segment is not None, f"cannot recover submitted source for {name}")
        source_bytes = (segment + "\n").encode("utf-8")
        actual_sha256 = sha256_bytes(source_bytes)
        ensure(actual_sha256 == expected_sha256, f"submitted function drift: {name}")
        rows.append(
            {
                "end_line": node.end_lineno,
                "name": name,
                "sha256": actual_sha256,
                "start_line": node.lineno,
            }
        )
    call_lines = [
        index
        for index, line in enumerate(text.splitlines(), start=1)
        if "_v5_tables_with_all_duals()" in line
        and not line.lstrip().startswith("def ")
    ]
    ensure(call_lines == [11_953], "enabled closure-generator call site drift")
    return {
        "engine_bytes": len(engine_source),
        "engine_sha256": sha256_bytes(engine_source),
        "functions": rows,
        "runtime_call_lines": call_lines,
        "schema_version": SCHEMA_VERSION,
        "static_ast_only": True,
    }
