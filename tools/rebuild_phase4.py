#!/usr/bin/env python3
"""Rebuild Phase 4's exact 1,487 payload and 2,901-table runtime closure."""

from __future__ import annotations

import argparse
import base64
import copy
import gzip
import json
import lzma
from pathlib import Path, PurePosixPath
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase2_common import (  # noqa: E402
    extract_embedded_false_solver_table_payload,
)
from tools.phase4_common import (  # noqa: E402
    CORE_COUNT,
    DERIVED_CANONICAL_ID_VECTOR_SHA256,
    DERIVED_RAW_BYTES,
    DERIVED_RAW_SHA256,
    DERIVED_TRANSPOSE_COUNT,
    EMBEDDED_B85_BYTES,
    EMBEDDED_B85_SHA256,
    EMBEDDED_CANONICAL_ID_VECTOR_SHA256,
    EMBEDDED_COUNT,
    EMBEDDED_NONTRIVIAL_TRANSPOSE_PAIR_COUNT,
    EMBEDDED_NONTRIVIAL_TRANSPOSE_SOURCE_COUNT,
    EMBEDDED_RAW_BYTES,
    EMBEDDED_RAW_SHA256,
    EMBEDDED_XZ_BYTES,
    EMBEDDED_XZ_SHA256,
    FALSE_ENGINE_SHA256,
    FINITE149_COUNT,
    HISTORICAL_REINTRODUCTION_COUNT,
    HISTORICAL_STAGE10_COUNT,
    HISTORICAL_STAGE80_COUNT,
    NEW_RUNTIME_TABLE_COUNT,
    RUNTIME_CANONICAL_ID_VECTOR_SHA256,
    RUNTIME_COUNT,
    RUNTIME_RAW_BYTES,
    RUNTIME_RAW_SHA256,
    SCHEMA_VERSION,
    SELF_TRANSPOSE_COUNT,
    STAGE70,
    STAGE80,
    STAGE81,
    STAGE90,
    STAGE100,
    SUBMISSION_RELATIVE,
    SUBMISSION_SHA256,
    audit_false_engine_functions,
    bank_summary,
    canonical_table_id,
    compact_json_table_id,
    csv_bytes,
    decode_false_engine_source,
    deterministic_gzip,
    ensure,
    jsonl_bytes,
    load_gzip_jsonl,
    parse_exact_records,
    pretty_json_bytes,
    replay_runtime_closure,
    sha256_bytes,
    sha256_path,
    table_record_from_row,
)


CAPTURED_AT = "2026-08-31T20:45:41+08:00"
MERGED_INPUT_REVISION = "8618129a58fd3680dc4c57c08c1090db0db0ab03"


def write_bytes(stage_dir: Path, relative: str, data: bytes) -> None:
    path = stage_dir / Path(PurePosixPath(relative))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def artifact(
    stage_dir: Path,
    path: str,
    role: str,
    media_type: str,
    source_ids: list[str],
    *,
    record_count: int | None = None,
    attributes: dict[str, object] | None = None,
) -> dict[str, object]:
    absolute = stage_dir / Path(PurePosixPath(path))
    row: dict[str, object] = {
        "bytes": absolute.stat().st_size,
        "media_type": media_type,
        "path": path,
        "role": role,
        "sha256": sha256_path(absolute),
        "source_ids": source_ids,
    }
    if record_count is not None:
        row["record_count"] = record_count
    if attributes is not None:
        row["attributes"] = attributes
    return row


def write_manifest(
    stage_dir: Path,
    artifact_specs: list[dict[str, object]],
    manifest: dict[str, object],
) -> None:
    artifact_specs.sort(key=lambda row: str(row["path"]))
    checksums = b"".join(
        f"{row['sha256']}  {row['path']}\n".encode("ascii")
        for row in artifact_specs
    )
    write_bytes(stage_dir, "SHA256SUMS", checksums)
    manifest["artifacts"] = artifact_specs
    write_bytes(stage_dir, "stage.json", pretty_json_bytes(manifest))


def validate_rows(
    rows: list[dict[str, object]], records: tuple[bytes, ...], context: str
) -> None:
    ensure(len(rows) == len(records), f"{context} row/record count drift")
    for index, (row, record) in enumerate(zip(rows, records, strict=True)):
        ensure(
            table_record_from_row(row, f"{context}:{index}") == record,
            f"{context} JSON/binary drift at {index}",
        )


def corrected_finite149_rows(repository: Path) -> list[dict[str, object]]:
    stage80_rows = load_gzip_jsonl(
        repository / f"reproduction/{STAGE80}/normalized/base-tables.jsonl.gz"
    )
    provenance_rows = load_gzip_jsonl(
        repository
        / f"reproduction/{STAGE81}/normalized/base-table-provenance.jsonl.gz"
    )
    provenance_by_table = {
        str(row["effective_table_id"]): row for row in provenance_rows
    }
    ensure(len(provenance_by_table) == FINITE149_COUNT, "Stage 81 provenance count drift")
    corrected: list[dict[str, object]] = []
    for row in stage80_rows:
        table_id = str(row["table_id"])
        effective = provenance_by_table.get(table_id)
        ensure(effective is not None, f"missing Stage 81 provenance for {table_id}")
        copied = copy.deepcopy(row)
        stable_id = str(effective["stable_id"])
        copied["provenance"] = [
            {
                "notes": "Stage 81 effective-provenance record",
                "source_id": "stage81-stage80-evidence",
                "source_path": (
                    "reproduction/81-finite149-portable-verification/"
                    "normalized/base-table-provenance.jsonl.gz"
                ),
                "source_record": stable_id,
            },
            {
                "notes": str(effective["derivation"]),
                "source_id": "stage80-historical-snapshot",
                "source_path": str(effective["effective_source_path"]),
                "source_record": str(effective["effective_source_record"]),
            },
        ]
        notes = list(copied.get("notes", []))
        notes.append("effective_provenance=81-finite149-portable-verification")
        copied["notes"] = notes
        copied["verification"] = {
            "entry_range_checked": True,
            "shape_checked": True,
            "task_check_paths": [
                (
                    "reproduction/81-finite149-portable-verification/verification/"
                    "stage80-portable-semantic-audit.json"
                )
            ],
        }
        corrected.append(copied)
    return corrected


def identity_map_bytes(rows: list[dict[str, object]]) -> bytes:
    return csv_bytes(
        [
            "position",
            "table_id",
            "historical_json_table_id",
            "first_seen_stage",
        ],
        (
            (
                index,
                row["table_id"],
                next(
                    item["value"]
                    for item in row["identifiers"]
                    if item["scheme"] == "sha256-compact-json-table-v1"
                ),
                row["first_seen_stage"],
            )
            for index, row in enumerate(rows)
        ),
    )


def submission_payload_audit(repository: Path, reconstructed_raw: bytes) -> tuple[dict[str, object], bytes, bytes, bytes]:
    submission_index = repository / "reproduction/00-submission-anchor/submissions.jsonl"
    submissions: list[dict[str, object]] = []
    for line in submission_index.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            ensure(isinstance(value, dict), "non-object submission index row")
            submissions.append(value)
    ensure(len(submissions) == 4, "submission participation count drift")
    rows: list[dict[str, object]] = []
    payloads = []
    for submission in submissions:
        relative = str(submission["artifact"]["path"])
        path = repository / "reproduction/00-submission-anchor" / relative
        source = path.read_bytes()
        payload = extract_embedded_false_solver_table_payload(
            source, context=str(path)
        )
        ensure(payload.source_sha256 == FALSE_ENGINE_SHA256, "false engine drift")
        ensure(payload.raw == reconstructed_raw, f"submitted table payload drift: {path}")
        payloads.append(payload)
        rows.append(
            {
                "declared_model_count": payload.model_count,
                "false_engine_sha256": payload.source_sha256,
                "outer_solver_bytes": len(source),
                "outer_solver_sha256": sha256_bytes(source),
                "path": str(path.relative_to(repository)),
                "payload_base85_sha256": payload.encoded_sha256,
                "payload_raw_sha256": payload.raw_sha256,
                "payload_xz_sha256": payload.compressed_sha256,
                "track": submission["track"],
            }
        )
    first = payloads[0]
    ensure(
        all(
            payload.raw == first.raw
            and payload.compressed == first.compressed
            and payload.encoded == first.encoded
            for payload in payloads
        ),
        "four submissions do not share one false table payload",
    )
    ensure(
        len({str(row["outer_solver_sha256"]) for row in rows}) == 2,
        "submitted outer-solver blob cardinality drift",
    )
    compressed = lzma.compress(
        reconstructed_raw,
        format=lzma.FORMAT_XZ,
        check=lzma.CHECK_CRC64,
        preset=9 | lzma.PRESET_EXTREME,
    )
    encoded = base64.b85encode(compressed)
    ensure(compressed == first.compressed, "extreme-9 XZ recompression drift")
    ensure(encoded == first.encoded, "Base85 recompression drift")
    ensure(len(compressed) == EMBEDDED_XZ_BYTES, "XZ byte count drift")
    ensure(sha256_bytes(compressed) == EMBEDDED_XZ_SHA256, "XZ SHA-256 drift")
    ensure(len(encoded) == EMBEDDED_B85_BYTES, "Base85 byte count drift")
    ensure(sha256_bytes(encoded) == EMBEDDED_B85_SHA256, "Base85 SHA-256 drift")
    primary_path = repository / SUBMISSION_RELATIVE
    ensure(sha256_path(primary_path) == SUBMISSION_SHA256, "primary submission anchor drift")
    engine_source = decode_false_engine_source(primary_path.read_bytes())
    audit = {
        "base85": {
            "bytes": len(encoded),
            "canonical_round_trip": base64.b85encode(base64.b85decode(encoded)) == encoded,
            "exact_submitted_literal_match": encoded == first.encoded,
            "sha256": sha256_bytes(encoded),
        },
        "compression": {
            "check": "CRC64",
            "exact_submitted_xz_match": compressed == first.compressed,
            "format": "XZ",
            "preset": "9|PRESET_EXTREME",
            "tested_python_baseline": "3.11",
        },
        "decoded_payload": {
            "declared_model_count": first.model_count,
            "declared_raw_bytes": first.declared_raw_bytes,
            "records": len(first.records),
            "sha256": first.raw_sha256,
            "trailing_bytes": 0,
        },
        "false_engine_sha256": sha256_bytes(engine_source),
        "primary_anchor": SUBMISSION_RELATIVE,
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE90,
        "submission_files": rows,
        "submission_files_checked": len(rows),
        "unique_outer_solver_blobs": len({str(row["outer_solver_sha256"]) for row in rows}),
        "xz": {
            "bytes": len(compressed),
            "sha256": sha256_bytes(compressed),
        },
    }
    return audit, first.raw, compressed, encoded


def stage90_delta(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    delta: list[dict[str, object]] = []
    for sequence, row in enumerate(rows):
        is_core = sequence < CORE_COUNT
        delta.append(
            {
                "action": "retain" if is_core else "add",
                "evidence_paths": (
                    [
                        f"reproduction/{STAGE70}/normalized/tables.bin",
                        "verification/submitted-payload-audit.json",
                    ]
                    if is_core
                    else [
                        f"reproduction/{STAGE80}/normalized/append-order.csv",
                        (
                            f"reproduction/{STAGE81}/normalized/"
                            "base-table-provenance.jsonl.gz"
                        ),
                        "verification/submitted-payload-audit.json",
                    ]
                ),
                "reason_code": (
                    "payload_core_preserved"
                    if is_core
                    else "finite149_payload_append"
                ),
                "schema_version": SCHEMA_VERSION,
                "sequence": sequence,
                "source_stage_id": STAGE70 if is_core else STAGE80,
                "source_table_id": row["table_id"],
                "stage_id": STAGE90,
                "table_id": row["table_id"],
            }
        )
    return delta


def build_stage90(
    output_root: Path, repository: Path
) -> tuple[list[dict[str, object]], tuple[bytes, ...], list[str]]:
    stage = output_root / STAGE90
    stage70_raw = (
        repository / f"reproduction/{STAGE70}/normalized/tables.bin"
    ).read_bytes()
    stage80_raw = (
        repository / f"reproduction/{STAGE80}/normalized/base-tables.bin"
    ).read_bytes()
    core_records = parse_exact_records(stage70_raw, CORE_COUNT, "Stage 70 core")
    finite_records = parse_exact_records(
        stage80_raw, FINITE149_COUNT, "Stage 80 finite149 bases"
    )
    records = core_records + finite_records
    raw = stage70_raw + stage80_raw
    ensure(len(records) == EMBEDDED_COUNT, "Stage 90 record count drift")
    ensure(len(raw) == EMBEDDED_RAW_BYTES, "Stage 90 raw byte count drift")
    ensure(sha256_bytes(raw) == EMBEDDED_RAW_SHA256, "Stage 90 raw SHA-256 drift")
    ensure(
        sha256_bytes(stage70_raw)
        == "7bbc54d33415143349c92cd4c919052ed54c1e5f20973a9b189818362654da5b",
        "Stage 70 binary input drift",
    )
    ensure(
        sha256_bytes(stage80_raw)
        == "9cb8e94392548271c065df102579cfbe95cd512ff2352284f54df9022d6aa2ae",
        "Stage 80 binary input drift",
    )

    core_rows = load_gzip_jsonl(
        repository / f"reproduction/{STAGE70}/normalized/tables.jsonl.gz"
    )
    finite_rows = corrected_finite149_rows(repository)
    validate_rows(core_rows, core_records, "Stage 70 core")
    validate_rows(finite_rows, finite_records, "Stage 81-corrected finite149")
    rows = core_rows + finite_rows

    semantic_gate = json.loads(
        (
            repository
            / f"reproduction/{STAGE81}/verification/stage80-portable-semantic-audit.json"
        ).read_text(encoding="utf-8")
    )
    ensure(
        semantic_gate.get("full_stage80_semantic_replacement") is True
        and semantic_gate.get("suffix_exact_records") == FINITE149_COUNT,
        "Stage 81 semantic gate drift",
    )

    audit, submitted_raw, compressed, encoded = submission_payload_audit(
        repository, raw
    )
    ensure(submitted_raw == raw, "submitted raw payload mismatch")
    metrics = bank_summary(records)
    ensure(
        metrics["canonical_id_vector_sha256"]
        == EMBEDDED_CANONICAL_ID_VECTOR_SHA256,
        "Stage 90 canonical ID-vector drift",
    )
    delta = stage90_delta(rows)

    write_bytes(stage, "normalized/tables.bin", raw)
    write_bytes(
        stage,
        "normalized/tables.jsonl.gz",
        deterministic_gzip(jsonl_bytes(rows)),
    )
    write_bytes(
        stage,
        "normalized/table-id-map.csv.gz",
        deterministic_gzip(identity_map_bytes(rows)),
    )
    write_bytes(stage, "normalized/tables.xz", compressed)
    write_bytes(stage, "normalized/tables.xz.b85", encoded)
    write_bytes(stage, "delta.jsonl.gz", deterministic_gzip(jsonl_bytes(delta)))
    write_bytes(
        stage,
        "verification/submitted-payload-audit.json",
        pretty_json_bytes(audit),
    )

    summary = {
        "action_counts": {"add": FINITE149_COUNT, "retain": CORE_COUNT},
        "bank": metrics,
        "composition": {
            "core_records": CORE_COUNT,
            "finite149_records": FINITE149_COUNT,
            "finite149_uses_stage81_effective_provenance": True,
        },
        "metrics": {
            "payload.declared_embedded": EMBEDDED_COUNT,
            "payload.decoded_embedded": EMBEDDED_COUNT,
            "payload.embedded": EMBEDDED_COUNT,
        },
        "payload_bundle": {
            "base85_bytes": len(encoded),
            "base85_sha256": sha256_bytes(encoded),
            "exact_submitted_base85_match": True,
            "exact_submitted_xz_match": True,
            "raw_bytes": len(raw),
            "raw_sha256": sha256_bytes(raw),
            "xz_bytes": len(compressed),
            "xz_check": "CRC64",
            "xz_preset": "9|PRESET_EXTREME",
            "xz_sha256": sha256_bytes(compressed),
        },
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE90,
        "submission_boundary": {
            "complete_outer_solver_rebuilt": False,
            "exact_inner_table_payload_rebuilt": True,
            "submission_files_statically_checked": 4,
        },
    }
    write_bytes(stage, "summary.json", pretty_json_bytes(summary))

    input_sources = [
        "stage90-core-input",
        "stage90-finite149-input",
        "stage90-submission-anchor",
        "stage90-reproduction-code",
    ]
    table_attributes = {
        "canonical_id_vector_sha256": metrics["canonical_id_vector_sha256"],
        "encoding": "uint8-order-row-major-v1",
        "historical_id_vector_sha256": metrics["historical_id_vector_sha256"],
        "order_distribution": metrics["order_distribution"],
        "raw_bytes": metrics["raw_bytes"],
        "raw_sha256": metrics["raw_sha256"],
        "table_count": metrics["table_count"],
    }
    artifacts = [
        artifact(
            stage,
            "delta.jsonl.gz",
            "membership-delta",
            "application/x-ndjson+gzip",
            input_sources,
            record_count=EMBEDDED_COUNT,
        ),
        artifact(
            stage,
            "normalized/table-id-map.csv.gz",
            "identity-map",
            "text/csv+gzip",
            input_sources,
            record_count=EMBEDDED_COUNT,
        ),
        artifact(
            stage,
            "normalized/tables.bin",
            "table-binary",
            "application/octet-stream",
            input_sources,
            record_count=EMBEDDED_COUNT,
            attributes=table_attributes,
        ),
        artifact(
            stage,
            "normalized/tables.jsonl.gz",
            "table-index",
            "application/x-ndjson+gzip",
            input_sources,
            record_count=EMBEDDED_COUNT,
        ),
        artifact(
            stage,
            "normalized/tables.xz",
            "payload-compressed",
            "application/x-xz",
            input_sources,
            attributes={
                "check": "CRC64",
                "decoded_bytes": EMBEDDED_RAW_BYTES,
                "format": "XZ",
                "preset": "9|PRESET_EXTREME",
            },
        ),
        artifact(
            stage,
            "normalized/tables.xz.b85",
            "payload-base85",
            "text/plain",
            input_sources,
            attributes={"encoding": "Python Base85", "decoded_bytes": EMBEDDED_XZ_BYTES},
        ),
        artifact(
            stage,
            "summary.json",
            "stage-summary",
            "application/json",
            input_sources,
        ),
        artifact(
            stage,
            "verification/submitted-payload-audit.json",
            "payload-audit",
            "application/json",
            input_sources,
            record_count=4,
        ),
    ]
    manifest = {
        "$schema": "../../schemas/stage-manifest.schema.json",
        "captured_at": CAPTURED_AT,
        "claims": [
            "payload.embedded",
            "payload.declared_embedded",
            "payload.decoded_embedded",
        ],
        "depends_on": [STAGE70, STAGE81],
        "notes": [
            "The exact embedded stream is Stage 70's 1,470 records followed by Stage 80's 17 base records; Stage 81 supplies their corrected effective provenance.",
            "The XZ stream is regenerated with CRC64 and preset 9|PRESET_EXTREME, then Python Base85 encoded and compared byte for byte with all four submitted false engines.",
            "This stage reconstructs the inner finite-table payload, not the complete outer launcher.",
            "No raw directory is added because every input is already an immutable manifested artifact in a dependency stage.",
        ],
        "pipeline_order": 90,
        "schema_version": SCHEMA_VERSION,
        "sources": [
            {
                "captured_at": CAPTURED_AT,
                "kind": "repository-snapshot",
                "license_status": "inherits the per-source status recorded by Stage 70",
                "locator": f"reproduction/{STAGE70}",
                "revision": MERGED_INPUT_REVISION,
                "source_id": "stage90-core-input",
            },
            {
                "captured_at": CAPTURED_AT,
                "kind": "repository-snapshot",
                "license_status": "inherits the per-source status recorded by Stages 80 and 81",
                "locator": f"reproduction/{STAGE81} (including transitive Stage 80 data)",
                "revision": MERGED_INPUT_REVISION,
                "source_id": "stage90-finite149-input",
            },
            {
                "captured_at": CAPTURED_AT,
                "kind": "repository-snapshot",
                "license_status": "not-specified; authenticated submission bytes",
                "locator": SUBMISSION_RELATIVE,
                "revision": MERGED_INPUT_REVISION,
                "source_id": "stage90-submission-anchor",
            },
            {
                "captured_at": CAPTURED_AT,
                "kind": "generated",
                "license_status": "Apache-2.0 repository code",
                "locator": "tools/phase4_common.py and tools/rebuild_phase4.py",
                "source_id": "stage90-reproduction-code",
            },
        ],
        "stage_id": STAGE90,
        "status": "verified",
        "title": "exact 1,487-record submitted finite-table payload",
        "verification": {
            "checksum_file": "SHA256SUMS",
            "command": "python3 tools/verify_phase4.py",
            "notes": [
                "The verifier rebuilds both Phase 4 stages in a temporary directory, compares every generated byte, and runs the repository-level semantic checks."
            ],
        },
    }
    write_manifest(stage, artifacts, manifest)
    return rows, records, [str(row["path"]) for row in artifacts]


def historical_runtime_reintroductions(
    repository: Path, derived_records: tuple[bytes, ...]
) -> dict[str, dict[str, object]]:
    """Find the earliest committed table record for derived bytes seen before Phase 4."""

    wanted = {canonical_table_id(record): record for record in derived_records}
    indexes = [
        ("10-primary-9450", "normalized/tables.jsonl.gz"),
        ("20-registered-9852", "normalized/tables.jsonl.gz"),
        ("30-early-deltas-9957", "normalized/tables.jsonl.gz"),
        ("40-delivery-10059", "normalized/tables.jsonl.gz"),
        ("50-generator-prune-3535", "normalized/tables.jsonl.gz"),
        ("70-positive-marginal-core-1470", "normalized/tables.jsonl.gz"),
        (STAGE80, "normalized/required-transposes.jsonl.gz"),
    ]
    found: dict[str, dict[str, object]] = {}
    for historical_stage_id, relative in indexes:
        index_path = repository / f"reproduction/{historical_stage_id}/{relative}"
        with gzip.open(index_path, "rt", encoding="utf-8", newline="") as handle:
            for position, line in enumerate(handle):
                ensure(
                    len(line) <= 2 * 1024 * 1024,
                    f"historical table row exceeds bound: {index_path}:{position + 1}",
                )
                if not line.strip():
                    continue
                row = json.loads(line)
                ensure(
                    isinstance(row, dict),
                    f"non-object historical table row: {index_path}:{position + 1}",
                )
                table_id = str(row.get("table_id"))
                record = wanted.get(table_id)
                if record is None:
                    continue
                ensure(
                    table_record_from_row(row, f"{index_path}:{position + 1}")
                    == record,
                    f"historical table bytes drift: {table_id}",
                )
                found.setdefault(
                    table_id,
                    {
                        "first_seen_stage": row["first_seen_stage"],
                        "historical_index_path": (
                            f"reproduction/{historical_stage_id}/{relative}"
                        ),
                        "historical_position": position,
                        "historical_stage_id": historical_stage_id,
                        "provenance": copy.deepcopy(row["provenance"]),
                    },
                )
    counts: dict[str, int] = {}
    for historical in found.values():
        first_seen = str(historical["first_seen_stage"])
        counts[first_seen] = counts.get(first_seen, 0) + 1
    ensure(
        len(found) == HISTORICAL_REINTRODUCTION_COUNT,
        "historical runtime reintroduction count drift",
    )
    ensure(
        counts
        == {
            "10-primary-9450": HISTORICAL_STAGE10_COUNT,
            STAGE80: HISTORICAL_STAGE80_COUNT,
        },
        "historical runtime first-seen distribution drift",
    )
    return found


def derived_table_row(
    record: bytes,
    source_index: int,
    source_table_id: str,
    runtime_index: int,
    historical: dict[str, object] | None,
) -> dict[str, object]:
    order = record[0]
    notes = [
        f"strict_transpose_of={source_table_id}",
        f"source_payload_index={source_index}",
        f"runtime_index={runtime_index}",
    ]
    provenance: list[dict[str, object]] = [
        {
            "notes": "Generic strict row/column transpose; no problem-ID branch",
            "source_id": "stage100-payload-input",
            "source_path": f"reproduction/{STAGE90}/normalized/tables.jsonl.gz",
            "source_record": source_index,
        }
    ]
    first_seen_stage = STAGE100
    if historical is not None:
        first_seen_stage = str(historical["first_seen_stage"])
        notes.extend(
            [
                f"historical_exact_record_reintroduced_from={first_seen_stage}",
                (
                    "historical_table_index="
                    f"{historical['historical_index_path']}#position="
                    f"{historical['historical_position']}"
                ),
            ]
        )
        provenance.extend(copy.deepcopy(historical["provenance"]))
    return {
        "encoding": "uint8-order-row-major-v1",
        "entries": list(record[1:]),
        "first_seen_stage": first_seen_stage,
        "identifiers": [
            {
                "scheme": "sha256-compact-json-table-v1",
                "value": compact_json_table_id(record),
            }
        ],
        "notes": notes,
        "order": order,
        "provenance": provenance,
        "record_kind": "derived-transpose",
        "schema_version": SCHEMA_VERSION,
        "table_id": canonical_table_id(record),
        "verification": {
            "entry_range_checked": True,
            "shape_checked": True,
            "task_check_paths": ["verification/opposite-closure-audit.json"],
        },
    }


def stage100_delta(
    stage90_rows: list[dict[str, object]], closure
) -> list[dict[str, object]]:
    delta: list[dict[str, object]] = []
    for sequence, row in enumerate(stage90_rows):
        delta.append(
            {
                "action": "retain",
                "evidence_paths": [f"reproduction/{STAGE90}/normalized/tables.bin"],
                "reason_code": "embedded_runtime_prefix",
                "schema_version": SCHEMA_VERSION,
                "sequence": sequence,
                "source_stage_id": STAGE90,
                "source_table_id": row["table_id"],
                "stage_id": STAGE100,
                "table_id": row["table_id"],
            }
        )
    derived_decisions = [
        row
        for row in closure.classifications
        if row["classification"] == "derived-runtime-transpose"
    ]
    for row in derived_decisions:
        runtime_index = int(row["runtime_index"])
        delta.append(
            {
                "action": "derive",
                "evidence_paths": [
                    "normalized/opposite-decisions.jsonl.gz",
                    "verification/opposite-closure-audit.json",
                ],
                "reason_code": "missing_strict_transpose",
                "schema_version": SCHEMA_VERSION,
                "sequence": runtime_index,
                "source_stage_id": STAGE90,
                "source_table_id": row["source_table_id"],
                "stage_id": STAGE100,
                "table_id": row["transpose_table_id"],
            }
        )
    ensure(len(delta) == RUNTIME_COUNT, "Stage 100 delta count drift")
    return delta


def required_transpose_audit(
    repository: Path, closure
) -> list[dict[str, object]]:
    raw = (
        repository / f"reproduction/{STAGE80}/normalized/required-transposes.bin"
    ).read_bytes()
    required = parse_exact_records(raw, 11, "Stage 80 required transposes")
    runtime_by_record = {
        record: index for index, record in enumerate(closure.runtime_records)
    }
    derived_set = set(closure.derived_records)
    rows: list[dict[str, object]] = []
    for record in required:
        ensure(record in derived_set, "task-required transpose is not generically derived")
        rows.append(
            {
                "runtime_index": runtime_by_record[record],
                "table_id": canonical_table_id(record),
            }
        )
    ensure(len({row["table_id"] for row in rows}) == 11, "required transpose duplicate")
    return rows


def build_stage100(
    output_root: Path,
    repository: Path,
    stage90_rows: list[dict[str, object]],
    stage90_records: tuple[bytes, ...],
) -> list[str]:
    stage = output_root / STAGE100
    closure = replay_runtime_closure(stage90_records)
    derived_raw = b"".join(closure.derived_records)
    runtime_raw = b"".join(closure.runtime_records)
    ensure(len(derived_raw) == DERIVED_RAW_BYTES, "derived raw byte count drift")
    ensure(sha256_bytes(derived_raw) == DERIVED_RAW_SHA256, "derived raw SHA drift")
    ensure(len(runtime_raw) == RUNTIME_RAW_BYTES, "runtime raw byte count drift")
    ensure(sha256_bytes(runtime_raw) == RUNTIME_RAW_SHA256, "runtime raw SHA drift")
    ensure(
        bank_summary(closure.derived_records)["canonical_id_vector_sha256"]
        == DERIVED_CANONICAL_ID_VECTOR_SHA256,
        "derived ID-vector drift",
    )
    runtime_metrics = bank_summary(closure.runtime_records)
    ensure(
        runtime_metrics["canonical_id_vector_sha256"]
        == RUNTIME_CANONICAL_ID_VECTOR_SHA256,
        "runtime ID-vector drift",
    )

    derived_decisions = [
        row
        for row in closure.classifications
        if row["classification"] == "derived-runtime-transpose"
    ]
    historical = historical_runtime_reintroductions(
        repository, closure.derived_records
    )
    derived_rows = [
        derived_table_row(
            record,
            int(decision["source_payload_index"]),
            str(decision["source_table_id"]),
            int(decision["runtime_index"]),
            historical.get(canonical_table_id(record)),
        )
        for record, decision in zip(
            closure.derived_records, derived_decisions, strict=True
        )
    ]
    runtime_rows = stage90_rows + derived_rows
    validate_rows(runtime_rows, closure.runtime_records, "Stage 100 runtime bank")
    delta = stage100_delta(stage90_rows, closure)
    required_rows = required_transpose_audit(repository, closure)
    historical_rows = [
        {
            "first_seen_stage": metadata["first_seen_stage"],
            "historical_index_path": metadata["historical_index_path"],
            "historical_position": metadata["historical_position"],
            "historical_stage_id": metadata["historical_stage_id"],
            "runtime_index": int(decision["runtime_index"]),
            "table_id": canonical_table_id(record),
        }
        for record, decision in zip(
            closure.derived_records, derived_decisions, strict=True
        )
        if (metadata := historical.get(canonical_table_id(record))) is not None
    ]
    ensure(
        len(historical_rows) == HISTORICAL_REINTRODUCTION_COUNT,
        "historical runtime audit count drift",
    )

    classifications = list(closure.classifications)
    self_count = sum(row["classification"] == "self-transpose" for row in classifications)
    embedded_count = sum(
        row["classification"] == "nontrivial-transpose-embedded"
        for row in classifications
    )
    derived_count = sum(
        row["classification"] == "derived-runtime-transpose"
        for row in classifications
    )
    suffix = classifications[CORE_COUNT:]
    suffix_counts = {
        "derived": sum(
            row["classification"] == "derived-runtime-transpose" for row in suffix
        ),
        "embedded_nontrivial": sum(
            row["classification"] == "nontrivial-transpose-embedded" for row in suffix
        ),
        "self_transpose": sum(
            row["classification"] == "self-transpose" for row in suffix
        ),
    }
    ensure(suffix_counts == {"derived": 15, "embedded_nontrivial": 2, "self_transpose": 0}, "finite149 closure split drift")

    primary_source = (repository / SUBMISSION_RELATIVE).read_bytes()
    engine_source = decode_false_engine_source(primary_source)
    runtime_code_audit = audit_false_engine_functions(engine_source)
    runtime_code_audit.update(
        {
            "anchor_path": SUBMISSION_RELATIVE,
            "stage_id": STAGE100,
        }
    )
    closure_audit = {
        "arithmetic": {
            "derived": derived_count,
            "embedded": EMBEDDED_COUNT,
            "runtime": len(closure.runtime_records),
            "skipped_existing": self_count + embedded_count,
        },
        "canonical_id_vector": {
            "derived_sha256": DERIVED_CANONICAL_ID_VECTOR_SHA256,
            "runtime_sha256": RUNTIME_CANONICAL_ID_VECTOR_SHA256,
            "serialization": "lowercase canonical record SHA-256 hex plus LF",
        },
        "deduplication": {
            "exact_record_bytes_only": True,
            "isomorphism_quotient": False,
            "nontrivial_embedded_pair_count": EMBEDDED_NONTRIVIAL_TRANSPOSE_PAIR_COUNT,
            "nontrivial_transpose_already_embedded_sources": embedded_count,
            "self_transpose_sources": self_count,
        },
        "derived_stream": {
            "bytes": len(derived_raw),
            "sha256": sha256_bytes(derived_raw),
        },
        "finite149_suffix": suffix_counts,
        "historical_identity": {
            "first_seen_stage_counts": {
                "10-primary-9450": HISTORICAL_STAGE10_COUNT,
                STAGE80: HISTORICAL_STAGE80_COUNT,
            },
            "historical_exact_record_reintroductions": historical_rows,
            "new_exact_records_first_seen_here": NEW_RUNTIME_TABLE_COUNT,
            "reintroduced_exact_records": HISTORICAL_REINTRODUCTION_COUNT,
        },
        "ordering": "all embedded records, then missing strict transposes in ascending embedded source index",
        "required_stage80_transposes": required_rows,
        "required_stage80_transposes_are_subset_not_addition": True,
        "runtime_stream": {
            "bytes": len(runtime_raw),
            "distinct_records": len(set(closure.runtime_records)),
            "sha256": sha256_bytes(runtime_raw),
        },
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE100,
    }

    write_bytes(stage, "normalized/tables.bin", runtime_raw)
    write_bytes(
        stage,
        "normalized/tables.jsonl.gz",
        deterministic_gzip(jsonl_bytes(runtime_rows)),
    )
    write_bytes(
        stage,
        "normalized/table-id-map.csv.gz",
        deterministic_gzip(identity_map_bytes(runtime_rows)),
    )
    write_bytes(
        stage,
        "normalized/opposite-decisions.jsonl.gz",
        deterministic_gzip(jsonl_bytes(classifications)),
    )
    write_bytes(
        stage,
        "normalized/runtime-scan.csv.gz",
        deterministic_gzip(
            csv_bytes(
                [
                    "runtime_index",
                    "origin",
                    "source_payload_index",
                    "source_table_id",
                    "order",
                    "table_id",
                ],
                closure.runtime_scan_rows,
            )
        ),
    )
    write_bytes(stage, "delta.jsonl.gz", deterministic_gzip(jsonl_bytes(delta)))
    write_bytes(
        stage,
        "verification/opposite-closure-audit.json",
        pretty_json_bytes(closure_audit),
    )
    write_bytes(
        stage,
        "verification/submitted-runtime-code-audit.json",
        pretty_json_bytes(runtime_code_audit),
    )

    summary = {
        "action_counts": {
            "derive": DERIVED_TRANSPOSE_COUNT,
            "retain": EMBEDDED_COUNT,
        },
        "bank": runtime_metrics,
        "closure": {
            "derived_missing_transposes": derived_count,
            "embedded_nontrivial_transpose_pairs": EMBEDDED_NONTRIVIAL_TRANSPOSE_PAIR_COUNT,
            "embedded_nontrivial_transpose_sources": embedded_count,
            "finite149_suffix": suffix_counts,
            "historical_exact_record_reintroductions": (
                HISTORICAL_REINTRODUCTION_COUNT
            ),
            "historical_first_seen_stage_counts": {
                "10-primary-9450": HISTORICAL_STAGE10_COUNT,
                STAGE80: HISTORICAL_STAGE80_COUNT,
            },
            "new_exact_records_first_seen_here": NEW_RUNTIME_TABLE_COUNT,
            "runtime_records": len(closure.runtime_records),
            "self_transpose_sources": self_count,
            "stage80_required_transposes_in_derived_set": len(required_rows),
        },
        "metrics": {
            "closure.added": DERIVED_TRANSPOSE_COUNT,
            "closure.runtime": RUNTIME_COUNT,
        },
        "runtime_boundary": {
            "embedded_payload_records": EMBEDDED_COUNT,
            "executes_complete_solver": False,
            "runtime_derived_records": DERIVED_TRANSPOSE_COUNT,
            "static_algorithm_replay": True,
        },
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE100,
    }
    write_bytes(stage, "summary.json", pretty_json_bytes(summary))

    source_ids = [
        "stage100-payload-input",
        "stage100-runtime-algorithm-anchor",
        "stage100-reproduction-code",
    ]
    table_attributes = {
        "canonical_id_vector_sha256": runtime_metrics[
            "canonical_id_vector_sha256"
        ],
        "encoding": "uint8-order-row-major-v1",
        "historical_id_vector_sha256": runtime_metrics[
            "historical_id_vector_sha256"
        ],
        "order_distribution": runtime_metrics["order_distribution"],
        "raw_bytes": runtime_metrics["raw_bytes"],
        "raw_sha256": runtime_metrics["raw_sha256"],
        "table_count": runtime_metrics["table_count"],
    }
    artifacts = [
        artifact(
            stage,
            "delta.jsonl.gz",
            "membership-delta",
            "application/x-ndjson+gzip",
            source_ids,
            record_count=RUNTIME_COUNT,
        ),
        artifact(
            stage,
            "normalized/opposite-decisions.jsonl.gz",
            "opposite-decision-index",
            "application/x-ndjson+gzip",
            source_ids,
            record_count=EMBEDDED_COUNT,
        ),
        artifact(
            stage,
            "normalized/runtime-scan.csv.gz",
            "runtime-scan-index",
            "text/csv+gzip",
            source_ids,
            record_count=RUNTIME_COUNT,
        ),
        artifact(
            stage,
            "normalized/table-id-map.csv.gz",
            "identity-map",
            "text/csv+gzip",
            source_ids,
            record_count=RUNTIME_COUNT,
        ),
        artifact(
            stage,
            "normalized/tables.bin",
            "table-binary",
            "application/octet-stream",
            source_ids,
            record_count=RUNTIME_COUNT,
            attributes=table_attributes,
        ),
        artifact(
            stage,
            "normalized/tables.jsonl.gz",
            "table-index",
            "application/x-ndjson+gzip",
            source_ids,
            record_count=RUNTIME_COUNT,
        ),
        artifact(
            stage,
            "summary.json",
            "stage-summary",
            "application/json",
            source_ids,
        ),
        artifact(
            stage,
            "verification/opposite-closure-audit.json",
            "closure-audit",
            "application/json",
            source_ids,
        ),
        artifact(
            stage,
            "verification/submitted-runtime-code-audit.json",
            "runtime-code-audit",
            "application/json",
            source_ids,
        ),
    ]
    manifest = {
        "$schema": "../../schemas/stage-manifest.schema.json",
        "captured_at": CAPTURED_AT,
        "claims": ["closure.added", "closure.runtime"],
        "depends_on": [STAGE90],
        "notes": [
            "The runtime scan yields all 1,487 embedded records first, then derives each missing strict transpose in ascending embedded source-index order.",
            "Exact record bytes, not isomorphism classes, define deduplication.",
            "The 11 task-required Stage 80 transposes are verified as a subset of the 1,414 generic derivations and are not appended separately.",
            "Of the 1,414 runtime derivations, 17 exact records have earlier repository history (6 from Stage 10 and the 11 Stage 80 required transposes); their first_seen_stage values are preserved while the Stage 100 delta records their reintroduction relative to Stage 90.",
            "The 2,901 records are runtime-oriented scan tables, not embedded payload records.",
            "No raw directory is added because the submitted algorithm, exact payload, and transitive historical table indexes used for first-seen joins are already manifested predecessor artifacts.",
        ],
        "pipeline_order": 100,
        "schema_version": SCHEMA_VERSION,
        "sources": [
            {
                "captured_at": CAPTURED_AT,
                "kind": "repository-snapshot",
                "license_status": "inherits the per-source status recorded by Stage 90",
                "locator": f"reproduction/{STAGE90}",
                "source_id": "stage100-payload-input",
            },
            {
                "captured_at": CAPTURED_AT,
                "kind": "repository-snapshot",
                "license_status": "not-specified; authenticated submission bytes",
                "locator": SUBMISSION_RELATIVE,
                "revision": MERGED_INPUT_REVISION,
                "source_id": "stage100-runtime-algorithm-anchor",
            },
            {
                "captured_at": CAPTURED_AT,
                "kind": "generated",
                "license_status": "Apache-2.0 repository code",
                "locator": "tools/phase4_common.py and tools/rebuild_phase4.py",
                "source_id": "stage100-reproduction-code",
            },
        ],
        "stage_id": STAGE100,
        "status": "verified",
        "title": "generic opposite closure to 2,901 runtime scan tables",
        "verification": {
            "checksum_file": "SHA256SUMS",
            "command": "python3 tools/verify_phase4.py",
            "notes": [
                "The verifier rebuilds both Phase 4 stages in a temporary directory and compares every generated byte before repository-level transition checks."
            ],
        },
    }
    write_manifest(stage, artifacts, manifest)
    return [str(row["path"]) for row in artifacts]


def build(output_root: Path, repository: Path) -> dict[str, list[str]]:
    output_root.mkdir(parents=True, exist_ok=True)
    stage90_rows, stage90_records, stage90_artifacts = build_stage90(
        output_root, repository
    )
    stage100_artifacts = build_stage100(
        output_root, repository, stage90_rows, stage90_records
    )
    return {STAGE90: stage90_artifacts, STAGE100: stage100_artifacts}


def parse_args() -> argparse.Namespace:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=repository)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=repository / "reproduction",
        help="directory that will contain the two stage directories",
    )
    return parser.parse_args()


def main() -> int:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            "Phase 4 requires Python 3.10+; Python 3.11 matches the official sandbox"
        )
    args = parse_args()
    result = build(args.output_root.resolve(), args.repository_root.resolve())
    print(
        json.dumps(
            {
                "artifacts": {stage: len(paths) for stage, paths in result.items()},
                "output_root": str(args.output_root.resolve()),
                "stages": list(result),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
