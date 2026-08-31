#!/usr/bin/env python3
"""Build the bounded-memory correction record for the merged Stage 80 evidence."""

from __future__ import annotations

import argparse
import ast
import base64
import csv
import gzip
import hashlib
import io
import itertools
import json
import lzma
import re
import sys
import tarfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable


STAGE_ID = "81-finite149-portable-verification"
STAGE80 = "80-finite149"
STAGE70 = "70-positive-marginal-core-1470"
SCHEMA_VERSION = "1.0.0"
CAPTURED_AT = "2026-08-31T19:05:54+08:00"
RAW_MEMBER = "source/upstream/finite_outcomes.json.gz"
EXPECTED_EQUATION_COUNT = 4_694
EXPECTED_SELECTED_CELLS = 789
EXPECTED_FINITE_DIRECTIONS = 149
EXPECTED_BASE_TABLES = 17
EXPECTED_REQUIRED_TRANSPOSES = 11
EXPECTED_ORIENTATION_USAGE = {"direct": 129, "transpose": 20}
EXPECTED_SUBMITTED_RECORDS = 1_487
SUBMISSION_RELATIVE = (
    "reproduction/00-submission-anchor/raw/"
    "2026-08-31_marathon_openai-gpt-oss-120b_solver.py"
)
EXPECTED_FINITE_OUTCOMES_SHA256 = (
    "257f9e97bac460e3dcdb74469d95783a640c797d8d3423b8e9dbef95e5db52d5"
)
EXPECTED_STAGE80_RAW_SHA256 = (
    "15dcc1152d014e4a18996d160f0471e85e3c47f7227450c1c2ed2b8bf1dbc237"
)
JSON_CHUNK_BYTES = 64 * 1024
JSON_BUFFER_LIMIT_BYTES = 256 * 1024
OUTCOME_STATUSES = {
    "explicit_proof_false",
    "explicit_proof_true",
    "implicit_proof_false",
    "implicit_proof_true",
    "unknown",
}
LEAN_TABLE_RE = re.compile(
    r"This file is generated from the following operator table:\s*"
    r"(\[\[.*?\]\])\s*-/",
    re.DOTALL,
)


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


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


def gzip_bytes(data: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=output, mtime=0, compresslevel=9
    ) as handle:
        handle.write(data)
    return output.getvalue()


def write_bytes(stage_dir: Path, relative: str, data: bytes) -> None:
    path = stage_dir / Path(PurePosixPath(relative))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def load_csv(body: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))


def load_jsonl(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line]


def load_gzip_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_snapshot(path: Path) -> tuple[dict[str, bytes], dict[str, object]]:
    """Read the small outer archive while keeping the nested 499 MB JSON compressed."""

    members: dict[str, bytes] = {}
    with tarfile.open(path, mode="r:gz") as archive:
        for member in archive:
            pure_name = PurePosixPath(member.name)
            ensure(
                member.isfile()
                and member.name
                and not member.name.startswith("/")
                and ".." not in pure_name.parts,
                f"unsafe Stage 80 raw member: {member.name}",
            )
            ensure(member.name not in members, f"duplicate raw member: {member.name}")
            extracted = archive.extractfile(member)
            ensure(extracted is not None, f"cannot read raw member: {member.name}")
            body = extracted.read()
            ensure(len(body) == member.size, f"truncated raw member: {member.name}")
            members[member.name] = body

    metadata = json.loads(members["snapshot-metadata.json"])
    declared = metadata["source_files"]
    ensure(len(declared) + 1 == len(members), "raw snapshot member-count drift")
    for row in declared:
        body = members[row["archive_path"]]
        ensure(len(body) == row["bytes"], f"raw member size drift: {row['archive_path']}")
        ensure(
            sha256_bytes(body) == row["sha256"],
            f"raw member hash drift: {row['archive_path']}",
        )
    return members, metadata


class ChunkedJSONReader:
    """Bounded incremental JSON reader for one value at a time."""

    def __init__(
        self,
        stream: BinaryIO,
        *,
        chunk_bytes: int = JSON_CHUNK_BYTES,
        buffer_limit_bytes: int = JSON_BUFFER_LIMIT_BYTES,
    ) -> None:
        ensure(chunk_bytes > 0, "chunk size must be positive")
        ensure(buffer_limit_bytes >= chunk_bytes, "buffer limit is smaller than chunk")
        self.stream = stream
        self.chunk_bytes = chunk_bytes
        self.buffer_limit_bytes = buffer_limit_bytes
        self.buffer = bytearray()
        self.position = 0
        self.eof = False
        self.total_bytes_read = 0
        self.max_buffer_bytes = 0
        self.max_decoded_value_bytes = 0
        self.decoder = json.JSONDecoder()

    def _available(self) -> int:
        return len(self.buffer) - self.position

    def _compact(self) -> None:
        if self.position:
            del self.buffer[: self.position]
            self.position = 0

    def _fill(self) -> bool:
        if self.eof:
            return False
        self._compact()
        available = len(self.buffer)
        ensure(
            available < self.buffer_limit_bytes,
            f"JSON value exceeds {self.buffer_limit_bytes} byte buffer limit",
        )
        request = min(self.chunk_bytes, self.buffer_limit_bytes - available)
        chunk = self.stream.read(request)
        if not chunk:
            self.eof = True
            return False
        self.buffer.extend(chunk)
        self.total_bytes_read += len(chunk)
        self.max_buffer_bytes = max(self.max_buffer_bytes, len(self.buffer))
        return True

    def _ensure_available(self) -> bool:
        return self._available() > 0 or self._fill()

    def skip_whitespace(self) -> None:
        while True:
            if not self._ensure_available():
                return
            while self.position < len(self.buffer) and self.buffer[self.position] in b" \t\r\n":
                self.position += 1
            if self.position < len(self.buffer):
                return

    def take_byte(self) -> int:
        self.skip_whitespace()
        ensure(self._ensure_available(), "unexpected end of JSON stream")
        value = self.buffer[self.position]
        self.position += 1
        return value

    def expect_byte(self, expected: int) -> None:
        actual = self.take_byte()
        ensure(
            actual == expected,
            f"expected JSON byte {chr(expected)!r}; found {chr(actual)!r}",
        )

    def decode_value(self) -> object:
        self.skip_whitespace()
        ensure(self._ensure_available(), "unexpected end before JSON value")
        while True:
            raw = bytes(self.buffer[self.position :])
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                if not self.eof and exc.end == len(raw):
                    self._fill()
                    continue
                raise RuntimeError("invalid UTF-8 in JSON stream") from exc
            try:
                value, character_end = self.decoder.raw_decode(text)
            except json.JSONDecodeError as exc:
                if self.eof:
                    raise RuntimeError("invalid or truncated JSON value") from exc
                self._fill()
                continue
            consumed = len(text[:character_end].encode("utf-8"))
            ensure(consumed > 0, "JSON decoder consumed no bytes")
            self.position += consumed
            self.max_decoded_value_bytes = max(
                self.max_decoded_value_bytes, consumed
            )
            return value

    def finish(self) -> None:
        self.skip_whitespace()
        ensure(not self._ensure_available(), "trailing bytes after top-level JSON object")


def target_coordinates(
    labels: list[dict[str, str]], equation_count: int
) -> tuple[dict[int, set[int]], set[tuple[int, int]]]:
    by_row: dict[int, set[int]] = defaultdict(set)
    coordinates: set[tuple[int, int]] = set()
    for label in labels:
        lhs_id = int(label["lhs_id"])
        rhs_id = int(label["rhs_id"])
        ensure(
            1 <= lhs_id <= equation_count and 1 <= rhs_id <= equation_count,
            f"finite-outcome coordinate outside 1..{equation_count}: {lhs_id},{rhs_id}",
        )
        coordinate = (lhs_id - 1, rhs_id - 1)
        ensure(coordinate not in coordinates, f"duplicate finite-outcome coordinate: {coordinate}")
        coordinates.add(coordinate)
        by_row[coordinate[0]].add(coordinate[1])
    return dict(by_row), coordinates


def stream_finite_outcomes(
    compressed: bytes,
    coordinates_by_row: dict[int, set[int]],
    *,
    expected_equation_count: int = EXPECTED_EQUATION_COUNT,
    chunk_bytes: int = JSON_CHUNK_BYTES,
    buffer_limit_bytes: int = JSON_BUFFER_LIMIT_BYTES,
) -> tuple[list[str], dict[tuple[int, int], str], dict[str, object]]:
    """Parse every matrix row while retaining only the requested cells."""

    ensure(len(compressed) >= 18, "finite-outcomes gzip member is too short")
    expected_uncompressed_bytes = int.from_bytes(compressed[-4:], "little")
    projection: dict[tuple[int, int], str] = {}
    observed_statuses: set[str] = set()
    row_count = 0
    cell_count = 0
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as handle:
        reader = ChunkedJSONReader(
            handle,
            chunk_bytes=chunk_bytes,
            buffer_limit_bytes=buffer_limit_bytes,
        )
        reader.expect_byte(ord("{"))
        ensure(reader.decode_value() == "equations", "first top-level key is not equations")
        reader.expect_byte(ord(":"))
        equations = reader.decode_value()
        ensure(isinstance(equations, list), "equations is not a JSON array")
        expected_equations = [
            f"Equation{index}" for index in range(1, expected_equation_count + 1)
        ]
        ensure(equations == expected_equations, "equation vector/order drift")
        reader.expect_byte(ord(","))
        ensure(reader.decode_value() == "outcomes", "second top-level key is not outcomes")
        reader.expect_byte(ord(":"))
        reader.expect_byte(ord("["))

        while True:
            row = reader.decode_value()
            ensure(isinstance(row, list), f"outcome row {row_count} is not an array")
            ensure(
                len(row) == expected_equation_count,
                f"outcome row {row_count} has {len(row)} columns",
            )
            row_statuses = set(row)
            ensure(
                all(isinstance(value, str) for value in row),
                f"outcome row {row_count} contains a non-string value",
            )
            ensure(
                row_statuses.issubset(OUTCOME_STATUSES),
                f"outcome row {row_count} contains unknown statuses: "
                f"{sorted(row_statuses - OUTCOME_STATUSES)}",
            )
            observed_statuses.update(row_statuses)
            for column in coordinates_by_row.get(row_count, set()):
                projection[(row_count, column)] = row[column]
            row_count += 1
            cell_count += len(row)
            separator = reader.take_byte()
            if separator == ord(","):
                continue
            ensure(separator == ord("]"), "outcomes array has an invalid separator")
            break

        reader.expect_byte(ord("}"))
        reader.finish()

    ensure(row_count == expected_equation_count, f"outcome row count drift: {row_count}")
    ensure(
        reader.total_bytes_read == expected_uncompressed_bytes,
        "finite-outcomes uncompressed byte count disagrees with gzip ISIZE",
    )
    expected_coordinates = {
        (row, column)
        for row, columns in coordinates_by_row.items()
        for column in columns
    }
    ensure(set(projection) == expected_coordinates, "selected outcome projection is incomplete")
    report = {
        "buffer_limit_bytes": buffer_limit_bytes,
        "chunk_bytes": chunk_bytes,
        "column_count": expected_equation_count,
        "compressed_bytes": len(compressed),
        "compressed_sha256": sha256_bytes(compressed),
        "equation_count": len(equations),
        "full_json_syntax_scanned_to_eof": True,
        "matrix_cells_scanned": cell_count,
        "matrix_materialized": False,
        "max_buffer_bytes_observed": reader.max_buffer_bytes,
        "max_decoded_value_bytes_observed": reader.max_decoded_value_bytes,
        "observed_statuses": sorted(observed_statuses),
        "row_count": row_count,
        "selected_cells_retained": len(projection),
        "uncompressed_bytes_read": reader.total_bytes_read,
    }
    return equations, projection, report


def compact_table_sha256(table: list[list[int]]) -> str:
    body = json.dumps(table, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256_bytes(body)


def table_record(table: list[list[int]]) -> bytes:
    order = len(table)
    ensure(1 <= order <= 255, f"invalid table order: {order}")
    ensure(all(len(row) == order for row in table), "table is not square")
    flat = [value for row in table for value in row]
    ensure(
        all(type(value) is int and 0 <= value < order for value in flat),
        "table entry outside carrier",
    )
    return bytes([order, *flat])


def canonical_table_id(table: list[list[int]]) -> str:
    return "sha256:" + sha256_bytes(table_record(table))


def canonical_record_id(record: bytes) -> str:
    return "sha256:" + sha256_bytes(record)


def transpose(table: list[list[int]]) -> list[list[int]]:
    return [list(values) for values in zip(*table, strict=True)]


def parse_table_records(data: bytes) -> list[bytes]:
    records: list[bytes] = []
    position = 0
    while position < len(data):
        order = data[position]
        ensure(order > 0, "zero-order canonical table")
        end = position + 1 + order * order
        ensure(end <= len(data), "truncated canonical table stream")
        record = data[position:end]
        ensure(all(value < order for value in record[1:]), "entry outside carrier")
        records.append(record)
        position = end
    ensure(position == len(data), "canonical table stream has trailing bytes")
    return records


def parse_top_level_literals(source: bytes, names: tuple[str, ...]) -> dict[str, object]:
    tree = ast.parse(source.decode("utf-8"))
    wanted = set(names)
    found: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                ensure(target.id not in found, f"duplicate submitted literal: {target.id}")
                found[target.id] = ast.literal_eval(node.value)
    ensure(set(found) == wanted, f"missing submitted literals: {sorted(wanted - set(found))}")
    return found


def extract_direct_table_payload(source: bytes) -> tuple[int, bytes, list[bytes]]:
    literals = parse_top_level_literals(
        source, ("_MODEL_COUNT", "_TABLE_RAW_BYTES", "_TABLES_XZ_B85")
    )
    model_count = literals["_MODEL_COUNT"]
    raw_bytes = literals["_TABLE_RAW_BYTES"]
    encoded = literals["_TABLES_XZ_B85"]
    ensure(type(model_count) is int and model_count >= 0, "invalid model count")
    ensure(type(raw_bytes) is int and raw_bytes >= 0, "invalid raw-byte count")
    if isinstance(encoded, str):
        encoded = encoded.encode("ascii")
    ensure(isinstance(encoded, bytes), "submitted table payload is not bytes")
    compressed = base64.b85decode(encoded)
    ensure(base64.b85encode(compressed) == encoded, "noncanonical table Base85")
    raw = lzma.decompress(compressed)
    ensure(len(raw) == raw_bytes, "submitted table raw-byte declaration drift")
    records = parse_table_records(raw)
    ensure(len(records) == model_count, "submitted table record-count drift")
    ensure(len(set(records)) == len(records), "duplicate submitted table records")
    return model_count, raw, records


def extract_submitted_table_payload(source: bytes) -> tuple[int, bytes, list[bytes]]:
    literals = parse_top_level_literals(
        source,
        (
            "_ENGINE_PAYLOAD_B85",
            "_ENGINE_PAYLOAD_SHA256",
            "_ENGINE_PAYLOAD_FORMAT",
            "_ENGINE_LZMA_DICT_SIZE",
        ),
    )
    encoded = literals["_ENGINE_PAYLOAD_B85"]["false"]
    expected_sha = literals["_ENGINE_PAYLOAD_SHA256"]["false"]
    payload_format = literals["_ENGINE_PAYLOAD_FORMAT"]["false"]
    dictionary_size = literals["_ENGINE_LZMA_DICT_SIZE"]
    ensure(isinstance(encoded, bytes), "embedded false engine is not bytes")
    ensure(payload_format == "utf8_source", "unexpected embedded engine format")
    ensure(type(dictionary_size) is int and dictionary_size > 0, "bad LZMA dictionary")
    compressed = base64.b85decode(encoded)
    ensure(base64.b85encode(compressed) == encoded, "noncanonical engine Base85")
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
    engine = lzma.decompress(compressed, format=lzma.FORMAT_RAW, filters=filters)
    ensure(sha256_bytes(engine) == expected_sha, "embedded false-engine hash drift")
    return extract_direct_table_payload(engine)


def strip_outer_parentheses(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        closes_at_end = True
        for index, character in enumerate(text):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            if depth == 0 and index != len(text) - 1:
                closes_at_end = False
                break
        if not closes_at_end or depth != 0:
            break
        text = text[1:-1].strip()
    return text


def parse_term(text: str, variables: dict[str, int]):
    text = strip_outer_parentheses(text)
    depth = 0
    cut = -1
    for index, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "◇" and depth == 0:
            cut = index
    ensure(depth == 0, f"unbalanced term: {text}")
    if cut >= 0:
        return parse_term(text[:cut], variables), parse_term(
            text[cut + 1 :], variables
        )
    ensure(text in variables, f"unknown term atom: {text}")
    return variables[text]


def parse_equation(text: str, variables: dict[str, int]):
    normalized = text.replace("*", "◇")
    lhs, rhs = normalized.split("=", 1)
    return parse_term(lhs, variables), parse_term(rhs, variables)


def eval_term(term, values: tuple[int, ...], table: list[list[int]]) -> int:
    if type(term) is int:
        return values[term]
    return table[eval_term(term[0], values, table)][eval_term(term[1], values, table)]


def exhaustive_task(
    problem_id: str,
    source: str,
    target: str,
    table: list[list[int]],
    orientation: str,
    table_id: str,
) -> dict[str, object]:
    variable_names: list[str] = []
    for name in re.findall(r"\b([a-z])\b", source + " " + target):
        if name not in variable_names:
            variable_names.append(name)
    variables = {name: index for index, name in enumerate(variable_names)}
    source_lhs, source_rhs = parse_equation(source, variables)
    target_lhs, target_rhs = parse_equation(target, variables)
    order = len(table)
    source_violations = 0
    target_failures = 0
    first_failure = None
    checked = 0
    for values in itertools.product(range(order), repeat=len(variable_names)):
        checked += 1
        source_left = eval_term(source_lhs, values, table)
        source_right = eval_term(source_rhs, values, table)
        if source_left != source_right:
            source_violations += 1
        target_left = eval_term(target_lhs, values, table)
        target_right = eval_term(target_rhs, values, table)
        if target_left != target_right:
            target_failures += 1
            if first_failure is None:
                first_failure = {
                    "assignment": dict(zip(variable_names, values, strict=True)),
                    "lhs_value": target_left,
                    "rhs_value": target_right,
                }
    ensure(checked == order ** len(variable_names), "assignment count drift")
    ensure(source_violations == 0, f"source equation fails: {problem_id}")
    ensure(target_failures > 0, f"target equation holds: {problem_id}")
    return {
        "assignments_checked": checked,
        "effective_order": order,
        "effective_table_id": table_id,
        "first_target_failure": first_failure,
        "problem_id": problem_id,
        "source_violation_count": source_violations,
        "target_failure_count": target_failures,
        "usage_orientation": orientation,
        "variable_count": len(variable_names),
        "variables": variable_names,
    }


def table_from_stage80_record(row: dict[str, object]) -> list[list[int]]:
    order = row["order"]
    entries = row["entries"]
    ensure(type(order) is int and isinstance(entries, list), "invalid Stage 80 table row")
    ensure(len(entries) == order * order, "Stage 80 table entry-count drift")
    table = [entries[offset : offset + order] for offset in range(0, len(entries), order)]
    ensure(canonical_table_id(table) == row["table_id"], "Stage 80 table ID drift")
    return table


def parse_lean_operator_table(source: bytes) -> list[list[int]]:
    text = source.decode("utf-8")
    matches = LEAN_TABLE_RE.findall(text)
    ensure(len(matches) == 1, "Lean source must contain exactly one generated table comment")
    table = json.loads(matches[0])
    ensure(isinstance(table, list), "Lean operator table is not a list")
    table_record(table)
    return table


def artifact(
    stage_dir: Path,
    relative: str,
    role: str,
    media_type: str,
    source_ids: list[str],
    *,
    source_path: Path | None = None,
    record_count: int | None = None,
    attributes: dict[str, object] | None = None,
) -> dict[str, object]:
    path = source_path or stage_dir / Path(PurePosixPath(relative))
    result: dict[str, object] = {
        "bytes": path.stat().st_size,
        "media_type": media_type,
        "path": relative,
        "role": role,
        "sha256": sha256_path(path),
        "source_ids": source_ids,
    }
    if record_count is not None:
        result["record_count"] = record_count
    if attributes is not None:
        result["attributes"] = attributes
    return result


def build(
    output_stage: Path,
    repository_root: Path,
    stage80: Path,
    script_source_stage: Path,
) -> list[str]:
    raw_snapshot = stage80 / "raw/finite149-source-snapshot.tar.gz"
    ensure(
        sha256_path(raw_snapshot) == EXPECTED_STAGE80_RAW_SHA256,
        "Stage 80 raw snapshot hash drift",
    )
    members, snapshot_metadata = read_snapshot(raw_snapshot)
    labels = load_csv(members["source/789/not_generated_labels.csv"])
    ensure(len(labels) == EXPECTED_SELECTED_CELLS, "selected-label count drift")
    type_audit = json.loads(
        members["source/789/not_generated_type_audit.json"].decode("utf-8")
    )
    path_manifest = load_csv(members["source/finite149/manifest.csv"])
    ensure(len(path_manifest) == EXPECTED_FINITE_DIRECTIONS, "path inventory count drift")
    coordinates_by_row, coordinates = target_coordinates(
        labels, EXPECTED_EQUATION_COUNT
    )
    ensure(len(coordinates) == EXPECTED_SELECTED_CELLS, "selected coordinates drift")

    compressed_outcomes = members[RAW_MEMBER]
    ensure(
        sha256_bytes(compressed_outcomes) == EXPECTED_FINITE_OUTCOMES_SHA256,
        "finite-outcomes compressed hash drift",
    )
    equations, projection, matrix_report = stream_finite_outcomes(
        compressed_outcomes, coordinates_by_row
    )

    stage80_screening = load_gzip_jsonl(
        stage80 / "normalized/screening-decisions.jsonl.gz"
    )
    ensure(len(stage80_screening) == EXPECTED_SELECTED_CELLS, "Stage 80 screening count drift")
    projected_rows: list[dict[str, object]] = []
    expected_screening: list[dict[str, object]] = []
    category_counts: Counter[str] = Counter()
    for sequence, (label, committed) in enumerate(
        zip(labels, stage80_screening, strict=True)
    ):
        lhs_id = int(label["lhs_id"])
        rhs_id = int(label["rhs_id"])
        finite_outcome = projection[(lhs_id - 1, rhs_id - 1)]
        if label["official_label"] == "false" and finite_outcome.endswith(
            "proof_false"
        ):
            action = "retain"
            category = "finite_countermodel_proved"
            reason = "official_finite_outcome_endswith_proof_false"
        elif label["official_label"] == "true":
            action = "exclude"
            category = "general_true"
            reason = "official_general_outcome_true"
        elif finite_outcome == "unknown":
            action = "exclude"
            category = "finite_status_unknown"
            reason = "official_finite_outcome_unknown"
        else:
            action = "exclude"
            category = "infinite_countermodel_required"
            reason = "general_false_without_finite_false_proof"
        category_counts[category] += 1
        expected = {
            "action": action,
            "category": category,
            "finite_outcome": finite_outcome,
            "general_outcome": label["official_outcome"],
            "lhs_equation": label["lhs_equation"],
            "lhs_id": lhs_id,
            "pair_index": int(label["pair_index"]),
            "problem_id": label["problem_id"],
            "reason_code": reason,
            "rhs_equation": label["rhs_equation"],
            "rhs_id": rhs_id,
            "sequence": sequence,
        }
        ensure(expected == committed, f"Stage 80 screening drift: {label['problem_id']}")
        expected_screening.append(expected)
        projected_rows.append(
            {
                "finite_outcome": finite_outcome,
                "lhs_equation_id": equations[lhs_id - 1],
                "lhs_id": lhs_id,
                "pair_index": int(label["pair_index"]),
                "problem_id": label["problem_id"],
                "rhs_equation_id": equations[rhs_id - 1],
                "rhs_id": rhs_id,
                "sequence": sequence,
            }
        )
    expected_categories = {
        "finite_countermodel_proved": 149,
        "finite_status_unknown": 2,
        "general_true": 38,
        "infinite_countermodel_required": 600,
    }
    ensure(dict(category_counts) == expected_categories, "screening partition drift")
    selected_ids = {row["problem_id"] for row in path_manifest}
    retained_ids = {
        row["problem_id"] for row in expected_screening if row["action"] == "retain"
    }
    ensure(retained_ids == selected_ids, "streamed screening/path selected-set drift")
    unknown_ids = {
        row["problem_id"] for row in type_audit["finite_status_unknown_pairs"]
    }
    ensure(
        {
            row["problem_id"]
            for row in expected_screening
            if row["category"] == "finite_status_unknown"
        }
        == unknown_ids,
        "streamed screening/type-audit unknown-set drift",
    )
    ensure(
        type_audit["false_semantic_type_counts"]
        == {
            "finite_countermodel_proved": 149,
            "finite_status_unknown": 2,
            "infinite_countermodel_required": 600,
        },
        "raw finite type-audit partition drift",
    )
    write_bytes(
        output_stage,
        "normalized/finite-outcomes-789.jsonl.gz",
        gzip_bytes(jsonl_bytes(projected_rows)),
    )
    screening_audit = {
        "category_counts": expected_categories,
        "matrix": matrix_report,
        "one_based_ids_converted_to_zero_based_coordinates": True,
        "projection_records": len(projected_rows),
        "schema_version": SCHEMA_VERSION,
        "stage80_screening_exact_record_match": True,
        "stage80_screening_path": (
            "reproduction/80-finite149/normalized/screening-decisions.jsonl.gz"
        ),
        "stage80_screening_sha256": sha256_path(
            stage80 / "normalized/screening-decisions.jsonl.gz"
        ),
    }
    write_bytes(
        output_stage,
        "verification/screening-stream-audit.json",
        pretty_json_bytes(screening_audit),
    )

    bases = load_jsonl(members["source/finite149/static_library_base_models.jsonl"])
    table_map = load_csv((stage80 / "normalized/table-id-map.csv").read_bytes())
    effective_rows = load_gzip_jsonl(stage80 / "normalized/base-tables.jsonl.gz")
    ensure(
        len(bases) == len(table_map) == len(effective_rows) == EXPECTED_BASE_TABLES,
        "base-table inventory count drift",
    )
    bundle_manifest = json.loads(
        members["source/finite149/bundle_manifest.json"].decode("utf-8")
    )
    ensure(
        bundle_manifest["scope"]["experiment_not_generated"] == 789
        and bundle_manifest["scope"]["finite_counterexample_count"] == 149,
        "finite149 bundle scope drift",
    )
    reductions = json.loads(
        members["source/refutation934/order24_coverage_reductions.json"].decode(
            "utf-8"
        )
    )
    refutation934_base = next(
        row for row in bases if str(row["official_source"]).endswith("Refutation934.lean")
    )
    reduction_candidates = [
        row
        for row in reductions["directions"]
        if row["orientation"] == "direct" and int(row["best"]["order"]) == 22
    ]
    ensure(reduction_candidates, "missing direct order-22 Refutation934 reduction")
    reduction = reduction_candidates[0]
    substitute = reduction["best"]["table_rows"]
    ensure(
        all(row["best"]["table_rows"] == substitute for row in reduction_candidates),
        "direct Refutation934 reductions disagree on the effective table",
    )
    subset = [int(value) for value in reduction["best"]["subset"]]
    official24 = refutation934_base["table_rows"]
    ensure(len(official24) == 24 and len(subset) == 22, "Refutation934 order drift")
    position = {value: index for index, value in enumerate(subset)}
    ensure(len(position) == len(subset), "Refutation934 subset contains duplicates")
    induced: list[list[int]] = []
    for left in subset:
        induced_row: list[int] = []
        for right in subset:
            value = official24[left][right]
            ensure(value in position, "Refutation934 subset is not closed")
            induced_row.append(position[value])
        induced.append(induced_row)
    ensure(induced == substitute, "Refutation934 reduction is not the induced table")
    ensure(
        compact_table_sha256(substitute) == reduction["best"]["table_sha256"],
        "Refutation934 reduction compact-table hash drift",
    )

    lean_rows: list[dict[str, object]] = []
    provenance_rows: list[dict[str, object]] = []
    effective_table_by_stable: dict[str, list[list[int]]] = {}
    base_model_id_by_stable: dict[str, str] = {}
    refutation934_effective: dict[str, object] | None = None
    for sequence, (base, mapping, effective_record) in enumerate(
        zip(bases, table_map, effective_rows, strict=True)
    ):
        stable_id = mapping["stable_id"]
        ensure(
            mapping["base_model_id"] == base["base_model_id"],
            f"base/stable-ID join drift: {stable_id}",
        )
        official_source = str(base["official_source"])
        member_name = f"source/official_sources/{official_source}"
        source_body = members[member_name]
        ensure(
            sha256_bytes(source_body) == base["official_source_sha256"],
            f"official Lean source hash drift: {stable_id}",
        )
        bundle_source = bundle_manifest["official_sources"][official_source]
        ensure(
            bundle_source["sha256"] == base["official_source_sha256"],
            f"bundle/source hash join drift: {stable_id}",
        )
        lean_table = parse_lean_operator_table(source_body)
        historical_table = base["table_rows"]
        ensure(lean_table == historical_table, f"Lean table mismatch: {stable_id}")
        ensure(
            compact_table_sha256(lean_table) == base["base_table_sha256"],
            f"Lean compact-table hash mismatch: {stable_id}",
        )
        ensure(
            compact_table_sha256(transpose(lean_table))
            == base["dual_table_sha256"],
            f"Lean transpose compact-table hash mismatch: {stable_id}",
        )
        effective_table = table_from_stage80_record(effective_record)
        ensure(
            canonical_table_id(effective_table) == mapping["canonical_table_id"],
            f"effective Stage 80 table-map mismatch: {stable_id}",
        )
        effective_table_by_stable[stable_id] = effective_table
        base_model_id_by_stable[stable_id] = str(base["base_model_id"])
        is_substitute = mapping["is_refutation934_substitute"] == "true"
        ensure(
            stable_id == f"F149-{sequence + 1:03d}"
            and int(mapping["append_sequence"]) == sequence
            and int(mapping["submitted_record_index"]) == 1470 + sequence
            and int(mapping["official_order"]) == len(lean_table)
            and int(mapping["effective_order"]) == len(effective_table)
            and mapping["compact_json_table_id"]
            == "sha256:" + compact_table_sha256(effective_table)
            and mapping["official_source"] == official_source
            and mapping["payload_orientation"] == "direct"
            and effective_record["first_seen_stage"] == STAGE80
            and effective_record["encoding"] == "uint8-order-row-major-v1",
            f"Stage 80 stable table metadata drift: {stable_id}",
        )
        expected_record_kind = "verified-substitute" if is_substitute else "exact-explicit"
        ensure(
            mapping["record_kind"] == effective_record["record_kind"] == expected_record_kind,
            f"Stage 80 table record-kind drift: {stable_id}",
        )
        ensure(
            any(
                identifier.get("scheme") == "sha256-compact-json-table-v1"
                and identifier.get("value") == mapping["compact_json_table_id"]
                for identifier in effective_record["identifiers"]
            ),
            f"Stage 80 compact table identifier drift: {stable_id}",
        )
        if is_substitute:
            ensure(stable_id == "F149-014", "unexpected substitute stable ID")
            ensure(effective_table == substitute, "Stage 80 substitute table drift")
            effective_source_path = (
                "reproduction/80-finite149/raw/finite149-source-snapshot.tar.gz#"
                "source/refutation934/order24_coverage_reductions.json"
            )
            effective_source_record = (
                f"directions[problem_id={reduction['problem_id']}].best.table_rows"
            )
            derivation = "closed induced substructure of the official order-24 Lean table"
        else:
            ensure(effective_table == lean_table, f"effective/Lean table mismatch: {stable_id}")
            effective_source_path = (
                "reproduction/80-finite149/raw/finite149-source-snapshot.tar.gz#"
                f"source/official_sources/{official_source}#generated-operator-table-comment"
            )
            effective_source_record = base["base_model_id"]
            derivation = "byte-exact table parsed from the captured official Lean source"
        lean_rows.append(
            {
                "base_model_id": base["base_model_id"],
                "compact_json_sha256": base["base_table_sha256"],
                "lean_source_path": (
                    "reproduction/80-finite149/raw/finite149-source-snapshot.tar.gz#"
                    f"source/official_sources/{official_source}"
                ),
                "lean_source_sha256": base["official_source_sha256"],
                "lean_table_canonical_id": canonical_table_id(lean_table),
                "lean_table_matches_historical_table_rows": True,
                "official_order": len(lean_table),
                "stable_id": stable_id,
            }
        )
        provenance_row = {
            "base_model_id": base["base_model_id"],
            "derivation": derivation,
            "effective_order": len(effective_table),
            "effective_source_path": effective_source_path,
            "effective_source_record": effective_source_record,
            "effective_table_id": canonical_table_id(effective_table),
            "official_lean_source": official_source,
            "official_order": len(lean_table),
            "schema_version": SCHEMA_VERSION,
            "stable_id": stable_id,
            "supersedes_stage80_record": (
                "reproduction/80-finite149/normalized/base-tables.jsonl.gz#"
                f"stable_id={stable_id}"
            ),
        }
        provenance_rows.append(provenance_row)
        if is_substitute:
            refutation934_effective = provenance_row

    ensure(len(lean_rows) == EXPECTED_BASE_TABLES, "Lean audit count drift")
    ensure(refutation934_effective is not None, "Refutation934 effective record missing")
    write_bytes(
        output_stage,
        "verification/lean-source-table-audit.jsonl.gz",
        gzip_bytes(jsonl_bytes(lean_rows)),
    )
    write_bytes(
        output_stage,
        "normalized/base-table-provenance.jsonl.gz",
        gzip_bytes(jsonl_bytes(provenance_rows)),
    )
    refutation934_audit = {
        "all_direct_order22_reductions_agree": True,
        "closed_substructure": True,
        "corrected_effective_provenance": refutation934_effective,
        "direct_reduction_problem_ids": sorted(
            row["problem_id"] for row in reduction_candidates
        ),
        "effective_table_matches_stage80_F149_014": True,
        "official_lean_table_canonical_id": canonical_table_id(official24),
        "official_order": 24,
        "official_source": refutation934_base["official_source"],
        "schema_version": SCHEMA_VERSION,
        "substitute_compact_json_sha256": compact_table_sha256(substitute),
        "substitute_order": 22,
        "substitute_table_canonical_id": canonical_table_id(substitute),
        "substructure_subset_in_official_carrier": subset,
    }
    write_bytes(
        output_stage,
        "verification/refutation934-effective-provenance.json",
        pretty_json_bytes(refutation934_audit),
    )

    # Re-run every material Stage 80 semantic check except the finite-outcomes
    # screening already replayed above.  This is the low-memory replacement for
    # the historical Stage 80 verifier, not merely an integrity/hash check.
    normalized_paths = load_gzip_jsonl(stage80 / "normalized/etp-paths.jsonl.gz")
    coverage_rows = load_gzip_jsonl(stage80 / "normalized/coverage.jsonl.gz")
    committed_exhaustive = load_gzip_jsonl(
        stage80 / "verification/coverage-exhaustive.jsonl.gz"
    )
    raw_coverage = load_csv(members["source/finite149/static_library_coverage.csv"])
    raw_oriented = load_jsonl(
        members["source/finite149/static_library_oriented_models.jsonl"]
    )
    ensure(len(raw_oriented) == 28, "raw oriented-table count drift")
    raw_library_summary = json.loads(
        members["source/finite149/static_library_summary.json"].decode("utf-8")
    )
    ensure(
        len(normalized_paths)
        == len(coverage_rows)
        == len(committed_exhaustive)
        == len(raw_coverage)
        == EXPECTED_FINITE_DIRECTIONS,
        "Stage 80 coverage artifact count drift",
    )
    base_by_id = {str(row["base_model_id"]): row for row in bases}
    stable_by_base = {
        base_model_id: stable_id
        for stable_id, base_model_id in base_model_id_by_stable.items()
    }
    raw_oriented_by_id = {
        str(row["oriented_model_id"]): row for row in raw_oriented
    }
    ensure(len(base_by_id) == 17, "duplicate base-model IDs")
    ensure(len(raw_oriented_by_id) == 28, "duplicate oriented-model IDs")
    path_by_problem = {row["problem_id"]: row for row in path_manifest}
    ensure(len(path_by_problem) == EXPECTED_FINITE_DIRECTIONS, "duplicate path problem IDs")
    ensure(
        {row["problem_id"] for row in raw_coverage}
        == {row["problem_id"] for row in coverage_rows}
        == {row["problem_id"] for row in committed_exhaustive}
        == set(path_by_problem),
        "coverage/path/exhaustive problem-ID sets drift",
    )
    orientation_counts: Counter[str] = Counter()
    transpose_stable_ids: set[str] = set()
    fresh_exhaustive: list[dict[str, object]] = []
    for sequence, (raw_row, normalized, committed_check, normalized_path) in enumerate(
        zip(
            raw_coverage,
            coverage_rows,
            committed_exhaustive,
            normalized_paths,
            strict=True,
        )
    ):
        problem_id = raw_row["problem_id"]
        ensure(normalized["sequence"] == sequence, f"coverage sequence drift: {problem_id}")
        ensure(normalized_path["sequence"] == sequence, f"path sequence drift: {problem_id}")
        ensure(
            normalized["problem_id"] == committed_check["problem_id"] == problem_id,
            f"coverage/exhaustive join drift: {problem_id}",
        )
        base_model_id = raw_row["base_model_id"]
        stable_id = stable_by_base[base_model_id]
        raw_orientation = raw_row["orientation"]
        ensure(raw_orientation in {"direct", "dual"}, "unknown raw orientation")
        usage_orientation = "direct" if raw_orientation == "direct" else "transpose"
        orientation_counts[usage_orientation] += 1
        if usage_orientation == "transpose":
            transpose_stable_ids.add(stable_id)
        base_table = effective_table_by_stable[stable_id]
        effective_table = (
            base_table if usage_orientation == "direct" else transpose(base_table)
        )
        effective_id = canonical_table_id(effective_table)
        raw_oriented_row = raw_oriented_by_id[raw_row["oriented_model_id"]]
        if int(raw_oriented_row["carrier_order"]) != 24:
            ensure(
                raw_oriented_row["table_rows"] == effective_table,
                f"raw oriented table drift: {problem_id}",
            )
        expected_normalized = {
            "base_model_id": base_model_id,
            "base_stable_id": stable_id,
            "effective_order": len(effective_table),
            "effective_table_id": effective_id,
            "lhs_equation": raw_row["equation1"],
            "lhs_id": int(raw_row["lhs_id"]),
            "official_base_order": int(base_by_id[base_model_id]["carrier_order"]),
            "problem_id": problem_id,
            "proof_path": path_by_problem[problem_id]["proof_path"],
            "rhs_equation": raw_row["equation2"],
            "rhs_id": int(raw_row["rhs_id"]),
            "sequence": sequence,
            "usage_orientation": usage_orientation,
        }
        ensure(
            normalized == expected_normalized,
            f"normalized coverage record drift: {problem_id}",
        )
        path_row = path_by_problem[problem_id]
        path_steps = [step.strip() for step in path_row["proof_path"].split("->")]
        ensure(path_steps[0] == str(path_row["lhs_id"]), "ETP path start drift")
        ensure(
            path_steps[-1] == f"{int(path_row['rhs_id'])}_neg",
            "ETP path end drift",
        )
        ensure(path_row["official_proven"].lower() == "true", "unproven ETP path")
        ensure(
            (path_row["uses_dual"].lower() == "true")
            == (usage_orientation == "transpose"),
            f"ETP path orientation drift: {problem_id}",
        )
        expected_path = {
            "official_proven": True,
            "official_source": path_row["official_source"],
            "official_source_line": int(path_row["official_line"]),
            "path_sources": [
                value for value in path_row["proof_path_sources"].split(";") if value
            ],
            "path_steps": path_steps,
            "problem_id": problem_id,
            "sequence": sequence,
            "source_equation": f"Equation{int(path_row['lhs_id'])}",
            "target_equation": f"Equation{int(path_row['rhs_id'])}",
            "uses_transpose": usage_orientation == "transpose",
            "witness_mode": path_row["witness_mode"],
        }
        ensure(normalized_path == expected_path, f"normalized path drift: {problem_id}")
        fresh = exhaustive_task(
            problem_id,
            raw_row["equation1"],
            raw_row["equation2"],
            effective_table,
            usage_orientation,
            effective_id,
        )
        ensure(fresh == committed_check, f"exhaustive semantic drift: {problem_id}")
        fresh_exhaustive.append(fresh)

    ensure(
        dict(orientation_counts) == EXPECTED_ORIENTATION_USAGE,
        "129/20 orientation-use split drift",
    )
    ensure(
        len(transpose_stable_ids) == EXPECTED_REQUIRED_TRANSPOSES,
        "required-transpose stable-ID count drift",
    )

    stable_order = [row["stable_id"] for row in table_map]
    base_records = [
        table_record(effective_table_by_stable[stable_id]) for stable_id in stable_order
    ]
    ensure(
        (stage80 / "normalized/base-tables.bin").read_bytes() == b"".join(base_records),
        "Stage 80 base-table binary drift",
    )
    expected_transpose_stable_order = [
        stable_id for stable_id in stable_order if stable_id in transpose_stable_ids
    ]
    expected_transpose_tables = [
        transpose(effective_table_by_stable[stable_id])
        for stable_id in expected_transpose_stable_order
    ]
    transpose_rows = load_gzip_jsonl(
        stage80 / "normalized/required-transposes.jsonl.gz"
    )
    transpose_binary_records = parse_table_records(
        (stage80 / "normalized/required-transposes.bin").read_bytes()
    )
    ensure(
        len(transpose_rows)
        == len(transpose_binary_records)
        == len(expected_transpose_tables)
        == EXPECTED_REQUIRED_TRANSPOSES,
        "required-transpose artifact count drift",
    )
    for stable_id, expected_table, committed_row, committed_binary in zip(
        expected_transpose_stable_order,
        expected_transpose_tables,
        transpose_rows,
        transpose_binary_records,
        strict=True,
    ):
        ensure(
            table_from_stage80_record(committed_row) == expected_table,
            f"derived transpose JSON drift: {stable_id}",
        )
        ensure(
            committed_binary == table_record(expected_table),
            f"derived transpose binary drift: {stable_id}",
        )
    base_ids = {canonical_record_id(record) for record in base_records}
    transpose_ids = {
        canonical_table_id(table) for table in expected_transpose_tables
    }
    ensure(len(base_ids) == 17 and len(transpose_ids) == 11, "table identity count drift")
    ensure(not (base_ids & transpose_ids), "transpose duplicates a finite149 base")

    stage70_records = parse_table_records(
        (repository_root / f"reproduction/{STAGE70}/normalized/tables.bin").read_bytes()
    )
    ensure(len(stage70_records) == 1_470, "Stage 70 core count drift")
    stage70_ids = {canonical_record_id(record) for record in stage70_records}
    base_overlap = sorted(base_ids & stage70_ids)
    oriented_overlap = sorted((base_ids | transpose_ids) & stage70_ids)
    ensure(not base_overlap and not oriented_overlap, "finite149/core overlap drift")
    ensure(
        raw_library_summary["current_solo_v4"]["new_base_tables_already_present"]
        == 0
        and raw_library_summary["current_solo_v4"]
        ["new_used_oriented_tables_already_present"]
        == 0,
        "historical zero-overlap summary drift",
    )
    expected_overlap_audit = {
        "base_overlap_count": 0,
        "base_overlaps": [],
        "base_table_count": 17,
        "comparison": "exact canonical bytes: order byte + n^2 row-major bytes",
        "oriented_asset_count": 28,
        "oriented_overlap_count": 0,
        "oriented_overlaps": [],
        "prior_core_canonical_id_vector_sha256": sha256_bytes(
            b"".join(
                (canonical_record_id(record) + "\n").encode("ascii")
                for record in stage70_records
            )
        ),
        "prior_core_count": 1470,
        "prior_core_path": f"reproduction/{STAGE70}/normalized/tables.bin",
        "schema_version": SCHEMA_VERSION,
    }
    ensure(
        json.loads(
            (stage80 / "verification/zero-overlap-with-core1470.json").read_text(
                encoding="utf-8"
            )
        )
        == expected_overlap_audit,
        "committed zero-overlap audit drift",
    )

    submission_path = repository_root / SUBMISSION_RELATIVE
    submission_source = submission_path.read_bytes()
    submitted_count, submitted_raw, submitted_records = extract_submitted_table_payload(
        submission_source
    )
    ensure(submitted_count == EXPECTED_SUBMITTED_RECORDS, "submitted record-count drift")
    ensure(submitted_records[:1470] == stage70_records, "submitted core prefix drift")
    ensure(submitted_records[1470:] == base_records, "submitted finite149 suffix drift")
    suffix_audit = json.loads(
        (stage80 / "verification/submission-suffix-audit.json").read_text(
            encoding="utf-8"
        )
    )
    expected_suffix_vector_sha = sha256_bytes(
        b"".join((canonical_record_id(record) + "\n").encode("ascii") for record in base_records)
    )
    ensure(
        suffix_audit["core_prefix_exact_record_order_match"]
        and suffix_audit["suffix_exact_record_order_match"]
        and suffix_audit["submitted_record_count_observed"] == submitted_count
        and suffix_audit["submitted_declared_raw_bytes"] == len(submitted_raw)
        and suffix_audit["submitted_solver_sha256"] == sha256_bytes(submission_source)
        and suffix_audit["suffix_canonical_id_vector_sha256"]
        == expected_suffix_vector_sha,
        "committed submission-suffix audit drift",
    )
    append_order = load_csv((stage80 / "normalized/append-order.csv").read_bytes())
    ensure(len(append_order) == 17, "append-order count drift")
    for sequence, (row, record) in enumerate(zip(append_order, base_records, strict=True)):
        ensure(
            int(row["append_sequence"]) == sequence
            and int(row["submitted_record_index"]) == 1470 + sequence
            and row["stable_id"] == stable_order[sequence]
            and row["canonical_table_id"] == canonical_record_id(record)
            and row["expected_payload_orientation"] == "direct",
            f"append-order drift at sequence {sequence}",
        )

    delta_rows = load_gzip_jsonl(stage80 / "delta.jsonl.gz")
    ensure(len(delta_rows) == 28, "Stage 80 delta count drift")
    for sequence, (row, record) in enumerate(zip(delta_rows[:17], base_records, strict=True)):
        ensure(
            row["sequence"] == sequence
            and row["action"] == "add"
            and row["stage_id"] == STAGE80
            and row["table_id"] == canonical_record_id(record),
            f"Stage 80 base delta drift at sequence {sequence}",
        )
    for offset, (row, stable_id, table) in enumerate(
        zip(
            delta_rows[17:],
            expected_transpose_stable_order,
            expected_transpose_tables,
            strict=True,
        )
    ):
        sequence = 17 + offset
        ensure(
            row["sequence"] == sequence
            and row["action"] == "derive"
            and row["stage_id"] == STAGE80
            and row["source_stage_id"] == STAGE80
            and row["source_table_id"]
            == canonical_table_id(effective_table_by_stable[stable_id])
            and row["table_id"] == canonical_table_id(table),
            f"Stage 80 transpose delta drift at sequence {sequence}",
        )

    refutation934_problem_ids = {
        row["problem_id"]
        for row in coverage_rows
        if row["base_stable_id"] == "F149-014"
    }
    fresh_refutation934 = [
        row for row in fresh_exhaustive if row["problem_id"] in refutation934_problem_ids
    ]
    ensure(len(fresh_refutation934) == 5, "Refutation934 task-count drift")
    focused_refutation934 = json.loads(
        (stage80 / "verification/refutation934-five-task-exhaustive.json").read_text(
            encoding="utf-8"
        )
    )
    ensure(
        focused_refutation934["all_five_exhaustive_checks_passed"]
        and focused_refutation934["tasks"] == fresh_refutation934
        and focused_refutation934["substitute_canonical_table_id"]
        == canonical_table_id(substitute),
        "committed Refutation934 five-task audit drift",
    )

    stage80_summary = json.loads((stage80 / "summary.json").read_text(encoding="utf-8"))
    expected_metrics = {
        "finite149.base_tables": 17,
        "finite149.core_overlap": 0,
        "finite149.directions": 149,
        "finite149.no_submission_directions": 789,
        "finite149.official_payload_tables": 16,
        "finite149.oriented_assets": 28,
        "finite149.original_uses": 129,
        "finite149.required_transposes": 11,
        "finite149.substitute_tables": 1,
        "finite149.transpose_uses": 20,
        "refutation934.covered_tasks": 5,
        "refutation934.official_order": 24,
        "refutation934.substitute_order": 22,
    }
    ensure(stage80_summary["metrics"] == expected_metrics, "Stage 80 summary metric drift")
    ensure(
        stage80_summary["action_counts"] == {"add": 17, "derive": 11}
        and stage80_summary["orientation_usage"] == EXPECTED_ORIENTATION_USAGE
        and stage80_summary["zero_overlap"]
        == {"all_28_oriented_assets_vs_core1470": 0, "base_vs_core1470": 0},
        "Stage 80 summary semantic drift",
    )
    assignments_checked = sum(row["assignments_checked"] for row in fresh_exhaustive)
    semantic_audit = {
        "append_order_exact_records": len(append_order),
        "base_binary_exact_records": len(base_records),
        "core_prefix_exact_records": 1470,
        "delta_add_records": 17,
        "delta_derive_records": 11,
        "etp_path_inventory_records_validated": len(normalized_paths),
        "exhaustive_assignment_count": assignments_checked,
        "exhaustive_direction_exact_record_matches": len(fresh_exhaustive),
        "full_stage80_semantic_replacement": True,
        "orientation_usage": dict(orientation_counts),
        "refutation934_five_task_exact_record_matches": len(fresh_refutation934),
        "required_transpose_exact_records": len(expected_transpose_tables),
        "schema_version": SCHEMA_VERSION,
        "stage80_artifacts_modified": False,
        "submitted_record_count": submitted_count,
        "suffix_exact_records": len(base_records),
        "zero_overlap_with_core1470": {
            "base_tables": len(base_overlap),
            "oriented_assets": len(oriented_overlap),
        },
    }
    write_bytes(
        output_stage,
        "verification/stage80-portable-semantic-audit.json",
        pretty_json_bytes(semantic_audit),
    )

    declared_path_sources: set[str] = set()
    for row in path_manifest:
        declared_path_sources.add(row["official_source"])
        declared_path_sources.update(
            value for value in row["proof_path_sources"].split(";") if value
        )
    captured_official_sources = {
        name.removeprefix("source/official_sources/")
        for name in members
        if name.startswith("source/official_sources/")
    }
    ensure(
        len(declared_path_sources)
        == int(bundle_manifest["counts"]["official_source_files"]),
        "declared path-source count drift",
    )
    ensure(
        captured_official_sources.issubset(declared_path_sources),
        "captured official table source absent from path inventory",
    )
    missing_path_sources = sorted(declared_path_sources - captured_official_sources)
    finite_graph_captured = any("finite_graph" in name for name in members)
    ensure(not finite_graph_captured, "unexpected finite graph in Stage 80 snapshot")
    path_boundary = {
        "captured_official_source_count": len(captured_official_sources),
        "captured_official_sources": sorted(captured_official_sources),
        "declared_path_source_count": len(declared_path_sources),
        "edge_replay_performed": False,
        "finite_graph_captured": False,
        "finite_graph_expected_sha256": bundle_manifest["upstream"][
            "finite_graph_sha256"
        ],
        "independent_finite_table_semantics_available": True,
        "independent_semantics_evidence": (
            "reproduction/80-finite149/verification/coverage-exhaustive.jsonl.gz"
        ),
        "interpretation": (
            "The 149 ETP paths are a hash-pinned frozen inventory. Their graph edges "
            "are not independently replayable from the captured Stage 80 snapshot."
        ),
        "missing_path_source_count": len(missing_path_sources),
        "missing_path_sources": missing_path_sources,
        "path_inventory_rows": len(path_manifest),
        "path_source_closure_complete": not missing_path_sources,
        "schema_version": SCHEMA_VERSION,
    }
    write_bytes(
        output_stage,
        "verification/path-evidence-boundary.json",
        pretty_json_bytes(path_boundary),
    )

    summary = {
        "correction_scope": {
            "changes_stage80_membership_or_counts": False,
            "preserves_stage80_raw_and_generated_artifacts": True,
            "replaces_high_memory_stage80_rebuild_for_normal_review": True,
        },
        "finite_outcomes_streaming": screening_audit,
        "lean_source_tables": {
            "captured_sources_parsed": len(lean_rows),
            "exact_matches": len(lean_rows),
        },
        "path_evidence_boundary": {
            "captured_source_count": len(captured_official_sources),
            "declared_source_count": len(declared_path_sources),
            "edge_replay_performed": False,
            "missing_source_count": len(missing_path_sources),
        },
        "python": {
            "minimum": "3.10",
            "official_sandbox_image": "python:3.11-slim",
            "recommended_and_required_ci_baseline": "3.11",
            "standard_library_only": True,
        },
        "refutation934": refutation934_audit,
        "schema_version": SCHEMA_VERSION,
        "stage80_portable_semantics": semantic_audit,
        "stage80_inputs": {
            "finite_outcomes_compressed_sha256": sha256_bytes(compressed_outcomes),
            "outer_archive_member_bytes": sum(len(value) for value in members.values()),
            "outer_archive_members": len(members),
            "raw_snapshot_sha256": sha256_path(raw_snapshot),
            "source_snapshot_captured_at": snapshot_metadata["captured_at"],
        },
        "stage_id": STAGE_ID,
    }
    write_bytes(output_stage, "summary.json", pretty_json_bytes(summary))

    stage80_source = ["stage81-stage80-evidence"]
    code_source = ["stage81-correction-code"]
    artifact_specs = [
        artifact(
            output_stage,
            "normalized/base-table-provenance.jsonl.gz",
            "effective-provenance-index",
            "application/x-ndjson+gzip",
            stage80_source,
            record_count=17,
        ),
        artifact(
            output_stage,
            "normalized/finite-outcomes-789.jsonl.gz",
            "selected-outcomes-index",
            "application/x-ndjson+gzip",
            stage80_source,
            record_count=789,
            attributes={
                "full_matrix_rows_scanned": matrix_report["row_count"],
                "max_buffer_bytes_observed": matrix_report[
                    "max_buffer_bytes_observed"
                ],
            },
        ),
        artifact(
            output_stage,
            "scripts/rebuild.py",
            "rebuild-script",
            "text/x-python",
            code_source,
            source_path=script_source_stage / "scripts/rebuild.py",
        ),
        artifact(
            output_stage,
            "scripts/verify.py",
            "verification-script",
            "text/x-python",
            code_source,
            source_path=script_source_stage / "scripts/verify.py",
        ),
        artifact(
            output_stage,
            "summary.json",
            "correction-summary",
            "application/json",
            ["stage81-stage80-evidence", "stage81-official-runtime-doc"],
        ),
        artifact(
            output_stage,
            "verification/lean-source-table-audit.jsonl.gz",
            "lean-source-audit",
            "application/x-ndjson+gzip",
            stage80_source,
            record_count=17,
        ),
        artifact(
            output_stage,
            "verification/path-evidence-boundary.json",
            "evidence-boundary",
            "application/json",
            stage80_source,
        ),
        artifact(
            output_stage,
            "verification/refutation934-effective-provenance.json",
            "provenance-correction",
            "application/json",
            stage80_source,
            record_count=1,
        ),
        artifact(
            output_stage,
            "verification/screening-stream-audit.json",
            "streaming-screening-audit",
            "application/json",
            stage80_source,
            record_count=789,
        ),
        artifact(
            output_stage,
            "verification/stage80-portable-semantic-audit.json",
            "portable-semantic-audit",
            "application/json",
            stage80_source,
        ),
    ]
    artifact_specs.sort(key=lambda row: str(row["path"]))
    checksums = b"".join(
        f"{row['sha256']}  {row['path']}\n".encode("ascii")
        for row in artifact_specs
    )
    write_bytes(output_stage, "SHA256SUMS", checksums)

    manifest = {
        "$schema": "../../schemas/stage-manifest.schema.json",
        "artifacts": artifact_specs,
        "captured_at": CAPTURED_AT,
        "claims": [],
        "depends_on": [STAGE80],
        "notes": [
            "This corrective layer preserves every manifested Stage 80 artifact byte for byte and changes no finite149 count or table membership.",
            "The nested 498,673,223-byte finite-outcomes JSON is parsed to top-level EOF one matrix row at a time under a 256 KiB application buffer cap.",
            "All 17 captured official Lean operator-table comments are parsed and compared with the historical table rows.",
            "The portable verifier also reruns all 149 exhaustive task checks, the 11 transpose derivations, 129/20 orientation split, zero-overlap check, delta/order joins, and exact 1,470-prefix/17-suffix submission comparison.",
            "The 149 ETP paths remain a frozen inventory because the finite graph and 13 of 30 referenced path-source files were not captured; direct finite-table semantics remain exhaustively checked in Stage 80.",
            "Python 3.10+ is required; Python 3.11 is the recommended and required CI baseline aligned with the official python:3.11-slim sandbox.",
        ],
        "pipeline_order": 81,
        "schema_version": SCHEMA_VERSION,
        "sources": [
            {
                "captured_at": CAPTURED_AT,
                "kind": "repository-snapshot",
                "license_status": "inherits the per-source status recorded by Stage 80",
                "locator": "reproduction/80-finite149",
                "notes": [
                    f"Stage 80 raw snapshot SHA-256: {EXPECTED_STAGE80_RAW_SHA256}",
                    "The corrective build consumes the committed Stage 80 archive and normalized records without modifying them.",
                ],
                "revision": "be7d492ed4651f1193c823238ef528f32afc90d1",
                "source_id": "stage81-stage80-evidence",
            },
            {
                "captured_at": CAPTURED_AT,
                "kind": "generated",
                "license_status": "Apache-2.0 repository code",
                "locator": "reproduction/81-finite149-portable-verification/scripts",
                "source_id": "stage81-correction-code",
            },
            {
                "captured_at": CAPTURED_AT,
                "kind": "third-party",
                "license_status": "upstream repository documentation; see upstream licensing",
                "locator": "https://github.com/SAIRcompetition/equational-theories-lean-stage2/blob/817a4653bf762584931d49c6714c9fcfab7df66a/README.md#sandbox-python-environment",
                "notes": [
                    "The official README identifies python:3.11-slim as the sandbox image; its Python 3.8+ prerequisite describes local harness tooling."
                ],
                "revision": "817a4653bf762584931d49c6714c9fcfab7df66a",
                "source_id": "stage81-official-runtime-doc",
            },
        ],
        "stage_id": STAGE_ID,
        "status": "verified",
        "title": "portable finite149 verification and provenance correction",
        "verification": {
            "checksum_file": "SHA256SUMS",
            "command": (
                "python3 reproduction/81-finite149-portable-verification/"
                "scripts/verify.py"
            ),
            "notes": [
                "The stage-local verifier regenerates all correction artifacts in a temporary directory and compares every generated byte."
            ],
        },
    }
    write_bytes(output_stage, "stage.json", pretty_json_bytes(manifest))
    return [str(row["path"]) for row in artifact_specs]


def parse_args() -> argparse.Namespace:
    stage = Path(__file__).resolve().parents[1]
    repository = stage.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=repository)
    parser.add_argument("--output-stage", type=Path, default=stage)
    parser.add_argument(
        "--stage80", type=Path, default=repository / f"reproduction/{STAGE80}"
    )
    parser.add_argument("--script-source-stage", type=Path, default=stage)
    return parser.parse_args()


def main() -> int:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            "Stage 81 requires Python 3.10+; Python 3.11 matches the official sandbox"
        )
    args = parse_args()
    paths = build(
        args.output_stage.resolve(),
        args.repository_root.resolve(),
        args.stage80.resolve(),
        args.script_source_stage.resolve(),
    )
    print(
        json.dumps(
            {
                "artifacts": len(paths),
                "output_stage": str(args.output_stage.resolve()),
                "stage_id": STAGE_ID,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
