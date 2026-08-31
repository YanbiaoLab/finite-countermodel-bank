from __future__ import annotations

import csv
import gzip
import hashlib
import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tools.verify_repository import (
    VerificationError,
    advance_coverage_union,
    canonical_table_bytes,
    canonical_table_id,
    count_csv_rows,
    historical_table_id,
    resolve_stage_directories,
    validate_delta_record,
    validate_stage_manifest_structure,
    validate_submission_record,
    validate_table_record,
    verify_identity_map,
    verify_repository,
    verify_claims,
    verify_stage,
    verify_stage70_semantics,
    verify_stage90_transition,
    verify_stage100_transition,
    verify_stage_transitions,
)


ROOT = Path(__file__).resolve().parents[1]


class CanonicalTableTests(unittest.TestCase):
    def test_coverage_overlap_cannot_exceed_prior_union(self) -> None:
        with self.assertRaises(VerificationError):
            advance_coverage_union(0, 1, 0, 1, 10, "fixture")

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
        stage_count, artifact_count = verify_repository(
            ROOT,
            [
                "00-submission-anchor",
                "10-primary-9450",
                "20-registered-9852",
                "30-early-deltas-9957",
                "40-delivery-10059",
            ],
        )
        self.assertEqual(stage_count, 5)
        self.assertEqual(artifact_count, 37)

    def test_full_repository_contract(self) -> None:
        stage_count, artifact_count = verify_repository(ROOT)
        self.assertEqual(stage_count, 12)
        self.assertEqual(artifact_count, 106)

    def test_stage_selection_includes_transitive_dependencies(self) -> None:
        stage_dirs = resolve_stage_directories(
            ROOT / "reproduction", ["70-positive-marginal-core-1470"]
        )
        self.assertEqual(
            [path.name for path in stage_dirs],
            [
                "00-submission-anchor",
                "10-primary-9450",
                "20-registered-9852",
                "30-early-deltas-9957",
                "40-delivery-10059",
                "50-generator-prune-3535",
                "60-fin4-residual-284151591",
                "70-positive-marginal-core-1470",
            ],
        )

    def test_stage81_selection_includes_stage80_and_all_dependencies(self) -> None:
        stage_dirs = resolve_stage_directories(
            ROOT / "reproduction", ["81-finite149-portable-verification"]
        )
        self.assertEqual(
            [path.name for path in stage_dirs],
            [
                "00-submission-anchor",
                "10-primary-9450",
                "20-registered-9852",
                "30-early-deltas-9957",
                "40-delivery-10059",
                "50-generator-prune-3535",
                "60-fin4-residual-284151591",
                "70-positive-marginal-core-1470",
                "80-finite149",
                "81-finite149-portable-verification",
            ],
        )

    def test_stage100_selection_includes_all_transitive_dependencies(self) -> None:
        stage_dirs = resolve_stage_directories(
            ROOT / "reproduction", ["100-opposite-closure-2901"]
        )
        self.assertEqual(
            [path.name for path in stage_dirs],
            [
                "00-submission-anchor",
                "10-primary-9450",
                "20-registered-9852",
                "30-early-deltas-9957",
                "40-delivery-10059",
                "50-generator-prune-3535",
                "60-fin4-residual-284151591",
                "70-positive-marginal-core-1470",
                "80-finite149",
                "81-finite149-portable-verification",
                "90-payload-1487",
                "100-opposite-closure-2901",
            ],
        )

    def test_stage100_rejects_a_tampered_closure_audit(self) -> None:
        source = ROOT / "reproduction/100-opposite-closure-2901"
        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary_root = Path(temporary_dir)
            reproduction = temporary_root / "reproduction"
            stage_dir = reproduction / source.name
            shutil.copytree(source, stage_dir)
            required_target = (
                reproduction
                / "80-finite149/normalized/required-transposes.bin"
            )
            required_target.parent.mkdir(parents=True)
            shutil.copy2(
                ROOT
                / "reproduction/80-finite149/normalized/required-transposes.bin",
                required_target,
            )
            for historical_stage, relative in (
                ("10-primary-9450", "normalized/tables.jsonl.gz"),
                ("20-registered-9852", "normalized/tables.jsonl.gz"),
                ("30-early-deltas-9957", "normalized/tables.jsonl.gz"),
                ("40-delivery-10059", "normalized/tables.jsonl.gz"),
                ("50-generator-prune-3535", "normalized/tables.jsonl.gz"),
                ("70-positive-marginal-core-1470", "normalized/tables.jsonl.gz"),
                ("80-finite149", "normalized/required-transposes.jsonl.gz"),
            ):
                historical_target = (
                    reproduction / historical_stage / relative
                )
                historical_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(
                    ROOT / "reproduction" / historical_stage / relative,
                    historical_target,
                )
            solver_target = (
                reproduction
                / "00-submission-anchor/raw/"
                "2026-08-31_marathon_openai-gpt-oss-120b_solver.py"
            )
            solver_target.parent.mkdir(parents=True)
            shutil.copy2(
                ROOT
                / "reproduction/00-submission-anchor/raw/"
                "2026-08-31_marathon_openai-gpt-oss-120b_solver.py",
                solver_target,
            )
            audit_path = stage_dir / "verification/opposite-closure-audit.json"
            body = audit_path.read_bytes()
            self.assertIn(b'"derived": 1414', body)
            tampered = body.replace(
                b'"derived": 1414',
                b'"derived": 1415',
                1,
            )
            audit_path.write_bytes(tampered)
            new_sha256 = hashlib.sha256(tampered).hexdigest()
            manifest_path = stage_dir / "stage.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact = next(
                row
                for row in manifest["artifacts"]
                if row["path"] == "verification/opposite-closure-audit.json"
            )
            old_sha256 = artifact["sha256"]
            artifact["sha256"] = new_sha256
            artifact["bytes"] = len(tampered)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            checksums_path = stage_dir / "SHA256SUMS"
            checksums = checksums_path.read_text(encoding="ascii")
            checksums_path.write_text(
                checksums.replace(old_sha256, new_sha256, 1), encoding="ascii"
            )
            with self.assertRaisesRegex(
                VerificationError,
                "Stage100 opposite-closure audit drift",
            ):
                verify_stage(stage_dir, verify_claims(ROOT))

    def test_pr4_transitions_reject_trailing_delta_rows_cleanly(self) -> None:
        claims = verify_claims(ROOT)
        stage70 = verify_stage(
            ROOT / "reproduction/70-positive-marginal-core-1470", claims
        )[3]
        stage90 = verify_stage(ROOT / "reproduction/90-payload-1487", claims)[3]
        stage100 = verify_stage(
            ROOT / "reproduction/100-opposite-closure-2901", claims
        )[3]

        trailing90 = deepcopy(stage90)
        row90 = deepcopy(trailing90["delta"]["rows"][-1])
        row90["sequence"] = 1_487
        trailing90["delta"]["rows"].append(row90)
        with self.assertRaisesRegex(
            VerificationError, "Stage90 delta cardinality drift"
        ):
            verify_stage90_transition(trailing90, stage70)

        trailing100 = deepcopy(stage100)
        row100 = deepcopy(trailing100["delta"]["rows"][-1])
        row100["sequence"] = 2_901
        trailing100["delta"]["rows"].append(row100)
        with self.assertRaisesRegex(
            VerificationError, "Stage100 delta cardinality drift"
        ):
            verify_stage100_transition(trailing100, stage90)

    def test_stage70_rejects_a_false_submission_prefix_summary(self) -> None:
        stage_dir = ROOT / "reproduction/70-positive-marginal-core-1470"
        _artifact_count, _submission_count, _claims, result = verify_stage(
            stage_dir, verify_claims(ROOT)
        )
        summary = deepcopy(result["summary"])
        summary["submitted_payload_anchor"][
            "core_prefix_exact_record_order_match"
        ] = False
        with self.assertRaises(VerificationError):
            verify_stage70_semantics(
                stage_dir,
                result["manifest"]["artifacts"],
                result["bank"],
                result["delta"],
                summary,
            )
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

    def test_table_stage_allows_two_dependencies_with_one_bank_provider(self) -> None:
        table_id = "sha256:" + "1" * 64

        def bank(first_seen: str) -> dict[str, object]:
            return {
                "id_set": {table_id},
                "first_seen": {table_id: first_seen},
                "provenance_source_ids": set(),
            }

        results = {
            "10-bank": {
                "manifest": {
                    "sources": [{"source_id": "bank-source"}],
                    "pipeline_order": 10,
                    "depends_on": [],
                },
                "bank": bank("10-bank"),
                "delta": {
                    "rows": [{"table_id": table_id, "action": "add"}]
                },
            },
            "20-evidence": {
                "manifest": {
                    "sources": [{"source_id": "evidence-source"}],
                    "pipeline_order": 20,
                    "depends_on": [],
                },
                "bank": None,
                "delta": None,
            },
            "30-combined": {
                "manifest": {
                    "sources": [{"source_id": "combined-source"}],
                    "pipeline_order": 30,
                    "depends_on": ["10-bank", "20-evidence"],
                },
                "bank": bank("10-bank"),
                "delta": {
                    "rows": [{"table_id": table_id, "action": "retain"}]
                },
            },
        }
        verify_stage_transitions(results)

    def test_csv_record_count_excludes_header_for_gzip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "rows.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(["id", "value"])
                writer.writerow(["1", "a"])
                writer.writerow(["2", "b"])
            self.assertEqual(count_csv_rows(path), 2)

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
