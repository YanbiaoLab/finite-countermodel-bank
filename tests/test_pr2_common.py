from pathlib import Path
import unittest

from tools.pr2_common import (
    Stage50Error,
    extract_embedded_false_solver_table_payload,
)


ROOT = Path(__file__).resolve().parents[1]


class SubmittedPayloadTests(unittest.TestCase):
    def test_static_false_engine_decode_matches_submission_anchor(self) -> None:
        path = (
            ROOT
            / "reproduction/00-submission-anchor/raw/"
            "2026-08-31_marathon_openai-gpt-oss-120b_solver.py"
        )
        payload = extract_embedded_false_solver_table_payload(
            path.read_bytes(),
            context=str(path),
        )
        self.assertEqual(payload.model_count, 1_487)
        self.assertEqual(payload.declared_raw_bytes, 111_009)
        self.assertEqual(
            payload.raw_sha256,
            "17240427976219ef8da8b2ecb1bd14731b6c11d3be052711911443539e92a680",
        )
        self.assertEqual(len(payload.records), 1_487)

    def test_static_launcher_reader_rejects_nonliteral_payload(self) -> None:
        source = b"""
_ENGINE_PAYLOAD_B85 = {'false': make_payload()}
_ENGINE_PAYLOAD_SHA256 = {'false': '0' * 64}
_ENGINE_PAYLOAD_FORMAT = {'false': 'utf8_source'}
_ENGINE_LZMA_DICT_SIZE = 1048576
"""
        with self.assertRaises(Stage50Error):
            extract_embedded_false_solver_table_payload(source)


if __name__ == "__main__":
    unittest.main()
