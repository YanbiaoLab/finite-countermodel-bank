# Stage 70 — positive-marginal core 1,470

This stage deterministically replays the historical selection of the embedded core:

```text
3,535 candidates - 2,065 zero-marginal candidates = 1,470 retained tables
```

The candidate bank comes from Stage 50 and the 284,151,591-pair residual universe
comes from Stage 60. The output is the first 1,470 embedded records of the submitted
Marathon solver in the historical 2026-08-31 capture, in exact record order.

## Frozen selection rule

The selection order is fixed once, before marginal coverage is scanned:

1. descending individual coverage of the 284M residual;
2. ascending historical `model_index` as the tie-breaker;
3. no adaptive reranking.

For each table in that order, the frozen deduplicated coverage report records how
many previously uncovered residual pairs it newly contributes. A table is retained
exactly when that marginal is positive. `normalized/selection-decisions.jsonl.gz`
and `delta.jsonl.gz` expose all 3,535 decisions in coverage-rank order.

Exact checkpoints from the frozen reports are:

- 2,303 candidates have positive individual coverage and 1,232 have zero
  individual coverage;
- individual coverage sums to 48,939,148 when overlap is counted;
- 1,470 candidates have positive marginal coverage in the fixed scan and 2,065
  have zero marginal coverage;
- the retained core covers a union of 32,336,615 residual pairs, leaving
  251,814,976 outside this core.

The final canonical table stream is 101,870 bytes with SHA-256
`7bbc54d33415143349c92cd4c919052ed54c1e5f20973a9b189818362654da5b`.
Every historical compact-JSON model digest maps to exactly one Stage 50 table. The
separate law-count audit checks all 3,535 rows and a recorded aggregate of
11,673,374,836 assignments; its satisfied/refuted law-profile counts agree with
the corresponding columns in the coverage reports.

## Reproduce

The commands require CPython 3.9 or newer and were tested with CPython 3.9.6;
only the standard library is used.

```bash
python3 tools/rebuild_phase2.py
python3 tools/verify_repository.py --stage 70-positive-marginal-core-1470
```

The one-time source capture is:

```bash
python3 tools/capture_phase2_snapshots.py \
  --source-root ../math-distill-equational-stage2 \
  --stage 70-positive-marginal-core-1470
```

Normal reconstruction reads the two small frozen coverage CSVs, maps their 3,535
identities to the Stage 50 bank, emits every decision, and checks the selected
records against the historical 2026-08-31 submitted solver. It does not need to
materialize the 284M pair universe.

## Evidence boundary

The exact historical `d17_fix` solver named by the coverage manifests is no longer
available at its recorded digest. Its table identity is nevertheless anchored in
two independent directions: all 3,535 coverage model digests map exactly to the
published Stage 50 d17 bank, and the selected 1,470 records match the authenticated
2026-08-31 historical submission prefix exactly.

Normal verification validates the frozen individual and deduplicated coverage
outputs structurally and replays their deterministic selection. Re-executing the
historical C evaluator is optional, requires a compiler and the large residual
bitset, and is not claimed by this stage.
