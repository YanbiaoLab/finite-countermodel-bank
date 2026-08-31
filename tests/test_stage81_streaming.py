from __future__ import annotations

import gzip
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "reproduction/81-finite149-portable-verification/scripts/rebuild.py"
)
SPEC = importlib.util.spec_from_file_location("stage81_rebuild", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
stage81 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage81)


def compressed_fixture(*, trailing: bytes = b"") -> bytes:
    payload = {
        "equations": ["Equation1", "Equation2"],
        "outcomes": [
            ["unknown", "explicit_proof_false"],
            ["implicit_proof_true", "explicit_proof_true"],
        ],
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8") + trailing
    return gzip.compress(body, mtime=0)


class Stage81StreamingTests(unittest.TestCase):
    def test_streams_full_matrix_and_retains_only_selected_cells(self) -> None:
        equations, projection, report = stage81.stream_finite_outcomes(
            compressed_fixture(),
            {0: {1}, 1: {0}},
            expected_equation_count=2,
            chunk_bytes=8,
            buffer_limit_bytes=128,
        )
        self.assertEqual(equations, ["Equation1", "Equation2"])
        self.assertEqual(
            projection,
            {(0, 1): "explicit_proof_false", (1, 0): "implicit_proof_true"},
        )
        self.assertEqual(report["matrix_cells_scanned"], 4)
        self.assertTrue(report["full_json_syntax_scanned_to_eof"])
        self.assertFalse(report["matrix_materialized"])
        self.assertLessEqual(
            report["max_buffer_bytes_observed"], report["buffer_limit_bytes"]
        )

    def test_rejects_trailing_top_level_bytes(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "trailing bytes"):
            stage81.stream_finite_outcomes(
                compressed_fixture(trailing=b"x"),
                {0: {0}},
                expected_equation_count=2,
                chunk_bytes=16,
                buffer_limit_bytes=128,
            )

    def test_enforces_a_bounded_value_buffer(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "buffer limit"):
            stage81.stream_finite_outcomes(
                compressed_fixture(),
                {0: {0}},
                expected_equation_count=2,
                chunk_bytes=16,
                buffer_limit_bytes=32,
            )

    def test_target_coordinates_are_one_based_and_unique(self) -> None:
        labels = [{"lhs_id": "1", "rhs_id": "2"}]
        by_row, coordinates = stage81.target_coordinates(labels, 2)
        self.assertEqual(by_row, {0: {1}})
        self.assertEqual(coordinates, {(0, 1)})
        with self.assertRaisesRegex(RuntimeError, "outside"):
            stage81.target_coordinates([{"lhs_id": "0", "rhs_id": "1"}], 2)
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            stage81.target_coordinates(labels * 2, 2)

    def test_parses_only_the_generated_lean_table_comment(self) -> None:
        source = b"""
/-!
This file is generated from the following operator table:
[[0,1],[1,0]]
-/
def ignored := \"[[1,1],[1,1]]\"
"""
        self.assertEqual(stage81.parse_lean_operator_table(source), [[0, 1], [1, 0]])


if __name__ == "__main__":
    unittest.main()
