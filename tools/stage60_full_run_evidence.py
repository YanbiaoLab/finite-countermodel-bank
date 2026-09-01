#!/usr/bin/env python3
"""Validate compact evidence from the committed Stage 60 seed-free full run.

This verifier deliberately does not open either 489,598,720-byte pair bitset.
The repository's Phase 2 verifier already streams those bitsets and checks their
hashes, popcounts, subset relation, and row ledger.  This module instead binds
the compact full-run report and sanitized logs to those known results, the
current implementation bytes, all 256 shard summaries, and exact enumeration
accounting.
"""

from __future__ import annotations

from datetime import datetime
import gzip
import json
import math
from pathlib import Path
import re
from typing import Iterator, Mapping, Sequence

from tools.stage60_seedfree import (
    BITSLICE_ENGINE_BYTES,
    BITSLICE_ENGINE_SHA256,
    FINAL_284_BYTES,
    FINAL_284_SHA256,
    RECONSTRUCTED_INPUTS,
    SOURCE_324_BYTES,
    SOURCE_324_SHA256,
    sha256_path,
)


STAGE60_RELATIVE = Path("reproduction/60-fin4-residual-284151591")
REPORT_SCHEMA = "stage60-seedfree-full-run-evidence-v1"
LOG_SCHEMA = "stage60-seedfree-sanitized-log-line-v1"
IMPLEMENTATION_SCHEMA = "stage60-seedfree-implementation-identity-v1"
ENUMERATION_METHOD = "seed-free-all-bitslice-opposite-result-level"

REPORT_RELATIVE = STAGE60_RELATIVE / "verification/seedfree-full-run.json"
LOGS_RELATIVE = STAGE60_RELATIVE / "verification/seedfree-full-run-logs.jsonl.gz"
PARTITION_RELATIVE = STAGE60_RELATIVE / "normalized/pair-partition-by-source.csv.gz"
RUNNER_RELATIVE = STAGE60_RELATIVE / "scripts/run_seedfree.py"
CAPTURE_RELATIVE = STAGE60_RELATIVE / "scripts/capture_seedfree_evidence.py"
HELPER_RELATIVE = Path("tools/stage60_seedfree.py")
PAIR_VALIDATOR_RELATIVE = Path("tools/phase2_common.py")

FULL_TABLE_COUNT = 1 << 32
SHARD_SIZE = 1 << 24
SHARD_COUNT = 256
EQUATION_COUNT = 62_576
TARGETED_PAIR_COUNT = 324_157_667
RESIDUAL_PAIR_COUNT = 284_151_591
COVERED_PAIR_COUNT = 40_006_076
CANONICAL_MODEL_COUNT = 178_981_952
EVALUATED_MODEL_COUNT = 89_521_056
DERIVED_MODEL_COUNT = 89_460_896
ACTIVE_SOURCE_COUNT = 41_696

MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_LOG_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_LOG_LINE_BYTES = 1024 * 1024
EXPECTED_STDERR_LINES_PER_SHARD = 20
EXPECTED_LOG_ROWS = SHARD_COUNT * (1 + EXPECTED_STDERR_LINES_PER_SHARD)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

REPORT_KEYS = {
    "schema",
    "status",
    "completed_at",
    "configuration",
    "enumeration_method",
    "historical_seed_chain_used",
    "bitsets",
    "enumeration_accounting",
    "enumeration_timing",
    "retry_status",
    "maximum_engine_rss_raw",
    "maximum_engine_rss_raw_unit",
    "maximum_engine_rss_bytes",
    "pair_bitset_stream_validation",
    "input_hashes",
    "implementation_identity",
    "work_runtime",
    "capture_implementation",
    "environment",
    "compiler_engine",
    "shards",
    "raw_evidence",
    "scope_boundary",
}

SHARD_KEYS = {
    "index",
    "range_start",
    "range_count",
    "attempt",
    "resumed_after_incomplete_attempt",
    "threads",
    "summary",
    "summary_sha256",
    "stderr_log",
    "stderr_sha256",
    "wall_seconds",
    "engine_elapsed_seconds",
    "engine_user_cpu_seconds",
    "engine_system_cpu_seconds",
    "engine_maximum_rss_raw",
    "engine_maximum_rss_raw_unit",
    "engine_maximum_rss_bytes",
    "raw_tables_scanned",
    "canonical_models",
    "model_signatures_evaluated",
    "opposite_signatures_derived",
    "canonical_models_skipped_as_derived",
    "expanded_models_accounted_now",
    "initial_remaining_pairs",
    "covered_pairs",
    "remaining_pairs_after",
}

ENGINE_SUMMARY_KEYS = {
    "schema_version",
    "status",
    "mode",
    "batch_size",
    "range_start",
    "range_count",
    "pair_start",
    "pair_end",
    "threads",
    "equation_count",
    "active_source_count",
    "raw_tables_scanned",
    "canonical_models_in_range",
    "model_signatures_evaluated",
    "opposite_signatures_derived",
    "canonical_models_skipped_as_derived",
    "expanded_models_accounted_now",
    "expanded_relevant_models",
    "expanded_source_satisfactions",
    "initial_remaining_pairs",
    "covered_pairs",
    "remaining_pairs_after",
    "elapsed_seconds",
    "user_cpu_seconds",
    "system_cpu_seconds",
    "ru_maxrss_raw",
    "full_fin4_isomorphism_class_target",
    "full_fin4_isomorphism_or_anti_isomorphism_target",
}


class Stage60FullRunEvidenceError(RuntimeError):
    """Raised when committed Stage 60 full-run evidence is inconsistent."""


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise Stage60FullRunEvidenceError(message)


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Stage60FullRunEvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise Stage60FullRunEvidenceError(f"non-finite JSON number: {value}")


def _loads_json(payload: str, context: str) -> object:
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except Stage60FullRunEvidenceError:
        raise
    except json.JSONDecodeError as exc:
        raise Stage60FullRunEvidenceError(f"invalid JSON in {context}: {exc}") from exc


def _load_report(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_REPORT_BYTES + 1)
    except OSError as exc:
        raise Stage60FullRunEvidenceError(f"cannot read evidence report {path}: {exc}") from exc
    _ensure(len(payload) <= MAX_REPORT_BYTES, "Stage 60 evidence report exceeds size cap")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Stage60FullRunEvidenceError("Stage 60 evidence report is not UTF-8") from exc
    report = _loads_json(text, str(path))
    _ensure(isinstance(report, dict), "Stage 60 evidence report is not an object")
    return report


def _exact_keys(value: Mapping[str, object], expected: set[str], context: str) -> None:
    actual = set(value)
    _ensure(actual == expected, f"{context} keys drift: {sorted(actual ^ expected)}")


def _exact_int(value: object, expected: int, context: str) -> None:
    _ensure(type(value) is int and value == expected, f"{context} drift")


def _nonnegative_int(value: object, context: str) -> int:
    _ensure(type(value) is int and int(value) >= 0, f"{context} is not a nonnegative integer")
    return int(value)


def _positive_int(value: object, context: str) -> int:
    result = _nonnegative_int(value, context)
    _ensure(result > 0, f"{context} is not positive")
    return result


def _nonnegative_number(value: object, context: str) -> float:
    _ensure(type(value) in {int, float}, f"{context} is not numeric")
    result = float(value)
    _ensure(math.isfinite(result) and result >= 0.0, f"{context} is invalid")
    return result


def _exact_hash(value: object, expected: str | None, context: str) -> str:
    _ensure(isinstance(value, str) and HASH_RE.fullmatch(value) is not None, f"{context} is not SHA-256")
    if expected is not None:
        _ensure(value == expected, f"{context} drift")
    return value


def _metadata(value: object, *, expected_bytes: int, expected_sha256: str, context: str) -> None:
    _ensure(isinstance(value, dict), f"{context} is not an object")
    _exact_keys(value, {"bytes", "sha256"}, context)
    _exact_int(value.get("bytes"), expected_bytes, f"{context}.bytes")
    _exact_hash(value.get("sha256"), expected_sha256, f"{context}.sha256")


def _historical_metadata(
    value: object, *, expected_bytes: int, expected_sha256: str, context: str
) -> None:
    _ensure(isinstance(value, dict), f"{context} is not an object")
    _exact_keys(value, {"bytes", "sha256", "historical_bytes_exact"}, context)
    _exact_int(value.get("bytes"), expected_bytes, f"{context}.bytes")
    _exact_hash(value.get("sha256"), expected_sha256, f"{context}.sha256")
    _ensure(value.get("historical_bytes_exact") is True, f"{context} is not byte-exact")


def _validate_datetime(value: object, context: str) -> str:
    _ensure(isinstance(value, str) and value.endswith("Z"), f"{context} is not UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Stage60FullRunEvidenceError(f"{context} is not ISO-8601") from exc
    _ensure(parsed.tzinfo is not None, f"{context} lacks a timezone")
    return value


def _validate_report_header(report: dict[str, object]) -> None:
    _exact_keys(report, REPORT_KEYS, "full-run report")
    _ensure(report.get("schema") == REPORT_SCHEMA, "full-run report schema drift")
    _ensure(report.get("status") == "validated-exact", "full-run report status drift")
    _validate_datetime(report.get("completed_at"), "completed_at")
    _ensure(report.get("enumeration_method") == ENUMERATION_METHOD, "enumeration method drift")
    _ensure(report.get("historical_seed_chain_used") is False, "historical seed-chain claim drift")
    _ensure(
        report.get("scope_boundary")
        == (
            "This captures a new seed-free result-level run. It does not recover "
            "the historical seeded execution/provenance chain."
        ),
        "full-run scope boundary drift",
    )
    expected_configuration = {
        "range_start": 0,
        "range_count": FULL_TABLE_COUNT,
        "range_end": FULL_TABLE_COUNT,
        "shard_size": SHARD_SIZE,
        "shard_count": SHARD_COUNT,
    }
    _ensure(report.get("configuration") == expected_configuration, "full-run configuration drift")


def _validate_bitset_claims(report: dict[str, object]) -> None:
    expected_bitsets = {
        "source_324m": {"bytes": SOURCE_324_BYTES, "sha256": SOURCE_324_SHA256},
        "residual_284m": {"bytes": FINAL_284_BYTES, "sha256": FINAL_284_SHA256},
    }
    _ensure(report.get("bitsets") == expected_bitsets, "full-run bitset metadata drift")
    expected_validation = {
        "validator": "tools.phase2_common.validate_pair_bitset_streams",
        "expected_rows": "normalized/pair-partition-by-source.csv.gz",
        "original_popcount": TARGETED_PAIR_COUNT,
        "residual_popcount": RESIDUAL_PAIR_COUNT,
        "removed_popcount": COVERED_PAIR_COUNT,
        "original_active_sources": ACTIVE_SOURCE_COUNT,
        "residual_active_sources": ACTIVE_SOURCE_COUNT,
        "rows_checked": EQUATION_COUNT,
        "residual_is_subset": True,
        "diagonal_bits_all_zero": True,
        "out_of_range_bits_all_zero": True,
    }
    _ensure(
        report.get("pair_bitset_stream_validation") == expected_validation,
        "full-run pair-bitset validation claim drift",
    )


def _validate_implementation(repository_root: Path, report: dict[str, object]) -> None:
    expected_input_hashes = {
        name: digest for name, (_size, digest) in RECONSTRUCTED_INPUTS.items()
    }
    _ensure(report.get("input_hashes") == expected_input_hashes, "full-run input hashes drift")

    identity = report.get("implementation_identity")
    _ensure(isinstance(identity, dict), "implementation_identity is not an object")
    _exact_keys(
        identity,
        {
            "schema",
            "engine_source_sha256",
            "partition_ledger",
            "python_sources",
            "reconstructed_inputs",
            "source_bitset",
        },
        "implementation_identity",
    )
    _ensure(identity.get("schema") == IMPLEMENTATION_SCHEMA, "implementation schema drift")
    _exact_hash(
        identity.get("engine_source_sha256"),
        BITSLICE_ENGINE_SHA256,
        "implementation engine source hash",
    )

    expected_reconstructed = {
        name: {"bytes": size, "sha256": digest}
        for name, (size, digest) in RECONSTRUCTED_INPUTS.items()
    }
    _ensure(
        identity.get("reconstructed_inputs") == expected_reconstructed,
        "implementation reconstructed-input metadata drift",
    )
    _ensure(
        identity.get("source_bitset")
        == {"bytes": SOURCE_324_BYTES, "sha256": SOURCE_324_SHA256},
        "implementation source-bitset metadata drift",
    )

    partition_path = repository_root / PARTITION_RELATIVE
    _ensure(partition_path.is_file(), f"missing implementation ledger: {partition_path}")
    expected_partition = {
        "path": PARTITION_RELATIVE.as_posix(),
        "bytes": partition_path.stat().st_size,
        "sha256": sha256_path(partition_path),
    }
    _ensure(identity.get("partition_ledger") == expected_partition, "partition-ledger identity drift")

    python_sources = identity.get("python_sources")
    _ensure(isinstance(python_sources, dict), "python_sources is not an object")
    _exact_keys(
        python_sources,
        {"runner", "input_helper", "pair_bitset_validator"},
        "python_sources",
    )
    expected_sources = {
        "runner": RUNNER_RELATIVE,
        "input_helper": HELPER_RELATIVE,
        "pair_bitset_validator": PAIR_VALIDATOR_RELATIVE,
    }
    for key, relative in expected_sources.items():
        path = repository_root / relative
        _ensure(path.is_file(), f"missing implementation source: {path}")
        _ensure(
            python_sources.get(key)
            == {"path": relative.as_posix(), "sha256": sha256_path(path)},
            f"implementation source hash drift: {relative}",
        )

    capture = report.get("capture_implementation")
    capture_path = repository_root / CAPTURE_RELATIVE
    _ensure(isinstance(capture, dict), "capture_implementation is not an object")
    _ensure(
        capture
        == {"path": CAPTURE_RELATIVE.as_posix(), "sha256": sha256_path(capture_path)},
        "evidence-capture implementation hash drift",
    )

    runtime = report.get("work_runtime")
    _ensure(isinstance(runtime, dict), "work_runtime is not an object")
    _exact_keys(runtime, {"reconstructed_inputs", "engine_source", "engine_executable"}, "work_runtime")
    reconstructed = runtime.get("reconstructed_inputs")
    _ensure(isinstance(reconstructed, dict), "work_runtime.reconstructed_inputs is not an object")
    _exact_keys(reconstructed, set(RECONSTRUCTED_INPUTS), "work_runtime.reconstructed_inputs")
    for name, (size, digest) in RECONSTRUCTED_INPUTS.items():
        _historical_metadata(
            reconstructed.get(name),
            expected_bytes=size,
            expected_sha256=digest,
            context=f"work_runtime.reconstructed_inputs.{name}",
        )
    _metadata(
        runtime.get("engine_source"),
        expected_bytes=BITSLICE_ENGINE_BYTES,
        expected_sha256=BITSLICE_ENGINE_SHA256,
        context="work_runtime.engine_source",
    )

    executable = runtime.get("engine_executable")
    _ensure(isinstance(executable, dict), "work_runtime.engine_executable is not an object")
    _exact_keys(executable, {"bytes", "sha256"}, "work_runtime.engine_executable")
    _positive_int(executable.get("bytes"), "work_runtime.engine_executable.bytes")
    executable_sha = _exact_hash(
        executable.get("sha256"), None, "work_runtime.engine_executable.sha256"
    )

    compiler = report.get("compiler_engine")
    _ensure(isinstance(compiler, dict), "compiler_engine is not an object")
    _exact_keys(
        compiler,
        {
            "compiler_executable_name",
            "compiler_version_first_line",
            "engine_sha256",
            "engine_source_sha256",
        },
        "compiler_engine",
    )
    compiler_name = compiler.get("compiler_executable_name")
    compiler_version = compiler.get("compiler_version_first_line")
    _ensure(
        isinstance(compiler_name, str)
        and compiler_name
        and Path(compiler_name).name == compiler_name,
        "compiler executable name drift",
    )
    _ensure(
        isinstance(compiler_version, str)
        and bool(compiler_version)
        and "\n" not in compiler_version,
        "compiler version evidence drift",
    )
    _exact_hash(compiler.get("engine_sha256"), executable_sha, "compiler engine hash")
    _exact_hash(
        compiler.get("engine_source_sha256"),
        BITSLICE_ENGINE_SHA256,
        "compiler engine-source hash",
    )

    environment = report.get("environment")
    _ensure(isinstance(environment, dict), "environment is not an object")
    _exact_keys(
        environment,
        {"python", "platform", "machine", "byteorder", "cpu_count"},
        "environment",
    )
    for key in ("python", "platform", "machine"):
        _ensure(isinstance(environment.get(key), str) and bool(environment[key]), f"environment.{key} drift")
    _ensure(environment.get("byteorder") in {"little", "big"}, "environment.byteorder drift")
    _positive_int(environment.get("cpu_count"), "environment.cpu_count")


def _validate_retry_and_accounting(report: dict[str, object]) -> None:
    expected_retry = {
        "any_retried_shards": False,
        "failed_attempt_resources_fully_accounted": True,
        "retried_shard_indexes": [],
        "successful_attempt_coverage_attribution_complete": True,
    }
    _ensure(report.get("retry_status") == expected_retry, "full-run retry status drift")
    expected_accounting = {
        "raw_tables_scanned": FULL_TABLE_COUNT,
        "canonical_models": CANONICAL_MODEL_COUNT,
        "model_signatures_evaluated": EVALUATED_MODEL_COUNT,
        "opposite_signatures_derived": DERIVED_MODEL_COUNT,
        "canonical_models_skipped_as_derived": DERIVED_MODEL_COUNT,
        "evaluated_plus_skipped": CANONICAL_MODEL_COUNT,
        "evaluated_plus_derived": CANONICAL_MODEL_COUNT,
        "authoritative_bitset_difference": COVERED_PAIR_COUNT,
        "successful_attempt_covered_pairs_sum": COVERED_PAIR_COUNT,
        "successful_attempt_coverage_attribution_complete": True,
        "retry_boundary": (
            "A retry after an interrupted in-place shard can preserve partial clears. "
            "In that case successful-attempt covered-pair totals are intentionally not "
            "claimed as a complete attribution ledger; final bitset difference/hash is "
            "authoritative."
        ),
    }
    _ensure(
        report.get("enumeration_accounting") == expected_accounting,
        "full-run enumeration accounting drift",
    )


def _validate_shards(report: dict[str, object]) -> dict[str, float | int]:
    shards = report.get("shards")
    _ensure(isinstance(shards, list) and len(shards) == SHARD_COUNT, "full-run shard count drift")
    totals: dict[str, float | int] = {
        "raw_tables_scanned": 0,
        "canonical_models": 0,
        "model_signatures_evaluated": 0,
        "opposite_signatures_derived": 0,
        "canonical_models_skipped_as_derived": 0,
        "expanded_models_accounted_now": 0,
        "covered_pairs": 0,
        "wall_seconds": 0.0,
        "engine_elapsed_seconds": 0.0,
        "engine_user_cpu_seconds": 0.0,
        "engine_system_cpu_seconds": 0.0,
        "maximum_engine_rss_bytes": 0,
    }
    previous_remaining = TARGETED_PAIR_COUNT
    for index, value in enumerate(shards):
        context = f"shards[{index}]"
        _ensure(isinstance(value, dict), f"{context} is not an object")
        _exact_keys(value, SHARD_KEYS, context)
        _exact_int(value.get("index"), index, f"{context}.index")
        _exact_int(value.get("range_start"), index * SHARD_SIZE, f"{context}.range_start")
        _exact_int(value.get("range_count"), SHARD_SIZE, f"{context}.range_count")
        _exact_int(value.get("attempt"), 1, f"{context}.attempt")
        _ensure(value.get("resumed_after_incomplete_attempt") is False, f"{context} retry flag drift")
        _positive_int(value.get("threads"), f"{context}.threads")
        _ensure(value.get("summary") == f"shards/shard_{index:03d}.json", f"{context}.summary path drift")
        _ensure(
            value.get("stderr_log") == f"shards/shard_{index:03d}.stderr.log",
            f"{context}.stderr path drift",
        )
        _exact_hash(value.get("summary_sha256"), None, f"{context}.summary_sha256")
        _exact_hash(value.get("stderr_sha256"), None, f"{context}.stderr_sha256")

        integers = {
            key: _nonnegative_int(value.get(key), f"{context}.{key}")
            for key in (
                "raw_tables_scanned",
                "canonical_models",
                "model_signatures_evaluated",
                "opposite_signatures_derived",
                "canonical_models_skipped_as_derived",
                "expanded_models_accounted_now",
                "initial_remaining_pairs",
                "covered_pairs",
                "remaining_pairs_after",
                "engine_maximum_rss_raw",
                "engine_maximum_rss_bytes",
            )
        }
        _ensure(integers["raw_tables_scanned"] == SHARD_SIZE, f"{context} scan count drift")
        _ensure(
            integers["canonical_models"]
            == integers["model_signatures_evaluated"]
            + integers["canonical_models_skipped_as_derived"],
            f"{context} canonical accounting drift",
        )
        _ensure(
            integers["expanded_models_accounted_now"]
            == integers["model_signatures_evaluated"]
            + integers["opposite_signatures_derived"],
            f"{context} expanded accounting drift",
        )
        _ensure(integers["initial_remaining_pairs"] == previous_remaining, f"{context} initial pair continuity drift")
        _ensure(
            integers["initial_remaining_pairs"] - integers["covered_pairs"]
            == integers["remaining_pairs_after"],
            f"{context} remaining-pair recurrence drift",
        )
        previous_remaining = integers["remaining_pairs_after"]
        _ensure(value.get("engine_maximum_rss_raw_unit") == "bytes", f"{context} RSS unit drift")
        _ensure(
            integers["engine_maximum_rss_raw"] == integers["engine_maximum_rss_bytes"],
            f"{context} RSS conversion drift",
        )

        numbers = {
            key: _nonnegative_number(value.get(key), f"{context}.{key}")
            for key in (
                "wall_seconds",
                "engine_elapsed_seconds",
                "engine_user_cpu_seconds",
                "engine_system_cpu_seconds",
            )
        }
        for key in (
            "raw_tables_scanned",
            "canonical_models",
            "model_signatures_evaluated",
            "opposite_signatures_derived",
            "canonical_models_skipped_as_derived",
            "expanded_models_accounted_now",
            "covered_pairs",
        ):
            totals[key] = int(totals[key]) + integers[key]
        for key, number in numbers.items():
            totals[key] = float(totals[key]) + number
        totals["maximum_engine_rss_bytes"] = max(
            int(totals["maximum_engine_rss_bytes"]),
            integers["engine_maximum_rss_bytes"],
        )

    _ensure(previous_remaining == RESIDUAL_PAIR_COUNT, "final shard remaining-pair count drift")
    expected_integer_totals = {
        "raw_tables_scanned": FULL_TABLE_COUNT,
        "canonical_models": CANONICAL_MODEL_COUNT,
        "model_signatures_evaluated": EVALUATED_MODEL_COUNT,
        "opposite_signatures_derived": DERIVED_MODEL_COUNT,
        "canonical_models_skipped_as_derived": DERIVED_MODEL_COUNT,
        "expanded_models_accounted_now": CANONICAL_MODEL_COUNT,
        "covered_pairs": COVERED_PAIR_COUNT,
    }
    for key, expected in expected_integer_totals.items():
        _ensure(totals[key] == expected, f"full-run shard {key} total drift")
    return totals


def _validate_timing_and_rss(report: dict[str, object], totals: Mapping[str, float | int]) -> None:
    timing = report.get("enumeration_timing")
    _ensure(isinstance(timing, dict), "enumeration_timing is not an object")
    _exact_keys(
        timing,
        {
            "engine_elapsed_seconds_sum",
            "engine_user_cpu_seconds_sum",
            "engine_system_cpu_seconds_sum",
            "shard_wall_seconds_sum",
            "failed_attempt_resources_fully_accounted",
            "retry_resource_boundary",
            "scope",
        },
        "enumeration_timing",
    )
    _ensure(timing.get("failed_attempt_resources_fully_accounted") is True, "timing retry accounting drift")
    _ensure(timing.get("scope") == "successful shard attempts recorded in completed_shards", "timing scope drift")
    _ensure(
        timing.get("retry_resource_boundary")
        == (
            "If a shard was retried, these sums exclude resource use from failed or "
            "interrupted attempts and are therefore lower bounds for the whole run."
        ),
        "timing retry boundary drift",
    )
    comparisons = {
        "engine_elapsed_seconds_sum": "engine_elapsed_seconds",
        "engine_user_cpu_seconds_sum": "engine_user_cpu_seconds",
        "engine_system_cpu_seconds_sum": "engine_system_cpu_seconds",
        "shard_wall_seconds_sum": "wall_seconds",
    }
    for report_key, total_key in comparisons.items():
        actual = _nonnegative_number(timing.get(report_key), f"enumeration_timing.{report_key}")
        expected = float(totals[total_key])
        _ensure(
            math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-6),
            f"enumeration_timing.{report_key} aggregate drift",
        )
    maximum_rss = int(totals["maximum_engine_rss_bytes"])
    _exact_int(report.get("maximum_engine_rss_bytes"), maximum_rss, "maximum_engine_rss_bytes")
    _exact_int(report.get("maximum_engine_rss_raw"), maximum_rss, "maximum_engine_rss_raw")
    _ensure(report.get("maximum_engine_rss_raw_unit") == "bytes", "maximum RSS unit drift")


def _validate_engine_summary(
    summary: object, shard: Mapping[str, object], shard_index: int
) -> None:
    context = f"sanitized logs shard {shard_index} summary"
    _ensure(isinstance(summary, dict), f"{context} is not an object")
    _exact_keys(summary, ENGINE_SUMMARY_KEYS, context)
    fixed = {
        "schema_version": 1,
        "status": "complete",
        "mode": "enumerate-bitslice-inplace",
        "batch_size": 64,
        "range_start": shard_index * SHARD_SIZE,
        "range_count": SHARD_SIZE,
        "pair_start": 0,
        "pair_end": FULL_TABLE_COUNT,
        "threads": shard["threads"],
        "equation_count": EQUATION_COUNT,
        "active_source_count": ACTIVE_SOURCE_COUNT,
        "full_fin4_isomorphism_class_target": CANONICAL_MODEL_COUNT,
        "full_fin4_isomorphism_or_anti_isomorphism_target": EVALUATED_MODEL_COUNT,
    }
    for key, expected in fixed.items():
        _ensure(summary.get(key) == expected and type(summary.get(key)) is type(expected), f"{context}.{key} drift")
    mapping = {
        "raw_tables_scanned": "raw_tables_scanned",
        "canonical_models_in_range": "canonical_models",
        "model_signatures_evaluated": "model_signatures_evaluated",
        "opposite_signatures_derived": "opposite_signatures_derived",
        "canonical_models_skipped_as_derived": "canonical_models_skipped_as_derived",
        "expanded_models_accounted_now": "expanded_models_accounted_now",
        "initial_remaining_pairs": "initial_remaining_pairs",
        "covered_pairs": "covered_pairs",
        "remaining_pairs_after": "remaining_pairs_after",
        "elapsed_seconds": "engine_elapsed_seconds",
        "user_cpu_seconds": "engine_user_cpu_seconds",
        "system_cpu_seconds": "engine_system_cpu_seconds",
        "ru_maxrss_raw": "engine_maximum_rss_raw",
    }
    for summary_key, shard_key in mapping.items():
        _ensure(summary.get(summary_key) == shard.get(shard_key), f"{context}.{summary_key} ledger drift")
    _nonnegative_int(summary.get("expanded_relevant_models"), f"{context}.expanded_relevant_models")
    _nonnegative_int(summary.get("expanded_source_satisfactions"), f"{context}.expanded_source_satisfactions")


def _iter_log_rows(path: Path) -> Iterator[tuple[int, dict[str, object]]]:
    total_bytes = 0
    try:
        with gzip.open(path, "rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                total_bytes += len(raw_line)
                _ensure(total_bytes <= MAX_LOG_UNCOMPRESSED_BYTES, "sanitized log exceeds decompressed size cap")
                _ensure(len(raw_line) <= MAX_LOG_LINE_BYTES, f"sanitized log line {line_number} exceeds size cap")
                try:
                    text = raw_line.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise Stage60FullRunEvidenceError(
                        f"sanitized log line {line_number} is not UTF-8"
                    ) from exc
                value = _loads_json(text, f"{path}:{line_number}")
                _ensure(isinstance(value, dict), f"sanitized log line {line_number} is not an object")
                yield line_number, value
    except Stage60FullRunEvidenceError:
        raise
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise Stage60FullRunEvidenceError(f"cannot read sanitized logs {path}: {exc}") from exc


def _parse_event_text(text: object, context: str) -> dict[str, object]:
    _ensure(isinstance(text, str), f"{context}.text is not a string")
    value = _loads_json(text, f"{context}.text")
    _ensure(isinstance(value, dict), f"{context}.text is not a JSON event")
    _ensure("command" not in value, f"{context} leaks a command")
    return value


def _validate_logs(
    report: dict[str, object], logs_path: Path
) -> tuple[int, int]:
    raw_evidence = report.get("raw_evidence")
    _ensure(isinstance(raw_evidence, dict), "raw_evidence is not an object")
    _exact_keys(raw_evidence, {"progress_json", "final_json", "sanitized_logs"}, "raw_evidence")
    for key, relative in (("progress_json", "progress.json"), ("final_json", "final.json")):
        metadata = raw_evidence.get(key)
        _ensure(isinstance(metadata, dict), f"raw_evidence.{key} is not an object")
        _exact_keys(metadata, {"workdir_relative_path", "copied", "bytes", "sha256"}, f"raw_evidence.{key}")
        _ensure(metadata.get("workdir_relative_path") == relative, f"raw_evidence.{key} path drift")
        _ensure(metadata.get("copied") is False, f"raw_evidence.{key} copied flag drift")
        _positive_int(metadata.get("bytes"), f"raw_evidence.{key}.bytes")
        _exact_hash(metadata.get("sha256"), None, f"raw_evidence.{key}.sha256")

    logs_metadata = raw_evidence.get("sanitized_logs")
    _ensure(isinstance(logs_metadata, dict), "raw_evidence.sanitized_logs is not an object")
    _exact_keys(logs_metadata, {"path", "bytes", "sha256", "encoding"}, "raw_evidence.sanitized_logs")
    _ensure(logs_metadata.get("path") == logs_path.name, "sanitized-log path drift")
    _ensure(logs_metadata.get("encoding") == "deterministic-gzip-jsonl-v1", "sanitized-log encoding drift")
    _exact_int(logs_metadata.get("bytes"), logs_path.stat().st_size, "sanitized-log byte size")
    _exact_hash(logs_metadata.get("sha256"), sha256_path(logs_path), "sanitized-log SHA-256")
    try:
        with logs_path.open("rb") as handle:
            header = handle.read(10)
    except OSError as exc:
        raise Stage60FullRunEvidenceError(f"cannot read sanitized-log header: {exc}") from exc
    _ensure(len(header) == 10 and header[:3] == b"\x1f\x8b\x08", "sanitized-log gzip header drift")
    _ensure(header[4:8] == b"\0\0\0\0", "sanitized-log gzip timestamp is not deterministic")

    shards = report["shards"]
    _ensure(isinstance(shards, list), "shards is not a list")
    expected_shard = 0
    stderr_lines = 0
    total_rows = 0
    current_stderr_line = 0
    first_event: dict[str, object] | None = None
    last_event: dict[str, object] | None = None
    last_event_line = 0

    def finish_shard(index: int) -> None:
        nonlocal current_stderr_line, first_event, last_event, last_event_line
        _ensure(
            current_stderr_line == EXPECTED_STDERR_LINES_PER_SHARD,
            f"sanitized logs shard {index} stderr-line count drift",
        )
        _ensure(first_event is not None and last_event is not None, f"sanitized logs shard {index} lacks boundary events")
        _ensure(
            last_event_line == current_stderr_line,
            f"sanitized logs shard {index} runner-end is not the final line",
        )
        _exact_keys(first_event, {"at", "attempt", "event"}, f"shard {index} runner-start event")
        _validate_datetime(first_event.get("at"), f"shard {index} runner-start timestamp")
        _exact_int(first_event.get("attempt"), 1, f"shard {index} runner-start attempt")
        _ensure(first_event.get("event") == "runner-start", f"shard {index} runner-start event drift")
        _exact_keys(
            last_event,
            {"at", "attempt", "event", "returncode", "wall_seconds"},
            f"shard {index} runner-end event",
        )
        _validate_datetime(last_event.get("at"), f"shard {index} runner-end timestamp")
        _exact_int(last_event.get("attempt"), 1, f"shard {index} runner-end attempt")
        _ensure(last_event.get("event") == "runner-end", f"shard {index} runner-end event drift")
        _exact_int(last_event.get("returncode"), 0, f"shard {index} return code")
        _ensure(last_event.get("wall_seconds") == shards[index].get("wall_seconds"), f"shard {index} wall-time log drift")
        current_stderr_line = 0
        first_event = None
        last_event = None
        last_event_line = 0

    for physical_line, row in _iter_log_rows(logs_path):
        total_rows += 1
        _ensure(row.get("schema") == LOG_SCHEMA, f"sanitized log schema drift at line {physical_line}")
        kind = row.get("record_kind")
        if kind == "summary":
            if expected_shard > 0:
                finish_shard(expected_shard - 1)
            _ensure(expected_shard < SHARD_COUNT, "sanitized logs contain extra shard summaries")
            _exact_keys(
                row,
                {"schema", "record_kind", "shard_index", "raw_summary_sha256", "summary"},
                f"sanitized log summary row {physical_line}",
            )
            _exact_int(row.get("shard_index"), expected_shard, f"sanitized log summary index {physical_line}")
            _exact_hash(
                row.get("raw_summary_sha256"),
                str(shards[expected_shard]["summary_sha256"]),
                f"sanitized log summary hash {physical_line}",
            )
            _validate_engine_summary(row.get("summary"), shards[expected_shard], expected_shard)
            expected_shard += 1
            continue
        _ensure(kind == "stderr-line", f"unknown sanitized log record kind at line {physical_line}")
        _ensure(expected_shard > 0, "sanitized stderr appears before the first summary")
        shard_index = expected_shard - 1
        _exact_keys(
            row,
            {"schema", "record_kind", "shard_index", "line_number", "text"},
            f"sanitized stderr row {physical_line}",
        )
        _exact_int(row.get("shard_index"), shard_index, f"sanitized stderr shard index {physical_line}")
        current_stderr_line += 1
        stderr_lines += 1
        _exact_int(row.get("line_number"), current_stderr_line, f"sanitized stderr line number {physical_line}")
        _ensure(isinstance(row.get("text"), str), f"sanitized stderr text drift at line {physical_line}")
        _ensure('"command"' not in str(row["text"]), f"sanitized stderr command leak at line {physical_line}")
        if current_stderr_line == 1:
            first_event = _parse_event_text(row.get("text"), f"sanitized stderr row {physical_line}")
        last_event_candidate = row.get("text")
        if isinstance(last_event_candidate, str) and last_event_candidate.startswith("{"):
            event = _parse_event_text(last_event_candidate, f"sanitized stderr row {physical_line}")
            if event.get("event") == "runner-end":
                last_event = event
                last_event_line = current_stderr_line

    _ensure(expected_shard == SHARD_COUNT, "sanitized logs do not cover all 256 shards")
    finish_shard(SHARD_COUNT - 1)
    _ensure(total_rows == EXPECTED_LOG_ROWS, "sanitized log row count drift")
    _ensure(stderr_lines == SHARD_COUNT * EXPECTED_STDERR_LINES_PER_SHARD, "sanitized stderr total drift")
    return total_rows, stderr_lines


def validate_committed_full_run_evidence(
    repository_root: Path,
    evidence_path: Path,
    logs_path: Path,
) -> dict[str, object]:
    """Validate committed compact evidence and return summary-ready metrics.

    Only small committed files and current implementation sources are hashed.
    Pair-bitset bytes are not opened by this function.
    """

    repository_root = repository_root.resolve()
    evidence_path = evidence_path.resolve()
    logs_path = logs_path.resolve()
    _ensure(repository_root.is_dir(), f"missing repository root: {repository_root}")
    _ensure(evidence_path.is_file(), f"missing Stage 60 evidence report: {evidence_path}")
    _ensure(logs_path.is_file(), f"missing Stage 60 sanitized logs: {logs_path}")

    report = _load_report(evidence_path)
    _validate_report_header(report)
    _validate_bitset_claims(report)
    _validate_implementation(repository_root, report)
    _validate_retry_and_accounting(report)
    shard_totals = _validate_shards(report)
    _validate_timing_and_rss(report, shard_totals)
    log_rows, stderr_lines = _validate_logs(report, logs_path)

    return {
        "status": "validated-exact",
        "completed_at": report["completed_at"],
        "configuration": report["configuration"],
        "enumeration_method": report["enumeration_method"],
        "historical_seed_chain_used": False,
        "accounting": report["enumeration_accounting"],
        "timing": report["enumeration_timing"],
        "retry_status": report["retry_status"],
        "maximum_engine_rss_bytes": report["maximum_engine_rss_bytes"],
        "compiler_engine": report["compiler_engine"],
        "bitsets": report["bitsets"],
        "pair_bitset_stream_validation": report["pair_bitset_stream_validation"],
        "shards": SHARD_COUNT,
        "sanitized_log_rows": log_rows,
        "sanitized_stderr_lines": stderr_lines,
        "evidence_files": {
            "report": {
                "bytes": evidence_path.stat().st_size,
                "sha256": sha256_path(evidence_path),
            },
            "sanitized_logs": {
                "bytes": logs_path.stat().st_size,
                "sha256": sha256_path(logs_path),
            },
        },
    }


__all__ = [
    "Stage60FullRunEvidenceError",
    "validate_committed_full_run_evidence",
]
