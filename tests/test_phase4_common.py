from __future__ import annotations

import base64
from collections import Counter
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import phase4_common
from tools.phase4_common import (
    DERIVED_CANONICAL_ID_VECTOR_SHA256,
    DERIVED_RAW_BYTES,
    DERIVED_RAW_SHA256,
    DERIVED_TRANSPOSE_COUNT,
    EMBEDDED_B85_BYTES,
    EMBEDDED_B85_SHA256,
    EMBEDDED_CANONICAL_ID_VECTOR_SHA256,
    EMBEDDED_COUNT,
    EMBEDDED_RAW_BYTES,
    EMBEDDED_RAW_SHA256,
    EMBEDDED_XZ_BYTES,
    EMBEDDED_XZ_SHA256,
    FALSE_ENGINE_FUNCTION_SHA256,
    FALSE_ENGINE_SHA256,
    RUNTIME_CANONICAL_ID_VECTOR_SHA256,
    RUNTIME_COUNT,
    RUNTIME_RAW_BYTES,
    RUNTIME_RAW_SHA256,
    Phase4Error,
    audit_false_engine_functions,
    canonical_id_vector_sha256,
    decode_false_engine_source,
    parse_exact_records,
    replay_runtime_closure,
    transpose_record,
)


ROOT = Path(__file__).resolve().parents[1]
STAGE90 = ROOT / "reproduction/90-payload-1487"
STAGE100 = ROOT / "reproduction/100-opposite-closure-2901"
SUBMISSION = (
    ROOT
    / "reproduction/00-submission-anchor/raw/"
    "2026-09-01_marathon_openai-gpt-oss-120b_solver.py"
)


def record(order: int, entries: list[int]) -> bytes:
    return bytes([order, *entries])


class TransposeTests(unittest.TestCase):
    def test_transpose_is_an_involution(self) -> None:
        fixtures = (
            record(1, [0]),
            record(2, [0, 1, 0, 0]),
            record(3, [0, 1, 2, 2, 0, 1, 1, 2, 0]),
        )
        for original in fixtures:
            with self.subTest(
                order=original[0], digest=hashlib.sha256(original).hexdigest()
            ):
                transposed = transpose_record(original)
                self.assertEqual(transposed[0], original[0])
                self.assertEqual(transpose_record(transposed), original)

    def test_synthetic_closure_distinguishes_self_pair_and_missing(self) -> None:
        self_transpose = record(2, [0, 1, 1, 0])
        pair_left = record(2, [0, 0, 1, 1])
        pair_right = transpose_record(pair_left)
        missing_source = record(2, [0, 1, 0, 0])
        missing_transpose = transpose_record(missing_source)
        originals = (self_transpose, pair_left, pair_right, missing_source)

        with (
            patch.object(phase4_common, "EMBEDDED_COUNT", 4),
            patch.object(phase4_common, "SELF_TRANSPOSE_COUNT", 1),
            patch.object(
                phase4_common,
                "EMBEDDED_NONTRIVIAL_TRANSPOSE_SOURCE_COUNT",
                2,
            ),
            patch.object(phase4_common, "DERIVED_TRANSPOSE_COUNT", 1),
            patch.object(phase4_common, "RUNTIME_COUNT", 5),
        ):
            closure = replay_runtime_closure(originals)

        self.assertEqual(
            [row["classification"] for row in closure.classifications],
            [
                "self-transpose",
                "nontrivial-transpose-embedded",
                "nontrivial-transpose-embedded",
                "derived-runtime-transpose",
            ],
        )
        self.assertEqual(closure.derived_records, (missing_transpose,))
        self.assertEqual(closure.runtime_records, originals + (missing_transpose,))
        self.assertEqual(closure.classifications[1]["existing_payload_index"], 2)
        self.assertEqual(closure.classifications[2]["existing_payload_index"], 1)
        self.assertEqual(closure.classifications[3]["runtime_index"], 4)


class ActualPhase4RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload_raw = (STAGE90 / "normalized/tables.bin").read_bytes()
        cls.records = parse_exact_records(
            cls.payload_raw,
            EMBEDDED_COUNT,
            "committed Stage 90 payload",
        )
        cls.closure = replay_runtime_closure(cls.records)

    def test_actual_payload_closes_from_1487_to_2901_with_exact_hashes(self) -> None:
        self.assertEqual(len(self.records), EMBEDDED_COUNT)
        self.assertEqual(len(self.payload_raw), EMBEDDED_RAW_BYTES)
        self.assertEqual(
            hashlib.sha256(self.payload_raw).hexdigest(), EMBEDDED_RAW_SHA256
        )
        self.assertEqual(
            canonical_id_vector_sha256(self.records),
            EMBEDDED_CANONICAL_ID_VECTOR_SHA256,
        )

        derived_raw = b"".join(self.closure.derived_records)
        runtime_raw = b"".join(self.closure.runtime_records)
        self.assertEqual(len(self.closure.derived_records), DERIVED_TRANSPOSE_COUNT)
        self.assertEqual(len(derived_raw), DERIVED_RAW_BYTES)
        self.assertEqual(hashlib.sha256(derived_raw).hexdigest(), DERIVED_RAW_SHA256)
        self.assertEqual(
            canonical_id_vector_sha256(self.closure.derived_records),
            DERIVED_CANONICAL_ID_VECTOR_SHA256,
        )
        self.assertEqual(len(self.closure.runtime_records), RUNTIME_COUNT)
        self.assertEqual(len(set(self.closure.runtime_records)), RUNTIME_COUNT)
        self.assertEqual(len(runtime_raw), RUNTIME_RAW_BYTES)
        self.assertEqual(hashlib.sha256(runtime_raw).hexdigest(), RUNTIME_RAW_SHA256)
        self.assertEqual(
            canonical_id_vector_sha256(self.closure.runtime_records),
            RUNTIME_CANONICAL_ID_VECTOR_SHA256,
        )
        self.assertEqual(
            runtime_raw,
            (STAGE100 / "normalized/tables.bin").read_bytes(),
        )

    def test_runtime_metadata_preserves_historical_first_seen(self) -> None:
        with gzip.open(
            STAGE100 / "normalized/tables.jsonl.gz", "rt", encoding="utf-8"
        ) as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(
            Counter(row["first_seen_stage"] for row in rows[EMBEDDED_COUNT:]),
            Counter(
                {
                    "100-opposite-closure-2901": 1_397,
                    "80-finite149": 11,
                    "10-primary-9450": 6,
                }
            ),
        )
        audit = json.loads(
            (STAGE100 / "verification/opposite-closure-audit.json").read_text(
                encoding="utf-8"
            )
        )["historical_identity"]
        historical_rows = audit["historical_exact_record_reintroductions"]
        self.assertEqual(len(historical_rows), 17)
        self.assertEqual(audit["new_exact_records_first_seen_here"], 1_397)
        for historical in historical_rows:
            row = rows[historical["runtime_index"]]
            self.assertEqual(row["table_id"], historical["table_id"])
            self.assertEqual(
                row["first_seen_stage"], historical["first_seen_stage"]
            )

    def test_submitted_false_engine_functions_are_statically_anchored(self) -> None:
        engine_source = decode_false_engine_source(SUBMISSION.read_bytes())
        audit = audit_false_engine_functions(engine_source)

        self.assertTrue(audit["static_ast_only"])
        self.assertEqual(audit["engine_sha256"], FALSE_ENGINE_SHA256)
        self.assertEqual(audit["runtime_call_lines"], [11_953])
        self.assertEqual(
            {row["name"]: row["sha256"] for row in audit["functions"]},
            FALSE_ENGINE_FUNCTION_SHA256,
        )

    def test_false_engine_decode_enforces_output_bound(self) -> None:
        limit = 64
        oversized_source = b"x" * (limit + 1)
        dictionary_size = 1_048_576
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
        encoded = base64.b85encode(
            lzma.compress(
                oversized_source,
                format=lzma.FORMAT_RAW,
                filters=filters,
            )
        )
        digest = hashlib.sha256(oversized_source).hexdigest()
        launcher = (
            f"_ENGINE_PAYLOAD_B85 = {{'false': {encoded!r}}}\n"
            f"_ENGINE_PAYLOAD_SHA256 = {{'false': {digest!r}}}\n"
            "_ENGINE_PAYLOAD_FORMAT = {'false': 'utf8_source'}\n"
            f"_ENGINE_LZMA_DICT_SIZE = {dictionary_size}\n"
        ).encode("ascii")
        with (
            patch.object(phase4_common, "FALSE_ENGINE_SOURCE_LIMIT", limit),
            patch.object(phase4_common, "FALSE_ENGINE_SHA256", digest),
            self.assertRaisesRegex(Phase4Error, "exceeds bound"),
        ):
            decode_false_engine_source(launcher)

    def test_exact_extreme_xz_and_base85_regression_is_small(self) -> None:
        submitted_xz = (STAGE90 / "normalized/tables.xz").read_bytes()
        submitted_b85 = (STAGE90 / "normalized/tables.xz.b85").read_bytes()
        rebuilt_xz = lzma.compress(
            self.payload_raw,
            preset=9 | lzma.PRESET_EXTREME,
        )
        rebuilt_b85 = base64.b85encode(rebuilt_xz)

        self.assertEqual(len(rebuilt_xz), EMBEDDED_XZ_BYTES)
        self.assertEqual(hashlib.sha256(rebuilt_xz).hexdigest(), EMBEDDED_XZ_SHA256)
        self.assertEqual(rebuilt_xz, submitted_xz)
        self.assertEqual(len(rebuilt_b85), EMBEDDED_B85_BYTES)
        self.assertEqual(hashlib.sha256(rebuilt_b85).hexdigest(), EMBEDDED_B85_SHA256)
        self.assertEqual(rebuilt_b85, submitted_b85)
        self.assertNotEqual(lzma.compress(self.payload_raw, preset=9), submitted_xz)
        self.assertLessEqual(
            len(self.payload_raw) + len(rebuilt_xz) + len(rebuilt_b85),
            256 * 1024,
        )


if __name__ == "__main__":
    unittest.main()
