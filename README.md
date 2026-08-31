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

The finite149 augmentation and final payload integration will be added in later
chronological, reviewable stages. See
[TIMELINE.md](TIMELINE.md) for the planned sequence and [CLAIMS.csv](CLAIMS.csv)
for the claim ledger.

## Verify this checkout

The verifier uses only the Python standard library and hashes files in bounded
chunks:

```bash
python3 tools/verify_repository.py
python3 -m unittest discover -s tests -v
```

To regenerate the PR 1 and PR 2 normalized outputs, deltas, summaries, manifests,
and checksums from the committed raw snapshots:

```bash
python3 tools/rebuild_pr1.py
python3 tools/rebuild_pr2.py
git diff --exit-code
```

The PR 2 rebuild uses bounded streams for the two 489,598,720-byte uncompressed
pair bitsets; it does not load them into memory.

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

No repository-wide license has been selected. See [NOTICE.md](NOTICE.md) and
[LICENSES/README.md](LICENSES/README.md). Repository publication alone does not
grant permission to copy, modify, or redistribute the contents.
