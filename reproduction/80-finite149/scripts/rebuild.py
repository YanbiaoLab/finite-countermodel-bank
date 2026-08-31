#!/usr/bin/env python3
"""Rebuild Stage 80 from its raw snapshot and committed predecessor stages."""

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
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator


STAGE_ID = "80-finite149"
STAGE70 = "70-positive-marginal-core-1470"
STAGE00 = "00-submission-anchor"
SCHEMA_VERSION = "1.0.0"
TABLE_ENCODING = "uint8-order-row-major-v1"
SUBMISSION_RELATIVE = (
    "reproduction/00-submission-anchor/raw/"
    "2026-08-31_marathon_openai-gpt-oss-120b_solver.py"
)
EXPECTED_COUNTS = {
    "not_generated": 789,
    "finite": 149,
    "infinite_required": 600,
    "finite_unknown": 2,
    "general_true": 38,
    "base_tables": 17,
    "required_transposes": 11,
    "oriented_assets": 28,
    "direct_uses": 129,
    "transpose_uses": 20,
    "prior_core": 1470,
    "refutation934_tasks": 5,
    "submitted_records": 1487,
}
CLAIMS = [
    "finite149.no_submission_directions",
    "finite149.directions",
    "finite149.base_tables",
    "finite149.required_transposes",
    "finite149.oriented_assets",
    "finite149.original_uses",
    "finite149.transpose_uses",
    "finite149.core_overlap",
    "finite149.official_payload_tables",
    "finite149.substitute_tables",
    "refutation934.official_order",
    "refutation934.substitute_order",
    "refutation934.covered_tasks",
]


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


def compact_json_bytes(data: object) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def pretty_json_bytes(data: object) -> bytes:
    return (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def compact_table_sha256(table: list[list[int]]) -> str:
    # Historical table IDs preserve row order and do not sort object keys.
    raw = json.dumps(table, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256_bytes(raw)


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


def canonical_table_id(record: bytes) -> str:
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


def csv_bytes(fieldnames: list[str], rows: Iterable[dict[str, object]]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return text.getvalue().encode("utf-8")


def read_snapshot(path: Path) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    with tarfile.open(path, mode="r:gz") as archive:
        for member in archive:
            ensure(
                member.isfile()
                and member.name
                and not member.name.startswith("/")
                and ".." not in PurePosixPath(member.name).parts,
                f"unsafe raw snapshot member: {member.name}",
            )
            extracted = archive.extractfile(member)
            ensure(extracted is not None, f"cannot read raw member: {member.name}")
            body = extracted.read()
            ensure(len(body) == member.size, f"truncated raw member: {member.name}")
            ensure(member.name not in members, f"duplicate raw member: {member.name}")
            members[member.name] = body
    metadata = json.loads(members["snapshot-metadata.json"])
    declared = metadata["source_files"]
    ensure(len(declared) + 1 == len(members), "raw snapshot member-count drift")
    for row in declared:
        body = members[row["archive_path"]]
        ensure(len(body) == row["bytes"], f"raw member byte-count drift: {row}")
        ensure(
            sha256_bytes(body) == row["sha256"],
            f"raw member SHA-256 drift: {row['archive_path']}",
        )
    return members


def load_jsonl(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line]


def load_csv(body: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))


def parse_top_level_literals(source: bytes, names: tuple[str, ...]) -> dict[str, object]:
    tree = ast.parse(source.decode("utf-8"))
    found: dict[str, object] = {}
    wanted = set(names)
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        for target in targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                ensure(target.id not in found, f"duplicate literal: {target.id}")
                found[target.id] = ast.literal_eval(value)
    ensure(set(found) == wanted, f"missing literals: {sorted(wanted - set(found))}")
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
    ensure(isinstance(encoded, bytes), "table payload is not bytes")
    compressed = base64.b85decode(encoded)
    ensure(base64.b85encode(compressed) == encoded, "noncanonical table Base85")
    raw = lzma.decompress(compressed)
    ensure(len(raw) == raw_bytes, "table raw-byte declaration drift")
    records = parse_table_records(raw)
    ensure(len(records) == model_count, "table record-count drift")
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
        return (
            parse_term(text[:cut], variables),
            parse_term(text[cut + 1 :], variables),
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
    return table[eval_term(term[0], values, table)][
        eval_term(term[1], values, table)
    ]


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


def table_json_record(
    table: list[list[int]],
    *,
    compact_id: str,
    record_kind: str,
    source_record: str,
    notes: list[str],
) -> dict[str, object]:
    record = table_record(table)
    return {
        "encoding": TABLE_ENCODING,
        "entries": list(record[1:]),
        "first_seen_stage": STAGE_ID,
        "identifiers": [
            {
                "scheme": "sha256-compact-json-table-v1",
                "value": "sha256:" + compact_id,
            }
        ],
        "notes": notes,
        "order": record[0],
        "provenance": [
            {
                "source_id": "stage80-historical-snapshot",
                "source_path": "raw/finite149-source-snapshot.tar.gz#"
                "source/finite149/static_library_base_models.jsonl",
                "source_record": source_record,
            }
        ],
        "record_kind": record_kind,
        "schema_version": SCHEMA_VERSION,
        "table_id": canonical_table_id(record),
        "verification": {
            "entry_range_checked": True,
            "shape_checked": True,
            "task_check_paths": [
                "normalized/coverage.jsonl.gz",
                "verification/coverage-exhaustive.jsonl.gz",
            ],
        },
    }


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
    path = source_path or (stage_dir / Path(PurePosixPath(relative)))
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
    raw_snapshot: Path,
    script_source_stage: Path,
) -> list[str]:
    members = read_snapshot(raw_snapshot)
    snapshot_metadata = json.loads(members["snapshot-metadata.json"])
    captured_at = snapshot_metadata["captured_at"]
    labels = load_csv(members["source/789/not_generated_labels.csv"])
    type_audit = json.loads(
        members["source/789/not_generated_type_audit.json"].decode("utf-8")
    )
    finite_outcomes_payload = json.loads(
        gzip.decompress(members["source/upstream/finite_outcomes.json.gz"])
    )
    finite_outcomes = finite_outcomes_payload["outcomes"]
    path_manifest = load_csv(members["source/finite149/manifest.csv"])
    bundle_manifest = json.loads(
        members["source/finite149/bundle_manifest.json"].decode("utf-8")
    )
    bases = load_jsonl(
        members["source/finite149/static_library_base_models.jsonl"]
    )
    raw_oriented = load_jsonl(
        members["source/finite149/static_library_oriented_models.jsonl"]
    )
    raw_coverage = load_csv(
        members["source/finite149/static_library_coverage.csv"]
    )
    raw_library_summary = json.loads(
        members["source/finite149/static_library_summary.json"].decode("utf-8")
    )
    reductions = json.loads(
        members[
            "source/refutation934/order24_coverage_reductions.json"
        ].decode("utf-8")
    )

    ensure(len(labels) == EXPECTED_COUNTS["not_generated"], "789-input count drift")
    ensure(len(path_manifest) == EXPECTED_COUNTS["finite"], "path count drift")
    ensure(len(bases) == EXPECTED_COUNTS["base_tables"], "base count drift")
    ensure(len(raw_oriented) == EXPECTED_COUNTS["oriented_assets"], "oriented count drift")
    ensure(len(raw_coverage) == EXPECTED_COUNTS["finite"], "coverage count drift")
    ensure(bundle_manifest["scope"]["experiment_not_generated"] == 789, "bundle 789 drift")
    ensure(bundle_manifest["scope"]["finite_counterexample_count"] == 149, "bundle 149 drift")

    selected_ids = {row["problem_id"] for row in path_manifest}
    ensure(len(selected_ids) == 149, "duplicate selected problem IDs")
    unknown_ids = {
        row["problem_id"] for row in type_audit["finite_status_unknown_pairs"]
    }
    ensure(len(unknown_ids) == 2, "finite-unknown count drift")
    screening: list[dict[str, object]] = []
    category_counts: Counter[str] = Counter()
    for sequence, row in enumerate(labels):
        problem_id = row["problem_id"]
        finite_outcome = finite_outcomes[int(row["lhs_id"]) - 1][
            int(row["rhs_id"]) - 1
        ]
        if row["official_label"] == "false" and finite_outcome.endswith(
            "proof_false"
        ):
            action = "retain"
            category = "finite_countermodel_proved"
            reason = "official_finite_outcome_endswith_proof_false"
        elif row["official_label"] == "true":
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
        screening.append(
            {
                "action": action,
                "category": category,
                "finite_outcome": finite_outcome,
                "general_outcome": row["official_outcome"],
                "lhs_equation": row["lhs_equation"],
                "lhs_id": int(row["lhs_id"]),
                "pair_index": int(row["pair_index"]),
                "problem_id": problem_id,
                "reason_code": reason,
                "rhs_equation": row["rhs_equation"],
                "rhs_id": int(row["rhs_id"]),
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
    ensure(
        {row["problem_id"] for row in screening if row["action"] == "retain"}
        == selected_ids,
        "recomputed finite-outcomes selection disagrees with the 149-path manifest",
    )
    ensure(
        {
            row["problem_id"]
            for row in screening
            if row["category"] == "finite_status_unknown"
        }
        == unknown_ids,
        "recomputed finite-unknown set disagrees with the historical audit",
    )
    ensure(
        type_audit["false_semantic_type_counts"]
        == {
            "finite_countermodel_proved": 149,
            "finite_status_unknown": 2,
            "infinite_countermodel_required": 600,
        },
        "raw type-audit partition drift",
    )

    base_by_id = {str(row["base_model_id"]): row for row in bases}
    ensure(len(base_by_id) == 17, "duplicate base-model IDs")
    original_refutation934 = next(
        row for row in bases if int(row["carrier_order"]) == 24
    )
    ensure(
        original_refutation934["official_source"].endswith("Refutation934.lean"),
        "order-24 source is not Refutation934",
    )
    direct_reduction = next(
        row["best"]
        for row in reductions["directions"]
        if row["orientation"] == "direct" and int(row["best"]["order"]) == 22
    )
    substitute = direct_reduction["table_rows"]
    ensure(len(substitute) == 22, "substitute order drift")
    subset = [int(value) for value in direct_reduction["subset"]]
    official24 = original_refutation934["table_rows"]
    ensure(len(official24) == 24 and len(subset) == 22, "substructure size drift")
    position = {value: index for index, value in enumerate(subset)}
    ensure(len(position) == 22, "substructure subset is not unique")
    induced = []
    for left in subset:
        induced_row = []
        for right in subset:
            value = official24[left][right]
            ensure(value in position, "Refutation934 subset is not closed")
            induced_row.append(position[value])
        induced.append(induced_row)
    ensure(induced == substitute, "order-22 table is not the induced substructure")
    ensure(
        compact_table_sha256(substitute) == direct_reduction["table_sha256"],
        "substitute compact-table hash drift",
    )

    effective_bases: list[dict[str, object]] = []
    effective_table_by_base: dict[str, list[list[int]]] = {}
    base_record_by_id: dict[str, bytes] = {}
    stable_by_base: dict[str, str] = {}
    for sequence, base in enumerate(bases):
        base_id = str(base["base_model_id"])
        official_table = base["table_rows"]
        ensure(
            compact_table_sha256(official_table) == base["base_table_sha256"],
            f"official compact table hash drift: {base_id}",
        )
        ensure(
            compact_table_sha256(transpose(official_table))
            == base["dual_table_sha256"],
            f"official transpose hash drift: {base_id}",
        )
        source_member = f"source/official_sources/{base['official_source']}"
        source_body = members[source_member]
        ensure(
            sha256_bytes(source_body) == base["official_source_sha256"],
            f"official source hash drift: {base_id}",
        )
        is_substitute = base_id == original_refutation934["base_model_id"]
        table = substitute if is_substitute else official_table
        stable_id = f"F149-{sequence + 1:03d}"
        compact_id = compact_table_sha256(table)
        record = table_record(table)
        base_record_by_id[base_id] = record
        effective_table_by_base[base_id] = table
        stable_by_base[base_id] = stable_id
        notes = [
            f"stable_id={stable_id}",
            "expected_payload_orientation=direct",
            f"append_sequence={sequence}",
        ]
        if is_substitute:
            notes.extend(
                [
                    "Refutation934 order-22 verified closed-substructure substitute",
                    f"official_order24_compact_sha256={base['base_table_sha256']}",
                ]
            )
        json_record = table_json_record(
            table,
            compact_id=compact_id,
            record_kind="verified-substitute" if is_substitute else "exact-explicit",
            source_record=base_id,
            notes=notes,
        )
        effective_bases.append(
            {
                "append_sequence": sequence,
                "base_model_id": base_id,
                "canonical_record": record,
                "compact_id": compact_id,
                "effective_order": len(table),
                "is_refutation934_substitute": is_substitute,
                "json_record": json_record,
                "official_order": int(base["carrier_order"]),
                "official_source": base["official_source"],
                "stable_id": stable_id,
                "table_id": canonical_table_id(record),
            }
        )
    ensure(len({row["table_id"] for row in effective_bases}) == 17, "duplicate effective bases")

    raw_oriented_by_id = {
        str(row["oriented_model_id"]): row for row in raw_oriented
    }
    coverage_by_problem = {row["problem_id"]: row for row in raw_coverage}
    path_by_problem = {row["problem_id"]: row for row in path_manifest}
    ensure(
        set(coverage_by_problem) == selected_ids == set(path_by_problem),
        "path/coverage/screening selected sets disagree",
    )
    normalized_paths: list[dict[str, object]] = []
    normalized_coverage: list[dict[str, object]] = []
    exhaustive_rows: list[dict[str, object]] = []
    transpose_base_ids: set[str] = set()
    usage_counts: Counter[str] = Counter()
    for sequence, raw_row in enumerate(raw_coverage):
        problem_id = raw_row["problem_id"]
        path_row = path_by_problem[problem_id]
        base_id = raw_row["base_model_id"]
        raw_orientation = raw_row["orientation"]
        usage_orientation = "direct" if raw_orientation == "direct" else "transpose"
        ensure(raw_orientation in {"direct", "dual"}, "unknown raw orientation")
        ensure(
            (path_row["uses_dual"].lower() == "true")
            == (usage_orientation == "transpose"),
            f"ETP path orientation drift: {problem_id}",
        )
        if usage_orientation == "transpose":
            transpose_base_ids.add(base_id)
        usage_counts[usage_orientation] += 1
        base_table = effective_table_by_base[base_id]
        effective_table = (
            base_table if usage_orientation == "direct" else transpose(base_table)
        )
        effective_record = table_record(effective_table)
        effective_id = canonical_table_id(effective_record)
        raw_oriented_row = raw_oriented_by_id[raw_row["oriented_model_id"]]
        if int(raw_oriented_row["carrier_order"]) != 24:
            ensure(
                raw_oriented_row["table_rows"] == effective_table,
                f"raw oriented table drift: {problem_id}",
            )
        path_steps = [step.strip() for step in path_row["proof_path"].split("->")]
        ensure(path_steps[0] == str(path_row["lhs_id"]), "ETP path start drift")
        ensure(
            path_steps[-1] == f"{int(path_row['rhs_id'])}_neg",
            "ETP path end drift",
        )
        ensure(path_row["official_proven"].lower() == "true", "unproven ETP path")
        normalized_paths.append(
            {
                "official_proven": True,
                "official_source": path_row["official_source"],
                "official_source_line": int(path_row["official_line"]),
                "path_sources": [
                    value
                    for value in path_row["proof_path_sources"].split(";")
                    if value
                ],
                "path_steps": path_steps,
                "problem_id": problem_id,
                "sequence": sequence,
                "source_equation": f"Equation{int(path_row['lhs_id'])}",
                "target_equation": f"Equation{int(path_row['rhs_id'])}",
                "uses_transpose": usage_orientation == "transpose",
                "witness_mode": path_row["witness_mode"],
            }
        )
        normalized_coverage.append(
            {
                "base_model_id": base_id,
                "base_stable_id": stable_by_base[base_id],
                "effective_order": len(effective_table),
                "effective_table_id": effective_id,
                "lhs_equation": raw_row["equation1"],
                "lhs_id": int(raw_row["lhs_id"]),
                "official_base_order": int(base_by_id[base_id]["carrier_order"]),
                "problem_id": problem_id,
                "proof_path": path_row["proof_path"],
                "rhs_equation": raw_row["equation2"],
                "rhs_id": int(raw_row["rhs_id"]),
                "sequence": sequence,
                "usage_orientation": usage_orientation,
            }
        )
        exhaustive_rows.append(
            exhaustive_task(
                problem_id,
                raw_row["equation1"],
                raw_row["equation2"],
                effective_table,
                usage_orientation,
                effective_id,
            )
        )
    ensure(usage_counts == Counter({"direct": 129, "transpose": 20}), "129/20 drift")
    ensure(len(transpose_base_ids) == 11, "required-transpose count drift")

    transpose_rows: list[dict[str, object]] = []
    transpose_records: list[bytes] = []
    for base_id in [str(row["base_model_id"]) for row in bases]:
        if base_id not in transpose_base_ids:
            continue
        table = transpose(effective_table_by_base[base_id])
        record = table_record(table)
        compact_id = compact_table_sha256(table)
        source_id = canonical_table_id(base_record_by_id[base_id])
        row = table_json_record(
            table,
            compact_id=compact_id,
            record_kind="derived-transpose",
            source_record=base_id,
            notes=[
                f"derived_from={source_id}",
                f"base_stable_id={stable_by_base[base_id]}",
                "task-required transpose; not part of the embedded 17-record suffix",
            ],
        )
        transpose_rows.append(row)
        transpose_records.append(record)
    ensure(len(transpose_rows) == 11, "transpose output count drift")
    ensure(len(set(transpose_records)) == 11, "duplicate required transposes")
    ensure(
        not ({row["table_id"] for row in effective_bases} & {row["table_id"] for row in transpose_rows}),
        "required transpose duplicates an effective base",
    )

    refutation934_problem_ids = {
        row["problem_id"]
        for row in raw_coverage
        if row["base_model_id"] == original_refutation934["base_model_id"]
    }
    ensure(len(refutation934_problem_ids) == 5, "Refutation934 task-count drift")
    refutation934_checks = [
        row for row in exhaustive_rows if row["problem_id"] in refutation934_problem_ids
    ]
    ensure(len(refutation934_checks) == 5, "Refutation934 exhaustive rows missing")

    stage70_path = repository_root / f"reproduction/{STAGE70}/normalized/tables.bin"
    stage70_records = parse_table_records(stage70_path.read_bytes())
    ensure(len(stage70_records) == 1470, "Stage70 core count drift")
    stage70_ids = {canonical_table_id(record) for record in stage70_records}
    base_ids = {str(row["table_id"]) for row in effective_bases}
    transpose_ids = {str(row["table_id"]) for row in transpose_rows}
    base_overlap = sorted(base_ids & stage70_ids)
    oriented_overlap = sorted((base_ids | transpose_ids) & stage70_ids)
    ensure(not base_overlap, "finite149 base overlaps Stage70 core")
    ensure(not oriented_overlap, "finite149 oriented asset overlaps Stage70 core")
    ensure(
        raw_library_summary["current_solo_v4"]["new_base_tables_already_present"] == 0
        and raw_library_summary["current_solo_v4"][
            "new_used_oriented_tables_already_present"
        ]
        == 0,
        "historical zero-overlap audit drift",
    )

    submission_path = repository_root / SUBMISSION_RELATIVE
    submission_source = submission_path.read_bytes()
    submitted_count, submitted_raw, submitted_records = extract_submitted_table_payload(
        submission_source
    )
    ensure(submitted_count == 1487, "submitted record count drift")
    ensure(submitted_records[:1470] == stage70_records, "submitted 1470 prefix drift")
    effective_records = [row["canonical_record"] for row in effective_bases]
    ensure(submitted_records[1470:] == effective_records, "submitted 17-record suffix drift")

    output_stage.mkdir(parents=True, exist_ok=True)
    write_bytes(
        output_stage,
        "normalized/screening-decisions.jsonl.gz",
        gzip_bytes(jsonl_bytes(screening)),
    )
    write_bytes(
        output_stage,
        "normalized/etp-paths.jsonl.gz",
        gzip_bytes(jsonl_bytes(normalized_paths)),
    )
    write_bytes(
        output_stage,
        "normalized/base-tables.jsonl.gz",
        gzip_bytes(jsonl_bytes(row["json_record"] for row in effective_bases)),
    )
    base_binary = b"".join(effective_records)
    write_bytes(output_stage, "normalized/base-tables.bin", base_binary)
    write_bytes(
        output_stage,
        "normalized/required-transposes.jsonl.gz",
        gzip_bytes(jsonl_bytes(transpose_rows)),
    )
    transpose_binary = b"".join(transpose_records)
    write_bytes(output_stage, "normalized/required-transposes.bin", transpose_binary)
    write_bytes(
        output_stage,
        "normalized/coverage.jsonl.gz",
        gzip_bytes(jsonl_bytes(normalized_coverage)),
    )
    table_map_fields = [
        "stable_id",
        "append_sequence",
        "submitted_record_index",
        "base_model_id",
        "record_kind",
        "payload_orientation",
        "official_order",
        "effective_order",
        "canonical_table_id",
        "compact_json_table_id",
        "official_source",
        "is_refutation934_substitute",
    ]
    table_map_rows = [
        {
            "append_sequence": row["append_sequence"],
            "base_model_id": row["base_model_id"],
            "canonical_table_id": row["table_id"],
            "compact_json_table_id": "sha256:" + str(row["compact_id"]),
            "effective_order": row["effective_order"],
            "is_refutation934_substitute": str(
                row["is_refutation934_substitute"]
            ).lower(),
            "official_order": row["official_order"],
            "official_source": row["official_source"],
            "payload_orientation": "direct",
            "record_kind": row["json_record"]["record_kind"],
            "stable_id": row["stable_id"],
            "submitted_record_index": 1470 + int(row["append_sequence"]),
        }
        for row in effective_bases
    ]
    write_bytes(
        output_stage,
        "normalized/table-id-map.csv",
        csv_bytes(table_map_fields, table_map_rows),
    )
    append_fields = [
        "append_sequence",
        "submitted_record_index",
        "stable_id",
        "canonical_table_id",
        "effective_order",
        "expected_payload_orientation",
        "source_of_order",
    ]
    append_rows = [
        {
            "append_sequence": row["append_sequence"],
            "canonical_table_id": row["table_id"],
            "effective_order": row["effective_order"],
            "expected_payload_orientation": "direct",
            "source_of_order": SUBMISSION_RELATIVE,
            "stable_id": row["stable_id"],
            "submitted_record_index": 1470 + int(row["append_sequence"]),
        }
        for row in effective_bases
    ]
    write_bytes(
        output_stage,
        "normalized/append-order.csv",
        csv_bytes(append_fields, append_rows),
    )
    write_bytes(
        output_stage,
        "verification/coverage-exhaustive.jsonl.gz",
        gzip_bytes(jsonl_bytes(exhaustive_rows)),
    )

    substitute_row = next(row for row in effective_bases if row["is_refutation934_substitute"])
    substitution_audit = {
        "closed_substructure": True,
        "covered_problem_ids": sorted(refutation934_problem_ids),
        "covered_task_count": 5,
        "direct_task_count": sum(
            row["usage_orientation"] == "direct" for row in refutation934_checks
        ),
        "official_base_model_id": original_refutation934["base_model_id"],
        "official_canonical_table_id": canonical_table_id(table_record(official24)),
        "official_compact_json_sha256": original_refutation934["base_table_sha256"],
        "official_order": 24,
        "official_source": original_refutation934["official_source"],
        "schema_version": SCHEMA_VERSION,
        "stable_id": substitute_row["stable_id"],
        "substitute_canonical_table_id": substitute_row["table_id"],
        "substitute_compact_json_sha256": substitute_row["compact_id"],
        "substitute_order": 22,
        "substructure_subset_in_official_carrier": subset,
        "transpose_task_count": sum(
            row["usage_orientation"] == "transpose" for row in refutation934_checks
        ),
    }
    write_bytes(
        output_stage,
        "verification/refutation934-substitution.json",
        pretty_json_bytes(substitution_audit),
    )
    five_task_audit = {
        "all_five_exhaustive_checks_passed": True,
        "schema_version": SCHEMA_VERSION,
        "substitute_canonical_table_id": substitute_row["table_id"],
        "tasks": refutation934_checks,
    }
    write_bytes(
        output_stage,
        "verification/refutation934-five-task-exhaustive.json",
        pretty_json_bytes(five_task_audit),
    )
    overlap_audit = {
        "base_overlap_count": len(base_overlap),
        "base_overlaps": base_overlap,
        "base_table_count": 17,
        "comparison": "exact canonical bytes: order byte + n^2 row-major bytes",
        "oriented_asset_count": 28,
        "oriented_overlap_count": len(oriented_overlap),
        "oriented_overlaps": oriented_overlap,
        "prior_core_canonical_id_vector_sha256": sha256_bytes(
            b"".join(
                (canonical_table_id(record) + "\n").encode("ascii")
                for record in stage70_records
            )
        ),
        "prior_core_count": 1470,
        "prior_core_path": f"reproduction/{STAGE70}/normalized/tables.bin",
        "schema_version": SCHEMA_VERSION,
    }
    write_bytes(
        output_stage,
        "verification/zero-overlap-with-core1470.json",
        pretty_json_bytes(overlap_audit),
    )
    suffix_audit = {
        "append_order_recovered": True,
        "compared_in_memory_without_publishing_full_payload": True,
        "core_prefix_exact_record_order_match": True,
        "core_prefix_records": 1470,
        "excluded_from_stage": [
            "the cumulative 1,487-record payload binary",
            "the 2,901-record opposite-closure runtime bank",
        ],
        "schema_version": SCHEMA_VERSION,
        "submitted_declared_raw_bytes": len(submitted_raw),
        "submitted_record_count_observed": submitted_count,
        "submitted_solver_path": SUBMISSION_RELATIVE,
        "submitted_solver_sha256": sha256_bytes(submission_source),
        "suffix_canonical_id_vector_sha256": sha256_bytes(
            b"".join((str(row["table_id"]) + "\n").encode("ascii") for row in effective_bases)
        ),
        "suffix_exact_record_order_match": True,
        "suffix_records": 17,
    }
    write_bytes(
        output_stage,
        "verification/submission-suffix-audit.json",
        pretty_json_bytes(suffix_audit),
    )

    delta_rows: list[dict[str, object]] = []
    for row in effective_bases:
        evidence = [
            "normalized/table-id-map.csv",
            "verification/zero-overlap-with-core1470.json",
            "verification/submission-suffix-audit.json",
        ]
        reason = "finite149.official-base"
        notes = f"{row['stable_id']} appended in direct orientation"
        if row["is_refutation934_substitute"]:
            reason = "finite149.refutation934-order22-substitute"
            evidence.append("verification/refutation934-substitution.json")
            notes = f"{row['stable_id']} replaces the official order-24 table"
        delta_rows.append(
            {
                "action": "add",
                "evidence_paths": evidence,
                "notes": notes,
                "reason_code": reason,
                "schema_version": SCHEMA_VERSION,
                "sequence": len(delta_rows),
                "stage_id": STAGE_ID,
                "table_id": row["table_id"],
            }
        )
    transpose_by_id = {row["table_id"]: row for row in transpose_rows}
    for base_id in [str(row["base_model_id"]) for row in bases]:
        if base_id not in transpose_base_ids:
            continue
        record = table_record(transpose(effective_table_by_base[base_id]))
        table_id = canonical_table_id(record)
        ensure(table_id in transpose_by_id, "transpose JSON/binary identity drift")
        delta_rows.append(
            {
                "action": "derive",
                "evidence_paths": [
                    "normalized/required-transposes.jsonl.gz",
                    "normalized/coverage.jsonl.gz",
                ],
                "notes": f"task-required transpose of {stable_by_base[base_id]}",
                "reason_code": "finite149.required-transpose",
                "schema_version": SCHEMA_VERSION,
                "sequence": len(delta_rows),
                "source_stage_id": STAGE_ID,
                "source_table_id": canonical_table_id(base_record_by_id[base_id]),
                "stage_id": STAGE_ID,
                "table_id": table_id,
            }
        )
    ensure(len(delta_rows) == 28, "delta count drift")
    write_bytes(
        output_stage, "delta.jsonl.gz", gzip_bytes(jsonl_bytes(delta_rows))
    )

    metrics = {
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
    summary = {
        "action_counts": {"add": 17, "derive": 11},
        "append_order": {
            "count": 17,
            "exact_submitted_suffix_match": True,
            "expected_payload_orientation": {"direct": 17},
            "source": SUBMISSION_RELATIVE,
        },
        "bank": {
            "base_binary_bytes": len(base_binary),
            "base_binary_sha256": sha256_bytes(base_binary),
            "base_tables": 17,
            "oriented_assets": 28,
            "required_transpose_binary_bytes": len(transpose_binary),
            "required_transpose_binary_sha256": sha256_bytes(transpose_binary),
            "required_transposes": 11,
        },
        "evidence_boundary": {
            "includes_full_1487_payload": False,
            "includes_opposite_closure_2901": False,
            "submission_used_only_for_suffix_order_and_byte_comparison": True,
        },
        "metrics": metrics,
        "orientation_usage": {"direct": 129, "transpose": 20},
        "refutation934": substitution_audit,
        "schema_version": SCHEMA_VERSION,
        "screening": {
            "input": 789,
            "partition": expected_categories,
            "retained": 149,
        },
        "stage_id": STAGE_ID,
        "zero_overlap": {
            "base_vs_core1470": 0,
            "all_28_oriented_assets_vs_core1470": 0,
        },
    }
    write_bytes(output_stage, "summary.json", pretty_json_bytes(summary))

    artifact_specs = [
        artifact(
            output_stage,
            "raw/finite149-source-snapshot.tar.gz",
            "raw-snapshot",
            "application/gzip",
            ["stage80-historical-snapshot", "stage80-etp-proof-graph"],
            source_path=raw_snapshot,
            record_count=len(members),
            attributes={
                "archive_format": "deterministic-tar-gzip-v1",
                "uncompressed_source_bytes": sum(len(value) for value in members.values()),
            },
        ),
        artifact(
            output_stage,
            "scripts/capture.py",
            "capture-script",
            "text/x-python",
            ["stage80-historical-snapshot"],
            source_path=script_source_stage / "scripts/capture.py",
        ),
        artifact(
            output_stage,
            "scripts/rebuild.py",
            "rebuild-script",
            "text/x-python",
            ["stage80-historical-snapshot"],
            source_path=script_source_stage / "scripts/rebuild.py",
        ),
        artifact(
            output_stage,
            "scripts/verify.py",
            "verification-script",
            "text/x-python",
            ["stage80-historical-snapshot"],
            source_path=script_source_stage / "scripts/verify.py",
        ),
        artifact(output_stage, "normalized/screening-decisions.jsonl.gz", "screening-index", "application/x-ndjson+gzip", ["stage80-historical-snapshot", "stage80-etp-proof-graph"], record_count=789),
        artifact(output_stage, "normalized/etp-paths.jsonl.gz", "etp-path-index", "application/x-ndjson+gzip", ["stage80-historical-snapshot", "stage80-etp-proof-graph"], record_count=149),
        artifact(output_stage, "normalized/base-tables.jsonl.gz", "base-table-index", "application/x-ndjson+gzip", ["stage80-historical-snapshot", "stage80-etp-proof-graph"], record_count=17),
        artifact(output_stage, "normalized/base-tables.bin", "base-table-binary", "application/octet-stream", ["stage80-historical-snapshot", "stage80-etp-proof-graph"], record_count=17, attributes={"encoding": TABLE_ENCODING}),
        artifact(output_stage, "normalized/required-transposes.jsonl.gz", "transpose-table-index", "application/x-ndjson+gzip", ["stage80-historical-snapshot"], record_count=11),
        artifact(output_stage, "normalized/required-transposes.bin", "transpose-table-binary", "application/octet-stream", ["stage80-historical-snapshot"], record_count=11, attributes={"encoding": TABLE_ENCODING}),
        artifact(output_stage, "normalized/coverage.jsonl.gz", "finite149-coverage-index", "application/x-ndjson+gzip", ["stage80-historical-snapshot", "stage80-etp-proof-graph"], record_count=149),
        artifact(output_stage, "normalized/table-id-map.csv", "stable-table-map", "text/csv", ["stage80-historical-snapshot", "stage80-submission-suffix"], record_count=17),
        artifact(output_stage, "normalized/append-order.csv", "append-order", "text/csv", ["stage80-submission-suffix"], record_count=17),
        artifact(output_stage, "verification/coverage-exhaustive.jsonl.gz", "exhaustive-coverage", "application/x-ndjson+gzip", ["stage80-historical-snapshot"], record_count=149),
        artifact(output_stage, "verification/refutation934-substitution.json", "substitution-audit", "application/json", ["stage80-historical-snapshot", "stage80-etp-proof-graph"]),
        artifact(output_stage, "verification/refutation934-five-task-exhaustive.json", "exhaustive-task-audit", "application/json", ["stage80-historical-snapshot"], record_count=5),
        artifact(output_stage, "verification/zero-overlap-with-core1470.json", "overlap-audit", "application/json", ["stage80-core-bank"]),
        artifact(output_stage, "verification/submission-suffix-audit.json", "submission-suffix-audit", "application/json", ["stage80-core-bank", "stage80-submission-suffix"]),
        artifact(output_stage, "delta.jsonl.gz", "membership-delta", "application/x-ndjson+gzip", ["stage80-historical-snapshot", "stage80-core-bank"], record_count=28),
        artifact(output_stage, "summary.json", "stage-summary", "application/json", ["stage80-historical-snapshot", "stage80-core-bank", "stage80-submission-suffix", "stage80-etp-proof-graph"]),
    ]
    artifact_specs.sort(key=lambda row: str(row["path"]))
    checksums = b"".join(
        f"{row['sha256']}  {row['path']}\n".encode("ascii") for row in artifact_specs
    )
    write_bytes(output_stage, "SHA256SUMS", checksums)

    upstream = bundle_manifest["upstream"]
    manifest = {
        "$schema": "../../schemas/stage-manifest.schema.json",
        "artifacts": artifact_specs,
        "captured_at": captured_at,
        "claims": CLAIMS,
        "depends_on": [STAGE70],
        "notes": [
            "This stage publishes only the 17-record augmentation and 11 task-required transposes, never the cumulative 1,487-record payload.",
            "The 2,901-record runtime opposite closure is deferred to PR 4.",
            "All 149 task directions and the five Refutation934 directions are exhaustively evaluated over every assignment.",
        ],
        "pipeline_order": 80,
        "schema_version": SCHEMA_VERSION,
        "sources": [
            {
                "captured_at": captured_at,
                "kind": "local-filesystem-snapshot",
                "license_status": "not-specified; no license grant inferred",
                "locator": "math-distill-equational-stage2 finite149 historical artifacts",
                "notes": [
                    "The deterministic archive and per-member hashes identify the captured bytes; the sibling checkout was dirty and its revision is context only."
                ],
                "revision": snapshot_metadata["source_repository_revision"],
                "source_id": "stage80-historical-snapshot",
            },
            {
                "captured_at": captured_at,
                "kind": "generated",
                "license_status": "not-specified; no license grant inferred",
                "locator": f"reproduction/{STAGE70}/normalized/tables.bin",
                "notes": ["Committed predecessor used only for exact zero-overlap checking."],
                "source_id": "stage80-core-bank",
            },
            {
                "captured_at": captured_at,
                "kind": "generated",
                "license_status": "not-specified; no license grant inferred",
                "locator": SUBMISSION_RELATIVE,
                "notes": [
                    "Statically decoded in memory only to recover and verify the final 17-record append order; the cumulative payload is not emitted."
                ],
                "source_id": "stage80-submission-suffix",
            },
            {
                "captured_at": captured_at,
                "kind": "third-party",
                "license_status": "upstream source snapshot; see upstream repository licensing",
                "locator": upstream["repository"],
                "notes": [
                    f"finite_outcomes SHA-256: {upstream['finite_outcomes_compressed_sha256']}",
                    f"finite_graph SHA-256: {upstream['finite_graph_sha256']}",
                ],
                "revision": upstream["commit"],
                "source_id": "stage80-etp-proof-graph",
            },
        ],
        "stage_id": STAGE_ID,
        "status": "verified",
        "title": "finite149 augmentation: 789 -> 149 directions -> 17 + 11 tables",
        "verification": {
            "checksum_file": "SHA256SUMS",
            "command": "python3 reproduction/80-finite149/scripts/verify.py",
            "notes": [
                "The stage-local verifier rebuilds in a temporary directory, compares every generated byte, reruns exhaustive task evaluation, and then runs the repository verifier."
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
        "--raw-snapshot",
        type=Path,
        default=stage / "raw/finite149-source-snapshot.tar.gz",
    )
    parser.add_argument("--script-source-stage", type=Path, default=stage)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = build(
        args.output_stage.resolve(),
        args.repository_root.resolve(),
        args.raw_snapshot.resolve(),
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
