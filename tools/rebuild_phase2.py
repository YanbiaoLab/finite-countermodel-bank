#!/usr/bin/env python3
"""Rebuild Phase 2's pruning, Fin4 residual, and positive-marginal core.

The command reads only committed raw snapshots plus earlier committed stages.
Historical Python files are parsed as data and are never imported or executed.
The two 467 MiB pair bitsets are copied and validated in bounded forward-only
streams; neither bitset is loaded into memory.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from typing import BinaryIO, Iterable, Iterator, Mapping
import zipfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase1_common import (
    HISTORICAL_ID_SCHEME,
    SCHEMA_VERSION,
    TABLE_ENCODING,
    atomic_text_writer,
    deterministic_gzip_writer,
    iter_archive_members,
    json_line,
    read_bounded,
    sha256_bytes,
    sha256_path,
)
from tools.phase2_common import (
    D15_SOURCE_PATH,
    D17_DIRECT_AFFINE_INVENTORY_PATH,
    D17_SOURCE_PATH,
    EXPECTED_AFFINE_COUNT,
    EXPECTED_DIRECT_AFFINE_COUNT,
    EXPECTED_D17_MODEL_COUNT,
    EXPECTED_D17_RAW_SHA256,
    EXPECTED_D17_RAW_BYTES,
    EXPECTED_SMALL_COUNT,
    extract_embedded_false_solver_table_payload,
    extract_solver_table_payload,
    read_bounded_file,
    reconstruct_stage50_sources,
    validate_pair_bitset_streams,
    write_deterministic_gzip_copy,
)
from tools.phase2_stage70 import (
    FINAL_REMAINING_COUNT,
    FINAL_UNION_COUNT,
    MODEL_COUNT,
    NORMALIZED_COVERAGE_HEADER,
    POSITIVE_MARGINAL_COUNT,
    REMAINING_PAIR_UNIVERSE,
    ZERO_MARGINAL_COUNT,
    derive_positive_marginal_core,
)
from tools.stage60_seedfree import reconstruction_report_for_repository
from tools.stage60_full_run_evidence import validate_committed_full_run_evidence
from tools.rebuild_phase1 import (
    Table,
    atomic_binary,
    bank_details,
    delta_record,
    write_json,
    write_jsonl_gz,
    write_table_outputs,
)


STAGE00 = "00-submission-anchor"
STAGE40 = "40-delivery-10059"
STAGE50 = "50-generator-prune-3535"
STAGE60 = "60-fin4-residual-284151591"
STAGE70 = "70-positive-marginal-core-1470"
CAPTURED_AT = "2026-08-31T15:30:00+08:00"
SOURCE_CONTEXT_REVISION = "6d8b449071a9168b3ddb35f77533e093833c70a4"
SOURCE_NOTE = (
    "The captured member tree was ignored by the source repository. The revision "
    "is context only; archive and member hashes identify the captured bytes."
)
LICENSE_STATUS = "not-specified; no license grant inferred"

RAW_ARCHIVE_SHA256 = {
    STAGE50: "92882a129706a950226472bc88e09c12befe98b70786035fdac8a7224c648fb3",
    STAGE60: "589f3b272fb970c9b995e6d9433dc3deec66241a2cf061be230254445704d9d0",
    STAGE70: "e2ed1caac2f800c3fae6af7da4413d1381af5f0c988a772740595366875d06f8",
}

BITSET324_SHA256 = "f3cce217528adee2305e618a81a1fdb7399c6732523bb60f055b1d5acf61f383"
BITSET284_SHA256 = "03f4a7eccc7df811756fc5da361a647b49b9064f35b2b14730362fc3fb810756"
BITSET_BYTES = 489_598_720
EQUATIONS_CSV_SHA256 = "62b9fa9d5b5fa0ef499e7a9b30ae3e244485e4cc62e996de99c39897a74bdc7c"
SUBMITTED_MARATHON_SHA256 = (
    "e301cbd091df1376c21ac297e1afb05decb70c34879cd6e485744d09e017c809"
)


class ReconstructionError(RuntimeError):
    """Raised when a committed Phase 2 source or derived invariant drifts."""


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ReconstructionError(message)


def verify_raw_archive(stage_id: str, archive: Path) -> None:
    ensure(archive.is_file(), f"missing {archive}")
    actual = sha256_path(archive)
    ensure(
        actual == RAW_ARCHIVE_SHA256[stage_id],
        f"raw snapshot drift for {stage_id}: {actual}",
    )


def table_from_record(record: Mapping[str, object]) -> Table:
    ensure(record.get("record_kind") == "exact-explicit", "unexpected table record kind")
    verification = record.get("verification")
    task_paths = []
    if isinstance(verification, Mapping):
        value = verification.get("task_check_paths", [])
        ensure(isinstance(value, list), "invalid task_check_paths")
        task_paths = list(value)
    table = Table(
        order=int(record["order"]),
        entries=tuple(record["entries"]),
        first_seen_stage=str(record["first_seen_stage"]),
        provenance=[dict(item) for item in record["provenance"]],
        task_check_paths=task_paths,
    )
    ensure(table.table_id == record.get("table_id"), "canonical table ID drift")
    aliases = record.get("identifiers")
    ensure(isinstance(aliases, list) and len(aliases) == 1, "historical alias drift")
    ensure(
        aliases[0]
        == {"scheme": HISTORICAL_ID_SCHEME, "value": table.historical_id},
        "historical table ID drift",
    )
    return table


def load_stage_tables(root: Path, stage_id: str) -> list[Table]:
    stage = root / "reproduction" / stage_id
    index_path = stage / "normalized/tables.jsonl.gz"
    binary_path = stage / "normalized/tables.bin"
    tables: list[Table] = []
    with gzip.open(index_path, "rt", encoding="utf-8") as index, binary_path.open("rb") as binary:
        for line_number, line in enumerate(index, start=1):
            ensure(len(line) <= 1024 * 1024, f"oversized table line {line_number}")
            record = json.loads(line)
            ensure(isinstance(record, dict), f"non-object table line {line_number}")
            table = table_from_record(record)
            ensure(binary.read(len(table.raw)) == table.raw, f"table binary drift at {line_number}")
            tables.append(table)
        ensure(not binary.read(1), f"trailing table bytes in {stage_id}")
    return tables


def witness_record(witness) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_position": witness.source_index,
        "table_id": witness.table_id,
        "order": witness.order,
        "classification": witness.classification,
        "mapping_to_zn": list(witness.mapping_to_zn),
        "left_coefficient": witness.left_coefficient,
        "right_coefficient": witness.right_coefficient,
        "constant": witness.constant,
    }


def build_stage50(root: Path, bank10059: list[Table]) -> tuple[list[Table], dict]:
    stage_dir = root / "reproduction" / STAGE50
    archive = stage_dir / "raw/d15-d17-prune-snapshot.tar.gz"
    verify_raw_archive(STAGE50, archive)
    captured: dict[str, bytes] = {}
    for name, member, handle in iter_archive_members(archive):
        ensure(member.size <= 2 * 1024 * 1024, f"unexpectedly large Stage50 member: {name}")
        captured[name] = read_bounded(handle, member.size, limit=2 * 1024 * 1024)
    ensure(len(captured) == 5, f"Stage50 raw member count is {len(captured)}")

    def one(suffix: str) -> tuple[str, bytes]:
        matches = [(name, payload) for name, payload in captured.items() if name.endswith(suffix)]
        ensure(len(matches) == 1, f"expected one Stage50 member ending {suffix}")
        return matches[0]

    d15_name, d15_source = one("/d15/solver.py")
    d17_name, d17_source = one("solvers/false/20260812_d17/solver.py")
    inventory_name, inventory_payload = one("/d17/static-affine-inventory.json")
    report_name, report_payload = one("/D17相对D15改动与实验报告.md")
    _audit_name, _audit_payload = one("/d17/audit_static_affine_inventory.py")

    result = reconstruct_stage50_sources(d15_source, d17_source)
    ensure(len(bank10059) == 10_059, "Stage40 input count drift")
    ensure(
        b"".join(table.raw for table in bank10059) == b"".join(result.input_records),
        "Stage40 normalized bank differs from captured d15 payload",
    )

    inventory = json.loads(inventory_payload)
    inherited = inventory.get("inherited_static_bank", {})
    ensure(inherited.get("total_models") == 10_059, "historical affine inventory total drift")
    ensure(
        inherited.get("scalar_affine_models") == EXPECTED_DIRECT_AFFINE_COUNT,
        "historical direct-affine count drift",
    )
    historical_models = inherited.get("models")
    ensure(isinstance(historical_models, list), "historical affine model list missing")
    direct_witnesses = [row for row in result.affine_witnesses if row.classification == "direct"]
    expected_historical = [
        {
            "model_index": row.source_index,
            "model": [
                row.order,
                row.left_coefficient,
                row.right_coefficient,
                row.constant,
            ],
        }
        for row in direct_witnesses
    ]
    ensure(historical_models == expected_historical, "historical affine inventory rows drift")

    report = report_payload.decode("utf-8")
    for text in ("10,059", "241", "9,818", "6,283", "3,535", "237,631"):
        ensure(text in report, f"Stage50 report omits checkpoint {text}")

    affine_set = set(result.affine_indices)
    small_indices = tuple(
        index
        for index, record in enumerate(result.input_records)
        if index not in affine_set and record[0] <= 4
    )
    keep_indices = tuple(
        index
        for index, record in enumerate(result.input_records)
        if index not in affine_set and record[0] > 4
    )
    ensure(len(small_indices) == EXPECTED_SMALL_COUNT, "small-model index count drift")
    ensure(len(keep_indices) == EXPECTED_D17_MODEL_COUNT, "candidate index count drift")
    candidates = [bank10059[index] for index in keep_indices]
    ensure(
        b"".join(table.raw for table in candidates) == b"".join(result.final_records),
        "Stage50 candidate order differs from published d17",
    )

    raw_evidence = f"reproduction/{STAGE50}/raw/{archive.name}"
    delta: list[dict] = []
    witness_by_index = {row.source_index: row for row in result.affine_witnesses}
    for source_index in result.affine_indices:
        witness = witness_by_index[source_index]
        evidence_member = inventory_name if witness.classification == "direct" else report_name
        delta.append(
            delta_record(
                STAGE50,
                len(delta),
                "remove",
                bank10059[source_index],
                "scalar_affine_regenerated",
                f"{raw_evidence}#{evidence_member}",
                notes=(
                    f"Stage40 position {source_index}; {witness.classification}; "
                    f"affine parameters ({witness.left_coefficient},"
                    f"{witness.right_coefficient},{witness.constant}) modulo {witness.order}"
                ),
                source_stage=STAGE40,
            )
        )
    for source_index in small_indices:
        delta.append(
            delta_record(
                STAGE50,
                len(delta),
                "remove",
                bank10059[source_index],
                "fin4_regenerated",
                f"{raw_evidence}#{report_name}",
                notes=f"Stage40 position {source_index}; order {bank10059[source_index].order}",
                source_stage=STAGE40,
            )
        )

    bank, details = write_table_outputs(stage_dir, candidates)
    ensure(len(bank) == EXPECTED_D17_RAW_BYTES, "Stage50 candidate raw byte count drift")
    ensure(sha256_bytes(bank) == EXPECTED_D17_RAW_SHA256, "Stage50 candidate raw SHA drift")
    write_jsonl_gz(stage_dir / "delta.jsonl.gz", delta)
    write_jsonl_gz(
        stage_dir / "verification/scalar-affine-witnesses.jsonl.gz",
        (witness_record(row) for row in result.affine_witnesses),
    )

    delivery = bank10059[-102:]
    delivery_order4 = [table for table in delivery if table.order == 4]
    candidate_ids = {table.table_id for table in candidates}
    retained_delivery = [table for table in delivery if table.table_id in candidate_ids]
    ensure(len(delivery_order4) == 1, "delivery order-4 count drift")
    ensure(len(retained_delivery) == 101, "delivery retained count drift")
    delivery_audit = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE50,
        "delivery_source_stage": STAGE40,
        "delivery_count": len(delivery),
        "order4_count": len(delivery_order4),
        "order4_table_id": delivery_order4[0].table_id,
        "order4_stage40_position": next(
            index for index, table in enumerate(bank10059) if table.table_id == delivery_order4[0].table_id
        ),
        "candidate_retained_count": len(retained_delivery),
        "candidate_retained_table_ids": [table.table_id for table in retained_delivery],
    }
    write_json(stage_dir / "verification/delivery-102-retention.json", delivery_audit)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE50,
        "metrics": {
            "delivery.order4": 1,
            "delivery.candidate_retained": 101,
            "prune.scalar_affine": EXPECTED_AFFINE_COUNT,
            "prune.order_le_4": EXPECTED_SMALL_COUNT,
            "candidate.3535": len(candidates),
        },
        "action_counts": {"remove": len(delta)},
        "bank": details,
        "pruning": {
            "input_tables": len(bank10059),
            "direct_scalar_affine": len(direct_witnesses),
            "carrier_relabelled_scalar_affine": EXPECTED_AFFINE_COUNT - len(direct_witnesses),
            "non_affine_after_first_filter": len(result.non_affine_records),
            "order_at_most_4_after_affine_filter": len(small_indices),
            "candidate_tables": len(candidates),
            "stable_input_order_preserved": True,
        },
        "historical_payloads": {
            "d15_member": d15_name,
            "d15_source_sha256": sha256_bytes(d15_source),
            "d15_raw_sha256": sha256_bytes(b"".join(result.input_records)),
            "d17_member": d17_name,
            "d17_source_sha256": sha256_bytes(d17_source),
            "d17_raw_sha256": sha256_bytes(b"".join(result.final_records)),
            "published_d17_exact_match": True,
        },
        "delivery_audit": {
            "input": 102,
            "order4_removed": 1,
            "candidate_retained": 101,
        },
        "known_gaps": [
            "The report names d16.2 as the immediate historical build baseline, but that file was unavailable for capture.",
            "The complete 241-table classification is reconstructed from 227 historical direct-affine rows plus 14 explicit carrier-relabeling witnesses and the exact d15-to-d17 payload transition.",
        ],
    }
    write_json(stage_dir / "summary.json", summary)
    return candidates, summary


def drain(handle: BinaryIO) -> None:
    for _chunk in iter(lambda: handle.read(1024 * 1024), b""):
        pass


def _csv_reader(payload: bytes, context: str) -> csv.DictReader:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReconstructionError(f"{context}: not UTF-8") from exc
    return csv.DictReader(io.StringIO(text, newline=""))


def build_partition_ledger(
    output: Path,
    rows324_payload: bytes,
    rows284_payload: bytes,
    fin4_payload: bytes,
) -> dict:
    rows324 = _csv_reader(rows324_payload, "324M row CSV")
    rows284 = _csv_reader(rows284_payload, "284M row CSV")
    fin4_rows = _csv_reader(fin4_payload, "Fin4 row CSV")
    expected324 = [
        "source_equation_id", "bitmap_row_index", "bitmap_offset_bytes",
        "fin23_covered_target_count", "singleton_true_target_count",
        "remaining_target_count", "is_active_source", "singleton_family_mask",
        "singleton_primary_class",
    ]
    expected284 = [
        "source_equation_id", "bitmap_row_index", "bitmap_offset_bytes",
        "fin23_covered_target_count", "singleton_true_target_count",
        "original_324M_target_count", "fin4_covered_target_count",
        "remaining_target_count", "is_active_source", "singleton_family_mask",
        "singleton_primary_class",
    ]
    expected_fin4 = [
        "source_equation_id", "equation_text", "original_324M_target_count",
        "fin4_covered_target_count", "remaining_after_all_fin4_target_count",
        "fin4_coverage_percent_of_324M_source", "is_active_after_all_fin4",
    ]
    ensure(rows324.fieldnames == expected324, "324M row CSV header drift")
    ensure(rows284.fieldnames == expected284, "284M row CSV header drift")
    ensure(fin4_rows.fieldnames == expected_fin4, "Fin4 row CSV header drift")
    header = [
        "source_equation_id", "fin23_covered_target_count",
        "singleton_true_target_count", "targeted_324m_target_count",
        "fin4_covered_target_count", "residual_284m_target_count",
    ]
    totals = {name: 0 for name in header[1:]}
    rows_seen = 0
    with deterministic_gzip_writer(output) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="", write_through=True)
        writer = csv.writer(text, lineterminator="\n")
        writer.writerow(header)
        for source_id, triple in enumerate(zip(rows324, rows284, fin4_rows), start=1):
            row324, row284, row_fin4 = triple
            ids = {
                int(row324["source_equation_id"]),
                int(row284["source_equation_id"]),
                int(row_fin4["source_equation_id"]),
            }
            ensure(ids == {source_id}, f"pair row ID drift at Equation{source_id}")
            expected_offset = 4096 + (source_id - 1) * 7824
            ensure(int(row324["bitmap_row_index"]) == source_id - 1, "324M row index drift")
            ensure(int(row284["bitmap_row_index"]) == source_id - 1, "284M row index drift")
            ensure(int(row324["bitmap_offset_bytes"]) == expected_offset, "324M row offset drift")
            ensure(int(row284["bitmap_offset_bytes"]) == expected_offset, "284M row offset drift")
            fin23 = int(row324["fin23_covered_target_count"])
            singleton = int(row324["singleton_true_target_count"])
            targeted = int(row324["remaining_target_count"])
            fin4 = int(row284["fin4_covered_target_count"])
            residual = int(row284["remaining_target_count"])
            ensure(int(row284["fin23_covered_target_count"]) == fin23, "Fin2/3 row drift")
            ensure(int(row284["singleton_true_target_count"]) == singleton, "singleton row drift")
            ensure(int(row284["original_324M_target_count"]) == targeted, "324M join drift")
            ensure(int(row_fin4["original_324M_target_count"]) == targeted, "Fin4 original row drift")
            ensure(int(row_fin4["fin4_covered_target_count"]) == fin4, "Fin4 coverage row drift")
            ensure(int(row_fin4["remaining_after_all_fin4_target_count"]) == residual, "Fin4 residual row drift")
            ensure(fin23 + singleton + targeted == 62_575, "324M row partition drift")
            ensure(targeted == fin4 + residual, "Fin4 row partition drift")
            values = [fin23, singleton, targeted, fin4, residual]
            writer.writerow([source_id, *values])
            for name, value in zip(header[1:], values):
                totals[name] += value
            rows_seen += 1
        text.flush()
    ensure(next(rows324, None) is None, "324M row CSV has trailing rows")
    ensure(next(rows284, None) is None, "284M row CSV has trailing rows")
    ensure(next(fin4_rows, None) is None, "Fin4 row CSV has trailing rows")
    ensure(rows_seen == 62_576, f"pair row count is {rows_seen}")
    ensure(
        totals
        == {
            "fin23_covered_target_count": 2_285_032_108,
            "singleton_true_target_count": 1_306_503_425,
            "targeted_324m_target_count": 324_157_667,
            "fin4_covered_target_count": 40_006_076,
            "residual_284m_target_count": 284_151_591,
        },
        f"pair partition totals drift: {totals}",
    )
    return {"rows": rows_seen, "totals": totals}


def iter_partition_expected(path: Path) -> Iterator[tuple[int, int, int, int]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield (
                int(row["source_equation_id"]),
                int(row["targeted_324m_target_count"]),
                int(row["fin4_covered_target_count"]),
                int(row["residual_284m_target_count"]),
            )


def audit_fin4_shards(shards: dict[int, tuple[str, dict]], output: Path) -> dict:
    ensure(set(shards) == set(range(256)), "Fin4 shard set is incomplete")
    scalar_classes = 0
    bitslice_classes = 0
    evaluated = 0
    opposite = 0
    skipped = 0
    raw_tables = 0
    elapsed = 0.0
    maximum_rss = 0
    fields = [
        "shard", "engine", "range_start", "range_count", "raw_tables_scanned",
        "canonical_classes", "signatures_evaluated", "opposite_derived",
        "skipped_as_derived", "elapsed_seconds", "maximum_rss_bytes", "source_member",
    ]
    with deterministic_gzip_writer(output) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="", write_through=True)
        writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index in range(256):
            source_member, row = shards[index]
            ensure(row.get("status") == "complete", f"Fin4 shard {index} incomplete")
            start = int(row["range_start"])
            count = int(row["range_count"])
            scanned = int(row["raw_tables_scanned"])
            ensure(start == index * (1 << 24), f"Fin4 shard {index} range start drift")
            ensure(count == 1 << 24 and scanned == count, f"Fin4 shard {index} range count drift")
            raw_tables += scanned
            shard_elapsed = float(row["elapsed_seconds"])
            elapsed += shard_elapsed
            rss = int(row["ru_maxrss_raw"])
            maximum_rss = max(maximum_rss, rss)
            if index < 6:
                ensure(row.get("mode") == "enumerate-inplace", f"scalar shard {index} mode drift")
                canonical = int(row["canonical_models_evaluated"])
                scalar_classes += canonical
                shard_evaluated = canonical
                shard_opposite = 0
                shard_skipped = 0
                engine = "scalar"
            else:
                ensure(row.get("mode") == "enumerate-bitslice-inplace", f"bitslice shard {index} mode drift")
                canonical = int(row["canonical_models_in_range"])
                shard_evaluated = int(row["model_signatures_evaluated"])
                shard_opposite = int(row["opposite_signatures_derived"])
                shard_skipped = int(row["canonical_models_skipped_as_derived"])
                ensure(shard_evaluated + shard_skipped == canonical, f"bitslice shard {index} accounting drift")
                bitslice_classes += canonical
                evaluated += shard_evaluated
                opposite += shard_opposite
                skipped += shard_skipped
                engine = "bitslice-opposite"
            writer.writerow(
                {
                    "shard": index,
                    "engine": engine,
                    "range_start": start,
                    "range_count": count,
                    "raw_tables_scanned": scanned,
                    "canonical_classes": canonical,
                    "signatures_evaluated": shard_evaluated,
                    "opposite_derived": shard_opposite,
                    "skipped_as_derived": shard_skipped,
                    "elapsed_seconds": f"{shard_elapsed:.9f}",
                    "maximum_rss_bytes": rss,
                    "source_member": source_member,
                }
            )
        text.flush()
    result = {
        "shards": 256,
        "raw_labeled_tables_scanned": raw_tables,
        "scalar_isomorphism_classes": scalar_classes,
        "bitslice_interval_isomorphism_classes": bitslice_classes,
        "all_fin4_isomorphism_classes": scalar_classes + bitslice_classes,
        "bitslice_model_signatures_evaluated": evaluated,
        "bitslice_opposite_signatures_derived": opposite,
        "bitslice_classes_skipped_as_derived": skipped,
        "elapsed_seconds_sum": round(elapsed, 6),
        "maximum_engine_rss_bytes": maximum_rss,
        "ranges_contiguous_and_gapless": True,
    }
    ensure(result["raw_labeled_tables_scanned"] == 2**32, "Fin4 labeled-table total drift")
    ensure(result["scalar_isomorphism_classes"] == 58_254_198, "Fin4 scalar-class total drift")
    ensure(result["bitslice_interval_isomorphism_classes"] == 120_727_754, "Fin4 bitslice-class total drift")
    ensure(result["all_fin4_isomorphism_classes"] == 178_981_952, "Fin4 class total drift")
    ensure(result["bitslice_model_signatures_evaluated"] == 79_470_563, "Fin4 signature total drift")
    ensure(result["bitslice_opposite_signatures_derived"] == 41_257_191, "Fin4 opposite total drift")
    ensure(result["bitslice_classes_skipped_as_derived"] == 41_257_191, "Fin4 skipped total drift")
    ensure(result["maximum_engine_rss_bytes"] == 504_709_120, "Fin4 maximum RSS drift")
    return result


def build_stage60(root: Path) -> dict:
    stage_dir = root / "reproduction" / STAGE60
    archive = stage_dir / "raw/fin4-residual-snapshot.tar.gz"
    verify_raw_archive(STAGE60, archive)
    normalized324 = stage_dir / "normalized/324M_remaining_pairs.bitset.gz"
    normalized284 = stage_dir / "normalized/284M_remaining_pairs.bitset.gz"
    copies = {}
    captured: dict[str, bytes] = {}
    shards: dict[int, tuple[str, dict]] = {}
    shard_pattern = re.compile(r"/shards/shard_(\d{3})\.json$")
    for name, member, handle in iter_archive_members(archive):
        if name.endswith("/324M_remaining_pairs/324M_remaining_pairs.bitset"):
            copies["324"] = write_deterministic_gzip_copy(handle, normalized324)
            continue
        if name.endswith("/284M_remaining_pairs/284M_remaining_pairs.bitset"):
            copies["284"] = write_deterministic_gzip_copy(handle, normalized284)
            continue
        match = shard_pattern.search(name)
        wanted = (
            name.endswith("/324M_remaining_pairs/manifest.json")
            or name.endswith("/284M_remaining_pairs/manifest.json")
            or name.endswith("/324M_remaining_pairs/324M_remaining_pairs_by_source.csv")
            or name.endswith("/284M_remaining_pairs/284M_remaining_pairs_by_source.csv")
            or name.endswith("/324M_remaining_pairs/order5_equations.csv")
            or name.endswith("/fin4_coverage_by_source.csv")
            or name.endswith("/full_summary.json")
            or match is not None
        )
        if wanted:
            ensure(member.size <= 8 * 1024 * 1024, f"oversized Stage60 member: {name}")
            payload = read_bounded(handle, member.size, limit=8 * 1024 * 1024)
            captured[name] = payload
            if match is not None:
                index = int(match.group(1))
                ensure(index not in shards, f"duplicate Fin4 shard {index}")
                shards[index] = (name, json.loads(payload))
        else:
            drain(handle)
    ensure(set(copies) == {"324", "284"}, "Stage60 raw bitsets missing")
    ensure(copies["324"].uncompressed_bytes == BITSET_BYTES, "324M bitset size drift")
    ensure(copies["284"].uncompressed_bytes == BITSET_BYTES, "284M bitset size drift")
    ensure(copies["324"].uncompressed_sha256 == BITSET324_SHA256, "324M bitset SHA drift")
    ensure(copies["284"].uncompressed_sha256 == BITSET284_SHA256, "284M bitset SHA drift")

    def captured_one(suffix: str) -> tuple[str, bytes]:
        matches = [(name, payload) for name, payload in captured.items() if name.endswith(suffix)]
        ensure(len(matches) == 1, f"expected one Stage60 member ending {suffix}, found {len(matches)}")
        return matches[0]

    _manifest324_name, manifest324_payload = captured_one("/324M_remaining_pairs/manifest.json")
    _manifest284_name, manifest284_payload = captured_one("/284M_remaining_pairs/manifest.json")
    _rows324_name, rows324 = captured_one("/324M_remaining_pairs/324M_remaining_pairs_by_source.csv")
    _rows284_name, rows284 = captured_one("/284M_remaining_pairs/284M_remaining_pairs_by_source.csv")
    _equations_name, equations = captured_one("/324M_remaining_pairs/order5_equations.csv")
    _fin4_rows_name, fin4_rows = captured_one("/fin4_coverage_by_source.csv")
    _full_summary_name, full_summary_payload = captured_one("/full_summary.json")
    ensure(sha256_bytes(equations) == EQUATIONS_CSV_SHA256, "Stage60 equation CSV drift")

    manifest324 = json.loads(manifest324_payload)
    manifest284 = json.loads(manifest284_payload)
    full_summary = json.loads(full_summary_payload)
    ensure(manifest324["partition"]["remaining_pairs"] == 324_157_667, "324M manifest drift")
    ensure(manifest284["partition"]["remaining_pairs"] == 284_151_591, "284M manifest drift")
    ensure(manifest284["partition"]["fin4_incremental_covered_pairs"] == 40_006_076, "Fin4 manifest drift")
    ensure(full_summary["pair_counts"]["covered_by_all_fin4"] == 40_006_076, "Fin4 summary drift")

    partition_path = stage_dir / "normalized/pair-partition-by-source.csv.gz"
    partition = build_partition_ledger(partition_path, rows324, rows284, fin4_rows)
    with gzip.open(normalized324, "rb") as original, gzip.open(normalized284, "rb") as residual:
        validation = validate_pair_bitset_streams(
            original,
            residual,
            expected_rows=iter_partition_expected(partition_path),
        )
    ensure(validation.original_popcount == 324_157_667, "324M payload count drift")
    ensure(validation.removed_popcount == 40_006_076, "Fin4 payload difference drift")
    ensure(validation.residual_popcount == 284_151_591, "284M payload count drift")
    ensure(validation.original_active_sources == 41_696, "324M active-source drift")
    ensure(validation.residual_active_sources == 41_696, "284M active-source drift")

    shard_path = stage_dir / "normalized/fin4-shards.csv.gz"
    enumeration = audit_fin4_shards(shards, shard_path)
    ensure(full_summary["enumeration"]["raw_labeled_tables_scanned"] == 2**32, "Fin4 full-summary scan drift")
    ensure(full_summary["enumeration"]["all_fin4_isomorphism_classes"] == 178_981_952, "Fin4 full-summary class drift")

    reconstruction_report = reconstruction_report_for_repository(root)
    write_json(
        stage_dir / "verification/seedfree-input-reconstruction.json",
        reconstruction_report,
    )
    full_run = validate_committed_full_run_evidence(
        root,
        stage_dir / "verification/seedfree-full-run.json",
        stage_dir / "verification/seedfree-full-run-logs.jsonl.gz",
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE60,
        "metrics": {
            "pairs.target": validation.original_popcount,
            "pairs.fin4_covered": validation.removed_popcount,
            "pairs.residual": validation.residual_popcount,
        },
        "action_counts": {},
        "bank": {},
        "directed_pair_partition": {
            "full_nonreflexive_universe": 3_915_693_200,
            "fin2_or_fin3_covered": 2_285_032_108,
            "singleton_true": 1_306_503_425,
            "targeted_after_prior_filters": validation.original_popcount,
            "fin4_incremental_covered": validation.removed_popcount,
            "residual_after_fin4": validation.residual_popcount,
            "identity_before_fin4": "2285032108 + 1306503425 + 324157667 = 3915693200",
            "identity_after_fin4": "2285032108 + 1306503425 + 40006076 + 284151591 = 3915693200",
        },
        "bitset_validation": {
            "rows_checked": validation.rows_checked,
            "row_stride_bytes": validation.original_header.row_stride_bytes,
            "original_active_sources": validation.original_active_sources,
            "residual_active_sources": validation.residual_active_sources,
            "residual_is_subset": validation.residual_is_subset,
            "diagonal_bits_all_zero": validation.diagonal_bits_all_zero,
            "out_of_range_bits_all_zero": validation.out_of_range_bits_all_zero,
            "original_uncompressed_sha256": copies["324"].uncompressed_sha256,
            "residual_uncompressed_sha256": copies["284"].uncompressed_sha256,
        },
        "row_ledger": partition,
        "fin4_enumeration": enumeration,
        "seedfree_outcome_rerun": {
            "reconstructed_input_status": reconstruction_report["status"],
            "reconstructed_files": reconstruction_report["files"],
            "runner": "scripts/run_seedfree.py",
            "engine_smoke_test": "scripts/smoke_test_engines.py",
            "evidence_capture": "scripts/capture_seedfree_evidence.py",
            "enumeration_method": "seed-free-all-bitslice-opposite-result-level",
            "historical_seed_chain_used": False,
            "full_run_demonstrated_in_repository": (
                full_run["status"] == "validated-exact"
            ),
            "full_run_evidence_report": "verification/seedfree-full-run.json",
            "full_run_sanitized_logs": (
                "verification/seedfree-full-run-logs.jsonl.gz"
            ),
            "full_run_validation": full_run,
            "runner_consumed_reconstructed_files": [
                "equations.bin",
                "equation_mirror_map.bin",
            ],
            "support_or_upstream_files_not_consumed_by_runner": [
                "eq_size5.txt",
                "singleton_family_mask.u8",
                "singleton_primary.u8",
            ],
        },
        "resource_boundary": {
            "historical_maximum_engine_rss_bytes": enumeration["maximum_engine_rss_bytes"],
            "historical_shard_elapsed_seconds_sum": enumeration["elapsed_seconds_sum"],
            "seedfree_full_run_maximum_engine_rss_bytes": full_run[
                "maximum_engine_rss_bytes"
            ],
            "seedfree_full_run_successful_shard_wall_seconds_sum": full_run[
                "timing"
            ]["shard_wall_seconds_sum"],
            "bitset_copy_and_validation": (
                "two bounded gzip streams plus one 7,824-byte row per bitset"
            ),
        },
        "known_gaps": [
            "The complete historical 6,173-model seed-generation/provenance chain remains unavailable and is intentionally not used by the new result-level runner.",
            "The completed seed-free run demonstrates the exact result-level outcome, not the historical seeded execution order or provenance chain.",
            "The upstream 324M universe is not regenerated from the earliest Fin2/Fin3 and singleton discovery inputs.",
        ],
    }
    write_json(stage_dir / "summary.json", summary)
    return summary


def verify_coverage_share_zip(captured: dict[str, bytes]) -> dict:
    zip_matches = [(name, payload) for name, payload in captured.items() if name.endswith("-share.zip")]
    ensure(len(zip_matches) == 1, "Stage70 share zip missing")
    _zip_name, payload = zip_matches[0]
    expected_names = {
        "README.md", "model_284m_pair_coverage.csv",
        "model_284m_pair_coverage_deduplicated.csv", "manifest.json",
        "deduplicated_manifest.json", "compute_284m_model_pair_coverage.py",
        "compute_284m_deduplicated_pair_coverage.py",
        "compute_324m_model_pair_coverage.py",
        "compute_324m_deduplicated_pair_coverage.py",
        "d17_324m_pair_coverage.c", "d17_324m_deduplicate_profiles.c",
    }
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        ensure(len(names) == len(set(names)) and set(names) == expected_names, "Stage70 share zip member set drift")
        ensure(all(not name.startswith("/") and ".." not in Path(name).parts for name in names), "unsafe Stage70 zip member")
        for base_name in (
            "README.md", "model_284m_pair_coverage.csv",
            "model_284m_pair_coverage_deduplicated.csv", "manifest.json",
            "deduplicated_manifest.json", "compute_284m_model_pair_coverage.py",
            "compute_284m_deduplicated_pair_coverage.py",
        ):
            external = [value for name, value in captured.items() if name.endswith("/d17-finite-model-284m-pair-coverage-20260818/" + base_name)]
            ensure(len(external) == 1, f"Stage70 external {base_name} missing")
            ensure(archive.read(base_name) == external[0], f"Stage70 zip/external {base_name} drift")
    return {"members": len(expected_names), "external_members_byte_identical": 7}


def audit_law_counts(payload: bytes, scores) -> dict:
    ensure(sha256_bytes(payload) == "6c1c787de5d951db7d5ae76821da4382fbf8d0541e9c4b23128c9e7cab9f7c78", "law-count CSV SHA drift")
    reader = _csv_reader(payload, "Stage70 law-count CSV")
    ensure(
        reader.fieldnames
        == ["model_index", "order", "model_sha256", "satisfied_count", "refuted_count", "assignments_checked"],
        "law-count CSV header drift",
    )
    by_index = {score.individual.model_index: score.individual for score in scores}
    assignments = 0
    rows = 0
    for rows, row in enumerate(reader, start=1):
        model_index = int(row["model_index"])
        ensure(model_index == rows - 1, "law-count model index drift")
        score = by_index[model_index]
        ensure(int(row["order"]) == score.order, "law-count order drift")
        ensure(row["model_sha256"] == score.model_sha256, "law-count model SHA drift")
        ensure(int(row["satisfied_count"]) == score.satisfied_count, "law-count satisfied drift")
        ensure(int(row["refuted_count"]) == score.refuted_count, "law-count refuted drift")
        assignments += int(row["assignments_checked"])
    ensure(rows == MODEL_COUNT, f"law-count row count is {rows}")
    ensure(assignments == 11_673_374_836, "law-count assignment total drift")
    return {
        "rows": rows,
        "assignments_checked_sum": assignments,
        "satisfied_and_refuted_counts_match": True,
    }


def build_stage70(root: Path, candidates: list[Table]) -> tuple[list[Table], dict]:
    stage_dir = root / "reproduction" / STAGE70
    archive = stage_dir / "raw/d17-284m-coverage-snapshot.tar.gz"
    verify_raw_archive(STAGE70, archive)
    captured: dict[str, bytes] = {}
    for name, member, handle in iter_archive_members(archive):
        ensure(member.size <= 2 * 1024 * 1024, f"unexpectedly large Stage70 member: {name}")
        captured[name] = read_bounded(handle, member.size, limit=2 * 1024 * 1024)
    ensure(len(captured) == 13, f"Stage70 raw member count is {len(captured)}")

    def one(suffix: str) -> tuple[str, bytes]:
        matches = [(name, payload) for name, payload in captured.items() if name.endswith(suffix)]
        ensure(len(matches) == 1, f"expected one Stage70 member ending {suffix}")
        return matches[0]

    individual_name, individual_payload = one("/model_284m_pair_coverage.csv")
    deduplicated_name, deduplicated_payload = one("/model_284m_pair_coverage_deduplicated.csv")
    _law_name, law_payload = one("/model_order5_law_counts.csv")
    result = derive_positive_marginal_core(
        io.StringIO(individual_payload.decode("utf-8")),
        io.StringIO(deduplicated_payload.decode("utf-8")),
        (table.record() for table in candidates),
    )
    ensure(result.summary.candidate_count == MODEL_COUNT, "Stage70 candidate count drift")
    law_audit = audit_law_counts(law_payload, result.scores)
    zip_audit = verify_coverage_share_zip(captured)

    by_id = {table.table_id: table for table in candidates}
    core = [by_id[str(record["table_id"])] for record in result.core_records]
    bank, details = write_table_outputs(stage_dir, core)
    ensure(len(core) == POSITIVE_MARGINAL_COUNT, "Stage70 core count drift")

    coverage_path = stage_dir / "normalized/coverage-scores.csv.gz"
    with deterministic_gzip_writer(coverage_path) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="", write_through=True)
        writer = csv.DictWriter(text, fieldnames=list(NORMALIZED_COVERAGE_HEADER), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result.normalized_coverage_rows())
        text.flush()

    decisions = [*result.positive_decisions, *result.removal_metadata]
    decisions.sort(key=lambda row: row.coverage_rank)
    write_jsonl_gz(
        stage_dir / "normalized/selection-decisions.jsonl.gz",
        (row.as_dict() for row in decisions),
    )
    raw_evidence = f"reproduction/{STAGE70}/raw/{archive.name}#{deduplicated_name}"
    delta = []
    for decision in decisions:
        table = by_id[decision.canonical_table_id]
        delta.append(
            delta_record(
                STAGE70,
                len(delta),
                decision.action,
                table,
                decision.reason_code,
                raw_evidence,
                notes=(
                    f"coverage rank {decision.coverage_rank}; model_index {decision.model_index}; "
                    f"individual {decision.remaining_pair_coverage_count}; marginal "
                    f"{decision.new_unique_remaining_pair_count}; cumulative "
                    f"{decision.cumulative_unique_remaining_pair_count}"
                ),
                source_stage=STAGE50,
            )
        )
    write_jsonl_gz(stage_dir / "delta.jsonl.gz", delta)

    submitted = root / "reproduction/00-submission-anchor/raw/2026-08-31_marathon_openai-gpt-oss-120b_solver.py"
    submitted_source = read_bounded_file(submitted)
    ensure(
        sha256_bytes(submitted_source) == SUBMITTED_MARATHON_SHA256,
        "submitted Marathon solver SHA-256 drift",
    )
    submitted_payload = extract_embedded_false_solver_table_payload(
        submitted_source,
        context=str(submitted),
    )
    ensure(submitted_payload.model_count == 1_487, "submitted embedded model count drift")
    ensure(tuple(table.raw for table in core) == submitted_payload.records[:1_470], "Stage70 core differs from submitted payload prefix")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE70,
        "metrics": {
            "coverage.zero_marginal": result.summary.zero_marginal_count,
            "core.1470": result.summary.positive_marginal_count,
        },
        "action_counts": {
            "remove": result.summary.zero_marginal_count,
            "retain": result.summary.positive_marginal_count,
        },
        "bank": details,
        "coverage": {
            "candidate_count": result.summary.candidate_count,
            "individual_positive_count": 2_303,
            "individual_zero_count": 1_232,
            "individual_sum_with_overlap": 48_939_148,
            "positive_marginal_count": result.summary.positive_marginal_count,
            "zero_marginal_count": result.summary.zero_marginal_count,
            "final_unique_union": result.summary.final_union_count,
            "remaining_uncovered": result.summary.remaining_uncovered_count,
            "selection_order": "descending individual residual coverage, then ascending historical model_index; no adaptive reranking",
        },
        "law_count_audit": law_audit,
        "share_zip_audit": zip_audit,
        "submitted_payload_anchor": {
            "submission_path": str(submitted.relative_to(root)),
            "submission_sha256": SUBMITTED_MARATHON_SHA256,
            "embedded_table_count": submitted_payload.model_count,
            "core_prefix_count": 1_470,
            "core_prefix_exact_record_order_match": True,
        },
        "raw_members": {
            "individual_coverage": individual_name,
            "deduplicated_coverage": deduplicated_name,
        },
        "known_gaps": [
            "The exact historical d17_fix solver file named by the coverage manifests is no longer available at its recorded SHA-256.",
            "Its 3,535-table payload is nevertheless bound independently: every coverage model digest maps exactly to the Stage50 published d17 bank, and the selected 1,470-record order matches the submitted solver prefix.",
            "Normal verification checks the frozen coverage outputs structurally; replaying the historical C evaluator is optional and requires a compiler plus the large residual bitset.",
        ],
    }
    ensure(summary["coverage"]["final_unique_union"] == FINAL_UNION_COUNT, "Stage70 union drift")
    ensure(summary["coverage"]["remaining_uncovered"] == FINAL_REMAINING_COUNT, "Stage70 remaining drift")
    ensure(FINAL_UNION_COUNT + FINAL_REMAINING_COUNT == REMAINING_PAIR_UNIVERSE, "Stage70 universe identity drift")
    write_json(stage_dir / "summary.json", summary)
    return core, summary


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
    with atomic_text_writer(stage_dir / "SHA256SUMS") as handle:
        for artifact in sorted(artifacts, key=lambda value: value["path"]):
            handle.write(f"{artifact['sha256']}  {artifact['path']}\n")
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
                "Run python3 tools/rebuild_phase2.py first to regenerate Phase 2 normalized outputs from committed snapshots.",
                "Large bitsets are processed as bounded forward-only streams.",
            ],
        },
        "notes": notes,
    }
    write_json(stage_dir / "stage.json", manifest)


def finalize_phase2(root: Path, summaries: dict[str, dict]) -> None:
    s50_local = "stage50-local-snapshot"
    s50_prior = "stage50-prior-bank"
    s60_local = "stage60-local-snapshot"
    s60_eq = "stage60-equation-index"
    s60_code = "stage60-seedfree-tooling"
    s70_local = "stage70-local-snapshot"
    s70_candidate = "stage70-candidate-bank"
    s70_residual = "stage70-residual-bitset"
    s70_submission = "stage70-submission-anchor"

    finalize_stage(
        root,
        stage_id=STAGE50,
        title="Generator and Fin4 pruning: 10,059 - 241 - 6,283 = 3,535",
        pipeline_order=50,
        depends_on=[STAGE40],
        claims=[
            "delivery.order4", "delivery.candidate_retained", "prune.scalar_affine",
            "prune.order_le_4", "candidate.3535",
        ],
        sources=[
            source_record(s50_prior, "generated", f"reproduction/{STAGE40}/normalized/tables.bin", upstream=True),
            source_record(s50_local, "local-filesystem-snapshot", "math-distill-equational-stage2: d15/d17 table payloads, direct-affine audit, and d17 change report"),
        ],
        artifact_specs=[
            dict(relative="raw/d15-d17-prune-snapshot.tar.gz", role="raw-snapshot", media_type="application/gzip", source_ids=[s50_local], record_count=5, attributes={"archive_format": "deterministic-tar-gzip-v1", "uncompressed_source_bytes": 758714}),
            dict(relative="summary.json", role="stage-summary", media_type="application/json", source_ids=[s50_prior, s50_local]),
            dict(relative="normalized/tables.jsonl.gz", role="table-index", media_type="application/x-ndjson+gzip", source_ids=[s50_prior, s50_local], record_count=3535),
            dict(relative="normalized/tables.bin", role="table-binary", media_type="application/octet-stream", source_ids=[s50_prior, s50_local], record_count=3535, attributes={"encoding": TABLE_ENCODING, **summaries[STAGE50]["bank"]}),
            dict(relative="normalized/table-id-map.csv.gz", role="identity-map", media_type="text/csv+gzip", source_ids=[s50_prior, s50_local], record_count=3535),
            dict(relative="delta.jsonl.gz", role="membership-delta", media_type="application/x-ndjson+gzip", source_ids=[s50_prior, s50_local], record_count=6524),
            dict(relative="verification/scalar-affine-witnesses.jsonl.gz", role="affine-classification", media_type="application/x-ndjson+gzip", source_ids=[s50_local], record_count=241),
            dict(relative="verification/delivery-102-retention.json", role="delivery-audit", media_type="application/json", source_ids=[s50_prior, s50_local]),
        ],
        notes=[
            "The 227 direct affine rows are cross-checked against the historical audit; fourteen further exact tables have explicit carrier-relabeling witnesses.",
            "Both filters are stable: retained tables preserve their d15/Stage40 order, and the result matches the published d17 payload byte for byte.",
        ],
    )

    finalize_stage(
        root,
        stage_id=STAGE60,
        title="Fin4 residual pair universe: 324,157,667 - 40,006,076 = 284,151,591",
        pipeline_order=60,
        depends_on=["10-primary-9450"],
        claims=["pairs.target", "pairs.fin4_covered", "pairs.residual"],
        sources=[
            source_record(s60_eq, "repository-snapshot", "reproduction/10-primary-9450/raw/primary-recovery-snapshot.tar.gz#members/wubing/data/324M_remaining_pairs/order5_equations.csv", upstream=True),
            source_record(s60_local, "local-filesystem-snapshot", "math-distill-equational-stage2: stable 324M/284M packages plus scalar and bit-sliced Fin4 shard records"),
            {
                "source_id": s60_code,
                "kind": "generated",
                "locator": "repository-authored deterministic Stage60 seed-free tooling",
                "captured_at": CAPTURED_AT,
                "license_status": LICENSE_STATUS,
                "notes": [
                    "The tooling reconstructs byte-exact Stage60 support/upstream files from the committed snapshot and runs a new result-level method without the historical seed chain."
                ],
            },
        ],
        artifact_specs=[
            dict(relative="raw/fin4-residual-snapshot.tar.gz", role="raw-snapshot", media_type="application/gzip", source_ids=[s60_local], record_count=285, attributes={"archive_format": "deterministic-tar-gzip-v1", "uncompressed_source_bytes": 996151568}),
            dict(relative="summary.json", role="stage-summary", media_type="application/json", source_ids=[s60_eq, s60_local, s60_code]),
            dict(relative="normalized/324M_remaining_pairs.bitset.gz", role="pair-bitset", media_type="application/gzip", source_ids=[s60_local], attributes={"encoding": "o5rpair1-gzip-v1", "uncompressed_bytes": BITSET_BYTES, "uncompressed_sha256": BITSET324_SHA256, "set_bits": 324157667}),
            dict(relative="normalized/284M_remaining_pairs.bitset.gz", role="pair-bitset", media_type="application/gzip", source_ids=[s60_local], attributes={"encoding": "o5rpair1-gzip-v1", "uncompressed_bytes": BITSET_BYTES, "uncompressed_sha256": BITSET284_SHA256, "set_bits": 284151591}),
            dict(relative="normalized/pair-partition-by-source.csv.gz", role="pair-partition", media_type="text/csv+gzip", source_ids=[s60_eq, s60_local], record_count=62576),
            dict(relative="normalized/fin4-shards.csv.gz", role="fin4-shard-index", media_type="text/csv+gzip", source_ids=[s60_local], record_count=256),
            dict(relative="scripts/reconstruct_inputs.py", role="reconstruction-script", media_type="text/x-python", source_ids=[s60_code]),
            dict(relative="scripts/run_seedfree.py", role="runner-script", media_type="text/x-python", source_ids=[s60_code]),
            dict(relative="scripts/smoke_test_engines.py", role="engine-smoke-test", media_type="text/x-python", source_ids=[s60_code]),
            dict(relative="scripts/capture_seedfree_evidence.py", role="evidence-capture-script", media_type="text/x-python", source_ids=[s60_code]),
            dict(relative="verification/seedfree-input-reconstruction.json", role="input-reconstruction-audit", media_type="application/json", source_ids=[s60_eq, s60_local, s60_code]),
            dict(relative="verification/seedfree-full-run.json", role="full-run-evidence", media_type="application/json", source_ids=[s60_eq, s60_local, s60_code], record_count=256),
            dict(relative="verification/seedfree-full-run-logs.jsonl.gz", role="full-run-logs", media_type="application/x-ndjson+gzip", source_ids=[s60_eq, s60_local, s60_code], record_count=summaries[STAGE60]["seedfree_outcome_rerun"]["full_run_validation"]["sanitized_log_rows"]),
        ],
        notes=[
            "324,157,667 is the targeted universe after Fin2/3 coverage and singleton-true exclusions, not the full 3,915,693,200 directed nonreflexive universe.",
            "The normalized gzip mirrors make exact standard-library verification portable; their decompressed bytes equal the captured bitsets.",
            "Five standalone-missing Stage60 support/upstream files are now reconstructed byte-for-byte; only equations.bin and the mirror map are consumed by the new runner, while the singleton masks belong to upstream 324M construction.",
            "The guarded seed-free all-bitslice runner is a new result-level method. Its complete 256-shard 2^32 run finished without retries and reproduced the committed 284,151,591-pair residual byte for byte.",
            "The committed full-run report and sanitized logs bind all shard summaries, input and implementation hashes, resource measurements, and streamed bitset validation without claiming historical seeded-order replay.",
        ],
    )

    finalize_stage(
        root,
        stage_id=STAGE70,
        title="Positive-marginal core: 3,535 - 2,065 = 1,470",
        pipeline_order=70,
        depends_on=[STAGE00, STAGE50, STAGE60],
        claims=["coverage.zero_marginal", "core.1470"],
        sources=[
            source_record(s70_candidate, "generated", f"reproduction/{STAGE50}/normalized/tables.jsonl.gz", upstream=True),
            source_record(s70_residual, "generated", f"reproduction/{STAGE60}/normalized/284M_remaining_pairs.bitset.gz", upstream=True),
            source_record(s70_submission, "authenticated-web-download", "reproduction/00-submission-anchor/raw/2026-08-31_marathon_openai-gpt-oss-120b_solver.py", upstream=True),
            source_record(s70_local, "local-filesystem-snapshot", "math-distill-equational-stage2: d17 law counts and 284M individual/deduplicated coverage run"),
        ],
        artifact_specs=[
            dict(relative="raw/d17-284m-coverage-snapshot.tar.gz", role="raw-snapshot", media_type="application/gzip", source_ids=[s70_local], record_count=13, attributes={"archive_format": "deterministic-tar-gzip-v1", "uncompressed_source_bytes": 1858479}),
            dict(relative="summary.json", role="stage-summary", media_type="application/json", source_ids=[s70_candidate, s70_residual, s70_submission, s70_local]),
            dict(relative="normalized/tables.jsonl.gz", role="table-index", media_type="application/x-ndjson+gzip", source_ids=[s70_candidate, s70_local], record_count=1470),
            dict(relative="normalized/tables.bin", role="table-binary", media_type="application/octet-stream", source_ids=[s70_candidate, s70_local], record_count=1470, attributes={"encoding": TABLE_ENCODING, **summaries[STAGE70]["bank"]}),
            dict(relative="normalized/table-id-map.csv.gz", role="identity-map", media_type="text/csv+gzip", source_ids=[s70_candidate, s70_local], record_count=1470),
            dict(relative="normalized/coverage-scores.csv.gz", role="coverage-score-index", media_type="text/csv+gzip", source_ids=[s70_candidate, s70_residual, s70_local], record_count=3535),
            dict(relative="normalized/selection-decisions.jsonl.gz", role="selection-index", media_type="application/x-ndjson+gzip", source_ids=[s70_candidate, s70_residual, s70_local], record_count=3535),
            dict(relative="delta.jsonl.gz", role="membership-delta", media_type="application/x-ndjson+gzip", source_ids=[s70_candidate, s70_residual, s70_local], record_count=3535),
        ],
        notes=[
            "The historical order is frozen individual-coverage ranking, not adaptive greedy reranking.",
            "Every historical compact-JSON model digest maps to exactly one Stage50 canonical table, and every keep/drop decision is explicit.",
            "The 1,470 retained records match the submitted solver's first 1,470 embedded records in exact order.",
        ],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    bank10059 = load_stage_tables(root, STAGE40)
    candidates, stage50 = build_stage50(root, bank10059)
    print(f"{STAGE50}: {stage50['bank']['table_count']} tables")
    stage60 = build_stage60(root)
    print(f"{STAGE60}: {stage60['metrics']['pairs.residual']} residual pairs")
    _core, stage70 = build_stage70(root, candidates)
    print(f"{STAGE70}: {stage70['bank']['table_count']} tables")
    finalize_phase2(root, {STAGE50: stage50, STAGE60: stage60, STAGE70: stage70})
    print("Phase 2 manifests and checksums regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
