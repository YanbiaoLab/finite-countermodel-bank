from __future__ import annotations

import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tools.verify_repository import (
    VerificationError,
    canonical_table_bytes,
    canonical_table_id,
    historical_table_id,
    validate_delta_record,
    validate_stage_manifest_structure,
    validate_submission_record,
    validate_table_record,
    verify_identity_map,
    verify_repository,
    verify_stage_transitions,
)


ROOT = Path(__file__).resolve().parents[1]


class CanonicalTableTests(unittest.TestCase):
    def test_table_id_includes_order_and_row_major_entries(self) -> None:
        encoded = bytes([2, 0, 1, 1, 0])
        self.assertEqual(canonical_table_bytes(2, [0, 1, 1, 0]), encoded)
        self.assertEqual(
            canonical_table_id(2, [0, 1, 1, 0]),
            "sha256:" + hashlib.sha256(encoded).hexdigest(),
        )

    def test_table_shape_and_range_are_checked(self) -> None:
        with self.assertRaises(VerificationError):
            canonical_table_bytes(2, [0, 1, 0])
        with self.assertRaises(VerificationError):
            canonical_table_bytes(2, [0, 1, 1, 2])
        with self.assertRaises(VerificationError):
            canonical_table_bytes(True, [0])
        with self.assertRaises(VerificationError):
            canonical_table_bytes(1, [False])

    def test_historical_json_hash_is_an_alias_not_the_canonical_id(self) -> None:
        entries = [0, 1, 1, 0]
        self.assertNotEqual(canonical_table_id(2, entries), historical_table_id(2, entries))

    def test_table_record_checks_both_identifiers(self) -> None:
        entries = [0, 1, 1, 0]
        record = {
            "schema_version": "1.0.0",
            "table_id": canonical_table_id(2, entries),
            "identifiers": [
                {
                    "scheme": "sha256-compact-json-table-v1",
                    "value": historical_table_id(2, entries),
                }
            ],
            "encoding": "uint8-order-row-major-v1",
            "order": 2,
            "entries": entries,
            "first_seen_stage": "10-primary-9450",
            "record_kind": "exact-explicit",
            "provenance": [{"source_id": "fixture", "source_path": "fixture.py"}],
        }
        self.assertEqual(validate_table_record(record, "fixture"), bytes([2, *entries]))
        record["identifiers"][0]["value"] = "sha256:" + "0" * 64
        with self.assertRaises(VerificationError):
            validate_table_record(record, "fixture")


class RepositoryFixtureTests(unittest.TestCase):
    def test_committed_repository_contract(self) -> None:
        stage_count, artifact_count = verify_repository(
            ROOT, ["00-submission-anchor"]
        )
        self.assertEqual(stage_count, 1)
        self.assertEqual(artifact_count, 5)

    def test_full_pr1_repository_contract(self) -> None:
        stage_count, artifact_count = verify_repository(ROOT)
        self.assertEqual(stage_count, 5)
        self.assertEqual(artifact_count, 37)

    def test_submission_schema_rejects_an_invalid_track(self) -> None:
        index_path = ROOT / "reproduction/00-submission-anchor/submissions.jsonl"
        record = json.loads(index_path.read_text(encoding="utf-8").splitlines()[0])
        record["track"] = "invalid"
        with self.assertRaises(VerificationError):
            validate_submission_record(record, "test submission")

    def test_stage_schema_requires_source_rights_status(self) -> None:
        manifest_path = ROOT / "reproduction/00-submission-anchor/stage.json"
        manifest = deepcopy(json.loads(manifest_path.read_text(encoding="utf-8")))
        del manifest["sources"][0]["license_status"]
        with self.assertRaises(VerificationError):
            validate_stage_manifest_structure(manifest, "test manifest")

    def test_delta_schema_rejects_a_partial_source_reference(self) -> None:
        record = {
            "schema_version": "1.0.0",
            "stage_id": "30-early-deltas-9957",
            "sequence": 0,
            "action": "duplicate",
            "table_id": "sha256:" + "0" * 64,
            "source_stage_id": "20-registered-9852",
            "reason_code": "fixture",
            "evidence_paths": ["fixture"],
        }
        with self.assertRaises(VerificationError):
            validate_delta_record(record, "fixture")

    def test_full_transition_check_rejects_a_missing_dependency(self) -> None:
        results = {
            "20-fixture": {
                "manifest": {
                    "sources": [{"source_id": "fixture-source"}],
                    "pipeline_order": 20,
                    "depends_on": ["10-missing"],
                },
                "bank": None,
                "delta": None,
            }
        }
        with self.assertRaises(VerificationError):
            verify_stage_transitions(results)
        verify_stage_transitions(results, allow_missing_dependencies=True)

    def test_identity_map_rejects_wrong_first_seen_stage(self) -> None:
        entries = [0, 1, 1, 0]
        table_id = canonical_table_id(2, entries)
        historical_id = historical_table_id(2, entries)
        bank = {
            "ids": [table_id],
            "historical_ids": [historical_id],
            "first_seen": {table_id: "10-primary-9450"},
            "count": 1,
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            stage_dir = Path(temporary_dir)
            path = stage_dir / "identity.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(
                    [
                        "position",
                        "table_id",
                        "historical_json_table_id",
                        "first_seen_stage",
                    ]
                )
                writer.writerow([0, table_id, historical_id, "20-registered-9852"])
            with self.assertRaises(VerificationError):
                verify_identity_map(
                    stage_dir,
                    {"path": path.name, "record_count": 1},
                    bank,
                )


if __name__ == "__main__":
    unittest.main()
