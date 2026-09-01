# Reproduction stages

Directories are ordered by the historical pipeline, not by the date on which they
are uploaded to GitHub. A stage should be independently reviewable. Historical raw
bytes and scientific claims are not silently rewritten; explicit repository-wide
maintenance may update tooling names and manifest commands when the evidence is
unchanged and the result is reverified.

## Phase and stage terminology

`Phase` is the stable high-level grouping; `Stage` is the independently
verifiable evidence unit. `PR` is reserved for actual GitHub development history
in the root `TIMELINE.md`.

| Phase | Included stages |
| --- | --- |
| Phase 0 | Stage 00 |
| Phase 1 | Stages 10–40 |
| Phase 2 | Stages 50–70 |
| Phase 3 | Stages 80–81 |
| Phase 4 | Stages 90–100 |

## Required stage files

- `README.md`: human reproduction guide, exact commands, expected counts, and gaps.
- `stage.json`: sources, dependencies, claim IDs, and immutable artifact metadata.
- `raw/`: source bytes as received, without normalization or deduplication.
- `normalized/`: canonical records produced deterministically from `raw/`, when applicable.
- `delta.jsonl` or a compressed equivalent: ordered membership decisions, when applicable.
- `SHA256SUMS`: hashes for every immutable artifact listed by `stage.json`.

Not every stage needs every optional directory. Omissions must be explained in its
README.

Maintained reproduction commands require Python 3.10+ and are recommended and
tested with Python 3.11, the official competition sandbox version. CI requires
3.11 and keeps 3.12 as an additional compatibility check.

## Canonical table identity

For an operation table of order `n` (`1 <= n <= 255`):

1. validate that there are exactly `n²` entries;
2. validate every entry is in `0..n-1`;
3. encode one byte containing `n`, followed by the row-major entries as bytes;
4. set `table_id` to `sha256:` followed by the lowercase SHA-256 hex digest.

Deduplication uses this exact identifier. It does not quotient by isomorphism.

## Raw, normalized, and delta data

`raw/` answers “what bytes were available at that historical point?”
`normalized/` answers “what canonical tables do those bytes represent?”
The delta answers “why did each record enter, stay in, leave, replace, or derive
from the previous set?” This separation allows a reviewer to rerun normalization
without losing the original evidence.

Large files should be processed as streams or bounded chunks. Compressed future
artifacts should use deterministic settings documented in the stage README.

## Phase 1 capture and rebuild

Phase 1 deliberately separates the one-time local capture from the portable rebuild.
If the matching historical sibling checkout is available, recreate the four raw
archives with:

```bash
python3 tools/capture_phase1_snapshots.py \
  --source-root ../math-distill-equational-stage2
```

The capture command selects an explicit file list, sorts archive paths, streams
file bytes, and normalizes tar ownership, modes, and timestamps plus the gzip
header. It does not edit the sibling checkout. Normal reviewers do not need that
checkout; they reproduce all normalized data from the committed archives:

```bash
python3 tools/rebuild_phase1.py
python3 tools/verify_repository.py
```

Phase 1 uses deterministic `tar.gz`, JSONL gzip (`mtime=0`), and uncompressed
canonical table binaries so the workflow depends only on the Python standard
library. Historical `.py` inputs are parsed as data and never imported or run.

## Phase 2 capture and rebuild

Phase 2 contains three linked but separately reviewable stages:

| Stage | Exact transition | Reproduction level |
| --- | --- | --- |
| `50-generator-prune-3535` | `10,059 - 241 - 6,283 = 3,535` tables | Static reconstruction with exact d17 payload match |
| `60-fin4-residual-284151591` | `324,157,667 - 40,006,076 = 284,151,591` pairs | Frozen-artifact validation plus a completed, exactly matching seed-free result-level rerun |
| `70-positive-marginal-core-1470` | `3,535 - 2,065 = 1,470` tables | Deterministic selection replay with submission-prefix match |

The one-time capture reads an explicit, stage-specific file list from the sibling
development checkout:

```bash
python3 tools/capture_phase2_snapshots.py \
  --source-root ../math-distill-equational-stage2
```

Stage 60 capture sequentially reads two 489,598,720-byte bitsets, so it performs
substantial disk I/O even though its memory use is bounded. Normal reviewers do not
need the sibling checkout. Rebuild all three stages from the committed snapshots
with:

```bash
python3 tools/rebuild_phase2.py
python3 tools/verify_repository.py
```

The rebuild parses captured Python sources through a restricted AST literal reader
and never imports them. Pair bitsets are validated as forward-only gzip streams,
one 7,824-byte row from each bitset at a time. Stage 70 joins only 3,535 frozen CSV
rows to canonical table identities and does not materialize the residual pair set.
Stage-targeted verifier commands automatically include transitive dependencies, so
the cross-stage table identity and order checks are not skipped.

Stage 60 now deterministically reconstructs `eq_size5.txt`, `equations.bin`, the
mirror map, and both singleton masks byte for byte from its frozen snapshot. These
are Stage 60 support/upstream files: the new runner consumes only `equations.bin`
and the mirror map, while the singleton masks belong to upstream 324M construction.
It also provides a guarded, resumable, seed-free all-bit-sliced runner and a bounded
scalar/bitslice semantic smoke test. The new runner is a result-level method. Its
complete 256-shard `2^32` execution finished without retries and reproduced the
committed 284,151,591-pair bitset exactly; the compact report and sanitized logs
are committed in the Stage 60 verification directory. The historical 6,173-model
seed-generation/provenance chain remains unavailable. Stage 70 likewise replays
the frozen coverage outputs by default; rerunning its historical C evaluator is
outside the portable standard-library workflow.

## Phase 3 finite149 augmentation and portable correction

Stage `80-finite149` preserves the immutable finite149 snapshot and the
`789 → 149 → 17 + 11` augmentation. Its merged historical builder materializes the
complete finite-outcomes JSON, so normal review now uses the append-only corrective
stage `81-finite149-portable-verification`:

```bash
python3 tools/rebuild_phase3.py
python3 reproduction/81-finite149-portable-verification/scripts/verify.py
```

`tools/rebuild_phase3.py` is the maintained Phase-level entry point. It delegates
to the manifested Stage 81 bounded-memory builder and does not run the historical
high-memory Stage 80 rebuild path.

Stage 81 validates all 4,694 equation names, streams all 4,694 matrix rows through
top-level EOF under a 256 KiB application-buffer cap, and retains only the 789
requested cells. It reproduces the exact Stage 80 screening ledger, parses all 17
captured Lean operator-table comments, and publishes the corrected effective source
for the order-22 `F149-014` table. The same portable command reruns all 149
exhaustive task checks, 11 transpose derivations, orientation/delta joins, exact
zero-overlap, and submitted prefix/suffix comparisons, so replacing the historical
high-memory command does not reduce CI semantic coverage.

The correction also completes the finite149 graph/path source closure. A companion
raw archive preserves the pinned graph, dual mapping, graph-construction page,
companion `full_entries.json`, exact Apache-2.0 license text, and the 13 path-only
Lean files that supplement Stage 80's 17 table sources. The bounded replay ports
the captured graph-consumer rules and validates all 405 edge instances of the 149
frozen paths (159 unique directed edges, 170 nodes) with zero missing, reversed-only,
or source-mismatched edges. It does not rerun upstream graph extraction/building,
shortest-path discovery, Judge v3, Lean compilation, or outer-solver generation.
Independent exhaustive finite-table semantics for all 149 directions remain
available in Stage 80.

Stage 81 adds the manifested companion `raw/` snapshot described above while
leaving the immutable Stage 80 archive untouched. It has no delta because it
changes no table membership.

## Phase 4 exact payload and runtime closure

Phase 4 contains two deterministic stages that consume only committed predecessors:

| Stage | Exact transition | Published boundary |
| --- | --- | --- |
| `90-payload-1487` | `1,470 + 17 = 1,487` embedded records | Exact inner canonical stream and current 2026-09-01 submitted XZ/Base85 table literal |
| `100-opposite-closure-2901` | `1,487 + 1,414 = 2,901` runtime records | Static replay of the generic missing-transpose closure |

Rebuild and verify both stages with Python 3.11:

```bash
python3 tools/rebuild_phase4.py
python3 tools/verify_phase4.py
```

Stage 90 concatenates the Stage 70 core and Stage 80 base records in exact submitted
order, while taking the finite149 effective provenance from the merged Stage 81
correction. The resulting 111,009-byte stream is regenerated as the exact submitted
XZ payload using CRC64 and `9 | lzma.PRESET_EXTREME`, then Python Base85 encoded.
All four current 2026-09-01 submitted launchers are parsed as data through
restricted AST extraction; none is imported or executed. The superseded
2026-08-31 submission bytes remain historical inputs to Stages 70–81.

Stage 100 yields all 1,487 embedded records first, then scans those originals in
order and appends a strict transpose only when its canonical bytes are absent. Nine
sources are self-transpose and 64 sources form 32 already-embedded opposite pairs,
so 1,414 new records are derived and the runtime scan contains 2,901 distinct
records. The 11 task-required Stage 80 transposes are an exact subset of these
generic derivations, not an additional append. The delta's `derive` action is
relative to Stage 90 membership: six derived byte strings were first recorded in
Stage 10 and the eleven required transposes were first recorded in Stage 80. Those
17 preserve their historical `first_seen_stage`; 1,397 are first seen here.

Neither stage has a new `raw/` directory because its complete inputs are already
manifested dependencies. The byte-for-byte reconstruction covers the inner table
payload and its pinned transformation; it does not rebuild or execute the complete
current outer solver launchers (490,289-byte Solo and 499,149-byte Marathon), rerun
the finite149 search, or revalidate Lean certificate generation.
