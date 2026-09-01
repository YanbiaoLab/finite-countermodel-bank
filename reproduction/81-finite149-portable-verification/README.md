# Stage 81 — portable finite149 verification

This is the corrective review layer for the already merged `80-finite149` stage;
its merge history is recorded in [`TIMELINE.md`](../../TIMELINE.md).
It preserves every Stage 80 raw and generated artifact byte for byte and changes
none of the `789 → 149 → 17 + 11` counts or table-membership decisions.

## What this corrects

The historical Stage 80 builder called `gzip.decompress()` and then `json.loads()`
on the complete finite-outcomes matrix. The nested JSON is 498,673,223 bytes after
decompression, so that implementation could require roughly 3.3 GB of resident
memory. It also documented Python 3.9 even though it uses `zip(..., strict=True)`,
which requires Python 3.10 or newer.

Stage 81 replaces that normal-review path with a standard-library parser that:

1. validates the exact `Equation1` through `Equation4694` vector;
2. parses all 4,694 matrix rows and 22,033,636 cells through top-level EOF;
3. retains only the 789 requested `(lhs_id, rhs_id)` cells;
4. limits its application buffer to 256 KiB (173,473 bytes observed for the
   committed input); and
5. reproduces the exact Stage 80 screening records and the partition
   `149 + 600 + 2 + 38 = 789`.

`verification/screening-stream-audit.json` records EOF completion, the buffer
bound, the input hash, and record-by-record agreement with the Stage 80 screening
ledger. The parser never constructs a complete two-dimensional Python list.

To avoid any CI coverage regression, the portable verifier also reruns the rest of
the material Stage 80 semantics under bounded memory: all 149 exhaustive
source/target evaluations, the 11 exact transpose derivations, the 129/20
orientation split, the 17-add/11-derive delta joins, zero overlap with the 1,470
core records, and the exact submitted 1,470-prefix/17-suffix order. It compares the
fresh 149 exhaustive records and all five Refutation934 task records with the
committed Stage 80 audits. The aggregate result is
`verification/stage80-portable-semantic-audit.json`.

## Lean tables and Refutation934

Stage 81 parses the generated operator-table comment from every one of the 17
captured official Lean files and compares the resulting table byte for byte with
the historical base-table rows. All 17 match. The audit is in
`verification/lean-source-table-audit.jsonl.gz`.

`F149-014` is special: its effective order-22 payload table does not come directly
from the order-24 row in `static_library_base_models.jsonl`. Its effective source is
`source/refutation934/order24_coverage_reductions.json`, where it is recorded as a
closed induced substructure of the captured official `Refutation934.lean` table.
The corrected source chain is published in
`verification/refutation934-effective-provenance.json` and the 17-row superseding
index `normalized/base-table-provenance.jsonl.gz`.

## ETP frozen-path edge replay

Stage 81 adds a deterministic companion raw snapshot containing the exact
hash-pinned `finite_graph.json`, `implications.js`, `show_proof.html`, companion
`full_entries.json`, the dual-pair data, and the 13 path-only Lean files absent
from Stage 80. Together with Stage 80's 17 table-source files, this closes the
30-file source inventory. The archive uses a fixed member allowlist, rejects
unsafe or duplicate paths, caps each member at 10 MiB and total uncompressed
content at 20 MiB, and records every byte count and SHA-256. The upstream
Apache-2.0 license text is included with its exact hash.

The replay streams the 9,042,748-byte graph and retains only its final, small
`full_entries` object; it does not materialize the large RLE/equivalence payload.
It ports the captured `show_proof.html` rules for `i`, `f`, and `u` entries,
negation, duals, weights, and insertion-order tie handling. All 405 edge instances
of the 149 frozen paths replay successfully: 159 unique directed edges across 170
path nodes, with zero missing edges, reversed-only matches, conjectural winners,
or source mismatches. The 20 transpose paths are also checked against the actual
dual Facts edges, not only against the manifest flag.

This is an edge validation of already-recorded paths. It does not rerun upstream
Lean-to-entry extraction or graph production, independently rediscover the same
shortest paths, invoke Judge v3, compile the referenced Lean sources, regenerate
aggregate/submission Lean certificates, or rebuild the complete outer solver.
Those scope flags are machine-readable in
`verification/path-evidence-boundary.json`; detailed counts and input identities
are in `verification/path-edge-replay-audit.json`.

## Python version

The reproduction scripts require **Python 3.10+** and are recommended and tested
with **Python 3.11**. Python 3.11 is the required CI baseline because the official
competition sandbox is [`python:3.11-slim`](https://github.com/SAIRcompetition/equational-theories-lean-stage2/blob/main/README.md#sandbox-python-environment).
Python 3.12 remains an additional compatibility job. The upstream README's
“Python 3.8+” prerequisite describes local harness tooling, not the formal sandbox
runtime.

## Reproduce

From the repository root, using a Python 3.11 interpreter:

```bash
python3 tools/rebuild_phase3.py
git diff --exit-code
python3 reproduction/81-finite149-portable-verification/scripts/verify.py
```

The Phase-level rebuild entry delegates to this stage's manifested bounded-memory
builder; it does not run the historical high-memory Stage 80 rebuild path. The
verifier regenerates all Stage 81 outputs in a temporary directory, compares every
generated byte, checks the committed manifest, and runs the repository verifier
with the full transitive dependency chain. Normal reviewers should use these
commands instead of the historical Stage 80 rebuild/verifier.

The one-time companion capture can be reproduced separately when the matching
upstream-source checkout and network access are available:

```bash
python3 reproduction/81-finite149-portable-verification/scripts/capture_path_sources.py \
  --source-root ../math-distill-equational-stage2/third_party/equational_theories
```

The script accepts no unpinned identities: it derives the exact 13-file source
closure from the Stage 80 authority, checks it against a fixed allowlist, streams
the large upstream inputs, and requires the recorded byte counts and SHA-256
values. The committed result is 961,095 compressed bytes with SHA-256
`127e420e469b1a97d942f851542d99e03d4c30d5f73ec26ada0d04ff97f175df`.

## Files and omissions

- `normalized/finite-outcomes-789.jsonl.gz`: the 789 selected matrix cells.
- `normalized/base-table-provenance.jsonl.gz`: superseding effective provenance for
  all 17 base records.
- `normalized/path-edge-replay.jsonl.gz`: all 405 validated frozen-path edge
  instances with winning source, line, theorem, weight, and dual metadata.
- `raw/finite149-path-source-snapshot.tar.gz`: pinned graph inputs, graph consumer,
  dual mapping, exact license text, and 13 added Lean path sources.
- `verification/screening-stream-audit.json`: full-matrix streaming and exact
  screening replay report.
- `verification/stage80-portable-semantic-audit.json`: complete low-memory replay
  of the remaining Stage 80 semantic checks.
- `verification/lean-source-table-audit.jsonl.gz`: 17 parsed-Lean table matches.
- `verification/refutation934-effective-provenance.json`: corrected `F149-014`
  source and induced-substructure chain.
- `verification/path-edge-replay-audit.json`: graph-input identities, bounded-tail
  parsing report, replay counts, source closure, and explicit non-claims.
- `verification/path-evidence-boundary.json`: frozen-path validation and remaining
  historical-discovery/compilation boundary.
- `summary.json`, `stage.json`, and `SHA256SUMS`: correction summary, manifest, and
  immutable hashes.

There is no membership delta because the correction adds, removes, and derives
zero tables. The new raw archive only completes the graph/path evidence boundary;
it does not rewrite Stage 80's historical snapshot.

Downstream [`90-payload-1487`](../90-payload-1487/) consumes this stage's corrected
17-row effective-provenance index when publishing the exact 1,487-record inner
payload. [`100-opposite-closure-2901`](../100-opposite-closure-2901/) then derives
the 1,414 missing transposes for the 2,901-record runtime scan. Neither downstream
stage changes the Stage 80/81 finite149 evidence or claims to rebuild the complete
outer solver launcher.
