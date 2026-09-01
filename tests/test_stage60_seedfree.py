from __future__ import annotations

import importlib.util
import gzip
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.stage60_seedfree import (
    RECONSTRUCTED_INPUTS,
    SYMBOLIC_FIXTURE_FILES,
    Stage60SeedFreeError,
    build_symbolic_signature_fixture,
    reconstruct_stage60_inputs,
    sha256_path,
    verify_reconstructed_inputs,
)


ROOT = Path(__file__).resolve().parents[1]
STAGE60 = ROOT / "reproduction/60-fin4-residual-284151591"


def load_script(name: str, filename: str):
    path = STAGE60 / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_script("stage60_seedfree_runner", "run_seedfree.py")
smoke = load_script("stage60_engine_smoke", "smoke_test_engines.py")
capture = load_script(
    "stage60_seedfree_evidence_capture", "capture_seedfree_evidence.py"
)


def fixture_configuration(
    *, range_count: int = 10, shard_size: int = 10
) -> dict[str, int]:
    return {
        "range_start": 0,
        "range_count": range_count,
        "range_end": range_count,
        "shard_size": shard_size,
        "shard_count": (range_count + shard_size - 1) // shard_size,
    }


def fixture_environment() -> dict[str, object]:
    return {
        "python": "fixture",
        "platform": "fixture",
        "machine": "fixture",
        "byteorder": "little",
        "cpu_count": 1,
        "compiler": "/fixture/clang",
        "compiler_version": "clang fixture",
        "engine_sha256": "e" * 64,
        "engine_source_sha256": "s" * 64,
        "ru_maxrss_raw_unit": "bytes",
        "implementation_identity": {"schema": "fixture-implementation-v1"},
    }


def fixture_preflight() -> dict[str, object]:
    return {"schema": runner.PREFLIGHT_SCHEMA, "status": "ok"}


def fixture_ready_progress(
    configuration: dict[str, int], environment: dict[str, object]
) -> dict[str, object]:
    return {
        "schema": runner.SCHEMA,
        "status": "ready",
        "configuration": configuration,
        "environment_initial": environment,
        "implementation_identity": environment["implementation_identity"],
        "input_hashes": {
            name: digest for name, (_size, digest) in RECONSTRUCTED_INPUTS.items()
        },
        "source_bitset_bytes": runner.SOURCE_324_BYTES,
        "source_bitset_sha256": runner.SOURCE_324_SHA256,
        "historical_seed_chain_used": False,
        "enumeration_method": "seed-free-all-bitslice-opposite-result-level",
        "next_shard": 0,
        "last_remaining_pairs": 324_157_667,
        "maximum_engine_rss_raw": 0,
        "maximum_engine_rss_raw_unit": "bytes",
        "maximum_engine_rss_bytes": 0,
        "preflight_runs": [fixture_preflight()],
        "completed_shards": [],
        "inflight": None,
    }


def fixture_shard_result(
    configuration: dict[str, int], *, start: int = 0, count: int = 10
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "complete",
        "mode": "enumerate-bitslice-inplace",
        "batch_size": 64,
        "range_start": start,
        "range_count": count,
        "pair_start": configuration["range_start"],
        "pair_end": configuration["range_end"],
        "threads": 1,
        "equation_count": 62_576,
        "active_source_count": 41_696,
        "raw_tables_scanned": count,
        "canonical_models_in_range": 7,
        "model_signatures_evaluated": 4,
        "opposite_signatures_derived": 3,
        "canonical_models_skipped_as_derived": 3,
        "expanded_models_accounted_now": 7,
        "initial_remaining_pairs": 100,
        "covered_pairs": 2,
        "remaining_pairs_after": 98,
        "elapsed_seconds": 1.0,
        "user_cpu_seconds": 0.5,
        "system_cpu_seconds": 0.1,
        "ru_maxrss_raw": 123,
        "full_fin4_isomorphism_class_target": 178_981_952,
        "full_fin4_isomorphism_or_anti_isomorphism_target": 89_521_056,
    }


def fixture_completed_record(
    *, initial: int = 324_157_667, covered: int = 2, retried: bool = False
) -> dict[str, object]:
    return {
        "index": 0,
        "range_start": 0,
        "range_count": 10,
        "attempt": 2 if retried else 1,
        "resumed_after_incomplete_attempt": retried,
        "threads": 1,
        "summary": "shards/shard_000.json",
        "summary_sha256": "a" * 64,
        "stderr_log": "shards/shard_000.stderr.log",
        "stderr_sha256": "b" * 64,
        "wall_seconds": 1.0,
        "engine_elapsed_seconds": 1.0,
        "engine_user_cpu_seconds": 0.5,
        "engine_system_cpu_seconds": 0.1,
        "engine_maximum_rss_raw": 123,
        "engine_maximum_rss_raw_unit": "bytes",
        "engine_maximum_rss_bytes": 123,
        "raw_tables_scanned": 10,
        "canonical_models": 7,
        "model_signatures_evaluated": 4,
        "opposite_signatures_derived": 3,
        "canonical_models_skipped_as_derived": 3,
        "expanded_models_accounted_now": 7,
        "initial_remaining_pairs": initial,
        "covered_pairs": covered,
        "remaining_pairs_after": initial - covered,
    }


class Stage60InputRecoveryTests(unittest.TestCase):
    def test_reconstructs_five_historical_inputs_byte_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "inputs"
            report = reconstruct_stage60_inputs(ROOT, output)
            self.assertEqual(report["status"], "historical-bytes-exact")
            self.assertFalse(report["resource_boundary"]["large_bitsets_materialized"])
            self.assertEqual(
                report["resource_boundary"]["reconstructed_output_bytes"],
                sum(size for size, _digest in RECONSTRUCTED_INPUTS.values()),
            )
            self.assertEqual(
                {name: (metadata["bytes"], metadata["sha256"])
                 for name, metadata in report["files"].items()},
                RECONSTRUCTED_INPUTS,
            )

    def test_rejects_tampered_reconstructed_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "inputs"
            reconstruct_stage60_inputs(ROOT, output)
            equations = output / "equations.bin"
            body = bytearray(equations.read_bytes())
            body[-1] ^= 1
            equations.write_bytes(body)
            with self.assertRaisesRegex(Stage60SeedFreeError, "SHA-256 mismatch"):
                verify_reconstructed_inputs(output)

    def test_symbolic_fixture_is_small_and_hash_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            reconstruct_stage60_inputs(ROOT, base / "inputs")
            fixture = build_symbolic_signature_fixture(
                base / "inputs", base / "fixture"
            )
            self.assertEqual(fixture["equations"], 62_576)
            self.assertEqual(
                [row["satisfied_equations"] for row in fixture["models"]],
                [14_612, 14_612, 22_604],
            )
            self.assertEqual(
                (
                    fixture["models_file"]["bytes"],
                    fixture["models_file"]["sha256"],
                ),
                SYMBOLIC_FIXTURE_FILES["models.bin"],
            )
            self.assertEqual(
                (
                    fixture["signatures_file"]["bytes"],
                    fixture["signatures_file"]["sha256"],
                ),
                SYMBOLIC_FIXTURE_FILES["signatures.bin"],
            )


class Stage60EngineSmokeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("clang"), "clang is required for C-engine smoke")
    def test_scalar_and_bitslice_semantics_without_pair_bitset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = smoke.run_smoke(ROOT, Path(temporary), "clang")
        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["resource_boundary"]["large_pair_bitsets_materialized"])
        self.assertEqual(
            [check["stdout"]["status"] for check in report["checks"]],
            ["ok"] * 5,
        )
        self.assertTrue(
            all(
                engine["source_sha256"] == engine["expected_source_sha256"]
                for engine in report["engines"]
            )
        )


class Stage60RunnerSafetyTests(unittest.TestCase):
    def test_default_full_run_is_guarded_before_large_files_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary) / "must-not-exist"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(STAGE60 / "scripts/run_seedfree.py"),
                    "--work-dir",
                    str(work),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("--confirm-full-run", completed.stderr)
            self.assertFalse(work.exists())

    @unittest.skipUnless(shutil.which("clang"), "clang is required for preparation")
    def test_prepare_modes_do_not_create_pair_bitsets_or_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for index, option in enumerate(("--prepare-only", "--max-shards")):
                work = base / f"prepare-{index}"
                command = [
                    sys.executable,
                    str(STAGE60 / "scripts/run_seedfree.py"),
                    "--work-dir",
                    str(work),
                ]
                command.extend([option] if option == "--prepare-only" else [option, "0"])
                completed = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue((work / "preparation.json").is_file())
                self.assertFalse((work / "progress.json").exists())
                self.assertFalse(
                    (work / "source/324M_remaining_pairs.bitset").exists()
                )
                self.assertFalse((work / "run/remaining_pairs.bitset").exists())

    def test_resume_structure_and_environment_are_strict(self) -> None:
        configuration = fixture_configuration()
        environment = fixture_environment()
        progress = fixture_ready_progress(configuration, environment)
        runner.validate_progress_structure(progress, configuration, environment)

        broken = json.loads(json.dumps(progress))
        broken["next_shard"] = 1
        with self.assertRaisesRegex(Stage60SeedFreeError, "completed_shards"):
            runner.validate_progress_structure(broken, configuration, environment)

        changed_environment = json.loads(json.dumps(environment))
        changed_environment["compiler_version"] = "different compiler"
        with self.assertRaisesRegex(Stage60SeedFreeError, "environment/compiler"):
            runner.validate_progress_structure(
                progress, configuration, changed_environment
            )

        two_shards = fixture_configuration(range_count=20, shard_size=10)
        paused = fixture_ready_progress(two_shards, environment)
        record = fixture_completed_record()
        paused.update(
            {
                "status": "paused",
                "next_shard": 1,
                "last_remaining_pairs": record["remaining_pairs_after"],
                "maximum_engine_rss_raw": 123,
                "maximum_engine_rss_bytes": 123,
                "completed_shards": [record],
            }
        )
        runner.validate_progress_structure(paused, two_shards, environment)
        paused["completed_shards"][0]["initial_remaining_pairs"] -= 1
        with self.assertRaisesRegex(Stage60SeedFreeError, "pair ledger|continuity"):
            runner.validate_progress_structure(paused, two_shards, environment)

    def test_shard_result_binds_interval_targets_and_expanded_count(self) -> None:
        configuration = fixture_configuration()
        result = fixture_shard_result(configuration)
        runner.validate_shard_result(
            result, configuration=configuration, start=0, count=10, threads=1
        )
        for field, replacement in (
            ("pair_end", 9),
            ("batch_size", 32),
            ("full_fin4_isomorphism_class_target", 0),
            ("expanded_models_accounted_now", 6),
        ):
            tampered = dict(result)
            tampered[field] = replacement
            with self.assertRaises(Stage60SeedFreeError, msg=field):
                runner.validate_shard_result(
                    tampered,
                    configuration=configuration,
                    start=0,
                    count=10,
                    threads=1,
                )

    def test_retry_checkpoint_rules(self) -> None:
        result = {"initial_remaining_pairs": 100}
        runner.validate_shard_checkpoint(result, expected_initial=100, retried=False)
        runner.validate_shard_checkpoint(result, expected_initial=101, retried=True)
        with self.assertRaises(Stage60SeedFreeError):
            runner.validate_shard_checkpoint(
                result, expected_initial=101, retried=False
            )
        with self.assertRaises(Stage60SeedFreeError):
            runner.validate_shard_checkpoint(result, expected_initial=99, retried=True)

    def test_full_accounting_pins_all_bitslice_anti_counts(self) -> None:
        accounting = {
            "raw_tables_scanned": 1 << 32,
            "canonical_models": 178_981_952,
            "model_signatures_evaluated": 89_521_056,
            "opposite_signatures_derived": 89_460_896,
            "canonical_models_skipped_as_derived": 89_460_896,
            "evaluated_plus_skipped": 178_981_952,
            "evaluated_plus_derived": 178_981_952,
        }
        runner.validate_full_accounting(
            accounting,
            authoritative_difference=40_006_076,
            retried_after_partial=False,
            coverage_attribution_complete=True,
        )
        accounting["model_signatures_evaluated"] -= 1
        with self.assertRaisesRegex(Stage60SeedFreeError, "model_signatures_evaluated"):
            runner.validate_full_accounting(
                accounting,
                authoritative_difference=40_006_076,
                retried_after_partial=False,
                coverage_attribution_complete=True,
            )

    def test_workdir_lock_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            first = runner.acquire_workdir_lock(work)
            try:
                with self.assertRaisesRegex(Stage60SeedFreeError, "locked"):
                    runner.acquire_workdir_lock(work)
            finally:
                runner.release_workdir_lock(first)
            second = runner.acquire_workdir_lock(work)
            runner.release_workdir_lock(second)

    def test_existing_full_final_is_strict_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            Stage60EvidenceCaptureTests().build_synthetic_full_workdir(work)
            progress = json.loads((work / "progress.json").read_text(encoding="utf-8"))
            final = json.loads((work / "final.json").read_text(encoding="utf-8"))
            configuration = progress["configuration"]
            environment = progress["environment_initial"]
            before = sha256_path(work / "final.json")
            first = runner.load_existing_final(
                work, progress, configuration, environment
            )
            second = runner.load_existing_final(
                work, progress, configuration, environment
            )
            self.assertEqual(first, final)
            self.assertEqual(second, final)
            self.assertEqual(before, sha256_path(work / "final.json"))
            broken = json.loads(json.dumps(final))
            broken["enumeration_accounting"]["canonical_models"] -= 1
            (work / "final.json").write_text(
                json.dumps(broken, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Stage60SeedFreeError, "accounting drift"):
                runner.load_existing_final(
                    work, progress, configuration, environment
                )

    def test_disk_preflight_counts_two_missing_bitsets_and_reserve(self) -> None:
        usage = type("Usage", (), {"total": 10**12, "used": 0, "free": 10**12})()
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            runner.shutil, "disk_usage", return_value=usage
        ):
            report = runner.disk_preflight(Path(temporary))
        self.assertEqual(report["missing_bitset_bytes"], 2 * runner.SOURCE_324_BYTES)
        self.assertEqual(
            report["required_free_bytes"],
            2 * runner.SOURCE_324_BYTES + runner.DISK_RESERVE_BYTES,
        )

    def test_shard_count_safety_cap_rejects_one_table_shards(self) -> None:
        args = type(
            "Args",
            (),
            {
                "threads": 1,
                "range_start": 0,
                "range_count": 10_000,
                "shard_size": 1,
            },
        )()
        with self.assertRaisesRegex(Stage60SeedFreeError, "exceeds safety limit"):
            runner.run_configuration(args)

    def test_committed_partition_stream_has_expected_totals(self) -> None:
        count = 0
        original = 0
        removed = 0
        residual = 0
        last = None
        for row in runner.iter_committed_partition_expected(ROOT):
            count += 1
            last = row
            original += row[1]
            removed += row[2]
            residual += row[3]
        self.assertEqual(count, 62_576)
        self.assertEqual(last[0], 62_576)
        self.assertEqual((original, removed, residual), (324_157_667, 40_006_076, 284_151_591))

    def test_ru_maxrss_is_normalized_per_platform(self) -> None:
        expected = 1 if platform.system() == "Darwin" else 1024
        raw = 123
        self.assertEqual(runner.normalized_rss(raw)[0], raw * expected)
        with mock.patch.object(runner.platform, "system", return_value="unknown"):
            with self.assertRaisesRegex(Stage60SeedFreeError, "unsupported ru_maxrss"):
                runner.normalized_rss(raw)


class Stage60EvidenceCaptureTests(unittest.TestCase):
    def build_synthetic_full_workdir(self, work: Path) -> None:
        shards = work / "shards"
        shards.mkdir(parents=True)
        completed: list[dict[str, object]] = []
        raw_unit = runner.ru_maxrss_conversion()[1]
        rss_factor = 1 if raw_unit == "bytes" else 1024
        remaining_pairs = 324_157_667

        def distributed(total: int, index: int) -> int:
            quotient, remainder = divmod(total, 256)
            return quotient + (1 if index < remainder else 0)

        for index in range(256):
            start = index * (1 << 24)
            summary_path = shards / f"shard_{index:03d}.json"
            stderr_path = shards / f"shard_{index:03d}.stderr.log"
            canonical = distributed(178_981_952, index)
            evaluated = distributed(89_521_056, index)
            skipped = canonical - evaluated
            covered = distributed(40_006_076, index)
            initial_remaining = remaining_pairs
            remaining_pairs -= covered
            summary = {
                "schema_version": 1,
                "status": "complete",
                "mode": "enumerate-bitslice-inplace",
                "batch_size": 64,
                "range_start": start,
                "range_count": 1 << 24,
                "pair_start": 0,
                "pair_end": 1 << 32,
                "threads": 1,
                "equation_count": 62_576,
                "active_source_count": 41_696,
                "raw_tables_scanned": 1 << 24,
                "canonical_models_in_range": canonical,
                "model_signatures_evaluated": evaluated,
                "opposite_signatures_derived": skipped,
                "canonical_models_skipped_as_derived": skipped,
                "expanded_models_accounted_now": canonical,
                "expanded_relevant_models": 0,
                "expanded_source_satisfactions": 0,
                "initial_remaining_pairs": initial_remaining,
                "covered_pairs": covered,
                "remaining_pairs_after": remaining_pairs,
                "elapsed_seconds": 1.0,
                "user_cpu_seconds": 0.5,
                "system_cpu_seconds": 0.1,
                "ru_maxrss_raw": 100,
                "full_fin4_isomorphism_class_target": 178_981_952,
                "full_fin4_isomorphism_or_anti_isomorphism_target": 89_521_056,
            }
            summary_path.write_text(
                json.dumps(summary, sort_keys=True) + "\n", encoding="utf-8"
            )
            stderr_path.write_text(
                json.dumps(
                    {
                        "event": "runner-start",
                        "command": [str(work / "bin/engine")],
                    },
                    sort_keys=True,
                )
                + "\n"
                + f"engine workdir={work}\n",
                encoding="utf-8",
            )
            record = {
                "index": index,
                "range_start": start,
                "range_count": 1 << 24,
                "attempt": 1,
                "resumed_after_incomplete_attempt": False,
                "threads": 1,
                "summary": f"shards/shard_{index:03d}.json",
                "summary_sha256": sha256_path(summary_path),
                "stderr_log": f"shards/shard_{index:03d}.stderr.log",
                "stderr_sha256": sha256_path(stderr_path),
                "wall_seconds": 1.0,
                "engine_elapsed_seconds": 1.0,
                "engine_user_cpu_seconds": 0.5,
                "engine_system_cpu_seconds": 0.1,
                "engine_maximum_rss_raw": 100,
                "engine_maximum_rss_raw_unit": raw_unit,
                "engine_maximum_rss_bytes": 100 * rss_factor,
                "raw_tables_scanned": 1 << 24,
                "canonical_models": canonical,
                "model_signatures_evaluated": evaluated,
                "opposite_signatures_derived": skipped,
                "canonical_models_skipped_as_derived": skipped,
                "expanded_models_accounted_now": canonical,
                "initial_remaining_pairs": initial_remaining,
                "covered_pairs": covered,
                "remaining_pairs_after": remaining_pairs,
            }
            completed.append({**record, "command": ["omitted from final"]})

        configuration = {
            "range_start": 0,
            "range_count": 1 << 32,
            "range_end": 1 << 32,
            "shard_size": 1 << 24,
            "shard_count": 256,
        }
        identity = runner.implementation_identity(ROOT)
        environment = {
            "python": "fixture",
            "platform": "fixture",
            "machine": "fixture",
            "byteorder": "little",
            "cpu_count": 1,
            "compiler": "/fixture/clang",
            "compiler_version": "clang fixture\nsecond line",
            "engine_sha256": "e" * 64,
            "engine_source_sha256": runner.BITSLICE_ENGINE_SHA256,
            "ru_maxrss_raw_unit": raw_unit,
            "implementation_identity": identity,
        }
        input_hashes = {
            name: digest for name, (_size, digest) in RECONSTRUCTED_INPUTS.items()
        }
        preflights = [{"schema": runner.PREFLIGHT_SCHEMA, "status": "ok"}]
        progress: dict[str, object] = {
            "schema": capture.RUN_SCHEMA,
            "status": "complete",
            "configuration": configuration,
            "environment_initial": environment,
            "implementation_identity": identity,
            "input_hashes": input_hashes,
            "source_bitset_bytes": runner.SOURCE_324_BYTES,
            "source_bitset_sha256": runner.SOURCE_324_SHA256,
            "historical_seed_chain_used": False,
            "enumeration_method": "seed-free-all-bitslice-opposite-result-level",
            "next_shard": 256,
            "last_remaining_pairs": remaining_pairs,
            "maximum_engine_rss_raw": 100,
            "maximum_engine_rss_raw_unit": raw_unit,
            "maximum_engine_rss_bytes": 100 * rss_factor,
            "preflight_runs": preflights,
            "completed_shards": completed,
            "inflight": None,
        }
        accounting, timing, retry_status, final_shards = (
            runner.completed_run_rollups(
                progress, declared_remaining=remaining_pairs
            )
        )
        final = {
            "schema": capture.FINAL_SCHEMA,
            "status": "complete",
            "completed_at": "2026-09-01T00:00:00Z",
            "configuration": configuration,
            "historical_seed_chain_used": False,
            "enumeration_method": "seed-free-all-bitslice-opposite-result-level",
            "work_bitset_bytes": capture.FINAL_284_BYTES,
            "work_bitset_sha256": capture.FINAL_284_SHA256,
            "declared_remaining_pairs": 284_151_591,
            "fin4_incremental_covered_pairs": 40_006_076,
            "committed_284m_exact_match": True,
            "enumeration_accounting": accounting,
            "enumeration_timing": timing,
            "retry_status": retry_status,
            "maximum_engine_rss_raw": 100,
            "maximum_engine_rss_raw_unit": raw_unit,
            "maximum_engine_rss_bytes": 100 * rss_factor,
            "pair_bitset_stream_validation": {
                "validator": "tools.phase2_common.validate_pair_bitset_streams",
                "expected_rows": "normalized/pair-partition-by-source.csv.gz",
                "original_popcount": 324_157_667,
                "residual_popcount": 284_151_591,
                "removed_popcount": 40_006_076,
                "original_active_sources": 41_696,
                "residual_active_sources": 41_696,
                "rows_checked": 62_576,
                "residual_is_subset": True,
                "diagonal_bits_all_zero": True,
                "out_of_range_bits_all_zero": True,
            },
            "committed_284m_expected_bytes": capture.FINAL_284_BYTES,
            "committed_284m_expected_sha256": capture.FINAL_284_SHA256,
            "input_hashes": input_hashes,
            "implementation_identity": identity,
            "environment": environment,
            "disk_preflight_runs": preflights,
            "compiler_engine": {
                "compiler": "/fixture/clang",
                "compiler_version": "clang fixture\nsecond line",
                "engine_sha256": "e" * 64,
                "engine_source_sha256": runner.BITSLICE_ENGINE_SHA256,
            },
            "shard_evidence": final_shards,
            "scope_boundary": "fixture",
        }
        progress["final"] = final
        runner.validate_progress_structure(progress, configuration, environment)
        runner.validate_final_structure(final, progress, configuration, environment)
        (work / "final.json").write_text(
            json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (work / "progress.json").write_text(
            json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_capture_is_sanitized_deterministic_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            work = base / "work"
            output = base / "evidence"
            self.build_synthetic_full_workdir(work)
            bitsets = {
                "source_324m": {
                    "bytes": capture.SOURCE_324_BYTES,
                    "sha256": capture.SOURCE_324_SHA256,
                },
                "residual_284m": {
                    "bytes": capture.FINAL_284_BYTES,
                    "sha256": capture.FINAL_284_SHA256,
                },
            }
            runtime = {"status": "synthetic-runtime-validated"}
            capture.capture_evidence(
                work,
                output,
                bitset_verifier=lambda _work: bitsets,
                runtime_verifier=lambda _work, _environment: runtime,
            )
            first_json = sha256_path(output / "seedfree-full-run.json")
            first_logs = sha256_path(output / "seedfree-full-run-logs.jsonl.gz")
            capture.capture_evidence(
                work,
                output,
                bitset_verifier=lambda _work: bitsets,
                runtime_verifier=lambda _work, _environment: runtime,
            )
            self.assertEqual(first_json, sha256_path(output / "seedfree-full-run.json"))
            self.assertEqual(
                first_logs, sha256_path(output / "seedfree-full-run-logs.jsonl.gz")
            )
            with gzip.open(
                output / "seedfree-full-run-logs.jsonl.gz", "rt", encoding="utf-8"
            ) as handle:
                logs = handle.read()
            self.assertNotIn(str(work), logs)
            self.assertNotIn('"command"', logs)
            self.assertIn("<WORKDIR>", logs)

            final_path = work / "final.json"
            progress_path = work / "progress.json"
            original_final = final_path.read_text(encoding="utf-8")
            original_progress = progress_path.read_text(encoding="utf-8")
            forged_final = json.loads(original_final)
            forged_progress = json.loads(original_progress)
            forged_final["enumeration_accounting"]["canonical_models"] -= 1
            forged_progress["final"] = forged_final
            final_path.write_text(
                json.dumps(forged_final, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            progress_path.write_text(
                json.dumps(forged_progress, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Stage60SeedFreeError, "accounting drift"):
                capture.capture_evidence(
                    work,
                    output,
                    bitset_verifier=lambda _work: bitsets,
                    runtime_verifier=lambda _work, _environment: runtime,
                )
            final_path.write_text(original_final, encoding="utf-8")
            progress_path.write_text(original_progress, encoding="utf-8")

            tampered = work / "shards/shard_000.stderr.log"
            tampered.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(Stage60SeedFreeError, "hash drift"):
                capture.capture_evidence(
                    work,
                    output,
                    bitset_verifier=lambda _work: bitsets,
                    runtime_verifier=lambda _work, _environment: runtime,
                )


if __name__ == "__main__":
    unittest.main()
