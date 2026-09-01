# Stage 60 — Fin4 residual 284,151,591

This stage replays and independently validates the frozen pair artifacts for the
transition

```text
324,157,667 - 40,006,076 = 284,151,591 directed pairs
```

The 324,157,667 input is a targeted universe after earlier Fin2/Fin3 coverage and
singleton-true exclusions. It is not the full directed nonreflexive universe:

```text
2,285,032,108 Fin2/Fin3 covered
+ 1,306,503,425 singleton true
+   324,157,667 targeted before Fin4
= 3,915,693,200 = 62,576 * 62,575
```

## What is verified

The portable rebuild streams both 489,598,720-byte bitsets into deterministic gzip
mirrors. It checks all 62,576 rows using one 7,824-byte row from each bitset at a
time, without materializing either bitset or a directed-pair list in memory. The
uncompressed digests are:

- 324M input:
  `f3cce217528adee2305e618a81a1fdb7399c6732523bb60f055b1d5acf61f383`;
- 284M residual:
  `03f4a7eccc7df811756fc5da361a647b49b9064f35b2b14730362fc3fb810756`.

Validation requires the residual to be a subset of the input, recomputes both
popcounts and their difference, checks every per-source partition identity, and
requires diagonal and out-of-range bits to be zero. Both bitsets have 41,696 active
source rows.

The captured 256 completed shard records also form contiguous, gapless ranges over
all `2^32` labeled order-4 tables. Their frozen accounting contains 178,981,952
isomorphism classes: 58,254,198 from the first six scalar shards and 120,727,754
from the remaining bit-sliced shards. These records are audited for range and count
consistency; the historical engines are not executed by the normal rebuild.

## Reproduce

The commands require CPython 3.9 or newer and were tested with CPython 3.9.6;
only the standard library is used.

```bash
python3 tools/rebuild_phase2.py
python3 tools/verify_repository.py --stage 60-fin4-residual-284151591
```

The bitset copy/validation working set is bounded to two gzip streams plus one row
from each bitset; the large uncompressed files are never held in memory. Several
small manifests, CSV ledgers, and shard records are also processed under explicit
per-file bounds.

The one-time capture command reads the two large source bitsets sequentially and
therefore performs roughly a gigabyte of input I/O:

```bash
python3 tools/capture_phase2_snapshots.py \
  --source-root ../math-distill-equational-stage2 \
  --stage 60-fin4-residual-284151591
```

Normal reviewers do not need the sibling checkout and should not rerun capture.

## Reproduction boundary

This is a frozen-artifact replay and validation stage, not a from-scratch Fin4
rerun. The `singleton_family_mask.u8` and `singleton_primary.u8` inputs named by the
324M manifest are no longer present. The Fin4 runner's `equations.bin` and the
complete 6,173-model seed-generation chain are also unavailable. Those gaps prevent
regenerating the 324M universe and historical Fin4 search from their earliest
inputs, even though the exact committed bitsets, per-source ledgers, 256 shard
records, and their arithmetic can be independently checked.
