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

The captured 256 historical shard records also form contiguous, gapless ranges over
all `2^32` labeled order-4 tables. Their frozen accounting contains 178,981,952
isomorphism classes: 58,254,198 from the first six scalar shards and 120,727,754
from the remaining bit-sliced shards. These records are audited for range and count
consistency; the historical engines are not executed by the normal rebuild.

## Seed-free result-level rerun tooling

Five Stage 60 support/upstream files that were not preserved as standalone files
can now be reconstructed deterministically from the frozen snapshot:

- `eq_size5.txt`;
- `equations.bin`;
- `equation_mirror_map.bin`;
- `singleton_family_mask.u8`;
- `singleton_primary.u8`.

`verification/seedfree-input-reconstruction.json` records their exact historical
byte sizes and SHA-256 values. Reconstruct them outside the worktree with:

```bash
python3 reproduction/60-fin4-residual-284151591/scripts/reconstruct_inputs.py \
  --output-dir /tmp/finite-countermodel-stage60-inputs
```

The new enumeration runner consumes reconstructed `equations.bin` and
`equation_mirror_map.bin`. `eq_size5.txt` supports independent semantic fixtures.
The two singleton masks belong to upstream 324M construction and are recovered for
byte-level source closure; the new runner starts from the committed 324M bitset and
does not consume either mask.

The bounded semantic smoke test extracts and compiles both frozen C engines. It
checks three independently derived Fin4 signatures through the scalar evaluator,
the scalar evaluator embedded in the bit-sliced engine, and the 64-lane bit-sliced
evaluator:

```bash
python3 reproduction/60-fin4-residual-284151591/scripts/smoke_test_engines.py
```

That command reconstructs about 4 MiB of inputs and does not materialize either
489,598,720-byte pair bitset.

`--prepare-only` and `--max-shards 0` likewise stop after small-input recovery plus
engine compilation/self-test. They do not create an enumeration bitset or
`progress.json`:

```bash
python3 reproduction/60-fin4-residual-284151591/scripts/run_seedfree.py \
  --work-dir /tmp/finite-countermodel-stage60-prepare \
  --prepare-only
```

The guarded runner starts from a clean copy of the committed 324M bitset, does not
load the historical 6,173-model seeds, supports shard checkpoints/resume and
thread limits, and uses the frozen bit-sliced/opposite engine over the entire
requested interval. The all-bit-sliced schedule is a new result-level method, not
a byte-for-byte replay of the historical scalar/seeded execution order.

```bash
python3 reproduction/60-fin4-residual-284151591/scripts/run_seedfree.py \
  --work-dir /path/on-a-persistent-volume/stage60-seedfree-full \
  --threads 10 \
  --confirm-full-run
```

The default work directory is checkout-specific under the system temporary
directory, but a complete run should use an explicit persistent `--work-dir` as
shown above. Every actual enumeration, even a small range, materializes two
489,598,720-byte files: budget roughly 0.98 GB of bitset disk and approximately
0.5 GB peak RSS. It is not an ordinary CI task. Before materialization the runner
checks free space for both missing bitsets plus a 256 MiB reserve and records the
preflight. `--max-shards`, `--shard-size`, and `--threads` control pausing, shard
size, and concurrency; more than 4,096 shards is rejected.

An interrupted in-place shard is rerun. Because partial bit clears can survive
that interruption, its successful-attempt coverage sum is explicitly marked
non-authoritative. Wall/CPU totals then cover successful attempts only and are
lower bounds for the whole run. The final bitset comparison remains authoritative.

A complete run is accepted only if all of the following hold:

- the raw ranges sum to `2^32` and the canonical count is `178,981,952`;
- evaluated is exactly `89,521,056`, while opposite-derived and skipped are both
  exactly `89,460,896`; evaluated plus either count is `178,981,952`;
- an independent forward-only call to
  `tools.phase2_common.validate_pair_bitset_streams` binds all 62,576 rows to
  `normalized/pair-partition-by-source.csv.gz`;
- the popcounts are `324,157,667` and `284,151,591`, the removed count is
  `40,006,076`, and the final 489,598,720-byte bitset has SHA-256
  `03f4a7eccc7df811756fc5da361a647b49b9064f35b2b14730362fc3fb810756`.

After a successful default 256-shard run, compact durable evidence can be captured
without copying either bitset into the repository:

```bash
python3 reproduction/60-fin4-residual-284151591/scripts/capture_seedfree_evidence.py \
  --work-dir /path/on-a-persistent-volume/stage60-seedfree-full \
  --output-dir reproduction/60-fin4-residual-284151591/verification
```

The capture rehashes both work bitsets, validates `progress.json`, `final.json`, all
256 summary/log hashes, and writes `seedfree-full-run.json` plus deterministic-gzip
`seedfree-full-run-logs.jsonl.gz`. It includes every parsed shard summary and
sanitized stderr text while retaining the raw summary/stderr SHA-256 values. Those
two outputs are committed only after a full run succeeds.

The committed evidence records a successful full run completed at
`2026-09-01T06:50:17.096119Z` on arm64 macOS with CPython 3.9.6, Apple clang
21.0.0, ten runner threads, and 256 shards. No shard was retried. Successful shard
attempts account for 1,850.002391 wall seconds, 1,829.541131 engine elapsed
seconds, 16,319.442510 user CPU seconds, and 105.647160 system CPU seconds. Peak
engine RSS was 504,840,192 bytes. The final 489,598,720-byte residual has SHA-256
`03f4a7eccc7df811756fc5da361a647b49b9064f35b2b14730362fc3fb810756`
and matches the committed residual exactly.

`verification/seedfree-full-run.json` binds those metrics to all 256 shard
summaries, the reconstructed input and implementation hashes, compiler/engine
identity, and the independent 62,576-row streamed bitset check.
`verification/seedfree-full-run-logs.jsonl.gz` contains 256 parsed summaries plus
sanitized per-shard stderr. The run demonstrates the result-level outcome; it does
not reconstruct the historical seeded execution order or provenance chain.

## Reproduce

The Stage 60 runner and capture scripts were tested with CPython 3.9.6. The
maintained repository rebuild and verifier require Python 3.10+; only the standard
library is used.

```bash
python3 tools/rebuild_phase2.py
python3 tools/verify_repository.py --stage 60-fin4-residual-284151591
```

The normal bitset copy/validation working set is bounded to two gzip streams plus one row
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

The committed outcome remains a frozen-artifact replay and validation. The five
standalone-missing Stage 60 support/upstream files above are now byte-exactly
recoverable, and the new runner can perform a seed-free result-level enumeration.
The singleton masks are not inputs to that runner. The complete
6,173-model seed-generation/provenance chain is still unavailable, so the original
historical seeded workflow cannot be replayed byte for byte. Nor does this stage
regenerate the upstream 324M universe from its earliest Fin2/Fin3 and singleton
discovery inputs.
