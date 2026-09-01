from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.stage60_full_run_evidence import (
    Stage60FullRunEvidenceError,
    validate_committed_full_run_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
STAGE60 = ROOT / "reproduction/60-fin4-residual-284151591"
REPORT = STAGE60 / "verification/seedfree-full-run.json"
LOGS = STAGE60 / "verification/seedfree-full-run-logs.jsonl.gz"


def load_report() -> dict[str, object]:
    value = json.loads(REPORT.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("committed Stage 60 evidence is not an object")
    return value


def write_report(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Stage60CommittedFullRunEvidenceTests(unittest.TestCase):
    def test_committed_evidence_is_valid_without_opening_pair_bitsets(self) -> None:
        result = validate_committed_full_run_evidence(ROOT, REPORT, LOGS)
        self.assertEqual(result["status"], "validated-exact")
        self.assertEqual(result["shards"], 256)
        self.assertEqual(result["sanitized_log_rows"], 5_376)
        self.assertEqual(result["sanitized_stderr_lines"], 5_120)
        self.assertEqual(result["accounting"]["raw_tables_scanned"], 1 << 32)
        self.assertEqual(
            result["bitsets"]["residual_284m"]["sha256"],
            "03f4a7eccc7df811756fc5da361a647b49b9064f35b2b14730362fc3fb810756",
        )

    def test_rejects_shard_accounting_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.json"
            report = load_report()
            report["shards"][0]["canonical_models"] -= 1
            write_report(path, report)
            with self.assertRaisesRegex(
                Stage60FullRunEvidenceError, "canonical accounting drift"
            ):
                validate_committed_full_run_evidence(ROOT, path, LOGS)

    def test_rejects_current_implementation_hash_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.json"
            report = load_report()
            report["implementation_identity"]["python_sources"]["runner"][
                "sha256"
            ] = "0" * 64
            write_report(path, report)
            with self.assertRaisesRegex(
                Stage60FullRunEvidenceError, "implementation source hash drift"
            ):
                validate_committed_full_run_evidence(ROOT, path, LOGS)

    def test_rejects_log_summary_tamper_even_with_updated_log_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            report_path = base / "evidence.json"
            logs_path = base / LOGS.name
            report = copy.deepcopy(load_report())
            with gzip.open(LOGS, "rt", encoding="utf-8") as source:
                rows = [json.loads(line) for line in source]
            rows[0]["summary"]["canonical_models_in_range"] -= 1
            with logs_path.open("wb") as raw, gzip.GzipFile(
                filename="", mode="wb", compresslevel=9, mtime=0, fileobj=raw
            ) as output:
                for row in rows:
                    output.write(
                        (
                            json.dumps(
                                row,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            )
                            + "\n"
                        ).encode("utf-8")
                    )
            log_metadata = report["raw_evidence"]["sanitized_logs"]
            log_metadata["bytes"] = logs_path.stat().st_size
            log_metadata["sha256"] = sha256_path(logs_path)
            write_report(report_path, report)
            with self.assertRaisesRegex(
                Stage60FullRunEvidenceError, "summary.*ledger drift"
            ):
                validate_committed_full_run_evidence(
                    ROOT, report_path, logs_path
                )


if __name__ == "__main__":
    unittest.main()
