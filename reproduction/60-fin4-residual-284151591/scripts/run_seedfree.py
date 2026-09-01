#!/usr/bin/env python3
"""Run a resumable, seed-free Stage 60 Fin4 outcome enumeration.

The default range is the complete ``[0, 2^32)`` labeled-table universe, split
into historical ``2^24``-table shards.  A full run is intentionally guarded by
``--confirm-full-run``.  Any actual enumeration, including a small range, needs
two 489,598,720-byte bitsets and is not a normal CI task.  No historical
6,173-model seed file is read or required.  This uses the
preserved bitslice/opposite engine across the whole requested range; it is a
new result-level method, not a replay of the historical scalar/seeded order.

All large generated files live under ``--work-dir``.  Its default is a
checkout-specific directory under the system temporary directory, never the Git
worktree.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import json
import math
import os
import platform
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, TextIO


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.stage60_seedfree import (  # noqa: E402
    BITSLICE_ENGINE_SHA256,
    FINAL_284_BYTES,
    FINAL_284_SHA256,
    RECONSTRUCTED_INPUTS,
    SOURCE_324_BYTES,
    SOURCE_324_SHA256,
    Stage60SeedFreeError,
    copy_file_streaming,
    default_work_dir,
    extract_engine_source,
    materialize_source_324_bitset,
    reconstruct_stage60_inputs,
    sha256_path,
    verify_file,
    verify_reconstructed_inputs,
    write_json_atomic,
)
from tools.phase2_common import Stage60Error, validate_pair_bitset_streams  # noqa: E402


SCHEMA = "stage60-seedfree-run-v2"
FINAL_SCHEMA = "stage60-seedfree-final-v2"
PREPARATION_SCHEMA = "stage60-seedfree-preparation-v1"
PREFLIGHT_SCHEMA = "stage60-seedfree-disk-preflight-v1"
PAIR_MAGIC_PREFIX = b"O5RPAIR1"
FULL_TABLE_COUNT = 1 << 32
HISTORICAL_SHARD_SIZE = 1 << 24
MAX_SHARDS = 4_096
EXPECTED_EQUATIONS = 62_576
EXPECTED_ACTIVE_SOURCES = 41_696
EXPECTED_ISOMORPHISM_CLASSES = 178_981_952
EXPECTED_ANTI_ISOMORPHISM_CLASSES = 89_521_056
EXPECTED_FULL_EVALUATED = 89_521_056
EXPECTED_FULL_DERIVED = 89_460_896
DISK_RESERVE_BYTES = 256 * 1024 * 1024
PARTITION_GZIP_BYTES = 253_171
PARTITION_GZIP_SHA256 = (
    "53ff83710b96f3120ced63858255e097f11a145f3cf94bd2cff7a2639ddee287"
)
PARTITION_HEADER = [
    "source_equation_id",
    "fin23_covered_target_count",
    "singleton_true_target_count",
    "targeted_324m_target_count",
    "fin4_covered_target_count",
    "residual_284m_target_count",
]
SHARD_EVIDENCE_FIELDS = (
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
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_nonnegative(value: str) -> int:
    parsed = int(value, 0)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be nonnegative")
    return parsed


def parse_positive(value: str) -> int:
    parsed = int(value, 0)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="generated work directory (default: checkout-specific system temp path)",
    )
    parser.add_argument("--range-start", type=parse_nonnegative, default=0)
    parser.add_argument("--range-count", type=parse_positive, default=FULL_TABLE_COUNT)
    parser.add_argument("--shard-size", type=parse_positive, default=HISTORICAL_SHARD_SIZE)
    parser.add_argument(
        "--threads",
        type=parse_positive,
        default=min(10, os.cpu_count() or 1),
        help="worker threads in [1,64] (default: min(10, detected CPUs))",
    )
    parser.add_argument(
        "--max-shards",
        type=parse_nonnegative,
        help="run at most this many new shards, then exit resumably",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help=(
            "recover the small inputs and compile/self-test the engine; do not "
            "materialize pair bitsets or create progress"
        ),
    )
    parser.add_argument(
        "--confirm-full-run",
        action="store_true",
        help="explicitly permit the complete 2^32-table run",
    )
    parser.add_argument(
        "--cc",
        default=os.environ.get("CC", "clang"),
        help="C compiler executable (default: CC or clang)",
    )
    return parser.parse_args()


def bounded_command_output(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.stdout[:16_384]


def implementation_identity(repository: Path) -> dict[str, object]:
    """Bind resumable state to every Python component that interprets it."""

    paths = {
        "runner": repository
        / "reproduction/60-fin4-residual-284151591/scripts/run_seedfree.py",
        "input_helper": repository / "tools/stage60_seedfree.py",
        "pair_bitset_validator": repository / "tools/phase2_common.py",
        "partition_ledger": repository
        / "reproduction/60-fin4-residual-284151591"
        / "normalized/pair-partition-by-source.csv.gz",
    }
    current_runner = Path(__file__).resolve()
    if paths["runner"].resolve() != current_runner:
        raise Stage60SeedFreeError(
            "--repository-root does not contain the executing Stage 60 runner"
        )
    verify_file(
        paths["partition_ledger"],
        expected_bytes=PARTITION_GZIP_BYTES,
        expected_sha256=PARTITION_GZIP_SHA256,
    )
    return {
        "schema": "stage60-seedfree-implementation-identity-v1",
        "python_sources": {
            name: {
                "path": str(path.relative_to(repository)),
                "sha256": sha256_path(path),
            }
            for name, path in paths.items()
            if name != "partition_ledger"
        },
        "engine_source_sha256": BITSLICE_ENGINE_SHA256,
        "partition_ledger": {
            "path": str(paths["partition_ledger"].relative_to(repository)),
            "bytes": PARTITION_GZIP_BYTES,
            "sha256": PARTITION_GZIP_SHA256,
        },
        "reconstructed_inputs": {
            name: {"bytes": size, "sha256": digest}
            for name, (size, digest) in RECONSTRUCTED_INPUTS.items()
        },
        "source_bitset": {
            "bytes": SOURCE_324_BYTES,
            "sha256": SOURCE_324_SHA256,
        },
    }


def acquire_workdir_lock(work_dir: Path) -> TextIO:
    """Acquire a nonblocking POSIX lock and keep its inode for future runs."""

    lock_path = work_dir / ".seedfree.lock"
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.seek(0)
        holder = handle.read(4_096).strip() or "unknown holder"
        handle.close()
        raise Stage60SeedFreeError(
            f"Stage 60 work directory is locked by another process: {holder}"
        ) from exc
    handle.seek(0)
    handle.truncate()
    handle.write(
        json.dumps(
            {"pid": os.getpid(), "acquired_at": utc_now(), "argv": sys.argv},
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
    handle.flush()
    os.fsync(handle.fileno())
    return handle


def release_workdir_lock(handle: TextIO | None) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def disk_preflight(work_dir: Path) -> dict[str, object]:
    """Require space for each missing bitset plus an explicit safety reserve."""

    expected_paths = [
        work_dir / "source/324M_remaining_pairs.bitset",
        work_dir / "run/remaining_pairs.bitset",
    ]
    entries: list[dict[str, object]] = []
    missing_bytes = 0
    for path in expected_paths:
        exists = path.exists()
        if exists and (not path.is_file() or path.stat().st_size != SOURCE_324_BYTES):
            raise Stage60SeedFreeError(
                f"existing Stage 60 bitset has unexpected type/size: {path}"
            )
        if not exists:
            missing_bytes += SOURCE_324_BYTES
        entries.append(
            {
                "path": str(path.relative_to(work_dir)),
                "exists": exists,
                "bytes_if_missing": 0 if exists else SOURCE_324_BYTES,
            }
        )
    usage = shutil.disk_usage(work_dir)
    required = missing_bytes + DISK_RESERVE_BYTES
    report = {
        "schema": PREFLIGHT_SCHEMA,
        "checked_at": utc_now(),
        "filesystem_total_bytes": usage.total,
        "filesystem_used_bytes": usage.used,
        "filesystem_free_bytes": usage.free,
        "missing_bitset_bytes": missing_bytes,
        "reserve_bytes": DISK_RESERVE_BYTES,
        "required_free_bytes": required,
        "bitsets": entries,
        "status": "ok" if usage.free >= required else "insufficient-space",
    }
    write_json_atomic(work_dir / "preflight.json", report)
    if usage.free < required:
        raise Stage60SeedFreeError(
            "insufficient free disk for Stage 60 enumeration: "
            f"need {required} bytes ({missing_bytes} for missing bitsets plus "
            f"{DISK_RESERVE_BYTES} reserve), found {usage.free}"
        )
    return report


def compile_engine(
    repository: Path,
    work_dir: Path,
    compiler_name: str,
) -> tuple[Path, dict[str, object]]:
    source = work_dir / "source/fin4_bitslice_opposite_engine.c"
    extract_engine_source(repository, source, bitslice=True)
    compiler = shutil.which(compiler_name)
    if compiler is None:
        raise Stage60SeedFreeError(f"C compiler not found: {compiler_name}")
    compiler = str(Path(compiler).resolve())
    version = bounded_command_output([compiler, "--version"])
    executable = work_dir / "bin/fin4_bitslice_opposite_engine"
    build_report_path = work_dir / "build.json"
    command = [
        compiler,
        "-O3",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-pthread",
        str(source),
        "-o",
        str(executable),
    ]
    expected_build = {
        "schema": "stage60-seedfree-engine-build-v1",
        "source_sha256": BITSLICE_ENGINE_SHA256,
        "compiler": compiler,
        "compiler_version": version,
        "command": command,
    }
    if executable.exists() or build_report_path.exists():
        if not executable.is_file() or not build_report_path.is_file():
            raise Stage60SeedFreeError(
                f"partial compiler output in {work_dir}; use a clean work directory"
            )
        observed = json.loads(build_report_path.read_text(encoding="utf-8"))
        for key, value in expected_build.items():
            if observed.get(key) != value:
                raise Stage60SeedFreeError(
                    f"compiler configuration drift for existing work directory: {key}"
                )
        executable_hash = sha256_path(executable)
        if observed.get("executable_sha256") != executable_hash:
            raise Stage60SeedFreeError("compiled Fin4 engine hash drift")
        return executable, observed

    executable.parent.mkdir(parents=True, exist_ok=True)
    temporary = executable.with_name(executable.name + ".partial")
    completed = subprocess.run(command[:-1] + [str(temporary)], capture_output=True, text=True)
    if completed.returncode != 0:
        if temporary.exists():
            temporary.unlink()
        raise Stage60SeedFreeError(
            "Fin4 engine compilation failed:\n"
            + (completed.stdout + completed.stderr)[-16_384:]
        )
    temporary.chmod(0o755)
    os.replace(temporary, executable)
    build_report = {
        **expected_build,
        "executable_bytes": executable.stat().st_size,
        "executable_sha256": sha256_path(executable),
        "compiled_at": utc_now(),
        "compiler_stdout": completed.stdout[:16_384],
        "compiler_stderr": completed.stderr[:16_384],
    }
    self_test = subprocess.run(
        [str(executable), "self-test"], capture_output=True, text=True
    )
    if self_test.returncode != 0:
        raise Stage60SeedFreeError(
            "compiled Fin4 engine self-test failed:\n" + self_test.stderr[-16_384:]
        )
    try:
        self_test_json = json.loads(self_test.stdout)
    except json.JSONDecodeError as exc:
        raise Stage60SeedFreeError("Fin4 engine self-test returned invalid JSON") from exc
    if self_test_json.get("status") != "ok" or self_test_json.get("permutations") != 24:
        raise Stage60SeedFreeError("Fin4 engine self-test invariant drift")
    build_report["self_test"] = self_test_json
    write_json_atomic(build_report_path, build_report)
    return executable, build_report


def inspect_pair_header(path: Path) -> dict[str, int]:
    if not path.is_file() or path.stat().st_size != SOURCE_324_BYTES:
        raise Stage60SeedFreeError(f"bad Stage 60 work-bitset size: {path}")
    with path.open("rb") as handle:
        header = handle.read(96)
    if len(header) < 96 or header[:8] != PAIR_MAGIC_PREFIX:
        raise Stage60SeedFreeError(f"bad Stage 60 work-bitset header: {path}")
    version, header_bytes, equation_count, word_count, row_stride, bit_order = struct.unpack_from(
        "<6I", header, 16
    )
    universe, declared_remaining, payload_bytes = struct.unpack_from("<3Q", header, 40)
    if (
        version != 1
        or header_bytes != 4096
        or equation_count != EXPECTED_EQUATIONS
        or word_count != 978
        or row_stride != 7824
        or bit_order != 1
        or universe != EXPECTED_EQUATIONS * (EXPECTED_EQUATIONS - 1)
        or payload_bytes != EXPECTED_EQUATIONS * 7824
    ):
        raise Stage60SeedFreeError(f"unsupported Stage 60 work-bitset header: {path}")
    return {
        "declared_remaining": declared_remaining,
        "equation_count": equation_count,
        "bytes": path.stat().st_size,
    }


def environment_record(
    build: dict[str, object], repository: Path
) -> dict[str, object]:
    _factor, raw_unit = ru_maxrss_conversion()
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
        "cpu_count": os.cpu_count(),
        "compiler": build["compiler"],
        "compiler_version": build["compiler_version"],
        "engine_sha256": build["executable_sha256"],
        "engine_source_sha256": BITSLICE_ENGINE_SHA256,
        "ru_maxrss_raw_unit": raw_unit,
        "implementation_identity": implementation_identity(repository),
    }


def ru_maxrss_conversion() -> tuple[int, str]:
    """Return the platform conversion from getrusage.ru_maxrss to bytes.

    Darwin reports bytes.  Linux and the BSDs conventionally report KiB.  The
    runner records both the untouched C-engine value and this explicit unit so
    that resource reports never compare the raw numbers across platforms.
    """

    system = platform.system()
    if system == "Darwin":
        return 1, "bytes"
    if system in {"Linux", "FreeBSD", "OpenBSD", "NetBSD"}:
        return 1024, "KiB"
    raise Stage60SeedFreeError(
        f"unsupported ru_maxrss unit on platform {system!r}; add an explicit conversion"
    )


def normalized_rss(raw_value: object) -> tuple[int, str]:
    raw = int(raw_value)
    if raw < 0:
        raise Stage60SeedFreeError("Fin4 engine returned negative ru_maxrss")
    factor, unit = ru_maxrss_conversion()
    return raw * factor, unit


def run_configuration(args: argparse.Namespace) -> dict[str, int]:
    if not 1 <= args.threads <= 64:
        raise Stage60SeedFreeError("--threads must be in [1,64]")
    if args.range_start >= FULL_TABLE_COUNT:
        raise Stage60SeedFreeError("--range-start is outside [0,2^32)")
    if args.range_count > FULL_TABLE_COUNT - args.range_start:
        raise Stage60SeedFreeError("requested range extends beyond 2^32 tables")
    configuration = {
        "range_start": args.range_start,
        "range_count": args.range_count,
        "range_end": args.range_start + args.range_count,
        "shard_size": args.shard_size,
        "shard_count": (args.range_count + args.shard_size - 1) // args.shard_size,
    }
    if configuration["shard_count"] > MAX_SHARDS:
        raise Stage60SeedFreeError(
            f"requested {configuration['shard_count']} shards exceeds safety limit {MAX_SHARDS}"
        )
    return configuration


def _progress_int(value: object, context: str) -> int:
    if type(value) is not int or int(value) < 0:
        raise Stage60SeedFreeError(f"invalid nonnegative integer in progress: {context}")
    return int(value)


def _progress_hash(value: object, context: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Stage60SeedFreeError(f"invalid SHA-256 in progress: {context}")
    return value


def validate_progress_structure(
    progress: dict[str, object],
    configuration: dict[str, int],
    environment: dict[str, object],
) -> None:
    """Reject discontinuous, stale-code, or internally inconsistent resume state."""

    if progress.get("schema") != SCHEMA:
        raise Stage60SeedFreeError("unsupported existing seed-free progress schema")
    if progress.get("configuration") != configuration:
        raise Stage60SeedFreeError("existing seed-free progress configuration differs")
    if progress.get("implementation_identity") != environment["implementation_identity"]:
        raise Stage60SeedFreeError(
            "existing seed-free progress was created by different implementation bytes"
        )
    initial_environment = progress.get("environment_initial")
    if not isinstance(initial_environment, dict) or initial_environment != environment:
        raise Stage60SeedFreeError(
            "existing progress environment/compiler/engine identity drift"
        )
    if progress.get("input_hashes") != {
        name: digest for name, (_size, digest) in RECONSTRUCTED_INPUTS.items()
    }:
        raise Stage60SeedFreeError("existing progress reconstructed-input hashes drift")
    if (
        progress.get("source_bitset_bytes") != SOURCE_324_BYTES
        or progress.get("source_bitset_sha256") != SOURCE_324_SHA256
        or progress.get("historical_seed_chain_used") is not False
        or progress.get("enumeration_method")
        != "seed-free-all-bitslice-opposite-result-level"
    ):
        raise Stage60SeedFreeError("existing progress source/method identity drift")

    next_shard = _progress_int(progress.get("next_shard"), "next_shard")
    if next_shard > configuration["shard_count"]:
        raise Stage60SeedFreeError("existing progress next_shard exceeds shard_count")
    completed = progress.get("completed_shards")
    if not isinstance(completed, list) or len(completed) != next_shard:
        raise Stage60SeedFreeError(
            "existing progress completed_shards is not contiguous with next_shard"
    )
    prior_remaining = 324_157_667
    maximum_record_rss_raw = 0
    maximum_record_rss_bytes = 0
    for index, record in enumerate(completed):
        if not isinstance(record, dict):
            raise Stage60SeedFreeError(f"invalid completed shard record {index}")
        start, count = shard_bounds(configuration, index)
        expected = {
            "index": index,
            "range_start": start,
            "range_count": count,
            "raw_tables_scanned": count,
        }
        for key, value in expected.items():
            if record.get(key) != value:
                raise Stage60SeedFreeError(
                    f"completed shard {index} continuity drift for {key}"
                )
        attempt = _progress_int(record.get("attempt"), f"shard {index} attempt")
        if attempt < 1:
            raise Stage60SeedFreeError(f"completed shard {index} has zero attempts")
        retried = record.get("resumed_after_incomplete_attempt")
        if type(retried) is not bool or retried != (attempt > 1):
            raise Stage60SeedFreeError(f"completed shard {index} retry marker drift")
        initial = _progress_int(
            record.get("initial_remaining_pairs"), f"shard {index} initial"
        )
        covered = _progress_int(record.get("covered_pairs"), f"shard {index} covered")
        remaining = _progress_int(
            record.get("remaining_pairs_after"), f"shard {index} remaining"
        )
        if initial - covered != remaining:
            raise Stage60SeedFreeError(f"completed shard {index} pair ledger drift")
        if (not retried and initial != prior_remaining) or (
            retried and initial > prior_remaining
        ):
            raise Stage60SeedFreeError(
                f"completed shard {index} initial checkpoint continuity drift"
            )
        canonical = _progress_int(
            record.get("canonical_models"), f"shard {index} canonical"
        )
        evaluated = _progress_int(
            record.get("model_signatures_evaluated"), f"shard {index} evaluated"
        )
        derived = _progress_int(
            record.get("opposite_signatures_derived"), f"shard {index} derived"
        )
        skipped = _progress_int(
            record.get("canonical_models_skipped_as_derived"),
            f"shard {index} skipped",
        )
        expanded = _progress_int(
            record.get("expanded_models_accounted_now"), f"shard {index} expanded"
        )
        if (
            canonical > count
            or derived > evaluated
            or evaluated + skipped != canonical
            or evaluated + derived != expanded
        ):
            raise Stage60SeedFreeError(
                f"completed shard {index} model-accounting drift"
            )
        if record.get("summary") != f"shards/shard_{index:03d}.json" or record.get(
            "stderr_log"
        ) != f"shards/shard_{index:03d}.stderr.log":
            raise Stage60SeedFreeError(f"completed shard {index} evidence path drift")
        _progress_hash(record.get("summary_sha256"), f"shard {index} summary")
        _progress_hash(record.get("stderr_sha256"), f"shard {index} stderr")
        threads = _progress_int(record.get("threads"), f"shard {index} threads")
        if not 1 <= threads <= 64:
            raise Stage60SeedFreeError(f"completed shard {index} thread-count drift")
        for field in (
            "wall_seconds",
            "engine_elapsed_seconds",
            "engine_user_cpu_seconds",
            "engine_system_cpu_seconds",
        ):
            value = record.get(field)
            if type(value) not in {int, float} or not math.isfinite(float(value)) or value < 0:
                raise Stage60SeedFreeError(
                    f"completed shard {index} invalid resource value {field}"
                )
        rss_raw = _progress_int(
            record.get("engine_maximum_rss_raw"), f"shard {index} maximum RSS raw"
        )
        rss_unit = record.get("engine_maximum_rss_raw_unit")
        if rss_unit != environment["ru_maxrss_raw_unit"]:
            raise Stage60SeedFreeError(f"completed shard {index} RSS unit drift")
        rss_bytes = _progress_int(
            record.get("engine_maximum_rss_bytes"),
            f"shard {index} maximum RSS bytes",
        )
        expected_rss_bytes = rss_raw * (1 if rss_unit == "bytes" else 1024)
        if rss_unit not in {"bytes", "KiB"} or rss_bytes != expected_rss_bytes:
            raise Stage60SeedFreeError(f"completed shard {index} RSS conversion drift")
        maximum_record_rss_raw = max(maximum_record_rss_raw, rss_raw)
        maximum_record_rss_bytes = max(maximum_record_rss_bytes, rss_bytes)
        prior_remaining = remaining

    if _progress_int(progress.get("last_remaining_pairs"), "last_remaining_pairs") != prior_remaining:
        raise Stage60SeedFreeError("existing progress last_remaining_pairs drift")
    if (
        _progress_int(progress.get("maximum_engine_rss_raw"), "maximum_engine_rss_raw")
        != maximum_record_rss_raw
        or _progress_int(
            progress.get("maximum_engine_rss_bytes"), "maximum_engine_rss_bytes"
        )
        != maximum_record_rss_bytes
    ):
        raise Stage60SeedFreeError("existing progress maximum RSS ledger drift")
    if progress.get("maximum_engine_rss_raw_unit") != environment["ru_maxrss_raw_unit"]:
        raise Stage60SeedFreeError("existing progress ru_maxrss unit drift")
    preflights = progress.get("preflight_runs")
    if not isinstance(preflights, list) or not preflights or any(
        not isinstance(value, dict) or value.get("schema") != PREFLIGHT_SCHEMA
        for value in preflights
    ):
        raise Stage60SeedFreeError("existing progress disk-preflight history drift")

    status = progress.get("status")
    inflight = progress.get("inflight")
    if inflight is None:
        if status not in {"ready", "paused", "complete"}:
            raise Stage60SeedFreeError("existing progress status/inflight drift")
        if status == "ready" and next_shard != 0:
            raise Stage60SeedFreeError("ready progress has completed shards")
        if status == "paused" and not 0 < next_shard < configuration["shard_count"]:
            raise Stage60SeedFreeError("paused progress is not at an interior boundary")
        if status == "complete" and next_shard != configuration["shard_count"]:
            raise Stage60SeedFreeError("complete progress lacks all shards")
    else:
        if not isinstance(inflight, dict) or status != "running":
            raise Stage60SeedFreeError("existing progress in-flight structure drift")
        if next_shard >= configuration["shard_count"]:
            raise Stage60SeedFreeError("in-flight progress is past final shard")
        start, count = shard_bounds(configuration, next_shard)
        for key, value in {
            "index": next_shard,
            "range_start": start,
            "range_count": count,
        }.items():
            if inflight.get(key) != value:
                raise Stage60SeedFreeError(f"in-flight shard continuity drift for {key}")
        attempt = _progress_int(inflight.get("attempt"), "in-flight attempt")
        if attempt < 1 or inflight.get("resumed_after_incomplete_attempt") != (attempt > 1):
            raise Stage60SeedFreeError("in-flight retry marker drift")
        threads = _progress_int(inflight.get("threads"), "in-flight threads")
        if not 1 <= threads <= 64:
            raise Stage60SeedFreeError("in-flight thread-count drift")
        inflight_environment = inflight.get("environment")
        if not isinstance(inflight_environment, dict) or inflight_environment != environment:
            raise Stage60SeedFreeError("in-flight environment/compiler identity drift")


def validate_completed_evidence_files(
    work_dir: Path, progress: dict[str, object]
) -> None:
    completed = progress.get("completed_shards")
    if not isinstance(completed, list):
        raise Stage60SeedFreeError("progress lacks completed shard evidence")
    for record in completed:
        assert isinstance(record, dict)
        index = int(record["index"])
        for path_field, hash_field in (
            ("summary", "summary_sha256"),
            ("stderr_log", "stderr_sha256"),
        ):
            relative = str(record[path_field])
            path = work_dir / relative
            if not path.is_file() or sha256_path(path) != record[hash_field]:
                raise Stage60SeedFreeError(
                    f"completed shard {index} {path_field} hash drift"
                )


def initialize_progress(
    work_dir: Path,
    configuration: dict[str, int],
    environment: dict[str, object],
    work_bitset: Path,
    preflight: dict[str, object],
) -> dict[str, object]:
    progress_path = work_dir / "progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        validate_progress_structure(progress, configuration, environment)
        validate_completed_evidence_files(work_dir, progress)
        header = inspect_pair_header(work_bitset)
        last_remaining = int(progress["last_remaining_pairs"])
        inflight = progress.get("inflight")
        if inflight is None and header["declared_remaining"] != last_remaining:
            raise Stage60SeedFreeError(
                "work-bitset header disagrees with the last committed checkpoint"
            )
        if inflight is not None and header["declared_remaining"] > last_remaining:
            raise Stage60SeedFreeError("in-flight work bitset gained set bits")
        if progress.get("status") != "complete":
            preflight_runs = progress["preflight_runs"]
            assert isinstance(preflight_runs, list)
            preflight_runs.append(preflight)
            progress["updated_at"] = utc_now()
            write_json_atomic(progress_path, progress)
        return progress

    if work_bitset.exists():
        raise Stage60SeedFreeError(
            "work bitset exists without progress.json; use a clean work directory"
        )
    source_bitset = work_dir / "source/324M_remaining_pairs.bitset"
    copied = copy_file_streaming(source_bitset, work_bitset)
    if copied != {"bytes": SOURCE_324_BYTES, "sha256": SOURCE_324_SHA256}:
        raise Stage60SeedFreeError("initialized work bitset differs from the 324M source")
    progress: dict[str, object] = {
        "schema": SCHEMA,
        "status": "ready",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "configuration": configuration,
        "environment_initial": environment,
        "implementation_identity": environment["implementation_identity"],
        "input_hashes": {
            name: digest for name, (_size, digest) in RECONSTRUCTED_INPUTS.items()
        },
        "source_bitset_bytes": SOURCE_324_BYTES,
        "source_bitset_sha256": SOURCE_324_SHA256,
        "historical_seed_chain_used": False,
        "enumeration_method": "seed-free-all-bitslice-opposite-result-level",
        "next_shard": 0,
        "last_remaining_pairs": 324_157_667,
        "maximum_engine_rss_raw": 0,
        "maximum_engine_rss_raw_unit": environment["ru_maxrss_raw_unit"],
        "maximum_engine_rss_bytes": 0,
        "preflight_runs": [preflight],
        "completed_shards": [],
        "inflight": None,
    }
    validate_progress_structure(progress, configuration, environment)
    write_json_atomic(progress_path, progress)
    return progress


def shard_bounds(configuration: dict[str, int], index: int) -> tuple[int, int]:
    start = configuration["range_start"] + index * configuration["shard_size"]
    remaining = configuration["range_end"] - start
    return start, min(configuration["shard_size"], remaining)


def validate_shard_result(
    result: dict[str, object],
    *,
    configuration: dict[str, int],
    start: int,
    count: int,
    threads: int,
) -> None:
    expected = {
        "schema_version": 1,
        "status": "complete",
        "mode": "enumerate-bitslice-inplace",
        "batch_size": 64,
        "range_start": start,
        "range_count": count,
        "pair_start": configuration["range_start"],
        "pair_end": configuration["range_end"],
        "raw_tables_scanned": count,
        "threads": threads,
        "equation_count": EXPECTED_EQUATIONS,
        "active_source_count": EXPECTED_ACTIVE_SOURCES,
        "full_fin4_isomorphism_class_target": EXPECTED_ISOMORPHISM_CLASSES,
        "full_fin4_isomorphism_or_anti_isomorphism_target": (
            EXPECTED_ANTI_ISOMORPHISM_CLASSES
        ),
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise Stage60SeedFreeError(
                f"Fin4 shard result drift for {key}: expected {value}, found {result.get(key)}"
            )
    canonical = int(result["canonical_models_in_range"])
    evaluated = int(result["model_signatures_evaluated"])
    derived = int(result["opposite_signatures_derived"])
    skipped = int(result["canonical_models_skipped_as_derived"])
    expanded = int(result["expanded_models_accounted_now"])
    if min(canonical, evaluated, derived, skipped, expanded) < 0:
        raise Stage60SeedFreeError("Fin4 shard returned negative model accounting")
    if canonical > count or derived > evaluated:
        raise Stage60SeedFreeError("Fin4 shard impossible model accounting")
    if evaluated + skipped != canonical:
        raise Stage60SeedFreeError("Fin4 shard canonical accounting mismatch")
    if evaluated + derived != expanded:
        raise Stage60SeedFreeError("Fin4 shard expanded-model accounting mismatch")
    initial = int(result["initial_remaining_pairs"])
    covered = int(result["covered_pairs"])
    final = int(result["remaining_pairs_after"])
    if initial - covered != final or final < 0:
        raise Stage60SeedFreeError("Fin4 shard pair accounting mismatch")
    for field in (
        "elapsed_seconds",
        "user_cpu_seconds",
        "system_cpu_seconds",
        "ru_maxrss_raw",
    ):
        value = result.get(field)
        if type(value) not in {int, float} or not math.isfinite(float(value)) or value < 0:
            raise Stage60SeedFreeError(f"Fin4 shard invalid resource value: {field}")


def validate_shard_checkpoint(
    result: dict[str, object], *, expected_initial: int, retried: bool
) -> None:
    actual = int(result["initial_remaining_pairs"])
    if (not retried and actual != expected_initial) or (
        retried and actual > expected_initial
    ):
        raise Stage60SeedFreeError(
            "Fin4 shard initial checkpoint drift: expected "
            f"{'at most' if retried else 'exactly'} {expected_initial}, found {actual}"
        )


def iter_committed_partition_expected(
    repository: Path,
) -> Iterator[tuple[int, int, int, int]]:
    """Yield the committed 62,576-row bitset ledger in validator order."""

    ledger_path = (
        repository
        / "reproduction/60-fin4-residual-284151591"
        / "normalized/pair-partition-by-source.csv.gz"
    )
    verify_file(
        ledger_path,
        expected_bytes=PARTITION_GZIP_BYTES,
        expected_sha256=PARTITION_GZIP_SHA256,
    )
    with gzip.open(ledger_path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != PARTITION_HEADER:
            raise Stage60SeedFreeError("committed Stage 60 partition header drift")
        rows = 0
        for rows, row in enumerate(reader, start=1):
            if set(row) != set(PARTITION_HEADER) or any(
                row[key] is None for key in PARTITION_HEADER
            ):
                raise Stage60SeedFreeError(
                    f"malformed committed Stage 60 partition row {rows}"
                )
            try:
                values = {key: int(row[key]) for key in PARTITION_HEADER}
            except ValueError as exc:
                raise Stage60SeedFreeError(
                    f"non-integer committed Stage 60 partition row {rows}"
                ) from exc
            if any(str(values[key]) != row[key] or values[key] < 0 for key in PARTITION_HEADER):
                raise Stage60SeedFreeError(
                    f"non-canonical committed Stage 60 partition row {rows}"
                )
            if values["source_equation_id"] != rows:
                raise Stage60SeedFreeError(
                    f"committed Stage 60 partition source ID drift at row {rows}"
                )
            yield (
                values["source_equation_id"],
                values["targeted_324m_target_count"],
                values["fin4_covered_target_count"],
                values["residual_284m_target_count"],
            )
        if rows != EXPECTED_EQUATIONS:
            raise Stage60SeedFreeError(
                f"committed Stage 60 partition row count drift: {rows}"
            )


def load_existing_final(
    work_dir: Path,
    progress: dict[str, object],
    configuration: dict[str, int],
    environment: dict[str, object],
) -> dict[str, object]:
    """Return an existing final without changing its completion timestamp."""

    final_path = work_dir / "final.json"
    if not final_path.is_file():
        raise Stage60SeedFreeError("completed progress has no final.json")
    try:
        final = json.loads(final_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage60SeedFreeError("existing final.json is invalid JSON") from exc
    if not isinstance(final, dict):
        raise Stage60SeedFreeError("existing final.json is not an object")
    validate_final_structure(final, progress, configuration, environment)
    embedded = progress.get("final")
    if embedded is not None and embedded != final:
        raise Stage60SeedFreeError("progress/final.json evidence drift")
    if embedded is None:
        # Repair the narrow crash window after durable final.json but before the
        # same object was embedded in progress.  Preserve completed_at exactly.
        progress["final"] = final
        progress["status"] = "complete"
        progress["updated_at"] = final["completed_at"]
        write_json_atomic(work_dir / "progress.json", progress)
    return final


def validate_full_accounting(
    accounting: dict[str, object],
    *,
    authoritative_difference: int,
    retried_after_partial: bool,
    coverage_attribution_complete: bool,
) -> None:
    full_expected = {
        "raw_tables_scanned": FULL_TABLE_COUNT,
        "canonical_models": EXPECTED_ISOMORPHISM_CLASSES,
        "model_signatures_evaluated": EXPECTED_FULL_EVALUATED,
        "opposite_signatures_derived": EXPECTED_FULL_DERIVED,
        "canonical_models_skipped_as_derived": EXPECTED_FULL_DERIVED,
        "evaluated_plus_skipped": EXPECTED_ISOMORPHISM_CLASSES,
        "evaluated_plus_derived": EXPECTED_ISOMORPHISM_CLASSES,
    }
    for key, value in full_expected.items():
        if accounting.get(key) != value:
            raise Stage60SeedFreeError(
                f"complete seed-free enumeration accounting drift for {key}: "
                f"expected {value}, found {accounting.get(key)}"
            )
    if authoritative_difference != 40_006_076:
        raise Stage60SeedFreeError(
            "complete seed-free pair difference is not 324157667 - 284151591"
        )
    if not retried_after_partial and not coverage_attribution_complete:
        raise Stage60SeedFreeError(
            "complete seed-free shard coverage ledger does not close against the bitset"
        )


def completed_run_rollups(
    progress: dict[str, object], *, declared_remaining: int
) -> tuple[dict[str, object], dict[str, object], dict[str, object], list[dict[str, object]]]:
    """Recompute every final aggregate from the durable completed-shard ledger."""

    completed = progress.get("completed_shards")
    if not isinstance(completed, list):
        raise Stage60SeedFreeError("seed-free progress lacks completed shard records")
    accounting: dict[str, object] = {
        "raw_tables_scanned": sum(int(row["raw_tables_scanned"]) for row in completed),
        "canonical_models": sum(int(row["canonical_models"]) for row in completed),
        "model_signatures_evaluated": sum(
            int(row["model_signatures_evaluated"]) for row in completed
        ),
        "opposite_signatures_derived": sum(
            int(row["opposite_signatures_derived"]) for row in completed
        ),
        "canonical_models_skipped_as_derived": sum(
            int(row["canonical_models_skipped_as_derived"]) for row in completed
        ),
        "successful_attempt_covered_pairs_sum": sum(
            int(row["covered_pairs"]) for row in completed
        ),
    }
    accounting["evaluated_plus_skipped"] = (
        int(accounting["model_signatures_evaluated"])
        + int(accounting["canonical_models_skipped_as_derived"])
    )
    accounting["evaluated_plus_derived"] = (
        int(accounting["model_signatures_evaluated"])
        + int(accounting["opposite_signatures_derived"])
    )
    authoritative_difference = 324_157_667 - declared_remaining
    retried_after_partial = any(
        bool(row.get("resumed_after_incomplete_attempt")) for row in completed
    )
    coverage_attribution_complete = (
        not retried_after_partial
        and accounting["successful_attempt_covered_pairs_sum"]
        == authoritative_difference
    )
    accounting.update(
        {
            "authoritative_bitset_difference": authoritative_difference,
            "successful_attempt_coverage_attribution_complete": (
                coverage_attribution_complete
            ),
            "retry_boundary": (
                "A retry after an interrupted in-place shard can preserve partial clears. "
                "In that case successful-attempt covered-pair totals are intentionally not "
                "claimed as a complete attribution ledger; final bitset difference/hash is "
                "authoritative."
            ),
        }
    )
    timing: dict[str, object] = {
        "scope": "successful shard attempts recorded in completed_shards",
        "shard_wall_seconds_sum": math.fsum(
            float(row["wall_seconds"]) for row in completed
        ),
        "engine_elapsed_seconds_sum": math.fsum(
            float(row["engine_elapsed_seconds"]) for row in completed
        ),
        "engine_user_cpu_seconds_sum": math.fsum(
            float(row["engine_user_cpu_seconds"]) for row in completed
        ),
        "engine_system_cpu_seconds_sum": math.fsum(
            float(row["engine_system_cpu_seconds"]) for row in completed
        ),
        "failed_attempt_resources_fully_accounted": not retried_after_partial,
        "retry_resource_boundary": (
            "If a shard was retried, these sums exclude resource use from failed or "
            "interrupted attempts and are therefore lower bounds for the whole run."
        ),
    }
    retried_shards = [
        int(row["index"])
        for row in completed
        if bool(row["resumed_after_incomplete_attempt"])
    ]
    retry_status: dict[str, object] = {
        "any_retried_shards": bool(retried_shards),
        "retried_shard_indexes": retried_shards,
        "successful_attempt_coverage_attribution_complete": (
            coverage_attribution_complete
        ),
        "failed_attempt_resources_fully_accounted": not retried_after_partial,
    }
    shard_evidence = [
        {field: row[field] for field in SHARD_EVIDENCE_FIELDS} for row in completed
    ]
    return accounting, timing, retry_status, shard_evidence


def validate_final_structure(
    final: dict[str, object],
    progress: dict[str, object],
    configuration: dict[str, int],
    environment: dict[str, object],
) -> None:
    """Validate a cached final solely from its durable small evidence ledger."""

    if (
        final.get("schema") != FINAL_SCHEMA
        or final.get("status") != "complete"
        or final.get("configuration") != configuration
        or final.get("historical_seed_chain_used") is not False
        or final.get("enumeration_method")
        != "seed-free-all-bitslice-opposite-result-level"
        or final.get("environment") != environment
        or final.get("implementation_identity")
        != environment["implementation_identity"]
        or final.get("implementation_identity")
        != progress.get("implementation_identity")
        or final.get("input_hashes") != progress.get("input_hashes")
        or final.get("disk_preflight_runs") != progress.get("preflight_runs")
    ):
        raise Stage60SeedFreeError("existing final.json identity drift")
    completed_at = final.get("completed_at")
    if not isinstance(completed_at, str) or not completed_at:
        raise Stage60SeedFreeError("existing final.json completion timestamp drift")
    if (
        final.get("work_bitset_bytes") != FINAL_284_BYTES
        or final.get("declared_remaining_pairs")
        != progress.get("last_remaining_pairs")
        or final.get("fin4_incremental_covered_pairs")
        != 324_157_667 - int(progress["last_remaining_pairs"])
    ):
        raise Stage60SeedFreeError("existing final.json bitset metadata drift")
    _progress_hash(final.get("work_bitset_sha256"), "final work bitset")
    for field in (
        "maximum_engine_rss_raw",
        "maximum_engine_rss_raw_unit",
        "maximum_engine_rss_bytes",
    ):
        if final.get(field) != progress.get(field):
            raise Stage60SeedFreeError(f"existing final.json resource drift: {field}")
    expected_compiler = {
        "compiler": environment["compiler"],
        "compiler_version": environment["compiler_version"],
        "engine_sha256": environment["engine_sha256"],
        "engine_source_sha256": environment["engine_source_sha256"],
    }
    if final.get("compiler_engine") != expected_compiler:
        raise Stage60SeedFreeError("existing final.json compiler/engine drift")

    accounting, timing, retry_status, shard_evidence = completed_run_rollups(
        progress, declared_remaining=int(progress["last_remaining_pairs"])
    )
    if final.get("enumeration_accounting") != accounting:
        raise Stage60SeedFreeError("existing final.json enumeration accounting drift")
    if final.get("enumeration_timing") != timing:
        raise Stage60SeedFreeError("existing final.json timing accounting drift")
    if final.get("retry_status") != retry_status:
        raise Stage60SeedFreeError("existing final.json retry accounting drift")
    if final.get("shard_evidence") != shard_evidence:
        raise Stage60SeedFreeError("existing final.json shard evidence drift")

    is_full = (
        configuration["range_start"] == 0
        and configuration["range_count"] == FULL_TABLE_COUNT
    )
    if is_full:
        if (
            final.get("work_bitset_sha256") != FINAL_284_SHA256
            or final.get("declared_remaining_pairs") != 284_151_591
            or final.get("fin4_incremental_covered_pairs") != 40_006_076
            or final.get("committed_284m_expected_bytes") != FINAL_284_BYTES
            or final.get("committed_284m_expected_sha256") != FINAL_284_SHA256
            or final.get("committed_284m_exact_match") is not True
        ):
            raise Stage60SeedFreeError("existing full final.json exact-result drift")
        stream = final.get("pair_bitset_stream_validation")
        expected_stream = {
            "validator": "tools.phase2_common.validate_pair_bitset_streams",
            "expected_rows": "normalized/pair-partition-by-source.csv.gz",
            "original_popcount": 324_157_667,
            "residual_popcount": 284_151_591,
            "removed_popcount": 40_006_076,
            "original_active_sources": EXPECTED_ACTIVE_SOURCES,
            "residual_active_sources": EXPECTED_ACTIVE_SOURCES,
            "rows_checked": EXPECTED_EQUATIONS,
            "residual_is_subset": True,
            "diagonal_bits_all_zero": True,
            "out_of_range_bits_all_zero": True,
        }
        if stream != expected_stream:
            raise Stage60SeedFreeError("existing full final.json stream-validation drift")
        validate_full_accounting(
            accounting,
            authoritative_difference=40_006_076,
            retried_after_partial=bool(retry_status["any_retried_shards"]),
            coverage_attribution_complete=bool(
                retry_status["successful_attempt_coverage_attribution_complete"]
            ),
        )
    elif (
        final.get("committed_284m_expected_bytes") != FINAL_284_BYTES
        or final.get("committed_284m_expected_sha256") != FINAL_284_SHA256
        or final.get("committed_284m_exact_match") is not None
        or final.get("pair_bitset_stream_validation") is not None
    ):
        raise Stage60SeedFreeError("existing partial final.json result-boundary drift")


def finalize_run(
    repository: Path,
    work_dir: Path,
    progress: dict[str, object],
    configuration: dict[str, int],
    environment: dict[str, object],
) -> dict[str, object]:
    validate_progress_structure(progress, configuration, environment)
    if (work_dir / "final.json").exists():
        return load_existing_final(work_dir, progress, configuration, environment)
    work_bitset = work_dir / "run/remaining_pairs.bitset"
    header = inspect_pair_header(work_bitset)
    digest = sha256_path(work_bitset)
    is_full = configuration["range_start"] == 0 and configuration["range_count"] == FULL_TABLE_COUNT
    exact_match: bool | None = None
    stream_validation: dict[str, object] | None = None
    if is_full:
        exact_match = digest == FINAL_284_SHA256 and header["declared_remaining"] == 284_151_591
        if not exact_match:
            raise Stage60SeedFreeError(
                "complete seed-free run does not match the committed 284M result: "
                f"sha256={digest}, remaining={header['declared_remaining']}"
            )
        source_bitset = work_dir / "source/324M_remaining_pairs.bitset"
        with source_bitset.open("rb") as original, work_bitset.open("rb") as residual:
            validated = validate_pair_bitset_streams(
                original,
                residual,
                expected_rows=iter_committed_partition_expected(repository),
                context="Stage 60 seed-free full-run 324M/284M bitsets",
            )
        stream_validation = {
            "validator": "tools.phase2_common.validate_pair_bitset_streams",
            "expected_rows": "normalized/pair-partition-by-source.csv.gz",
            "original_popcount": validated.original_popcount,
            "residual_popcount": validated.residual_popcount,
            "removed_popcount": validated.removed_popcount,
            "original_active_sources": validated.original_active_sources,
            "residual_active_sources": validated.residual_active_sources,
            "rows_checked": validated.rows_checked,
            "residual_is_subset": validated.residual_is_subset,
            "diagonal_bits_all_zero": validated.diagonal_bits_all_zero,
            "out_of_range_bits_all_zero": validated.out_of_range_bits_all_zero,
        }
        expected_stream_counts = (324_157_667, 284_151_591, 40_006_076)
        observed_stream_counts = (
            validated.original_popcount,
            validated.residual_popcount,
            validated.removed_popcount,
        )
        if observed_stream_counts != expected_stream_counts:
            raise Stage60SeedFreeError(
                "complete seed-free bitset stream validation count drift: "
                f"expected {expected_stream_counts}, found {observed_stream_counts}"
            )
    accounting, timing, retry_status, shard_evidence = completed_run_rollups(
        progress, declared_remaining=header["declared_remaining"]
    )
    authoritative_difference = int(accounting["authoritative_bitset_difference"])
    retried_after_partial = bool(retry_status["any_retried_shards"])
    coverage_attribution_complete = bool(
        retry_status["successful_attempt_coverage_attribution_complete"]
    )
    if is_full:
        validate_full_accounting(
            accounting,
            authoritative_difference=authoritative_difference,
            retried_after_partial=retried_after_partial,
            coverage_attribution_complete=coverage_attribution_complete,
        )

    completed_at = utc_now()
    final = {
        "schema": FINAL_SCHEMA,
        "status": "complete",
        "completed_at": completed_at,
        "configuration": configuration,
        "historical_seed_chain_used": False,
        "enumeration_method": "seed-free-all-bitslice-opposite-result-level",
        "work_bitset_bytes": work_bitset.stat().st_size,
        "work_bitset_sha256": digest,
        "declared_remaining_pairs": header["declared_remaining"],
        "fin4_incremental_covered_pairs": authoritative_difference,
        "enumeration_accounting": accounting,
        "enumeration_timing": timing,
        "retry_status": retry_status,
        "shard_evidence": shard_evidence,
        "pair_bitset_stream_validation": stream_validation,
        "maximum_engine_rss_raw": progress["maximum_engine_rss_raw"],
        "maximum_engine_rss_raw_unit": progress["maximum_engine_rss_raw_unit"],
        "maximum_engine_rss_bytes": progress["maximum_engine_rss_bytes"],
        "committed_284m_expected_bytes": FINAL_284_BYTES,
        "committed_284m_expected_sha256": FINAL_284_SHA256,
        "committed_284m_exact_match": exact_match,
        "environment": progress["environment_initial"],
        "implementation_identity": progress["implementation_identity"],
        "input_hashes": progress["input_hashes"],
        "disk_preflight_runs": progress["preflight_runs"],
        "compiler_engine": {
            "compiler": progress["environment_initial"]["compiler"],
            "compiler_version": progress["environment_initial"]["compiler_version"],
            "engine_sha256": progress["environment_initial"]["engine_sha256"],
            "engine_source_sha256": progress["environment_initial"][
                "engine_source_sha256"
            ],
        },
        "scope_boundary": (
            "A complete-range exact match demonstrates the Stage 60 outcome, not a "
            "byte-for-byte replay of the historical seeded execution/provenance chain."
        ),
    }
    validate_final_structure(final, progress, configuration, environment)
    write_json_atomic(work_dir / "final.json", final)
    progress["status"] = "complete"
    progress["updated_at"] = completed_at
    progress["final"] = final
    write_json_atomic(work_dir / "progress.json", progress)
    return final


def main() -> int:
    args = parse_args()
    lock_handle: TextIO | None = None
    try:
        repository = args.repository_root.resolve()
        work_dir = args.work_dir.resolve() if args.work_dir else default_work_dir(repository)
        configuration = run_configuration(args)
        is_full = configuration["range_start"] == 0 and configuration["range_count"] == FULL_TABLE_COUNT
        will_run = not args.prepare_only and args.max_shards != 0
        if is_full and will_run and not args.confirm_full_run:
            raise Stage60SeedFreeError(
                "refusing the 2^32 full run without the explicit --confirm-full-run flag"
            )
        work_dir.mkdir(parents=True, exist_ok=True)
        lock_handle = acquire_workdir_lock(work_dir)
        input_dir = work_dir / "inputs"
        reconstruction = reconstruct_stage60_inputs(
            repository,
            input_dir,
            report_path=input_dir / "reconstruction.json",
        )
        verify_reconstructed_inputs(input_dir)
        executable, build = compile_engine(repository, work_dir, args.cc)
        environment = environment_record(build, repository)
        if args.prepare_only or args.max_shards == 0:
            preparation = {
                "schema": PREPARATION_SCHEMA,
                "status": "prepared-small-inputs-and-engine",
                "configuration": configuration,
                "reconstruction": reconstruction,
                "environment": environment,
                "engine_build": build,
                "large_pair_bitsets_materialized_by_this_invocation": False,
                "progress_created_by_this_invocation": False,
                "scope_boundary": (
                    "Preparation reconstructs about 4 MiB of support/upstream inputs "
                    "and compiles/self-tests the engine. It does not prepare the two "
                    "489,598,720-byte enumeration bitsets."
                ),
            }
            write_json_atomic(work_dir / "preparation.json", preparation)
            print(json.dumps(preparation, ensure_ascii=False, indent=2, sort_keys=True))
            print(f"prepared_work_dir={work_dir}")
            return 0

        existing_progress_path = work_dir / "progress.json"
        if existing_progress_path.exists():
            try:
                existing_progress = json.loads(
                    existing_progress_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError as exc:
                raise Stage60SeedFreeError("existing progress.json is invalid JSON") from exc
            if not isinstance(existing_progress, dict):
                raise Stage60SeedFreeError("existing progress.json is not an object")
            validate_progress_structure(existing_progress, configuration, environment)
            validate_completed_evidence_files(work_dir, existing_progress)
            if (
                existing_progress.get("status") == "complete"
                and (work_dir / "final.json").exists()
            ):
                final = load_existing_final(
                    work_dir, existing_progress, configuration, environment
                )
                print(json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True))
                return 0

        preflight = disk_preflight(work_dir)
        source_bitset = work_dir / "source/324M_remaining_pairs.bitset"
        materialize_source_324_bitset(repository, source_bitset)
        work_bitset = work_dir / "run/remaining_pairs.bitset"
        work_bitset.parent.mkdir(parents=True, exist_ok=True)
        progress = initialize_progress(
            work_dir, configuration, environment, work_bitset, preflight
        )
        progress_path = work_dir / "progress.json"
        if progress.get("status") == "complete":
            if (work_dir / "final.json").exists():
                final = load_existing_final(
                    work_dir, progress, configuration, environment
                )
            else:
                final = finalize_run(
                    repository, work_dir, progress, configuration, environment
                )
            print(json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        next_shard = int(progress["next_shard"])
        stop = configuration["shard_count"]
        if args.max_shards is not None:
            stop = min(stop, next_shard + args.max_shards)
        shards_dir = work_dir / "shards"
        shards_dir.mkdir(parents=True, exist_ok=True)
        for index in range(next_shard, stop):
            start, count = shard_bounds(configuration, index)
            summary_path = shards_dir / f"shard_{index:03d}.json"
            stderr_path = shards_dir / f"shard_{index:03d}.stderr.log"
            command = [
                str(executable),
                "enumerate-bitslice-inplace",
                str(input_dir / "equations.bin"),
                str(work_bitset),
                str(input_dir / "equation_mirror_map.bin"),
                str(start),
                str(count),
                str(configuration["range_start"]),
                str(configuration["range_end"]),
                str(args.threads),
                str(summary_path),
            ]
            prior_inflight = progress.get("inflight")
            attempt = 1
            resumed_partial = False
            if isinstance(prior_inflight, dict) and prior_inflight.get("index") == index:
                attempt = int(prior_inflight.get("attempt", 0)) + 1
                resumed_partial = True
            progress["status"] = "running"
            progress["updated_at"] = utc_now()
            progress["inflight"] = {
                "index": index,
                "range_start": start,
                "range_count": count,
                "attempt": attempt,
                "resumed_after_incomplete_attempt": resumed_partial,
                "started_at": utc_now(),
                "command": command,
                "threads": args.threads,
                "environment": environment,
            }
            validate_progress_structure(progress, configuration, environment)
            write_json_atomic(progress_path, progress)
            started = time.monotonic()
            with stderr_path.open("a", encoding="utf-8") as stderr:
                stderr.write(
                    json.dumps(
                        {
                            "event": "runner-start",
                            "at": utc_now(),
                            "attempt": attempt,
                            "command": command,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                stderr.flush()
                process = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=stderr)
                elapsed = time.monotonic() - started
                stderr.write(
                    json.dumps(
                        {
                            "event": "runner-end",
                            "at": utc_now(),
                            "attempt": attempt,
                            "returncode": process.returncode,
                            "wall_seconds": elapsed,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
            if process.returncode != 0:
                raise Stage60SeedFreeError(
                    f"Fin4 shard {index} failed with exit code {process.returncode}; "
                    f"see {stderr_path}"
                )
            try:
                result = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise Stage60SeedFreeError(f"invalid Fin4 shard summary: {summary_path}") from exc
            validate_shard_result(
                result,
                configuration=configuration,
                start=start,
                count=count,
                threads=args.threads,
            )
            expected_initial = int(progress["last_remaining_pairs"])
            validate_shard_checkpoint(
                result,
                expected_initial=expected_initial,
                retried=resumed_partial,
            )
            header = inspect_pair_header(work_bitset)
            if header["declared_remaining"] != int(result["remaining_pairs_after"]):
                raise Stage60SeedFreeError("work-bitset header does not match shard summary")
            completed = progress["completed_shards"]
            assert isinstance(completed, list)
            completed.append(
                {
                    "index": index,
                    "range_start": start,
                    "range_count": count,
                    "attempt": attempt,
                    "resumed_after_incomplete_attempt": resumed_partial,
                    "threads": args.threads,
                    "command": command,
                    "summary": str(summary_path.relative_to(work_dir)),
                    "summary_sha256": sha256_path(summary_path),
                    "stderr_log": str(stderr_path.relative_to(work_dir)),
                    "stderr_sha256": sha256_path(stderr_path),
                    "wall_seconds": elapsed,
                    "engine_elapsed_seconds": result["elapsed_seconds"],
                    "engine_user_cpu_seconds": result["user_cpu_seconds"],
                    "engine_system_cpu_seconds": result["system_cpu_seconds"],
                    "engine_maximum_rss_raw": result["ru_maxrss_raw"],
                    "engine_maximum_rss_raw_unit": normalized_rss(
                        result["ru_maxrss_raw"]
                    )[1],
                    "engine_maximum_rss_bytes": normalized_rss(
                        result["ru_maxrss_raw"]
                    )[0],
                    "raw_tables_scanned": result["raw_tables_scanned"],
                    "canonical_models": result["canonical_models_in_range"],
                    "model_signatures_evaluated": result[
                        "model_signatures_evaluated"
                    ],
                    "opposite_signatures_derived": result[
                        "opposite_signatures_derived"
                    ],
                    "canonical_models_skipped_as_derived": result[
                        "canonical_models_skipped_as_derived"
                    ],
                    "expanded_models_accounted_now": result[
                        "expanded_models_accounted_now"
                    ],
                    "initial_remaining_pairs": result["initial_remaining_pairs"],
                    "covered_pairs": result["covered_pairs"],
                    "remaining_pairs_after": result["remaining_pairs_after"],
                }
            )
            progress["next_shard"] = index + 1
            progress["last_remaining_pairs"] = result["remaining_pairs_after"]
            progress["maximum_engine_rss_raw"] = max(
                int(progress["maximum_engine_rss_raw"]), int(result["ru_maxrss_raw"])
            )
            progress["maximum_engine_rss_bytes"] = max(
                int(progress["maximum_engine_rss_bytes"]),
                normalized_rss(result["ru_maxrss_raw"])[0],
            )
            progress["inflight"] = None
            progress["updated_at"] = utc_now()
            progress["status"] = (
                "complete" if index + 1 == configuration["shard_count"] else "paused"
            )
            validate_progress_structure(progress, configuration, environment)
            write_json_atomic(progress_path, progress)

        if int(progress["next_shard"]) == configuration["shard_count"]:
            final = finalize_run(
                repository, work_dir, progress, configuration, environment
            )
            print(json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True))
            print(f"paused_work_dir={work_dir}")
        return 0
    except (
        Stage60Error,
        Stage60SeedFreeError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        release_workdir_lock(lock_handle)


if __name__ == "__main__":
    raise SystemExit(main())
