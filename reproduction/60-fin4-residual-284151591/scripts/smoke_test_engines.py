#!/usr/bin/env python3
"""Run a bounded semantic smoke test of both frozen Stage 60 C engines.

This test reconstructs only the five small inputs and never materializes either
489,598,720-byte pair bitset.  Three Fin4 tables have expected equation
signatures derived symbolically from equation text, independently of the
postfix evaluator in either engine.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.stage60_seedfree import (  # noqa: E402
    BITSLICE_ENGINE_SHA256,
    SCALAR_ENGINE_SHA256,
    Stage60SeedFreeError,
    build_symbolic_signature_fixture,
    extract_engine_source,
    reconstruct_stage60_inputs,
    sha256_path,
    write_json_atomic,
)


SCHEMA = "stage60-seedfree-engine-smoke-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="small generated work directory (default: a temporary directory)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="optional JSON report path outside the ephemeral work directory",
    )
    parser.add_argument("--cc", default=os.environ.get("CC", "clang"))
    return parser.parse_args()


def compiler_version(compiler: str) -> str:
    completed = subprocess.run(
        [compiler, "--version"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.stdout[:16_384]


def compile_engine(
    repository: Path,
    work_dir: Path,
    compiler: str,
    *,
    bitslice: bool,
) -> dict[str, object]:
    kind = "bitslice" if bitslice else "scalar"
    source = work_dir / "source" / f"fin4_{kind}_engine.c"
    executable = work_dir / "bin" / f"fin4_{kind}_engine"
    extract_engine_source(repository, source, bitslice=bitslice)
    executable.parent.mkdir(parents=True, exist_ok=True)
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
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise Stage60SeedFreeError(
            f"{kind} engine compilation failed:\n"
            + (completed.stdout + completed.stderr)[-16_384:]
        )
    return {
        "kind": kind,
        "source_sha256": sha256_path(source),
        "expected_source_sha256": (
            BITSLICE_ENGINE_SHA256 if bitslice else SCALAR_ENGINE_SHA256
        ),
        "executable": executable,
        "executable_bytes": executable.stat().st_size,
        "executable_sha256": sha256_path(executable),
        "compile_command": command,
        "compiler_stdout": completed.stdout[:16_384],
        "compiler_stderr": completed.stderr[:16_384],
    }


def run_check(command: list[str], expected: dict[str, object]) -> dict[str, object]:
    started = time.monotonic()
    completed = subprocess.run(command, capture_output=True, text=True)
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        raise Stage60SeedFreeError(
            f"engine smoke command failed ({' '.join(command)}):\n"
            + (completed.stdout + completed.stderr)[-16_384:]
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise Stage60SeedFreeError("engine smoke command returned invalid JSON") from exc
    for key, value in expected.items():
        if payload.get(key) != value:
            raise Stage60SeedFreeError(
                f"engine smoke result drift for {key}: expected {value}, found {payload.get(key)}"
            )
    return {
        "command": command,
        "wall_seconds": elapsed,
        "stdout": payload,
        "stderr": completed.stderr[-16_384:],
    }


def run_smoke(repository: Path, work_dir: Path, compiler_name: str) -> dict[str, object]:
    compiler_path = shutil.which(compiler_name)
    if compiler_path is None:
        raise Stage60SeedFreeError(f"C compiler not found: {compiler_name}")
    compiler = str(Path(compiler_path).resolve())
    inputs = work_dir / "inputs"
    fixture_dir = work_dir / "fixture"
    reconstruction = reconstruct_stage60_inputs(repository, inputs)
    fixture = build_symbolic_signature_fixture(inputs, fixture_dir)
    scalar = compile_engine(repository, work_dir, compiler, bitslice=False)
    bitslice = compile_engine(repository, work_dir, compiler, bitslice=True)

    scalar_executable = str(scalar.pop("executable"))
    bitslice_executable = str(bitslice.pop("executable"))
    equations = str(inputs / "equations.bin")
    models = str(fixture_dir / "models.bin")
    signatures = str(fixture_dir / "signatures.bin")
    checks = [
        run_check(
            [scalar_executable, "self-test"],
            {"status": "ok", "permutations": 24},
        ),
        run_check(
            [scalar_executable, "verify", equations, models, signatures, "3"],
            {"status": "ok", "verified_models": 3},
        ),
        run_check(
            [bitslice_executable, "self-test"],
            {"status": "ok", "permutations": 24},
        ),
        run_check(
            [bitslice_executable, "verify", equations, models, signatures, "3"],
            {"status": "ok", "verified_models": 3},
        ),
        run_check(
            [
                bitslice_executable,
                "verify-bitslice",
                equations,
                models,
                signatures,
                "3",
            ],
            {"status": "ok", "verified_bitslice_models": 3, "batch_size": 64},
        ),
    ]
    return {
        "schema": SCHEMA,
        "status": "ok",
        "resource_boundary": {
            "large_pair_bitsets_materialized": False,
            "models_verified": 3,
            "equation_signatures_per_model": 62_576,
        },
        "reconstructed_input_status": reconstruction["status"],
        "fixture": fixture,
        "compiler": compiler,
        "compiler_version": compiler_version(compiler),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "engines": [scalar, bitslice],
        "checks": checks,
        "scope_boundary": (
            "This bounded test checks equation parsing plus scalar and bitslice "
            "signature semantics. It does not enumerate the 2^32 Fin4 tables."
        ),
    }


def main() -> int:
    args = parse_args()
    try:
        repository = args.repository_root.resolve()
        if args.work_dir is None:
            with tempfile.TemporaryDirectory(prefix="stage60-engine-smoke-") as temporary:
                report = run_smoke(repository, Path(temporary), args.cc)
        else:
            work_dir = args.work_dir.resolve()
            if work_dir.exists() and any(work_dir.iterdir()):
                raise Stage60SeedFreeError(
                    f"smoke work directory is not empty: {work_dir}"
                )
            work_dir.mkdir(parents=True, exist_ok=True)
            report = run_smoke(repository, work_dir, args.cc)
        if args.report is not None:
            write_json_atomic(args.report.resolve(), report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, Stage60SeedFreeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
