# Finite Countermodel Bank

English | [简体中文](README.zh-CN.md)

This repository is a provenance-first archive for finite countermodels and the
pipeline that selected them. Its first concrete dataset is the reproduction record
for the SAIR Mathematics Distillation Challenge — Equational Theories Stage 2
False Solver.

## Current status

PR 0 establishes the repository contract and captures the four solver files that
were actually submitted to SAIR. PR 1 reconstructs the historical finite-table
accumulation as four separately reviewable stages: 9,450 primary tables, 9,852
after registry deduplication, 9,957 after the d1/d2 deltas, and 10,059 after the two
JiaMing deliveries. The final 102 explicit report countermodels are independently
rechecked by exhaustive assignment enumeration.

PR 2 reconstructs the stable pruning from 10,059 to 3,535 tables, validates the
frozen Fin4 transition from 324,157,667 targeted pairs to a 284,151,591-pair
residual, and replays the fixed-order positive-marginal selection of the 1,470-table
core. The core matches the first 1,470 embedded records of the submitted Marathon
solver exactly. The Fin4 stage is explicitly a frozen-artifact replay: missing
singleton and seed-chain inputs prevent a from-scratch rerun.

PR 3 captures and reproduces the finite149 augmentation: the 789 no-submission
directions reduce to 149 finite-countermodel directions covered by 17 stable base
tables and 11 required transposes (129 direct uses and 20 transpose uses). It also
verifies zero byte overlap with the 1,470-table core and the order-22 closed-subtable
replacement for the official order-24 Refutation934 table. The cumulative 1,487
payload and runtime opposite closure are completed in PR 4. See
[TIMELINE.md](TIMELINE.md) for the stage sequence and [CLAIMS.csv](CLAIMS.csv) for
the claim ledger.

The follow-up `81-finite149-portable-verification` stage corrects the PR 3 review
path without changing its data: it streams the 498,673,223-byte finite-outcomes
JSON by matrix row, parses all 17 captured Lean operator tables, records the exact
order-22 Refutation934 provenance, and marks the 149 ETP paths as a frozen inventory
rather than an independently replayed graph. It also retains the full Stage 80
semantic gate by rerunning all 149 exhaustive task checks, 11 transpose derivations,
zero-overlap and 1,470-prefix/17-suffix submission comparisons.

PR 4 reconstructs the exact inner finite-table payload as the Stage 70 core
followed by the Stage 80 augmentation: 1,470 + 17 = 1,487 records, 111,009 raw
bytes. It reproduces the submitted XZ/Base85 table literal byte for byte, then
statically replays the pinned generic opposite-closure algorithm. Of the 1,487
embedded records, 1,414 have a missing strict transpose, producing 2,901 distinct
runtime-oriented scan records. These 1,414 tables are runtime-derived and are not
additional embedded payload records. Seventeen exact derived records have earlier
repository history (six in Stage 10 and eleven in Stage 80), so only 1,397 receive
Stage 100 as their historical `first_seen_stage`. The evidence reconstructs the
inner table payload and transformation, not the complete 498,047-byte outer solver
launcher.

## Verify this checkout

The scripts require **Python 3.10+** and are recommended and tested with **Python
3.11**, matching the official competition
[`python:3.11-slim` sandbox](https://github.com/SAIRcompetition/equational-theories-lean-stage2/blob/main/README.md#sandbox-python-environment).
Python 3.12 is retained as an additional CI compatibility check. The verifier uses
only the Python standard library and processes large files in bounded streams or
chunks:

```bash
python3 tools/verify_repository.py
python3 reproduction/81-finite149-portable-verification/scripts/verify.py
python3 tools/verify_pr4.py
python3 -m unittest discover -s tests -v
```

To regenerate the PR 1 and PR 2 outputs, the corrected PR 3 verification layer,
and both PR 4 stages from committed inputs:

```bash
python3 tools/rebuild_pr1.py
python3 tools/rebuild_pr2.py
python3 reproduction/81-finite149-portable-verification/scripts/rebuild.py
python3 tools/rebuild_pr4.py
git diff --exit-code
```

The PR 2 rebuild uses bounded streams for the two 489,598,720-byte uncompressed
pair bitsets. The corrected PR 3 rebuild scans all 498,673,223 uncompressed
finite-outcomes bytes with a 256 KiB application-buffer cap and retains only the
789 requested cells. Neither path materializes its large input in memory.
The PR 4 rebuild handles only the bounded 111,009-byte embedded stream and its
215,433-byte runtime closure; submitted Python files are parsed as data and never
imported or executed.

## Repository layout

| Path | Purpose |
| --- | --- |
| `docs/submission-notes/` | Human-facing submission-note source |
| `reproduction/` | Ordered evidence stages and stage-level instructions |
| `schemas/` | Versioned machine-readable record contracts |
| `tools/` | Streaming validation and reconstruction helpers |
| `CLAIMS.csv` | One row per numerical or provenance claim |
| `TIMELINE.md` | PR boundaries, stage order, and acceptance criteria |
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
