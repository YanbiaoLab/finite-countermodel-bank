#!/usr/bin/env python3
"""Capture compact, durable evidence from a successful full seed-free run.

The capture contains no pair bitset.  It rehashes both large work bitsets, binds
all 256 shard summaries and stderr logs to ``progress.json``/``final.json``, and
emits a sanitized JSON report plus deterministic-gzip JSONL evidence.  Full raw
summary content and raw summary/stderr SHA-256 values are retained; stderr text is
sanitized before publication.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import os
import tempfile
import sys
from pathlib import Path
from typing import Callable, Iterator, TextIO


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from tools.stage60_seedfree import (  # noqa: E402
    BITSLICE_ENGINE_BYTES,
    BITSLICE_ENGINE_SHA256,
    FINAL_284_BYTES,
    FINAL_284_SHA256,
    SOURCE_324_BYTES,
    SOURCE_324_SHA256,
    Stage60SeedFreeError,
    file_metadata,
    sha256_path,
    verify_file,
    verify_reconstructed_inputs,
    write_json_atomic,
)
import run_seedfree as seedfree_runner  # noqa: E402


RUN_SCHEMA = "stage60-seedfree-run-v2"
FINAL_SCHEMA = "stage60-seedfree-final-v2"
CAPTURE_SCHEMA = "stage60-seedfree-full-run-evidence-v1"
LOG_SCHEMA = "stage60-seedfree-sanitized-log-line-v1"
FULL_TABLE_COUNT = 1 << 32
SHARD_SIZE = 1 << 24
SHARD_COUNT = 256
MAX_LOG_BYTES_PER_SHARD = 16 * 1024 * 1024
MAX_LOG_LINE_CHARS = 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="durable destination, for example the Stage 60 verification directory",
    )
    return parser.parse_args()


def load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage60SeedFreeError(f"cannot read evidence JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage60SeedFreeError(f"evidence JSON is not an object: {path}")
    return value


def safe_work_path(work_dir: Path, relative: object) -> Path:
    if not isinstance(relative, str):
        raise Stage60SeedFreeError("non-string path in shard evidence")
    parsed = Path(relative)
    if not relative or parsed.is_absolute() or ".." in parsed.parts:
        raise Stage60SeedFreeError(f"unsafe shard evidence path: {relative!r}")
    path = work_dir / parsed
    if path.is_symlink():
        raise Stage60SeedFreeError(f"symlinked shard evidence is not accepted: {relative}")
    return path


def verify_large_bitsets(work_dir: Path) -> dict[str, object]:
    source = verify_file(
        work_dir / "source/324M_remaining_pairs.bitset",
        expected_bytes=SOURCE_324_BYTES,
        expected_sha256=SOURCE_324_SHA256,
    )
    residual = verify_file(
        work_dir / "run/remaining_pairs.bitset",
        expected_bytes=FINAL_284_BYTES,
        expected_sha256=FINAL_284_SHA256,
    )
    return {"source_324m": source, "residual_284m": residual}


def verify_work_runtime(
    work_dir: Path, environment: dict[str, object]
) -> dict[str, object]:
    """Bind the capture to the exact recovered inputs and compiled engine."""

    inputs = verify_reconstructed_inputs(work_dir / "inputs")
    source = verify_file(
        work_dir / "source/fin4_bitslice_opposite_engine.c",
        expected_bytes=BITSLICE_ENGINE_BYTES,
        expected_sha256=BITSLICE_ENGINE_SHA256,
    )
    build = load_object(work_dir / "build.json")
    if (
        build.get("schema") != "stage60-seedfree-engine-build-v1"
        or build.get("source_sha256") != BITSLICE_ENGINE_SHA256
        or build.get("compiler") != environment.get("compiler")
        or build.get("compiler_version") != environment.get("compiler_version")
        or build.get("executable_sha256") != environment.get("engine_sha256")
        or not isinstance(build.get("executable_bytes"), int)
        or int(build["executable_bytes"]) <= 0
        or not isinstance(build.get("self_test"), dict)
        or build["self_test"].get("status") != "ok"
        or build["self_test"].get("permutations") != 24
    ):
        raise Stage60SeedFreeError("captured compiler/engine build identity drift")
    executable = verify_file(
        work_dir / "bin/fin4_bitslice_opposite_engine",
        expected_bytes=int(build["executable_bytes"]),
        expected_sha256=str(environment["engine_sha256"]),
    )
    return {
        "reconstructed_inputs": inputs,
        "engine_source": source,
        "engine_executable": executable,
    }


def acquire_capture_lock(work_dir: Path) -> TextIO:
    path = work_dir / ".seedfree.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise Stage60SeedFreeError(
            "cannot capture evidence while the Stage 60 work directory is active"
        ) from exc
    return handle


def release_capture_lock(handle: TextIO | None) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def validate_run_objects(
    work_dir: Path,
    progress: dict[str, object],
    final: dict[str, object],
) -> list[dict[str, object]]:
    configuration = {
        "range_start": 0,
        "range_count": FULL_TABLE_COUNT,
        "range_end": FULL_TABLE_COUNT,
        "shard_size": SHARD_SIZE,
        "shard_count": SHARD_COUNT,
    }
    environment = progress.get("environment_initial")
    if not isinstance(environment, dict):
        raise Stage60SeedFreeError("full-run progress environment evidence drift")
    current_identity = seedfree_runner.implementation_identity(REPOSITORY_ROOT)
    if environment.get("implementation_identity") != current_identity:
        raise Stage60SeedFreeError(
            "full-run evidence was produced by different implementation bytes"
        )
    seedfree_runner.validate_progress_structure(
        progress, configuration, environment
    )
    seedfree_runner.validate_final_structure(
        final, progress, configuration, environment
    )
    if (
        progress.get("schema") != RUN_SCHEMA
        or progress.get("status") != "complete"
        or progress.get("configuration") != configuration
        or final.get("schema") != FINAL_SCHEMA
        or final.get("status") != "complete"
        or final.get("configuration") != configuration
        or progress.get("final") != final
    ):
        raise Stage60SeedFreeError("full-run progress/final identity drift")
    if (
        final.get("committed_284m_exact_match") is not True
        or final.get("work_bitset_bytes") != FINAL_284_BYTES
        or final.get("work_bitset_sha256") != FINAL_284_SHA256
        or final.get("declared_remaining_pairs") != 284_151_591
        or final.get("fin4_incremental_covered_pairs") != 40_006_076
        or final.get("historical_seed_chain_used") is not False
        or final.get("enumeration_method")
        != "seed-free-all-bitslice-opposite-result-level"
    ):
        raise Stage60SeedFreeError("full-run final bitset claim drift")
    accounting = final.get("enumeration_accounting")
    expected_accounting = {
        "raw_tables_scanned": FULL_TABLE_COUNT,
        "canonical_models": 178_981_952,
        "model_signatures_evaluated": 89_521_056,
        "opposite_signatures_derived": 89_460_896,
        "canonical_models_skipped_as_derived": 89_460_896,
        "evaluated_plus_skipped": 178_981_952,
        "evaluated_plus_derived": 178_981_952,
        "authoritative_bitset_difference": 40_006_076,
    }
    if not isinstance(accounting, dict) or any(
        accounting.get(key) != value for key, value in expected_accounting.items()
    ):
        raise Stage60SeedFreeError("full-run enumeration accounting drift")
    if (
        final.get("implementation_identity") != progress.get("implementation_identity")
        or final.get("input_hashes") != progress.get("input_hashes")
    ):
        raise Stage60SeedFreeError("full-run implementation/input identity drift")

    completed = progress.get("completed_shards")
    final_shards = final.get("shard_evidence")
    if (
        not isinstance(completed, list)
        or not isinstance(final_shards, list)
        or len(completed) != SHARD_COUNT
        or len(final_shards) != SHARD_COUNT
        or progress.get("next_shard") != SHARD_COUNT
    ):
        raise Stage60SeedFreeError("full-run shard-count evidence drift")
    for index, (record, final_record) in enumerate(zip(completed, final_shards)):
        if not isinstance(record, dict) or not isinstance(final_record, dict):
            raise Stage60SeedFreeError(f"invalid shard evidence object {index}")
        expected_start = index * SHARD_SIZE
        if (
            record.get("index") != index
            or record.get("range_start") != expected_start
            or record.get("range_count") != SHARD_SIZE
            or final_record.get("index") != index
        ):
            raise Stage60SeedFreeError(f"full-run shard continuity drift at {index}")
        for key, value in final_record.items():
            if record.get(key) != value:
                raise Stage60SeedFreeError(
                    f"progress/final shard evidence drift at {index}.{key}"
                )
        for path_field, hash_field in (
            ("summary", "summary_sha256"),
            ("stderr_log", "stderr_sha256"),
        ):
            path = safe_work_path(work_dir, record.get(path_field))
            if not path.is_file() or sha256_path(path) != record.get(hash_field):
                raise Stage60SeedFreeError(
                    f"full-run shard {index} {path_field} hash drift"
                )
        summary = load_object(safe_work_path(work_dir, record["summary"]))
        seedfree_runner.validate_shard_result(
            summary,
            configuration=configuration,
            start=expected_start,
            count=SHARD_SIZE,
            threads=int(record["threads"]),
        )
        seedfree_runner.validate_shard_checkpoint(
            summary,
            expected_initial=(
                324_157_667
                if index == 0
                else int(completed[index - 1]["remaining_pairs_after"])
            ),
            retried=bool(record["resumed_after_incomplete_attempt"]),
        )
        summary_to_record = {
            "raw_tables_scanned": "raw_tables_scanned",
            "canonical_models_in_range": "canonical_models",
            "model_signatures_evaluated": "model_signatures_evaluated",
            "opposite_signatures_derived": "opposite_signatures_derived",
            "canonical_models_skipped_as_derived": (
                "canonical_models_skipped_as_derived"
            ),
            "expanded_models_accounted_now": "expanded_models_accounted_now",
            "initial_remaining_pairs": "initial_remaining_pairs",
            "covered_pairs": "covered_pairs",
            "remaining_pairs_after": "remaining_pairs_after",
            "elapsed_seconds": "engine_elapsed_seconds",
            "user_cpu_seconds": "engine_user_cpu_seconds",
            "system_cpu_seconds": "engine_system_cpu_seconds",
            "ru_maxrss_raw": "engine_maximum_rss_raw",
        }
        for summary_field, record_field in summary_to_record.items():
            if summary.get(summary_field) != record.get(record_field):
                raise Stage60SeedFreeError(
                    f"full-run shard summary/ledger drift at {index}.{summary_field}"
                )
    return completed


def sanitized_log_rows(
    work_dir: Path,
    completed: list[dict[str, object]],
    workdir_aliases: set[str] | None = None,
) -> Iterator[dict[str, object]]:
    aliases = sorted(
        workdir_aliases or {str(work_dir)}, key=len, reverse=True
    )
    for record in completed:
        index = int(record["index"])
        summary_path = safe_work_path(work_dir, record["summary"])
        yield {
            "schema": LOG_SCHEMA,
            "record_kind": "summary",
            "shard_index": index,
            "raw_summary_sha256": record["summary_sha256"],
            "summary": load_object(summary_path),
        }
        path = safe_work_path(work_dir, record["stderr_log"])
        if path.stat().st_size > MAX_LOG_BYTES_PER_SHARD:
            raise Stage60SeedFreeError(f"shard {index} stderr log exceeds safety cap")
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if len(raw_line) > MAX_LOG_LINE_CHARS:
                    raise Stage60SeedFreeError(
                        f"shard {index} stderr line exceeds safety cap"
                    )
                text = raw_line.rstrip("\r\n")
                for alias in aliases:
                    text = text.replace(alias, "<WORKDIR>")
                if text.startswith("{"):
                    try:
                        event = json.loads(text)
                    except json.JSONDecodeError:
                        event = None
                    if isinstance(event, dict):
                        event.pop("command", None)
                        text = json.dumps(
                            event,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                yield {
                    "schema": LOG_SCHEMA,
                    "record_kind": "stderr-line",
                    "shard_index": index,
                    "line_number": line_number,
                    "text": text,
                }


def write_deterministic_log_gzip(
    path: Path, rows: Iterator[dict[str, object]]
) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as raw, gzip.GzipFile(
            filename="", mode="wb", compresslevel=9, mtime=0, fileobj=raw
        ) as compressed:
            for row in rows:
                compressed.write(
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
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return file_metadata(path)


def capture_evidence(
    work_dir: Path,
    output_dir: Path,
    *,
    bitset_verifier: Callable[[Path], dict[str, object]] | None = None,
    runtime_verifier: Callable[
        [Path, dict[str, object]], dict[str, object]
    ]
    | None = None,
) -> dict[str, object]:
    workdir_aliases = {str(work_dir.absolute()), str(work_dir.resolve())}
    work_dir = work_dir.resolve()
    output_dir = output_dir.resolve()
    progress_path = work_dir / "progress.json"
    final_path = work_dir / "final.json"
    progress = load_object(progress_path)
    final = load_object(final_path)
    completed = validate_run_objects(work_dir, progress, final)
    environment = final.get("environment")
    if not isinstance(environment, dict):
        raise Stage60SeedFreeError("full-run environment evidence drift")
    verify_runtime = runtime_verifier or verify_work_runtime
    runtime = verify_runtime(work_dir, environment)
    verify_bitsets = bitset_verifier or verify_large_bitsets
    bitsets = verify_bitsets(work_dir)
    expected_bitsets = {
        "source_324m": {"bytes": SOURCE_324_BYTES, "sha256": SOURCE_324_SHA256},
        "residual_284m": {"bytes": FINAL_284_BYTES, "sha256": FINAL_284_SHA256},
    }
    if bitsets != expected_bitsets:
        raise Stage60SeedFreeError("captured full-run bitset hash evidence drift")

    logs_path = output_dir / "seedfree-full-run-logs.jsonl.gz"
    logs_metadata = write_deterministic_log_gzip(
        logs_path,
        sanitized_log_rows(work_dir, completed, workdir_aliases),
    )
    compiler_engine = final.get("compiler_engine")
    if not isinstance(environment, dict) or not isinstance(compiler_engine, dict):
        raise Stage60SeedFreeError("full-run environment/compiler evidence drift")
    compiler = str(compiler_engine.get("compiler", ""))
    compiler_version = str(compiler_engine.get("compiler_version", ""))
    report = {
        "schema": CAPTURE_SCHEMA,
        "status": "validated-exact",
        "completed_at": final["completed_at"],
        "configuration": final["configuration"],
        "enumeration_method": final["enumeration_method"],
        "historical_seed_chain_used": False,
        "bitsets": bitsets,
        "enumeration_accounting": final["enumeration_accounting"],
        "enumeration_timing": final["enumeration_timing"],
        "retry_status": final["retry_status"],
        "maximum_engine_rss_raw": final["maximum_engine_rss_raw"],
        "maximum_engine_rss_raw_unit": final["maximum_engine_rss_raw_unit"],
        "maximum_engine_rss_bytes": final["maximum_engine_rss_bytes"],
        "pair_bitset_stream_validation": final["pair_bitset_stream_validation"],
        "input_hashes": final["input_hashes"],
        "implementation_identity": final["implementation_identity"],
        "work_runtime": runtime,
        "capture_implementation": {
            "path": "reproduction/60-fin4-residual-284151591/scripts/capture_seedfree_evidence.py",
            "sha256": sha256_path(Path(__file__).resolve()),
        },
        "environment": {
            key: environment.get(key)
            for key in ("python", "platform", "machine", "byteorder", "cpu_count")
        },
        "compiler_engine": {
            "compiler_executable_name": Path(compiler).name,
            "compiler_version_first_line": compiler_version.splitlines()[0]
            if compiler_version
            else "",
            "engine_sha256": compiler_engine.get("engine_sha256"),
            "engine_source_sha256": compiler_engine.get("engine_source_sha256"),
        },
        "shards": final["shard_evidence"],
        "raw_evidence": {
            "progress_json": {
                "workdir_relative_path": "progress.json",
                "copied": False,
                **file_metadata(progress_path),
            },
            "final_json": {
                "workdir_relative_path": "final.json",
                "copied": False,
                **file_metadata(final_path),
            },
            "sanitized_logs": {
                "path": logs_path.name,
                **logs_metadata,
                "encoding": "deterministic-gzip-jsonl-v1",
            },
        },
        "scope_boundary": (
            "This captures a new seed-free result-level run. It does not recover "
            "the historical seeded execution/provenance chain."
        ),
    }
    write_json_atomic(output_dir / "seedfree-full-run.json", report)
    return report


def main() -> int:
    args = parse_args()
    lock: TextIO | None = None
    try:
        work_dir = args.work_dir.resolve()
        if not work_dir.is_dir():
            raise Stage60SeedFreeError(f"missing work directory: {work_dir}")
        lock = acquire_capture_lock(work_dir)
        report = capture_evidence(work_dir, args.output_dir)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"evidence_dir={args.output_dir.resolve()}")
        return 0
    except (OSError, ValueError, KeyError, TypeError, Stage60SeedFreeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        release_capture_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
