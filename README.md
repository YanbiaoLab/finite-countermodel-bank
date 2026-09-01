# Finite Countermodel Bank

English | [Simplified Chinese](README.zh-CN.md)

This repository is a provenance-first archive for finite countermodels and the
pipeline that selected them. Its first concrete dataset is the reproduction record
for the [SAIR Mathematics Distillation Challenge — Equational Theories Stage 2](https://competition.sair.foundation/competitions/mathematics-distillation-challenge-equational-theories-stage2/overview)
False Solver.

## How the 1,487 embedded tables were built

The submitted False Solver embeds exactly **1,487 finite-table records**: a
1,470-table coverage-selected core followed by 17 finite149 base records. This
repository rebuilds their 111,009-byte canonical payload and matches the submitted
XZ/Base85 table literal byte for byte. Counts below use exact canonical record bytes,
not isomorphism classes.

| Pipeline step | Count transition | Meaning and strongest check |
| --- | --- | --- |
| **Phase 1 · Stages 10–40** | `9,450 → 9,852 → 9,957 → 10,059` | Add 402 registry records, a net addition of 105 records from the early deltas, and 102 delivered records through exact membership deltas; exhaustively check the final 102 countermodels. |
| **Phase 2 · Stage 50** | `10,059 − 241 scalar-affine − 6,283 order≤4 = 3,535` | Apply explicit affine witnesses and the order-at-most-4 removal ledger; match the historical d17 bank exactly. |
| **Phase 2 · Stages 60–70** | `3,535 − 2,065 zero-marginal = 1,470` | Select against the verified 284,151,591-pair residual in fixed order; match the historical submitted solver prefix exactly. |
| **Phase 3 · Stages 80–81** | `789 no-submission directions → 149 finite-countermodel directions → 17 direct base records` | Exhaustively check all 149 tasks; verify zero overlap with the core and an exact historical submitted solver suffix. |
| **Phase 4 · Stage 90** | `1,470 + 17 = 1,487 embedded records` | Rebuild the exact 111,009-byte canonical stream and submitted XZ/Base85 literal. |
| **Phase 4 · Stage 100** | `1,487 + 1,414 missing transposes = 2,901 runtime records` | Replay the generic opposite closure; the 1,414 records are runtime-derived orientations, not additional embedded payload. |

Only the 17 direct finite149 base records are appended to the payload. The 11
distinct strict transposes needed by 20 of the 149 task directions are not appended;
they occur among the 1,414 transposes derived by the generic runtime closure.

Phase 0 hash-pins the current and historical submitted solver files used to verify
this lineage; it does not change table membership. The full stage sequence, evidence
requirements, and GitHub history remain in [TIMELINE.md](TIMELINE.md), while
[CLAIMS.csv](CLAIMS.csv) is the authoritative claim ledger. The evidence reconstructs
the inner table payload and its runtime transformation, not the complete outer solver
launchers.

## Terminology

- **Phase** is a stable high-level pipeline group, numbered 0–4.
- **Stage** is a concrete, independently verifiable evidence unit, numbered
  `00`, `10`, `20`, …, `100`.
- **PR** refers only to actual GitHub development history, recorded in
  [TIMELINE.md](TIMELINE.md).

## Reproducibility scope

`Rebuild` below means deterministic regeneration from inputs already committed in
this repository. It does not by itself imply rerunning the historical model search
or competition environment.

| Level | Covered here | Evidence boundary |
| --- | --- | --- |
| Deterministic rebuild from committed snapshots | Stages 10–50 reconstruct the `9,450 → 10,059 → 3,535` table lineage from captured inputs; Stage 60 reconstructs five historical support/upstream files byte for byte; Stages 81, 90, and 100 regenerate the portable finite149 evidence, exact 1,487-record payload, and 2,901-record runtime closure. | Historical programs and submitted solvers are normally parsed as data rather than executed. Stage 81 reconstructs only the graph edges needed by the frozen paths. |
| Frozen-artifact replay | Stages 60 and 70 validate the pinned 324M/284M bitsets and replay the fixed `3,535 → 1,470` selection from frozen coverage reports. Stage 81 validates every edge of the 149 hash-pinned ETP paths against the captured graph entries and source files. | The normal rebuild does not rerun Fin4 enumeration, upstream graph extraction/build, path discovery, or shortest-path search. Stage 60 separately provides an optional new seed-free result-level C runner. |
| Independent semantic and invariant checks | The 102 Stage 40 countermodels and all 149 finite149 directions are exhaustively checked; table identity, transpose, overlap, bitset, prefix/suffix, and payload invariants are recomputed. | These checks validate committed tables and results, not how the original search discovered them. |
| Independent Stage 60 outcome rerun | **Demonstrated with committed evidence.** | A new seed-free result-level method exhaustively scanned all `2^32` order-4 tables in 256 shards, completed without retries, and reproduced the committed 284,151,591-pair residual byte for byte. The evidence includes every shard summary, sanitized logs, exact input/implementation hashes, resource measurements, and an independent streamed bitset validation. This does not recover the historical seed-generation/provenance chain. |
| Byte-for-byte replay of the historical discovery and competition workflow | **Blocked by unrecovered historical inputs and environments.** | Outstanding blockers include the Stage 10 mining/export inputs, Stage 40 SAT runner inputs and raw journals, the Stage 50 d16.2 source/build patch, the original Stage 60 seed-generation/provenance chain, the full per-case Judge v3 certificate/result files and exact historical execution environment, the independent inputs/template/builder for the complete outer solver, and the aggregate/submission Lean-certificate generator and exact toolchain. |

Accordingly, this repository supports artifact-level reproducibility from committed
evidence. Key independent rerun components are now implemented, but the complete
end-to-end reconstruction has not yet been demonstrated; byte-for-byte replay
of the historical workflow remains blocked by unrecovered inputs and environments.
The required external inputs, environments, and per-item acceptance gates are
tracked in the [External Recovery Register](EXTERNAL_RECOVERY.md).

## Verify this checkout

The scripts require **Python 3.10+** and are recommended and tested with **Python
3.11**, matching the official competition
[`python:3.11-slim` sandbox](https://github.com/SAIRcompetition/equational-theories-lean-stage2/blob/main/README.md#sandbox-python-environment).
Python 3.12 is retained as an additional CI compatibility check. The verifier uses
only the Python standard library and processes large files in bounded streams or
chunks:

```bash
python3 tools/verify_all.py
```

The unified entry point fails immediately on Python older than 3.10 and runs the
repository verifier, the bounded Stage 81 verifier, the exact Phase 4 verifier,
and the unit tests with the same interpreter. Each verifier remains directly
runnable for stage-targeted review.

To regenerate the Phase 1 and Phase 2 outputs, the corrected Phase 3 verification
layer, and both Phase 4 stages from committed inputs:

```bash
python3 tools/rebuild_phase1.py
python3 tools/rebuild_phase2.py
python3 tools/rebuild_phase3.py
python3 tools/rebuild_phase4.py
git diff --exit-code
```

The Phase 2 rebuild uses bounded streams for the two 489,598,720-byte uncompressed
pair bitsets. The corrected Phase 3 rebuild scans all 498,673,223 uncompressed
finite-outcomes bytes with a 256 KiB application-buffer cap and retains only the
789 requested cells. Neither path materializes its large input in memory.
The Phase 4 rebuild handles only the bounded 111,009-byte embedded stream and its
215,433-byte runtime closure; the current 2026-09-01 submitted Python files are
parsed as data and never imported or executed.

## Repository layout

| Path | Purpose |
| --- | --- |
| `docs/submission-notes/` | Human-facing submission-note source |
| `reproduction/` | Ordered evidence stages and stage-level instructions |
| `schemas/` | Versioned machine-readable record contracts |
| `tools/` | Streaming validation and reconstruction helpers |
| `CLAIMS.csv` | One row per numerical or provenance claim |
| `TIMELINE.md` | Phase grouping, stage order, GitHub PR history, and acceptance criteria |
| `EXTERNAL_RECOVERY.md` | External restoration work items and acceptance gates |
| `NOTICE.md`, `LICENSES/` | Provenance and rights-status notices |

## Evidence model

Every completed stage contains a manifest, immutable raw inputs, explicit derived
outputs or membership deltas, checksums, and a bounded verification command. Exact
table identity is byte identity, not isomorphism: for a table of order `n`, the
canonical bytes are the one-byte order followed by the `n²` row-major entries, and
the stable table identifier is the SHA-256 digest of those bytes.

## License

This project is licensed under the [Apache License 2.0](LICENSE). The license
applies to material for which the project contributors hold the necessary rights.
Source artifacts with separate or unconfirmed rights retain the status recorded in
their stage manifests; see [NOTICE.md](NOTICE.md) and
[LICENSES/README.md](LICENSES/README.md).
