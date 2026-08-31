#!/usr/bin/env python3
"""Rebuild PR 1's 9,450 -> 10,059 finite-table timeline.

The command reads only committed deterministic snapshots.  Historical Python
files are parsed as data and are never imported or executed.  Large archives,
CSV files, JSONL files, and hashes are handled in bounded forward-only passes.
"""

from __future__ import annotations

import argparse
import ast
import base64
import codecs
import csv
from dataclasses import dataclass, field
import hashlib
import io
import itertools
import json
import lzma
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import BinaryIO, Iterable
import zlib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pr1_common import (
    HISTORICAL_ID_SCHEME,
    SCHEMA_VERSION,
    TABLE_ENCODING,
    atomic_text_writer,
    canonical_table_bytes,
    canonical_table_id,
    deterministic_gzip_writer,
    extract_chunked_ascii_constant,
    flatten_table,
    historical_table_id,
    iter_archive_members,
    json_line,
    read_bounded,
    sha256_bytes,
    sha256_path,
)


CAPTURED_AT = "2026-08-31T14:40:52+08:00"
SOURCE_CONTEXT_REVISION = "6d8b449071a9168b3ddb35f77533e093833c70a4"
SOURCE_NOTE = (
    "The members/wubing tree was ignored by the source repository. The revision is "
    "context only; archive and member hashes identify the captured bytes."
)
LICENSE_STATUS = "not-specified; no license grant inferred"
BITSET_BYTES = (62_576 + 7) // 8
HISTORICAL_PAYLOAD_LIMIT = 4 * 1024 * 1024
BYTE_BIT_COUNTS = tuple(bin(value).count("1") for value in range(256))
FALSE_ROOT = "members/wubing/data/processed/rulebooks/order5_rule_registry/false/"
PRIMARY_PREFIX = FALSE_ROOT + "selected_false_finmodel_rule_scripts/"
DRAFT_PREFIX = "members/wubing/experiments/solvers/false_solver/drafts/"

STAGE10 = "10-primary-9450"
STAGE20 = "20-registered-9852"
STAGE30 = "30-early-deltas-9957"
STAGE40 = "40-delivery-10059"
RAW_ARCHIVE_SHA256 = {
    STAGE10: "0d47b49df24bfe530ac3e566bfc5fa17994594da94bfbf6ab407cb6c39e6879f",
    STAGE20: "8baf705ea54315c2ec07d54f9d17d2b01266bae7a7c5657520c2a171a9b35fc6",
    STAGE30: "d7eac6a943a037f76ca85b8c65722eddcb0074ba1e57248ccca9cde29914a6a4",
    STAGE40: "512690db8218fd2f4a0b7a2df86c46069b8ad4bd90826af4487f02d2f7540f3c",
}


class ReconstructionError(RuntimeError):
    """Raised when a frozen source or derived invariant drifts."""


@dataclass
class Table:
    order: int
    entries: tuple[int, ...]
    first_seen_stage: str
    provenance: list[dict] = field(default_factory=list)
    task_check_paths: list[str] = field(default_factory=list)

    @property
    def table_id(self) -> str:
        return canonical_table_id(self.order, self.entries)

    @property
    def historical_id(self) -> str:
        return historical_table_id(self.order, self.entries)

    @property
    def raw(self) -> bytes:
        return canonical_table_bytes(self.order, self.entries)

    def record(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "table_id": self.table_id,
            "identifiers": [
                {"scheme": HISTORICAL_ID_SCHEME, "value": self.historical_id}
            ],
            "encoding": TABLE_ENCODING,
            "order": self.order,
            "entries": list(self.entries),
            "first_seen_stage": self.first_seen_stage,
            "record_kind": "exact-explicit",
            "provenance": self.provenance,
            "verification": {
                "shape_checked": True,
                "entry_range_checked": True,
                "task_check_paths": self.task_check_paths,
            },
        }


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ReconstructionError(message)


def verify_raw_archive(stage_id: str, archive: Path) -> None:
    ensure(archive.is_file(), f"missing {archive}")
    actual = sha256_path(archive)
    ensure(
        actual == RAW_ARCHIVE_SHA256[stage_id],
        f"raw snapshot drift for {stage_id}: expected {RAW_ARCHIVE_SHA256[stage_id]}, got {actual}",
    )


def decode_bitset(payload: object, context: str) -> bytes:
    ensure(isinstance(payload, str), f"{context}: bitset payload must be text")
    try:
        compressed = base64.b64decode(payload.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ReconstructionError(f"{context}: invalid Base64") from exc
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(compressed, BITSET_BYTES + 1)
    except zlib.error as exc:
        raise ReconstructionError(f"{context}: invalid zlib stream") from exc
    ensure(inflater.eof, f"{context}: zlib stream did not terminate within bound")
    ensure(not inflater.unconsumed_tail, f"{context}: zlib output exceeded bound")
    ensure(not inflater.unused_data, f"{context}: trailing compressed data")
    ensure(len(raw) == BITSET_BYTES, f"{context}: bitset length is {len(raw)}")
    return raw


def parse_rule_json(source: bytes, context: str) -> dict:
    try:
        tree = ast.parse(source.decode("utf-8"), filename=context)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise ReconstructionError(f"{context}: invalid Python source") from exc
    matches: list[ast.Call] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "RULE" for target in node.targets):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == "json"
            and value.func.attr == "loads"
            and len(value.args) == 1
            and not value.keywords
        ):
            matches.append(value)
    ensure(len(matches) == 1, f"{context}: expected one RULE = json.loads(...) assignment")
    try:
        literal = ast.literal_eval(matches[0].args[0])
        rule = json.loads(literal)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ReconstructionError(f"{context}: invalid literal RULE JSON") from exc
    ensure(isinstance(rule, dict), f"{context}: RULE must decode to an object")
    return rule


def table_from_nested(
    raw_table: object, stage: str, source_id: str, source_path: str, source_record: object
) -> Table:
    try:
        order, entries = flatten_table(raw_table)
    except ValueError as exc:
        raise ReconstructionError(f"{source_path}: {exc}") from exc
    return Table(
        order=order,
        entries=entries,
        first_seen_stage=stage,
        provenance=[
            {
                "source_id": source_id,
                "source_path": source_path,
                "source_record": source_record,
            }
        ],
    )


def vector_hash(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def order_distribution(tables: Iterable[Table]) -> dict[str, int]:
    counts: dict[int, int] = {}
    for table in tables:
        counts[table.order] = counts.get(table.order, 0) + 1
    return {str(order): counts[order] for order in sorted(counts)}


def bank_details(tables: list[Table]) -> tuple[bytes, dict]:
    payload = b"".join(table.raw for table in tables)
    return payload, {
        "table_count": len(tables),
        "raw_bytes": len(payload),
        "raw_sha256": sha256_bytes(payload),
        "canonical_id_vector_sha256": vector_hash(
            table.table_id.removeprefix("sha256:") for table in tables
        ),
        "historical_id_vector_sha256": vector_hash(
            table.historical_id.removeprefix("sha256:") for table in tables
        ),
        "order_distribution": order_distribution(tables),
    }


def atomic_binary(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: object) -> None:
    with atomic_text_writer(path) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl_gz(path: Path, rows: Iterable[dict]) -> int:
    count = 0
    with deterministic_gzip_writer(path) as handle:
        for row in rows:
            handle.write(json_line(row))
            count += 1
    return count


def write_table_outputs(stage_dir: Path, tables: list[Table]) -> tuple[bytes, dict]:
    bank, details = bank_details(tables)
    write_jsonl_gz(stage_dir / "normalized/tables.jsonl.gz", (table.record() for table in tables))
    atomic_binary(stage_dir / "normalized/tables.bin", bank)
    with deterministic_gzip_writer(stage_dir / "normalized/table-id-map.csv.gz") as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="", write_through=True)
        writer = csv.writer(text, lineterminator="\n")
        writer.writerow(
            ["position", "table_id", "historical_json_table_id", "first_seen_stage"]
        )
        for position, table in enumerate(tables):
            writer.writerow(
                [position, table.table_id, table.historical_id, table.first_seen_stage]
            )
        text.flush()
    return bank, details


def delta_record(
    stage: str,
    sequence: int,
    action: str,
    table: Table,
    reason: str,
    evidence: str,
    *,
    notes: str | None = None,
    source_stage: str | None = None,
) -> dict:
    record = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": stage,
        "sequence": sequence,
        "action": action,
        "table_id": table.table_id,
        "reason_code": reason,
        "evidence_paths": [evidence],
    }
    if notes:
        record["notes"] = notes
    if source_stage:
        record["source_stage_id"] = source_stage
        record["source_table_id"] = table.table_id
    return record


def parse_csv_member(handle: BinaryIO) -> csv.DictReader:
    return csv.DictReader(codecs.getreader("utf-8")(handle))


def validate_equation_index(handle: BinaryIO) -> int:
    reader = parse_csv_member(handle)
    ensure(
        reader.fieldnames
        == [
            "equation_id",
            "equation_text",
            "variable_count",
            "lhs_operation_count",
            "rhs_operation_count",
            "total_operation_count",
        ],
        "order5_equations.csv header drift",
    )
    count = 0
    total_operation_distribution: dict[int, int] = {}
    for count, row in enumerate(reader, start=1):
        ensure(int(row["equation_id"]) == count, "equation IDs are not contiguous")
        formula = row["equation_text"]
        ensure(bool(formula), f"Equation{count} has empty text")
        left, right = parse_equation(formula)
        variable_count = len(term_variables(left) | term_variables(right))
        left_operations = term_operation_count(left)
        right_operations = term_operation_count(right)
        total_operations = left_operations + right_operations
        ensure(
            (
                int(row["variable_count"]) == variable_count
                and int(row["lhs_operation_count"]) == left_operations
                and int(row["rhs_operation_count"]) == right_operations
                and int(row["total_operation_count"]) == total_operations
                and total_operations <= 5
            ),
            f"Equation{count} metadata drift",
        )
        total_operation_distribution[total_operations] = (
            total_operation_distribution.get(total_operations, 0) + 1
        )
    ensure(
        total_operation_distribution
        == {0: 2, 1: 5, 2: 39, 3: 364, 4: 4_284, 5: 57_882},
        "order-at-most-5 equation distribution drift",
    )
    return count


def audit_stage10_coverage(archive: Path) -> tuple[dict[str, dict], dict]:
    """Cross-check the two 229,666-row coverage rankings with a disk-backed join."""

    suffixes = {
        "coverage": "/false_model_coverage_9722317.csv",
        "primary": "/false_model_primary_coverage_9722317.csv",
    }
    headers = {
        "coverage": [
            "rank",
            "witness_family",
            "witness_n",
            "witness_model_idx",
            "model_key",
            "covered_final_false_pairs",
        ],
        "primary": [
            "rank",
            "witness_family",
            "witness_n",
            "witness_model_idx",
            "model_key",
            "primary_unique_false_pairs",
        ],
    }
    expected = {
        "coverage": {
            "rows": 229_666,
            "sum": 181_011_287,
            "nonzero": 229_666,
            "minimum": 1,
            "maximum": 1_344_197,
            "ordered_key_sha256": "be53f11ba25f95f7f87613e22a5cdbbcc9b56c7e59317746a4b0587059f332f6",
        },
        "primary": {
            "rows": 229_666,
            "sum": 9_722_317,
            "nonzero": 9_452,
            "minimum": 0,
            "maximum": 1_343_256,
            "ordered_key_sha256": "46084f1b54c11f4da2b7998240d6a338aaaacae2a6afe2ff9eebe030195d17b5",
        },
    }
    nonzero: dict[str, dict] = {}
    observed: dict[str, dict] = {}
    table_names = {"coverage": "coverage_rank", "primary": "primary_rank"}
    with tempfile.TemporaryDirectory(prefix="finite-bank-stage10-") as temporary_dir:
        database_path = Path(temporary_dir) / "coverage.sqlite3"
        with sqlite3.connect(database_path) as database:
            database.execute("PRAGMA journal_mode=OFF")
            database.execute("PRAGMA synchronous=OFF")
            database.execute("PRAGMA temp_store=FILE")
            for label in suffixes:
                database.execute(
                    f"CREATE TABLE {table_names[label]} ("
                    "model_key TEXT PRIMARY KEY, family TEXT NOT NULL, "
                    "model_order INTEGER NOT NULL, model_idx INTEGER NOT NULL, "
                    "pair_count INTEGER NOT NULL)"
                )

            member_counts = {label: 0 for label in suffixes}
            for name, _member, handle in iter_archive_members(archive):
                matches = [label for label, suffix in suffixes.items() if name.endswith(suffix)]
                if not matches:
                    continue
                ensure(len(matches) == 1, f"ambiguous Stage10 coverage member: {name}")
                label = matches[0]
                member_counts[label] += 1
                reader = parse_csv_member(handle)
                ensure(reader.fieldnames == headers[label], f"{label} coverage header drift")
                count_field = headers[label][-1]
                row_count = 0
                pair_sum = 0
                positive_count = 0
                minimum: int | None = None
                maximum: int | None = None
                previous_count: int | None = None
                ordered_keys = hashlib.sha256()
                for row_count, row in enumerate(reader, start=1):
                    ensure(int(row["rank"]) == row_count, f"{label} ranks are not contiguous")
                    pair_count = int(row[count_field])
                    ensure(pair_count >= 0, f"negative {label} coverage")
                    if previous_count is not None:
                        ensure(pair_count <= previous_count, f"{label} coverage is not descending")
                    previous_count = pair_count
                    pair_sum += pair_count
                    positive_count += pair_count > 0
                    minimum = pair_count if minimum is None else min(minimum, pair_count)
                    maximum = pair_count if maximum is None else max(maximum, pair_count)
                    model_key = row["model_key"]
                    ordered_keys.update(model_key.encode("utf-8"))
                    ordered_keys.update(b"\n")
                    try:
                        database.execute(
                            f"INSERT INTO {table_names[label]} VALUES (?, ?, ?, ?, ?)",
                            (
                                model_key,
                                row["witness_family"],
                                int(row["witness_n"]),
                                int(row["witness_model_idx"]),
                                pair_count,
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise ReconstructionError(
                            f"duplicate {label} model key: {model_key}"
                        ) from exc
                    if label == "primary" and pair_count:
                        nonzero[model_key] = {
                            "rank": row_count,
                            "witness_family": row["witness_family"],
                            "witness_n": int(row["witness_n"]),
                            "witness_model_idx": int(row["witness_model_idx"]),
                            "model_key": model_key,
                            "primary_unique_false_pairs": pair_count,
                        }
                observed[label] = {
                    "rows": row_count,
                    "sum": pair_sum,
                    "nonzero": positive_count,
                    "minimum": minimum,
                    "maximum": maximum,
                    "ordered_key_sha256": ordered_keys.hexdigest(),
                }

            ensure(member_counts == {"coverage": 1, "primary": 1}, "coverage snapshot incomplete")
            ensure(observed == expected, f"Stage10 coverage summaries drift: {observed}")
            missing_or_mismatched = database.execute(
                "SELECT COUNT(*) FROM coverage_rank AS c LEFT JOIN primary_rank AS p "
                "ON p.model_key = c.model_key WHERE p.model_key IS NULL "
                "OR p.family != c.family OR p.model_order != c.model_order "
                "OR p.model_idx != c.model_idx"
            ).fetchone()[0]
            extra_primary = database.execute(
                "SELECT COUNT(*) FROM primary_rank AS p LEFT JOIN coverage_rank AS c "
                "ON c.model_key = p.model_key WHERE c.model_key IS NULL"
            ).fetchone()[0]
            inequality_violations = database.execute(
                "SELECT COUNT(*) FROM coverage_rank AS c JOIN primary_rank AS p USING (model_key) "
                "WHERE p.pair_count > c.pair_count"
            ).fetchone()[0]
            equal_counts = database.execute(
                "SELECT COUNT(*) FROM coverage_rank AS c JOIN primary_rank AS p USING (model_key) "
                "WHERE p.pair_count = c.pair_count"
            ).fetchone()[0]
            ensure(missing_or_mismatched == 0 and extra_primary == 0, "coverage model sets differ")
            ensure(inequality_violations == 0, "primary coverage exceeds total model coverage")
            ensure(equal_counts == 3_694, f"coverage/primary equality count is {equal_counts}")

            sorted_keys = hashlib.sha256()
            joint_vector = hashlib.sha256()
            for model_key, coverage_count, primary_count in database.execute(
                "SELECT c.model_key, c.pair_count, p.pair_count "
                "FROM coverage_rank AS c JOIN primary_rank AS p USING (model_key) "
                "ORDER BY c.model_key"
            ):
                sorted_keys.update(model_key.encode("utf-8"))
                sorted_keys.update(b"\n")
                joint_vector.update(model_key.encode("utf-8"))
                joint_vector.update(b"\0")
                joint_vector.update(str(coverage_count).encode("ascii"))
                joint_vector.update(b"\0")
                joint_vector.update(str(primary_count).encode("ascii"))
                joint_vector.update(b"\n")
            ensure(
                sorted_keys.hexdigest()
                == "2975062d556650566f06d21a05f9c3235cbc3772ca8b8fcdff376caf9c5ad9e5",
                "sorted Stage10 model-key set drift",
            )
            ensure(
                joint_vector.hexdigest()
                == "f06f25843e6273249844b1acab6932d8b83d4c99bb0b4adc9ba36d7097500e46",
                "joint Stage10 coverage vector drift",
            )

    return nonzero, {
        "coverage_ranking": observed["coverage"],
        "primary_ranking": observed["primary"],
        "shared_model_key_count": 229_666,
        "metadata_mismatch_count": 0,
        "primary_exceeds_coverage_count": 0,
        "equal_pair_count_count": 3_694,
        "sorted_model_key_set_sha256": sorted_keys.hexdigest(),
        "joint_coverage_primary_vector_sha256": joint_vector.hexdigest(),
    }


def build_stage10(root: Path) -> tuple[list[Table], dict]:
    stage_dir = root / "reproduction" / STAGE10
    archive = stage_dir / "raw/primary-recovery-snapshot.tar.gz"
    verify_raw_archive(STAGE10, archive)

    nonzero, coverage_audit = audit_stage10_coverage(archive)
    coverage_rows = coverage_audit["primary_ranking"]["rows"]
    coverage_sum = coverage_audit["primary_ranking"]["sum"]
    equation_count = 0
    index: dict[str, dict] = {}
    historical_summary: dict | None = None
    tables: list[Table] = []
    primary_models: list[dict] = []
    seen_model_keys: set[str] = set()
    seen_table_ids: set[str] = set()
    script_vector = hashlib.sha256()
    script_raw_bytes = 0
    script_count = 0

    expected_rule_keys = {
        "coverage_count",
        "excluded_block_payloads",
        "law_count",
        "model_family",
        "model_idx",
        "model_key",
        "model_order",
        "model_table",
        "primary_rank",
        "primary_unique_false_pairs",
        "rule_id",
        "rule_key",
        "source_bits_payload",
        "source_count",
        "source_output_dir",
        "target_bits_payload",
        "target_count",
    }

    for name, member, handle in iter_archive_members(archive):
        if name.endswith("/order5_equations.csv"):
            equation_count = validate_equation_index(handle)
            continue
        if name.endswith(
            (
                "/false_model_coverage_9722317.csv",
                "/false_model_primary_coverage_9722317.csv",
            )
        ):
            # Both rankings were already cross-checked in a disk-backed pass.
            continue
        if name.endswith("/primary_nonzero_model_index.csv"):
            reader = parse_csv_member(handle)
            expected_header = [
                "rank",
                "script_path",
                "witness_family",
                "witness_n",
                "witness_model_idx",
                "model_key",
                "primary_unique_false_pairs",
                "source_count",
                "target_count",
                "source_output_dir",
            ]
            ensure(reader.fieldnames == expected_header, "primary index CSV header drift")
            for row in reader:
                key = row["script_path"]
                ensure(key not in index, f"duplicate primary index path: {key}")
                index[key] = row
            continue
        if name.endswith("/primary_nonzero_model_generation_summary.json"):
            payload = read_bounded(handle, member.size, limit=64 * 1024)
            historical_summary = json.loads(payload)
            continue
        if "/primary_nonzero_model_scripts/" not in name or not name.endswith(".py"):
            # README and narrative files remain immutable raw evidence.
            continue

        ensure(member.size <= 64 * 1024, f"unexpectedly large primary script: {name}")
        source = read_bounded(handle, member.size, limit=64 * 1024)
        script_hash = sha256_bytes(source)
        relative_false = name.removeprefix(FALSE_ROOT)
        ensure(relative_false != name, f"primary path outside false root: {name}")
        script_vector.update(relative_false.encode("utf-8"))
        script_vector.update(b"\0")
        script_vector.update(script_hash.encode("ascii"))
        script_vector.update(b"\n")
        script_raw_bytes += len(source)
        script_count += 1

        rule = parse_rule_json(source, name)
        ensure(set(rule) == expected_rule_keys, f"{name}: RULE key set drift")
        filename_rank = int(Path(name).name[:5])
        ensure(rule["primary_rank"] == filename_rank, f"{name}: rank/filename drift")
        ensure(rule["law_count"] == 62_576, f"{name}: law count drift")
        ensure(rule["excluded_block_payloads"] == [], f"{name}: excluded blocks present")
        ensure(
            rule["coverage_count"] == rule["primary_unique_false_pairs"],
            f"{name}: primary coverage drift",
        )
        ensure(rule["model_key"] not in seen_model_keys, f"{name}: duplicate model key")
        seen_model_keys.add(rule["model_key"])
        primary_row = nonzero.get(rule["model_key"])
        ensure(primary_row is not None, f"{name}: model is not a nonzero contributor")
        ensure(
            (
                primary_row["rank"] == rule["primary_rank"]
                and primary_row["witness_family"] == rule["model_family"]
                and primary_row["witness_n"] == rule["model_order"]
                and primary_row["witness_model_idx"] == rule["model_idx"]
                and primary_row["primary_unique_false_pairs"]
                == rule["primary_unique_false_pairs"]
            ),
            f"{name}: primary coverage row disagrees with RULE",
        )

        source_bits = decode_bitset(rule["source_bits_payload"], f"{name}:source")
        target_bits = decode_bitset(rule["target_bits_payload"], f"{name}:target")
        ensure(
            all((left ^ right) == 0xFF for left, right in zip(source_bits, target_bits)),
            f"{name}: source/target bitsets are not complements",
        )
        source_count = sum(BYTE_BIT_COUNTS[value] for value in source_bits)
        target_count = sum(BYTE_BIT_COUNTS[value] for value in target_bits)
        ensure(source_count == rule["source_count"], f"{name}: source count drift")
        ensure(target_count == rule["target_count"], f"{name}: target count drift")

        index_path = relative_false
        indexed = index.get(index_path)
        ensure(indexed is not None, f"{name}: missing primary index row")
        comparisons = {
            "rank": rule["primary_rank"],
            "witness_family": rule["model_family"],
            "witness_n": rule["model_order"],
            "witness_model_idx": rule["model_idx"],
            "model_key": rule["model_key"],
            "primary_unique_false_pairs": rule["primary_unique_false_pairs"],
            "source_count": rule["source_count"],
            "target_count": rule["target_count"],
            "source_output_dir": rule["source_output_dir"],
        }
        for field_name, expected in comparisons.items():
            actual = indexed[field_name]
            if isinstance(expected, int):
                actual = int(actual)
            ensure(actual == expected, f"{name}: index {field_name} drift")

        evidence = f"reproduction/{STAGE10}/raw/{archive.name}#{name}"
        table = table_from_nested(
            rule["model_table"],
            STAGE10,
            "stage10-local-snapshot",
            evidence,
            rule["rule_id"],
        )
        ensure(table.order == rule["model_order"], f"{name}: model order drift")
        ensure(table.table_id not in seen_table_ids, f"{name}: duplicate table")
        seen_table_ids.add(table.table_id)
        tables.append(table)
        primary_models.append(
            {
                "schema_version": SCHEMA_VERSION,
                "primary_rank": rule["primary_rank"],
                "model_key": rule["model_key"],
                "model_family": rule["model_family"],
                "model_idx": rule["model_idx"],
                "table_id": table.table_id,
                "historical_json_table_id": table.historical_id,
                "primary_unique_false_pairs": rule["primary_unique_false_pairs"],
                "source_count": rule["source_count"],
                "target_count": rule["target_count"],
                "source_output_dir": rule["source_output_dir"],
                "raw_script_path": evidence,
                "raw_script_sha256": script_hash,
            }
        )

    ensure(equation_count == 62_576, f"equation count is {equation_count}")
    ensure(coverage_rows == 229_666, f"coverage row count is {coverage_rows}")
    ensure(coverage_sum == 9_722_317, f"primary coverage sum is {coverage_sum}")
    ensure(len(nonzero) == 9_452, f"nonzero contributor count is {len(nonzero)}")
    ensure(len(index) == 9_450, f"primary index count is {len(index)}")
    ensure(script_count == 9_450, f"primary script count is {script_count}")
    ensure(len(tables) == 9_450, f"primary table count is {len(tables)}")
    ensure(
        script_vector.hexdigest()
        == "adb9a620da8c2ef707fe1e8a65bd34683855043477db1ed1a7b01a9e2a95ab28",
        "historical primary script vector drift",
    )
    ensure(script_raw_bytes == 52_840_787, f"primary script byte total is {script_raw_bytes}")
    ensure(
        historical_summary
        == {
            "elapsed_sec": 4054.1,
            "generated_scripts": 9450,
            "index_csv": "selected_false_finmodel_rule_scripts/primary_nonzero_model_index.csv",
            "missing_models": 0,
            "output_dir": "selected_false_finmodel_rule_scripts/primary_nonzero_model_scripts",
            "selected_nonzero_models": 9452,
            "skipped": 2,
        },
        "historical primary generation summary drift",
    )

    recovered_keys = {row["model_key"] for row in primary_models}
    skipped = sorted(
        (row for key, row in nonzero.items() if key not in recovered_keys),
        key=lambda row: row["rank"],
    )
    ensure(
        [(row["rank"], row["witness_model_idx"], row["primary_unique_false_pairs"]) for row in skipped]
        == [(3496, 42708, 14), (8142, 19904, 1)],
        "skipped primary records drift",
    )
    for row in skipped:
        row["schema_version"] = SCHEMA_VERSION
        row["reason"] = "model_table_not_recovered_from_historical_models_jsonl_gz"
    recovered_primary_sum = sum(row["primary_unique_false_pairs"] for row in primary_models)
    ensure(recovered_primary_sum == 9_722_302, "recovered primary contribution sum drift")

    delta = [
        delta_record(
            STAGE10,
            sequence,
            "add",
            table,
            "primary_nonzero_table_recovered",
            primary_models[sequence]["raw_script_path"],
            notes=f"historical primary rank {primary_models[sequence]['primary_rank']}",
        )
        for sequence, table in enumerate(tables)
    ]
    bank, details = write_table_outputs(stage_dir, tables)
    ensure(details["raw_sha256"] == "66c2f19b5c59f359f14524cee5ec9cfc7d527ff09e4aeb84cac13666cd5cf9e3", "primary binary hash drift")
    ensure(
        details["order_distribution"]
        == {"3": 9, "4": 6019, "5": 79, "6": 1192, "7": 18, "8": 781, "9": 754, "10": 146, "11": 93, "12": 359},
        "primary order distribution drift",
    )
    write_jsonl_gz(stage_dir / "normalized/primary-models.jsonl.gz", primary_models)
    write_jsonl_gz(stage_dir / "delta.jsonl.gz", delta)
    with atomic_text_writer(stage_dir / "normalized/skipped-models.jsonl") as handle:
        for row in skipped:
            handle.write(json_line(row).decode("utf-8"))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE10,
        "metrics": {
            "input.equations": equation_count,
            "mining.model_identities": coverage_rows,
            "primary.nonzero_contributors": len(nonzero),
            "primary.recoverable": len(tables),
        },
        "action_counts": {"add": len(delta)},
        "bank": details,
        "source_audit": {
            "coverage_rankings": coverage_audit,
            "primary_script_count": script_count,
            "primary_script_bytes": script_raw_bytes,
            "primary_script_vector_sha256": script_vector.hexdigest(),
            "primary_coverage_sum": coverage_sum,
            "recovered_primary_coverage_sum": recovered_primary_sum,
            "skipped_primary_coverage_sum": sum(row["primary_unique_false_pairs"] for row in skipped),
        },
        "known_gaps": [
            "The historical models.jsonl.gz and generator that created the 9,450 scripts are not present.",
            "The historical directed_unique_false_pairs_9715951.csv and out*/false_pairs.csv.gz witness inputs are not present.",
            "This stage reproduces normalization and validation from frozen scripts, not the original mining campaign.",
        ],
    }
    write_json(stage_dir / "summary.json", summary)
    return tables, summary


def update_path_vector(digest, relative: str, payload: bytes) -> None:
    digest.update(relative.encode("utf-8"))
    digest.update(b"\0")
    digest.update(sha256_bytes(payload).encode("ascii"))
    digest.update(b"\n")


def build_stage20(root: Path, primary_tables: list[Table]) -> tuple[list[Table], dict]:
    stage_dir = root / "reproduction" / STAGE20
    archive = stage_dir / "raw/registry-and-d3-snapshot.tar.gz"
    verify_raw_archive(STAGE20, archive)

    tables = list(primary_tables)
    by_id = {table.table_id: table for table in tables}
    manifest_vector = hashlib.sha256()
    rule_vector = hashlib.sha256()
    selected_vector = hashlib.sha256()
    manifest_count = 0
    rule_count = 0
    selected_count = 0
    table_manifest_count = 0
    no_table_inputs: list[dict] = []
    input_decisions: list[dict] = []
    delta: list[dict] = []
    registered_unique_ids: set[str] = set()
    registered_order_distribution: dict[int, int] = {}
    d3_audit: dict | None = None

    for name, member, handle in iter_archive_members(archive):
        ensure(member.size <= 4 * 1024 * 1024, f"unexpectedly large Stage20 member: {name}")
        payload = read_bounded(handle, member.size, limit=4 * 1024 * 1024)
        if name.startswith(FALSE_ROOT) and name.endswith(".manifest.json"):
            relative = name.removeprefix(FALSE_ROOT)
            update_path_vector(manifest_vector, relative, payload)
            manifest_index = manifest_count
            manifest_count += 1
            try:
                manifest = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ReconstructionError(f"invalid registry manifest {name}") from exc
            raw_table = manifest.get("model_table")
            if raw_table is None:
                decision = {
                    "schema_version": SCHEMA_VERSION,
                    "sequence": manifest_index,
                    "source_path": f"reproduction/{STAGE20}/raw/{archive.name}#{name}",
                    "source_record": manifest.get("rule_id", Path(name).name),
                    "classification": "no-table",
                    "reason": "manifest_has_null_model_table",
                }
                no_table_inputs.append(decision)
                input_decisions.append(decision)
                continue

            table_manifest_count += 1
            evidence = f"reproduction/{STAGE20}/raw/{archive.name}#{name}"
            candidate = table_from_nested(
                raw_table,
                STAGE20,
                "stage20-local-snapshot",
                evidence,
                manifest.get("rule_id", Path(name).name),
            )
            table_id = candidate.table_id
            historical = candidate.historical_id
            existing = by_id.get(table_id)
            if existing is None:
                action = "add"
                reason = "registered_table_first_occurrence"
                by_id[table_id] = candidate
                tables.append(candidate)
                existing = candidate
                registered_unique_ids.add(table_id)
                registered_order_distribution[candidate.order] = (
                    registered_order_distribution.get(candidate.order, 0) + 1
                )
            else:
                ensure(
                    existing.first_seen_stage == STAGE20,
                    f"registered table unexpectedly overlaps primary bank: {name}",
                )
                action = "duplicate"
                reason = "registered_table_repeated_manifest"
                existing.provenance.extend(candidate.provenance)

            input_decisions.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "sequence": manifest_index,
                    "source_path": evidence,
                    "source_record": manifest.get("rule_id", Path(name).name),
                    "classification": f"table-{action}",
                    "table_id": table_id,
                    "historical_json_table_id": historical,
                }
            )
            delta.append(
                delta_record(
                    STAGE20,
                    len(delta),
                    action,
                    existing,
                    reason,
                    evidence,
                )
            )
            continue

        if name.startswith(FALSE_ROOT) and name.endswith("_rule.py"):
            relative = name.removeprefix(FALSE_ROOT)
            update_path_vector(rule_vector, relative, payload)
            rule_count += 1
            continue

        if (
            name.startswith(PRIMARY_PREFIX)
            and "/primary_nonzero_model_scripts/" not in name
            and name.endswith(".py")
            and Path(name).name.startswith("false_finmodel_setcheck_")
        ):
            relative = name.removeprefix(FALSE_ROOT)
            update_path_vector(selected_vector, relative, payload)
            selected_count += 1
            rule = parse_rule_json(payload, name)
            candidate = table_from_nested(
                rule["model_table"],
                STAGE20,
                "stage20-local-snapshot",
                f"reproduction/{STAGE20}/raw/{archive.name}#{name}",
                rule["rule_id"],
            )
            ensure(candidate.table_id in registered_unique_ids, f"selected-root table is new: {name}")
            continue

        if name.endswith("/d3/false9852_model_audit.json"):
            d3_audit = json.loads(payload)

    ensure(manifest_count == 476, f"registry manifest count is {manifest_count}")
    ensure(rule_count == 476, f"registry rule count is {rule_count}")
    ensure(selected_count == 6, f"selected-root script count is {selected_count}")
    ensure(table_manifest_count == 475, f"table-bearing manifest count is {table_manifest_count}")
    ensure(len(no_table_inputs) == 1, f"no-table manifest count is {len(no_table_inputs)}")
    ensure(len(registered_unique_ids) == 402, f"registered unique count is {len(registered_unique_ids)}")
    ensure(len(delta) == 475, f"registered delta count is {len(delta)}")
    action_counts = {
        "add": sum(row["action"] == "add" for row in delta),
        "duplicate": sum(row["action"] == "duplicate" for row in delta),
    }
    ensure(action_counts == {"add": 402, "duplicate": 73}, "registered action counts drift")
    anchors = {
        "manifest_vector_sha256": (
            manifest_vector.hexdigest(),
            "84d6a43b1f180aac0e9591c53740186f7aed0f10673b7ce702334f2b4244e10e",
        ),
        "registered_rule_vector_sha256": (
            rule_vector.hexdigest(),
            "fb0e6eea56051baa6c0f695fbbb820f76c2e3a9699cfae5f1911866d1766f769",
        ),
        "selected_root_vector_sha256": (
            selected_vector.hexdigest(),
            "cf3a6350d73a6fd8cc47bf784c0c5570c08ff6371f48bed62c43d84bf503bddf",
        ),
    }
    for label, (actual, expected) in anchors.items():
        ensure(actual == expected, f"{label} drift: {actual}")
    ensure(d3_audit is not None, "missing d3 model audit")
    ensure(d3_audit["status"] == "passed", "historical d3 audit did not pass")

    bank, details = write_table_outputs(stage_dir, tables)
    ensure(len(tables) == 9_852, f"False9852 count is {len(tables)}")
    ensure(len(bank) == 352_146, f"False9852 raw bytes is {len(bank)}")
    ensure(sha256_bytes(bank) == "a1135cff6df0d55f714401ae90b9cba2e385c33ce2e3c31ae623130e0124cda8", "False9852 binary hash drift")
    ensure(
        details["historical_id_vector_sha256"]
        == "0e39adb599a9c7162bede403a32ae3901c5b87f6c33d1a5d2108a5a2a4cc32f4",
        "False9852 historical identity vector drift",
    )
    ensure(
        details["order_distribution"]
        == {"2": 10, "3": 111, "4": 6179, "5": 135, "6": 1208, "7": 36, "8": 792, "9": 764, "10": 146, "11": 104, "12": 359, "17": 8},
        "False9852 order distribution drift",
    )
    ensure(
        {str(key): registered_order_distribution[key] for key in sorted(registered_order_distribution)}
        == {"2": 10, "3": 102, "4": 160, "5": 56, "6": 16, "7": 18, "8": 11, "9": 10, "11": 11, "17": 8},
        "registered order distribution drift",
    )
    write_jsonl_gz(stage_dir / "normalized/input-decisions.jsonl.gz", input_decisions)
    write_jsonl_gz(stage_dir / "delta.jsonl.gz", delta)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE20,
        "metrics": {"registry.input": len(registered_unique_ids), "bank.9852": len(tables)},
        "action_counts": action_counts,
        "input_classification": {
            "manifest_count": manifest_count,
            "table_bearing_manifest_count": table_manifest_count,
            "no_table_manifest_count": len(no_table_inputs),
            "registered_unique_table_count": len(registered_unique_ids),
            "selected_root_representative_count": selected_count,
            "selected_root_new_table_count": 0,
            "primary_registered_overlap_count": 0,
        },
        "bank": details,
        "source_audit": {label: actual for label, (actual, _expected) in anchors.items()},
        "ordering": (
            "9,450 primary script paths in lexicographic order, followed by the first "
            "occurrence of each registered table in lexicographic manifest-path order"
        ),
    }
    write_json(stage_dir / "summary.json", summary)
    return tables, summary


def literal_assignments(source: str, names: set[str]) -> dict[str, object]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ReconstructionError("historical solver has invalid Python syntax") from exc
    expressions: dict[str, ast.expr] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in names:
                ensure(target.id not in expressions, f"duplicate assignment to {target.id}")
                expressions[target.id] = value
    ensure(set(expressions) == names, f"missing literal assignments: {sorted(names - set(expressions))}")
    result: dict[str, object] = {}
    for name, expression in expressions.items():
        try:
            result[name] = ast.literal_eval(expression)
        except (ValueError, TypeError) as exc:
            raise ReconstructionError(f"assignment to {name} is not literal") from exc
    return result


def d1_input_tables(source: str, evidence: str) -> list[tuple[str, Table]]:
    early_names = (
        "_RULEBOOK_REFUTATION4_TABLE",
        "_RULEBOOK_REFUTATION5_TABLE",
        "_RULEBOOK_REFUTATION852_TABLE",
        "_RULEBOOK_REFUTATION773_TABLE",
        "_RULEBOOK_ACCEPTED80_BLOCK019_TABLE",
        "_RULEBOOK_ACCEPTED80_BLOCK005_TABLE",
        "_RULEBOOK_ACCEPTED80_BLOCK049_TABLE",
    )
    special_names = {
        *early_names,
        "_RULEBOOK_AFFINE_N9_MICRO_ORBIT_DATA",
        "_RULEBOOK_PRINCIPAL_FEEDBACK_TABLE",
        "_RULEBOOK_FIN6_SPARSE_DECODE_TABLE",
        "_RULEBOOK_AFFINE_MODELS",
    }
    values = literal_assignments(source, special_names)
    rows: list[tuple[str, object]] = []
    for name in early_names:
        rows.append((name.removeprefix("_RULEBOOK_").removesuffix("_TABLE").lower(), values[name]))

    micro = values["_RULEBOOK_AFFINE_N9_MICRO_ORBIT_DATA"]
    ensure(isinstance(micro, tuple) and len(micro) == 7, "d1 micro-orbit data drift")
    for model_idx, digits, _source_payload in micro:
        ensure(isinstance(digits, str) and len(digits) == 81 and digits.isdigit(), "invalid d1 n9 digits")
        table = [[int(digits[9 * row + column]) for column in range(9)] for row in range(9)]
        rows.append((f"affine_n9_micro_orbit_idx{model_idx}", table))
    rows.append(("principal_feedback", values["_RULEBOOK_PRINCIPAL_FEEDBACK_TABLE"]))
    rows.append(("fin6_sparse_decode", values["_RULEBOOK_FIN6_SPARSE_DECODE_TABLE"]))

    affine = values["_RULEBOOK_AFFINE_MODELS"]
    ensure(isinstance(affine, tuple) and len(affine) == 50, "d1 affine portfolio drift")
    for order, left, right, constant in affine:
        table = [
            [
                (left * row + right * column + constant) % order
                for column in range(order)
            ]
            for row in range(order)
        ]
        rows.append((f"affine_n{order}_a{left}_b{right}_c{constant}", table))

    result = [
        (
            label,
            table_from_nested(
                raw_table,
                STAGE30,
                "stage30-local-snapshot",
                evidence,
                label,
            ),
        )
        for label, raw_table in rows
    ]
    ensure(len(result) == 66, f"d1 static table count is {len(result)}")
    ensure(len({table.table_id for _label, table in result}) == 66, "duplicate table inside d1")
    return result


def d2_input_tables(source: str, evidence: str) -> list[tuple[str, Table]]:
    values = literal_assignments(source, {"_OFFLINE_FALSE244_FINITE_TABLES"})
    frozen = values["_OFFLINE_FALSE244_FINITE_TABLES"]
    ensure(isinstance(frozen, dict) and len(frozen) == 145, "d2 finite table dictionary drift")
    result: list[tuple[str, Table]] = []
    for historical_digest, raw_table in frozen.items():
        ensure(
            isinstance(historical_digest, str) and re.fullmatch(r"[a-f0-9]{64}", historical_digest) is not None,
            "invalid d2 historical table digest",
        )
        table = table_from_nested(
            raw_table,
            STAGE30,
            "stage30-local-snapshot",
            evidence,
            historical_digest,
        )
        ensure(
            table.historical_id == "sha256:" + historical_digest,
            f"d2 frozen table digest drift: {historical_digest}",
        )
        result.append((historical_digest, table))
    ensure(len({table.table_id for _label, table in result}) == 145, "duplicate table inside d2")
    return result


def decode_historical_table_payload(
    source: str,
    constant: str,
    *,
    compression: str,
) -> tuple[bytes, bytes]:
    encoded = extract_chunked_ascii_constant(source, constant)
    try:
        packed = base64.b85decode(encoded)
        if compression == "xz":
            inflater = lzma.LZMADecompressor()
            raw = inflater.decompress(packed, max_length=HISTORICAL_PAYLOAD_LIMIT + 1)
            ensure(len(raw) <= HISTORICAL_PAYLOAD_LIMIT, f"{constant}: XZ output exceeds bound")
            ensure(inflater.eof, f"{constant}: XZ stream did not terminate within bound")
            ensure(not inflater.unused_data, f"{constant}: trailing XZ data")
        elif compression == "zlib":
            inflater = zlib.decompressobj()
            raw = inflater.decompress(packed, HISTORICAL_PAYLOAD_LIMIT + 1)
            ensure(len(raw) <= HISTORICAL_PAYLOAD_LIMIT, f"{constant}: zlib output exceeds bound")
            ensure(inflater.eof, f"{constant}: zlib stream did not terminate within bound")
            ensure(not inflater.unconsumed_tail, f"{constant}: zlib output exceeds bound")
            ensure(not inflater.unused_data, f"{constant}: trailing zlib data")
        else:
            raise ValueError(compression)
    except (ValueError, lzma.LZMAError, zlib.error) as exc:
        raise ReconstructionError(f"cannot decode historical payload {constant}") from exc
    return packed, raw


def build_stage30(root: Path, bank9852: list[Table]) -> tuple[list[Table], dict]:
    stage_dir = root / "reproduction" / STAGE30
    archive = stage_dir / "raw/d1-d2-d4-d6-d8-snapshot.tar.gz"
    verify_raw_archive(STAGE30, archive)
    wanted_suffixes = {
        "/d1/solver.py",
        "/d2/solver.py",
        "/d2/offline_false244_model_audit.json",
        "/d4/solver.py",
        "/d6/formula_solver.py",
        "/d6/model_audit.json",
        "/d8/formula_solver.py",
        "/d8/model_audit.json",
    }
    captured: dict[str, bytes] = {}
    member_hashes: dict[str, str] = {}
    for name, member, handle in iter_archive_members(archive):
        ensure(member.size <= 4 * 1024 * 1024, f"unexpectedly large Stage30 member: {name}")
        payload = read_bounded(handle, member.size, limit=4 * 1024 * 1024)
        member_hashes[name] = sha256_bytes(payload)
        if any(name.endswith(suffix) for suffix in wanted_suffixes):
            captured[name] = payload

    def source_for(suffix: str) -> tuple[str, str]:
        matches = [(name, payload) for name, payload in captured.items() if name.endswith(suffix)]
        ensure(len(matches) == 1, f"expected one archived {suffix}, found {len(matches)}")
        name, payload = matches[0]
        try:
            return name, payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReconstructionError(f"non-UTF-8 historical source: {name}") from exc

    d1_name, d1_source = source_for("/d1/solver.py")
    d2_name, d2_source = source_for("/d2/solver.py")
    d4_name, d4_source = source_for("/d4/solver.py")
    d6_name, d6_source = source_for("/d6/formula_solver.py")
    d8_name, d8_source = source_for("/d8/formula_solver.py")
    ensure(member_hashes[d1_name] == "e4c8d2168bbb5569a6d4db7cc1a8c9517426d10721f297b0370e59cf495c9cf0", "d1 solver hash drift")
    ensure(member_hashes[d2_name] == "f044c640a31106f3cfea4840c9024230eb4b26b32d2c54350afef6165c15df12", "d2 solver hash drift")
    ensure(member_hashes[d4_name] == "f547221f5ae06acdadddbae49e02366b41f165e52913594281feba451e42e949", "d4 solver hash drift")

    raw_archive_evidence = f"reproduction/{STAGE30}/raw/{archive.name}"
    d1_rows = d1_input_tables(d1_source, f"{raw_archive_evidence}#{d1_name}")
    d2_rows = d2_input_tables(d2_source, f"{raw_archive_evidence}#{d2_name}")
    ensure(
        order_distribution(table for _label, table in d1_rows)
        == {"4": 4, "5": 2, "6": 5, "7": 15, "8": 3, "9": 12, "11": 8, "13": 1, "16": 1, "17": 13, "41": 1, "43": 1},
        "d1 order distribution drift",
    )
    ensure(
        order_distribution(table for _label, table in d2_rows)
        == {"4": 6, "5": 31, "6": 35, "7": 12, "8": 18, "9": 13, "10": 4, "12": 1, "13": 15, "16": 3, "19": 1, "20": 3, "25": 2, "32": 1},
        "d2 order distribution drift",
    )
    ensure(
        not ({table.table_id for _label, table in d1_rows} & {table.table_id for _label, table in d2_rows}),
        "d1 and d2 unexpectedly overlap",
    )

    by_id = {table.table_id: table for table in bank9852}
    delta: list[dict] = []
    input_rows: list[dict] = []
    batch_counts: dict[str, dict[str, int]] = {
        "d1": {"input": 0, "add": 0, "duplicate": 0},
        "d2": {"input": 0, "add": 0, "duplicate": 0},
    }
    for batch, rows in (("d1", d1_rows), ("d2", d2_rows)):
        for batch_sequence, (label, candidate) in enumerate(rows):
            batch_counts[batch]["input"] += 1
            existing = by_id.get(candidate.table_id)
            if existing is None:
                action = "add"
                reason = f"{batch}_new_exact_table"
                by_id[candidate.table_id] = candidate
                existing = candidate
            else:
                action = "duplicate"
                reason = f"{batch}_existing_exact_table"
                existing.provenance.extend(candidate.provenance)
            batch_counts[batch][action] += 1
            evidence = candidate.provenance[0]["source_path"]
            delta.append(
                delta_record(
                    STAGE30,
                    len(delta),
                    action,
                    existing,
                    reason,
                    evidence,
                    notes=f"{batch} input {batch_sequence}: {label}",
                    source_stage=STAGE20 if action == "duplicate" else None,
                )
            )
            input_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "sequence": len(input_rows),
                    "batch": batch,
                    "batch_sequence": batch_sequence,
                    "source_record": label,
                    "table_id": candidate.table_id,
                    "historical_json_table_id": candidate.historical_id,
                    "classification": action,
                    "source_path": evidence,
                }
            )
    ensure(
        batch_counts
        == {
            "d1": {"input": 66, "add": 11, "duplicate": 55},
            "d2": {"input": 145, "add": 94, "duplicate": 51},
        },
        f"early delta counts drift: {batch_counts}",
    )
    ensure(len(by_id) == 9_957, f"early accumulated bank count is {len(by_id)}")

    # The historical d6/d8 payload order is a canonical build order, not the
    # chronological d1-then-d2 ingestion order represented by delta.jsonl.gz.
    tables = sorted(by_id.values(), key=lambda table: (table.order, table.historical_id))
    bank, details = write_table_outputs(stage_dir, tables)
    ensure(len(bank) == 367_581, f"False9957 raw bytes is {len(bank)}")
    ensure(sha256_bytes(bank) == "c032654b7674ed3386b7700ccf7f4ed7344d1e0791c851d2bf5a5cf16ce8902c", "False9957 binary hash drift")
    ensure(
        details["historical_id_vector_sha256"]
        == "094743ce81e80958039b285c2451f5415cfbe979b016842b861b60b606807657",
        "False9957 historical order vector drift",
    )
    ensure(
        details["order_distribution"]
        == {"2": 10, "3": 111, "4": 6179, "5": 166, "6": 1224, "7": 48, "8": 799, "9": 769, "10": 146, "11": 104, "12": 359, "13": 16, "16": 4, "17": 13, "19": 1, "20": 3, "25": 2, "32": 1, "41": 1, "43": 1},
        "False9957 order distribution drift",
    )

    d4_packed, d4_raw = decode_historical_table_payload(
        d4_source, "_FALSE9852_TABLES_XZ_B85", compression="xz"
    )
    ensure(d4_raw == b"".join(table.raw for table in bank9852), "d4 payload != reconstructed 9852")
    payload_checks = {}
    for label, source in (("d6", d6_source), ("d8", d8_source)):
        packed, raw = decode_historical_table_payload(source, "_TABLES_XZ_B85", compression="xz")
        ensure(raw == bank, f"{label} payload != reconstructed 9957")
        payload_checks[label] = {
            "xz_bytes": len(packed),
            "xz_sha256": sha256_bytes(packed),
            "raw_bytes": len(raw),
            "raw_sha256": sha256_bytes(raw),
        }
    ensure(payload_checks["d6"]["xz_sha256"] == "36841036d9464b4121ab578d431c9784d873349e65aa87f4598113abb0a6e1e1", "d6 XZ hash drift")

    write_jsonl_gz(stage_dir / "normalized/input-tables.jsonl.gz", input_rows)
    write_jsonl_gz(stage_dir / "delta.jsonl.gz", delta)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE30,
        "metrics": {
            "d1.input": batch_counts["d1"]["input"],
            "d1.overlap": batch_counts["d1"]["duplicate"],
            "d1.delta": batch_counts["d1"]["add"],
            "d2.input": batch_counts["d2"]["input"],
            "d2.overlap": batch_counts["d2"]["duplicate"],
            "d2.delta": batch_counts["d2"]["add"],
            "bank.9957": len(tables),
        },
        "action_counts": {
            "add": sum(row["action"] == "add" for row in delta),
            "duplicate": sum(row["action"] == "duplicate" for row in delta),
        },
        "batch_counts": batch_counts,
        "bank": details,
        "historical_payload_checks": {
            "d4_false9852": {
                "xz_bytes": len(d4_packed),
                "xz_sha256": sha256_bytes(d4_packed),
                "raw_bytes": len(d4_raw),
                "raw_sha256": sha256_bytes(d4_raw),
            },
            **payload_checks,
        },
        "ordering": {
            "delta": "d1 portfolio order, then d2 frozen-dictionary order",
            "bank_payload": "ascending (order, historical compact-JSON SHA-256)",
        },
    }
    write_json(stage_dir / "summary.json", summary)
    return tables, summary


class TermParser:
    def __init__(self, text: str):
        compact = "".join(text.replace("◇", "*").split())
        self.tokens = re.findall(r"[A-Za-z]+|[()*]", compact)
        ensure("".join(self.tokens) == compact, f"unsupported formula syntax: {text}")
        self.position = 0

    def parse(self) -> tuple:
        result = self.parse_product()
        ensure(self.position == len(self.tokens), "trailing term tokens")
        return result

    def parse_product(self) -> tuple:
        left = self.parse_factor()
        while self.position < len(self.tokens) and self.tokens[self.position] == "*":
            self.position += 1
            right = self.parse_factor()
            left = ("op", left, right)
        return left

    def parse_factor(self) -> tuple:
        ensure(self.position < len(self.tokens), "term ended early")
        token = self.tokens[self.position]
        self.position += 1
        if re.fullmatch(r"[A-Za-z]+", token):
            return ("var", token)
        ensure(token == "(", f"unexpected term token: {token}")
        value = self.parse_product()
        ensure(
            self.position < len(self.tokens) and self.tokens[self.position] == ")",
            "unbalanced term parentheses",
        )
        self.position += 1
        return value


def normalize_equation_text(text: str) -> str:
    """Normalize only notation and whitespace, preserving all term structure."""

    return "".join(text.replace("◇", "*").split())


def parse_equation(text: str) -> tuple[tuple, tuple]:
    depth = 0
    split_at = None
    for index, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            ensure(depth >= 0, "unbalanced equation parentheses")
        elif character == "=" and depth == 0:
            ensure(split_at is None, "equation has multiple top-level equals signs")
            split_at = index
    ensure(depth == 0 and split_at is not None, f"malformed equation: {text}")
    return TermParser(text[:split_at]).parse(), TermParser(text[split_at + 1 :]).parse()


def term_variables(term: tuple) -> set[str]:
    if term[0] == "var":
        return {term[1]}
    return term_variables(term[1]) | term_variables(term[2])


def term_operation_count(term: tuple) -> int:
    if term[0] == "var":
        return 0
    return 1 + term_operation_count(term[1]) + term_operation_count(term[2])


def evaluate_term(term: tuple, assignment: dict[str, int], table: Table) -> int:
    if term[0] == "var":
        return assignment[term[1]]
    left = evaluate_term(term[1], assignment, table)
    right = evaluate_term(term[2], assignment, table)
    return table.entries[left * table.order + right]


def exhaustive_equation_check(
    formula: str, table: Table
) -> tuple[int, int, dict[str, int] | None, int | None, int | None]:
    left, right = parse_equation(formula)
    variables = sorted(term_variables(left) | term_variables(right))
    assignment_count = table.order ** len(variables)
    failures = 0
    first_witness = None
    first_left = None
    first_right = None
    for values in itertools.product(range(table.order), repeat=len(variables)):
        assignment = dict(zip(variables, values))
        left_value = evaluate_term(left, assignment, table)
        right_value = evaluate_term(right, assignment, table)
        if left_value != right_value:
            failures += 1
            if first_witness is None:
                first_witness = assignment
                first_left = left_value
                first_right = right_value
    return assignment_count, failures, first_witness, first_left, first_right


def regex_required(pattern: str, text: str, context: str, flags: int = 0) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    ensure(match is not None, f"{context}: missing pattern {pattern!r}")
    return match


def parse_delivery_report(
    text: str,
    report_name: str,
    expected_count: int,
    source_path: str,
) -> tuple[list[Table], list[dict], dict]:
    sections = re.split(r"(?=^###\s+\d+\.)", text, flags=re.MULTILINE)
    tables: list[Table] = []
    evidence_rows: list[dict] = []
    generated_at_match = regex_required(r"生成时间：([^。]+)", text, report_name)
    generated_at = generated_at_match.group(1).strip()
    for section in sections:
        header = re.search(r"^###\s+(\d+)\.\s+.*?`([^`]+)`", section, re.MULTILINE)
        if header is None:
            continue
        local_index = int(header.group(1))
        ensure(local_index == len(tables) + 1, f"{report_name}: noncontiguous section number")
        problem_id = header.group(2)
        equation_ids = regex_required(
            r"- 等式编号：`(\d+)\s*→\s*(\d+)`", section, f"{report_name}#{local_index}"
        )
        source_formula = regex_required(
            r"- 条件等式：`([^`\n]+)`", section, f"{report_name}#{local_index}"
        ).group(1).strip()
        target_formula = regex_required(
            r"- 目标等式：`([^`\n]+)`", section, f"{report_name}#{local_index}"
        ).group(1).strip()
        order = int(
            regex_required(
                r"域大小：`(\d+)`", section, f"{report_name}#{local_index}"
            ).group(1)
        )
        audit = regex_required(
            r"独立验收：条件赋值 `(\d+)` 个全部通过；目标赋值 `(\d+)` 个全部检查，(?:其中)?失败 `(\d+)` 个",
            section,
            f"{report_name}#{local_index}",
        )
        reported_source_assignments = int(audit.group(1))
        reported_target_assignments = int(audit.group(2))
        reported_target_failures = int(audit.group(3))
        witness_match = regex_required(
            r"字典序最小失败见证：`(\{[^`]+\})`；目标左/右值：`(\d+)` / `(\d+)`",
            section,
            f"{report_name}#{local_index}",
        )
        reported_witness = json.loads(witness_match.group(1))
        reported_left = int(witness_match.group(2))
        reported_right = int(witness_match.group(3))
        historical_digest = regex_required(
            r"运算表 SHA-256：`([a-f0-9]{64})`",
            section,
            f"{report_name}#{local_index}",
        ).group(1)

        rows: list[list[int]] = []
        for line in section.splitlines():
            row_match = re.match(r"^\|\s*`(\d+)`\s*\|(.*)\|\s*$", line)
            if row_match is None:
                if rows:
                    break
                continue
            row_index = int(row_match.group(1))
            values = [int(value) for value in re.findall(r"`(\d+)`", row_match.group(2))]
            ensure(row_index == len(rows), f"{report_name}#{local_index}: row index drift")
            ensure(len(values) == order, f"{report_name}#{local_index}: row width drift")
            rows.append(values)
        ensure(len(rows) == order, f"{report_name}#{local_index}: incomplete table")
        table = table_from_nested(
            rows,
            STAGE40,
            "stage40-local-snapshot",
            source_path,
            local_index,
        )
        ensure(
            table.historical_id == "sha256:" + historical_digest,
            f"{report_name}#{local_index}: reported table hash drift",
        )

        source_count, source_failures, _source_witness, _source_left, _source_right = exhaustive_equation_check(
            source_formula, table
        )
        target_count, target_failures, witness, left_value, right_value = exhaustive_equation_check(
            target_formula, table
        )
        ensure(source_count == reported_source_assignments, f"{report_name}#{local_index}: source assignment count drift")
        ensure(source_failures == 0, f"{report_name}#{local_index}: source equation fails")
        ensure(target_count == reported_target_assignments, f"{report_name}#{local_index}: target assignment count drift")
        ensure(target_failures == reported_target_failures > 0, f"{report_name}#{local_index}: target failures drift")
        ensure(witness == reported_witness, f"{report_name}#{local_index}: minimum witness drift")
        ensure((left_value, right_value) == (reported_left, reported_right), f"{report_name}#{local_index}: witness values drift")

        task_path = f"reproduction/{STAGE40}/verification/task-evidence.jsonl.gz#{len(evidence_rows)}"
        table.task_check_paths.append(task_path)
        tables.append(table)
        evidence_rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "report": report_name,
                "report_index": local_index,
                "problem_id": problem_id,
                "source_equation_id": int(equation_ids.group(1)),
                "target_equation_id": int(equation_ids.group(2)),
                "source_formula": source_formula,
                "target_formula": target_formula,
                "table_id": table.table_id,
                "historical_json_table_id": table.historical_id,
                "order": table.order,
                "source_assignments": source_count,
                "source_failures": source_failures,
                "target_assignments": target_count,
                "target_failures": target_failures,
                "lexicographically_first_witness": witness,
                "target_left_value": left_value,
                "target_right_value": right_value,
                "verification": "independent_exhaustive_enumeration",
            }
        )
    ensure(len(tables) == expected_count, f"{report_name}: found {len(tables)} tables")
    ensure(len({table.table_id for table in tables}) == expected_count, f"{report_name}: duplicate tables")
    return tables, evidence_rows, {
        "report": report_name,
        "generated_at": generated_at,
        "table_count": len(tables),
        "source_assignments": sum(row["source_assignments"] for row in evidence_rows),
        "target_assignments": sum(row["target_assignments"] for row in evidence_rows),
        "target_failures": sum(row["target_failures"] for row in evidence_rows),
        "order_distribution": order_distribution(tables),
    }


def verify_official_equation_references(
    root: Path, evidence_rows: list[dict]
) -> dict:
    """Match delivery formulas to their IDs in the frozen 62,576-equation index."""

    references = [
        (row[f"{side}_equation_id"], row[f"{side}_formula"], row, side)
        for row in evidence_rows
        for side in ("source", "target")
    ]
    wanted_ids = {equation_id for equation_id, _formula, _row, _side in references}
    archive = (
        root
        / "reproduction"
        / STAGE10
        / "raw/primary-recovery-snapshot.tar.gz"
    )
    verify_raw_archive(STAGE10, archive)
    official: dict[int, str] = {}
    equation_member_count = 0
    equation_row_count = 0
    for name, _member, handle in iter_archive_members(archive):
        if not name.endswith("/order5_equations.csv"):
            continue
        equation_member_count += 1
        reader = parse_csv_member(handle)
        ensure(
            reader.fieldnames
            == [
                "equation_id",
                "equation_text",
                "variable_count",
                "lhs_operation_count",
                "rhs_operation_count",
                "total_operation_count",
            ],
            "order5_equations.csv header drift during delivery cross-check",
        )
        for equation_row_count, csv_row in enumerate(reader, start=1):
            equation_id = int(csv_row["equation_id"])
            ensure(
                equation_id == equation_row_count,
                "equation IDs are not contiguous during delivery cross-check",
            )
            if equation_id in wanted_ids:
                official[equation_id] = csv_row["equation_text"]

    ensure(equation_member_count == 1, "expected one official equation index")
    ensure(equation_row_count == 62_576, "official equation index row count drift")
    ensure(set(official) == wanted_ids, "delivery references an unknown equation ID")
    mismatches = []
    for equation_id, formula, evidence, side in references:
        matched = normalize_equation_text(formula) == normalize_equation_text(
            official[equation_id]
        )
        evidence[f"official_{side}_formula_match"] = matched
        if not matched:
            mismatches.append((equation_id, side))
    ensure(not mismatches, f"delivery formulas disagree with official IDs: {mismatches[:5]}")
    ensure(len(references) == 204, f"delivery equation reference count is {len(references)}")
    ensure(len(wanted_ids) == 195, f"delivery distinct equation count is {len(wanted_ids)}")
    return {
        "reference_count": len(references),
        "distinct_equation_count": len(wanted_ids),
        "mismatch_count": len(mismatches),
        "normalization": "diamond-to-asterisk-and-remove-whitespace",
    }


def build_stage40(root: Path, bank9957: list[Table]) -> tuple[list[Table], dict]:
    stage_dir = root / "reproduction" / STAGE40
    archive = stage_dir / "raw/jiaming-d11-snapshot.tar.gz"
    verify_raw_archive(STAGE40, archive)
    report_suffixes = ("/jiaming/交付.md", "/jiaming/剩余252题_false挖掘交付_52题.md")
    reports: dict[str, tuple[str, bytes]] = {}
    d11_formula_source: str | None = None
    for name, member, handle in iter_archive_members(archive):
        ensure(member.size <= 512 * 1024, f"unexpectedly large Stage40 member: {name}")
        payload = read_bounded(handle, member.size, limit=512 * 1024)
        for suffix in report_suffixes:
            if name.endswith(suffix):
                reports[suffix] = (name, payload)
        if name.endswith("/d11/formula_solver.py"):
            try:
                d11_formula_source = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ReconstructionError("d11 formula solver is not UTF-8") from exc
    ensure(set(reports) == set(report_suffixes), "delivery report snapshot incomplete")

    all_delivery: list[Table] = []
    all_evidence: list[dict] = []
    batch_summaries = []
    batch_payloads = []
    for suffix, expected_count in zip(report_suffixes, (50, 52)):
        name, payload = reports[suffix]
        source_path = f"reproduction/{STAGE40}/raw/{archive.name}#{name}"
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReconstructionError(f"delivery report is not UTF-8: {name}") from exc
        tables, evidence, batch_summary = parse_delivery_report(
            text, Path(name).name, expected_count, source_path
        )
        batch_summary["report_bytes"] = len(payload)
        batch_summary["report_sha256"] = sha256_bytes(payload)
        # Rebase task-evidence fragments across both reports.
        offset = len(all_evidence)
        for index, table in enumerate(tables):
            table.task_check_paths = [
                f"reproduction/{STAGE40}/verification/task-evidence.jsonl.gz#{offset + index}"
            ]
        all_delivery.extend(tables)
        all_evidence.extend(evidence)
        batch_summaries.append(batch_summary)
        batch_payloads.append(b"".join(table.raw for table in tables))

    ensure(len(all_delivery) == 102, "delivery table count drift")
    ensure(len({table.table_id for table in all_delivery}) == 102, "delivery contains duplicates")
    ensure(
        len({row["problem_id"] for row in all_evidence}) == 102,
        "delivery contains duplicate problem IDs",
    )
    ensure(
        len(
            {
                (row["source_equation_id"], row["target_equation_id"])
                for row in all_evidence
            }
        )
        == 102,
        "delivery contains duplicate equation directions",
    )
    ensure(
        batch_summaries[0]["generated_at"] == "2026-08-05T17:38:49+00:00"
        and batch_summaries[1]["generated_at"] == "2026-08-05T23:38:59+00:00",
        "delivery report generation times drift",
    )
    ensure(
        [(row["report_bytes"], row["report_sha256"]) for row in batch_summaries]
        == [
            (74_851, "64aed2f2161ab9793cd237b4754514ad5dcc6f2e4c83187fe14500de52d0004c"),
            (110_090, "2107f47f7bb7e70de04946a284620931862def65c68f203b78f9640d4b170a15"),
        ],
        "delivery report fingerprints drift",
    )
    ensure(
        [(row["source_assignments"], row["target_assignments"], row["target_failures"]) for row in batch_summaries]
        == [(14_606, 23_932, 12_062), (18_115, 9_823, 1_368)],
        "delivery exhaustive totals drift",
    )
    ensure(
        order_distribution(all_delivery)
        == {"4": 1, "5": 41, "6": 32, "7": 15, "8": 10, "9": 3},
        "delivery order distribution drift",
    )
    ensure(len(batch_payloads[0]) == 1_414 and sha256_bytes(batch_payloads[0]) == "405e6daacfa8af4390a5cdb7ac97c8fd3e63c8bf8eb7748f01139131e49f8abe", "delivery batch 50 binary drift")
    ensure(len(batch_payloads[1]) == 2_499 and sha256_bytes(batch_payloads[1]) == "4aff0008fca0cb1db268b578f4c95afdf38ec24692f4bdf1f15ce3a46dce50c5", "delivery batch 52 binary drift")
    delivery_payload = b"".join(batch_payloads)
    ensure(len(delivery_payload) == 3_913 and sha256_bytes(delivery_payload) == "2ab611ed7f0626291f6ebdcbd6d365f7509e497f85f2e3cc5529f71bf402b5f9", "delivery 102 binary drift")
    official_equation_mapping = verify_official_equation_references(root, all_evidence)

    by_id = {table.table_id: table for table in bank9957}
    delta: list[dict] = []
    for sequence, table in enumerate(all_delivery):
        ensure(table.table_id not in by_id, f"delivery overlaps 9957: {table.table_id}")
        by_id[table.table_id] = table
        delta.append(
            delta_record(
                STAGE40,
                sequence,
                "add",
                table,
                "new_exact_delivery_table",
                table.provenance[0]["source_path"],
                notes=f"delivery report local record {table.provenance[0]['source_record']}",
            )
        )
    tables = list(bank9957) + all_delivery
    bank, details = write_table_outputs(stage_dir, tables)
    ensure(len(tables) == 10_059, f"False10059 count is {len(tables)}")
    ensure(len(bank) == 371_494, f"False10059 raw bytes is {len(bank)}")
    ensure(sha256_bytes(bank) == "fcb18adf3ff344e51a8f46d3e8eb92f7bb5487f4a3ee5ef74836076d51f3c3d4", "False10059 binary hash drift")
    ensure(
        details["order_distribution"]
        == {"2": 10, "3": 111, "4": 6180, "5": 207, "6": 1256, "7": 63, "8": 809, "9": 772, "10": 146, "11": 104, "12": 359, "13": 16, "16": 4, "17": 13, "19": 1, "20": 3, "25": 2, "32": 1, "41": 1, "43": 1},
        "False10059 order distribution drift",
    )
    ensure(d11_formula_source is not None, "historical d11 formula solver missing")
    d11_xz, d11_raw = decode_historical_table_payload(
        d11_formula_source, "_TABLES_XZ_B85", compression="xz"
    )
    ensure(d11_raw == bank, "historical d11 payload != reconstructed 10059")
    atomic_binary(stage_dir / "normalized/delivery-batch-50.bin", batch_payloads[0])
    atomic_binary(stage_dir / "normalized/delivery-batch-52.bin", batch_payloads[1])
    atomic_binary(stage_dir / "normalized/delivery-102.bin", delivery_payload)
    write_jsonl_gz(stage_dir / "verification/task-evidence.jsonl.gz", all_evidence)
    write_jsonl_gz(stage_dir / "delta.jsonl.gz", delta)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE40,
        "metrics": {
            "delivery.input": len(all_delivery),
            "delivery.overlap": 0,
            "delivery.equation_references": official_equation_mapping["reference_count"],
            "delivery.distinct_equations": official_equation_mapping["distinct_equation_count"],
            "bank.10059": len(tables),
        },
        "action_counts": {"add": len(delta)},
        "batches": batch_summaries,
        "delivery": {
            "table_count": len(all_delivery),
            "raw_bytes": len(delivery_payload),
            "raw_sha256": sha256_bytes(delivery_payload),
            "order_distribution": order_distribution(all_delivery),
            "overlap_with_9957": 0,
            "verification": "independent exhaustive source/target assignment enumeration",
        },
        "official_equation_mapping": official_equation_mapping,
        "bank": details,
        "historical_payload_check": {
            "d11_xz_bytes": len(d11_xz),
            "d11_xz_sha256": sha256_bytes(d11_xz),
            "d11_raw_bytes": len(d11_raw),
            "d11_raw_sha256": sha256_bytes(d11_raw),
        },
        "ordering": "the 9,957-table d6 order followed by report 1 records 1..50 and report 2 records 1..52",
        "known_gaps": [
            "The original miss.md, solver journals, CNF files, and CaDiCaL event logs named by the reports were not captured beside d11.",
            "The explicit report tables and formulas permit independent mathematical rechecking, but not replay of the original SAT mining run.",
        ],
    }
    write_json(stage_dir / "summary.json", summary)
    return tables, summary


def source_record(source_id: str, kind: str, locator: str, *, upstream: bool = False) -> dict:
    record = {
        "source_id": source_id,
        "kind": kind,
        "locator": locator,
        "captured_at": CAPTURED_AT,
        "license_status": LICENSE_STATUS,
    }
    if upstream:
        record["notes"] = ["Committed evidence from an earlier reproduction stage."]
    else:
        record["revision"] = SOURCE_CONTEXT_REVISION
        record["notes"] = [SOURCE_NOTE]
    return record


def artifact_record(
    stage_dir: Path,
    relative: str,
    role: str,
    media_type: str,
    source_ids: list[str],
    *,
    record_count: int | None = None,
    attributes: dict | None = None,
) -> dict:
    path = stage_dir / relative
    ensure(path.is_file(), f"missing generated artifact: {path}")
    record = {
        "path": relative,
        "role": role,
        "media_type": media_type,
        "bytes": path.stat().st_size,
        "sha256": sha256_path(path),
        "source_ids": source_ids,
    }
    if record_count is not None:
        record["record_count"] = record_count
    if attributes:
        record["attributes"] = attributes
    return record


def finalize_stage(
    root: Path,
    *,
    stage_id: str,
    title: str,
    pipeline_order: int,
    depends_on: list[str],
    claims: list[str],
    sources: list[dict],
    artifact_specs: list[dict],
    notes: list[str],
) -> None:
    stage_dir = root / "reproduction" / stage_id
    artifacts = [artifact_record(stage_dir, **spec) for spec in artifact_specs]
    checksum_lines = [
        f"{artifact['sha256']}  {artifact['path']}\n"
        for artifact in sorted(artifacts, key=lambda value: value["path"])
    ]
    with atomic_text_writer(stage_dir / "SHA256SUMS") as handle:
        handle.writelines(checksum_lines)
    manifest = {
        "$schema": "../../schemas/stage-manifest.schema.json",
        "schema_version": SCHEMA_VERSION,
        "stage_id": stage_id,
        "title": title,
        "pipeline_order": pipeline_order,
        "status": "verified",
        "captured_at": CAPTURED_AT,
        "depends_on": depends_on,
        "claims": claims,
        "sources": sources,
        "artifacts": artifacts,
        "verification": {
            "checksum_file": "SHA256SUMS",
            "command": f"python3 tools/verify_repository.py --stage {stage_id}",
            "notes": [
                "Run python3 tools/rebuild_pr1.py first to regenerate normalized outputs from committed raw snapshots.",
                "All archive and data processing is bounded or forward-only; historical Python is never executed.",
            ],
        },
        "notes": notes,
    }
    write_json(stage_dir / "stage.json", manifest)


def finalize_pr1(root: Path, summaries: dict[str, dict]) -> None:
    local10 = "stage10-local-snapshot"
    local20 = "stage20-local-snapshot"
    local30 = "stage30-local-snapshot"
    local40 = "stage40-local-snapshot"
    upstream10 = "stage10-bank"
    upstream20 = "stage20-bank"
    upstream30 = "stage30-bank"
    equation10 = "stage10-equation-index"

    common10 = [local10]
    common20 = [upstream10, local20]
    common30 = [upstream20, local30]
    common40 = [upstream30, local40]

    finalize_stage(
        root,
        stage_id=STAGE10,
        title="Primary nonzero contributors: 9,452 selected, 9,450 recoverable tables",
        pipeline_order=10,
        depends_on=[],
        claims=[
            "input.equations",
            "mining.model_identities",
            "primary.nonzero_contributors",
            "primary.recoverable",
        ],
        sources=[
            source_record(
                local10,
                "local-filesystem-snapshot",
                "math-distill-equational-stage2: selected primary scripts, coverage/index files, and order5_equations.csv",
            )
        ],
        artifact_specs=[
            dict(relative="raw/primary-recovery-snapshot.tar.gz", role="raw-snapshot", media_type="application/gzip", source_ids=common10, record_count=9457, attributes={"archive_format": "deterministic-tar-gzip-v1", "uncompressed_source_bytes": 91297610}),
            dict(relative="summary.json", role="stage-summary", media_type="application/json", source_ids=common10),
            dict(relative="normalized/tables.jsonl.gz", role="table-index", media_type="application/x-ndjson+gzip", source_ids=common10, record_count=9450),
            dict(relative="normalized/tables.bin", role="table-binary", media_type="application/octet-stream", source_ids=common10, record_count=9450, attributes={"encoding": TABLE_ENCODING, **summaries[STAGE10]["bank"]}),
            dict(relative="normalized/table-id-map.csv.gz", role="identity-map", media_type="text/csv+gzip", source_ids=common10, record_count=9450),
            dict(relative="normalized/primary-models.jsonl.gz", role="primary-model-index", media_type="application/x-ndjson+gzip", source_ids=common10, record_count=9450),
            dict(relative="normalized/skipped-models.jsonl", role="skipped-model-index", media_type="application/x-ndjson", source_ids=common10, record_count=2),
            dict(relative="delta.jsonl.gz", role="membership-delta", media_type="application/x-ndjson+gzip", source_ids=common10, record_count=9450),
        ],
        notes=[
            "The two unrecoverable contributors retain historical ranks 3496 and 8142; recovered records are not renumbered.",
            "The missing historical models.jsonl.gz prevents replay of the original mining/first-witness selection, but every frozen recovered script is independently parsed and validated.",
        ],
    )

    finalize_stage(
        root,
        stage_id=STAGE20,
        title="Registered exact tables: 9,450 + 402 = 9,852",
        pipeline_order=20,
        depends_on=[STAGE10],
        claims=["registry.input", "bank.9852"],
        sources=[
            source_record(upstream10, "generated", f"reproduction/{STAGE10}/normalized/tables.bin", upstream=True),
            source_record(local20, "local-filesystem-snapshot", "math-distill-equational-stage2: false registry and d3 audit/build snapshot"),
        ],
        artifact_specs=[
            dict(relative="raw/registry-and-d3-snapshot.tar.gz", role="raw-snapshot", media_type="application/gzip", source_ids=[local20], record_count=962, attributes={"archive_format": "deterministic-tar-gzip-v1", "uncompressed_source_bytes": 4661322}),
            dict(relative="summary.json", role="stage-summary", media_type="application/json", source_ids=common20),
            dict(relative="normalized/tables.jsonl.gz", role="table-index", media_type="application/x-ndjson+gzip", source_ids=common20, record_count=9852),
            dict(relative="normalized/tables.bin", role="table-binary", media_type="application/octet-stream", source_ids=common20, record_count=9852, attributes={"encoding": TABLE_ENCODING, **summaries[STAGE20]["bank"]}),
            dict(relative="normalized/table-id-map.csv.gz", role="identity-map", media_type="text/csv+gzip", source_ids=common20, record_count=9852),
            dict(relative="normalized/input-decisions.jsonl.gz", role="input-classification", media_type="application/x-ndjson+gzip", source_ids=[local20], record_count=476),
            dict(relative="delta.jsonl.gz", role="membership-delta", media_type="application/x-ndjson+gzip", source_ids=common20, record_count=475),
        ],
        notes=[
            "One of 476 manifests has a null model_table and is represented only in input-decisions, because a delta record requires a real table_id.",
            "Historical compact-JSON SHA-256 identifiers are aliases; canonical table_id values hash order-byte plus row-major entries.",
        ],
    )

    finalize_stage(
        root,
        stage_id=STAGE30,
        title="Early d1/d2 additions: 9,852 + 11 + 94 = 9,957",
        pipeline_order=30,
        depends_on=[STAGE20],
        claims=[
            "d1.input",
            "d1.overlap",
            "d1.delta",
            "d2.input",
            "d2.overlap",
            "d2.delta",
            "bank.9957",
        ],
        sources=[
            source_record(upstream20, "generated", f"reproduction/{STAGE20}/normalized/tables.bin", upstream=True),
            source_record(local30, "local-filesystem-snapshot", "math-distill-equational-stage2: false solver drafts d1, d2, d4, d6, and d8"),
        ],
        artifact_specs=[
            dict(relative="raw/d1-d2-d4-d6-d8-snapshot.tar.gz", role="raw-snapshot", media_type="application/gzip", source_ids=[local30], record_count=21, attributes={"archive_format": "deterministic-tar-gzip-v1", "uncompressed_source_bytes": 6492430}),
            dict(relative="summary.json", role="stage-summary", media_type="application/json", source_ids=common30),
            dict(relative="normalized/tables.jsonl.gz", role="table-index", media_type="application/x-ndjson+gzip", source_ids=common30, record_count=9957),
            dict(relative="normalized/tables.bin", role="table-binary", media_type="application/octet-stream", source_ids=common30, record_count=9957, attributes={"encoding": TABLE_ENCODING, **summaries[STAGE30]["bank"]}),
            dict(relative="normalized/table-id-map.csv.gz", role="identity-map", media_type="text/csv+gzip", source_ids=common30, record_count=9957),
            dict(relative="normalized/input-tables.jsonl.gz", role="input-classification", media_type="application/x-ndjson+gzip", source_ids=[local30], record_count=211),
            dict(relative="delta.jsonl.gz", role="membership-delta", media_type="application/x-ndjson+gzip", source_ids=common30, record_count=211),
        ],
        notes=[
            "delta.jsonl.gz preserves the narrative ingestion order d1 then d2.",
            "The final bank preserves the historical d6/d8 payload order sorted by (order, compact-JSON SHA-256); these are intentionally different orders.",
        ],
    )

    finalize_stage(
        root,
        stage_id=STAGE40,
        title="Two JiaMing deliveries: 9,957 + 50 + 52 = 10,059",
        pipeline_order=40,
        depends_on=[STAGE30],
        claims=[
            "delivery.input",
            "delivery.overlap",
            "delivery.equation_references",
            "delivery.distinct_equations",
            "bank.10059",
        ],
        sources=[
            source_record(upstream30, "generated", f"reproduction/{STAGE30}/normalized/tables.bin", upstream=True),
            source_record(
                equation10,
                "repository-snapshot",
                f"reproduction/{STAGE10}/raw/primary-recovery-snapshot.tar.gz#members/wubing/data/324M_remaining_pairs/order5_equations.csv",
                upstream=True,
            ),
            source_record(local40, "local-filesystem-snapshot", "math-distill-equational-stage2: two JiaMing delivery reports and d11 integration evidence"),
        ],
        artifact_specs=[
            dict(relative="raw/jiaming-d11-snapshot.tar.gz", role="raw-snapshot", media_type="application/gzip", source_ids=[local40], record_count=7, attributes={"archive_format": "deterministic-tar-gzip-v1", "uncompressed_source_bytes": 505277}),
            dict(relative="summary.json", role="stage-summary", media_type="application/json", source_ids=[*common40, equation10]),
            dict(relative="normalized/tables.jsonl.gz", role="table-index", media_type="application/x-ndjson+gzip", source_ids=common40, record_count=10059),
            dict(relative="normalized/tables.bin", role="table-binary", media_type="application/octet-stream", source_ids=common40, record_count=10059, attributes={"encoding": TABLE_ENCODING, **summaries[STAGE40]["bank"]}),
            dict(relative="normalized/table-id-map.csv.gz", role="identity-map", media_type="text/csv+gzip", source_ids=common40, record_count=10059),
            dict(relative="normalized/delivery-batch-50.bin", role="delivery-binary", media_type="application/octet-stream", source_ids=[local40], record_count=50),
            dict(relative="normalized/delivery-batch-52.bin", role="delivery-binary", media_type="application/octet-stream", source_ids=[local40], record_count=52),
            dict(relative="normalized/delivery-102.bin", role="delivery-binary", media_type="application/octet-stream", source_ids=[local40], record_count=102),
            dict(relative="verification/task-evidence.jsonl.gz", role="task-verification", media_type="application/x-ndjson+gzip", source_ids=[local40, equation10], record_count=102),
            dict(relative="delta.jsonl.gz", role="membership-delta", media_type="application/x-ndjson+gzip", source_ids=common40, record_count=102),
        ],
        notes=[
            "Each of the 102 report tables is rechecked by exhaustive source and target assignment enumeration, including the reported failure count and lexicographically first witness.",
            "The later 107-table report is outside this historical stage and is intentionally excluded.",
            "Missing SAT journals prevent replay of discovery; explicit countermodels remain independently verifiable.",
        ],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: inferred from this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    primary, stage10 = build_stage10(root)
    print(f"{STAGE10}: {stage10['bank']['table_count']} tables")
    bank9852, stage20 = build_stage20(root, primary)
    print(f"{STAGE20}: {stage20['bank']['table_count']} tables")
    bank9957, stage30 = build_stage30(root, bank9852)
    print(f"{STAGE30}: {stage30['bank']['table_count']} tables")
    _bank10059, stage40 = build_stage40(root, bank9957)
    print(f"{STAGE40}: {stage40['bank']['table_count']} tables")
    finalize_pr1(
        root,
        {STAGE10: stage10, STAGE20: stage20, STAGE30: stage30, STAGE40: stage40},
    )
    print("PR 1 manifests and checksums regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
