from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path

from tools.verify_repository import (
    VerificationError,
    canonical_table_bytes,
    canonical_table_id,
    validate_stage_manifest_structure,
    validate_submission_record,
    verify_repository,
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


class RepositoryFixtureTests(unittest.TestCase):
    def test_committed_repository_contract(self) -> None:
        stage_count, artifact_count = verify_repository(
            ROOT, ["00-submission-anchor"]
        )
        self.assertEqual(stage_count, 1)
        self.assertEqual(artifact_count, 5)

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


if __name__ == "__main__":
    unittest.main()
