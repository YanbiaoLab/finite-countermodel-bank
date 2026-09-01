# Reproduction timeline

This file is the review order for reconstructing the False Solver data lineage.
Historical raw bytes and scientific claims are not silently replaced after merge.
A correction adds a manifested artifact or superseding stage; a repository-wide
terminology migration may update maintained script names and manifest commands
while preserving the raw bytes, transitions, and claims.

## Phase, Stage, and GitHub history

| Phase | Stage | Transition or anchor | Required evidence | GitHub history |
| --- | --- | --- | --- | --- |
| Phase 0 | `00-submission-anchor` | Four current SAIR submissions → two byte-distinct solver blobs; four superseded files retained historically | Eight downloaded files, current and historical indexes, hashes, schema, verifier | Initial capture merged in PR #2; refreshed 2026-09-01 |
| Phase 1 | `10-primary-9450` | 9,452 nonzero contributors → 9,450 recoverable exact tables | Historical inputs, recovery report, normalized tables, per-record provenance | Merged in PR #3 |
| Phase 1 | `20-registered-9852` | 9,450 + 402 → 9,852 | Registry snapshot, exact-dedup delta | Merged in PR #3 |
| Phase 1 | `30-early-deltas-9957` | 9,852 + (66 − 55) + (145 − 51) → 9,957 | Separate d1 and d2 snapshots and membership deltas | Merged in PR #3 |
| Phase 1 | `40-delivery-10059` | 9,957 + 102 → 10,059 | Delivery snapshot, independent-check report, zero-overlap delta | Merged in PR #3 |
| Phase 2 | `50-generator-prune-3535` | 10,059 − 241 − 6,283 → 3,535 | Affine witnesses, order-at-most-4 removal ledger, exact d17 match | Merged in PR #4 |
| Phase 2 | `60-fin4-residual-284151591` | 324,157,667 − 40,006,076 → 284,151,591 directed pairs | Frozen bitsets, per-source partition, Fin4 shard ledger, byte-exact input recovery, and completed seed-free result-level rerun | Merged in PR #4; rerun tooling and full-run evidence added after merge |
| Phase 2 | `70-positive-marginal-core-1470` | 3,535 − 2,065 → 1,470 | Residual coverage scores, fixed selection order, keep/drop delta, historical 2026-08-31 submission-prefix match | Merged in PR #4 |
| Phase 3 | `80-finite149` | 789 no-submission directions → 149 finite directions → 17 base tables + 11 required opposite orientations | Official-path inventory, exhaustive task checks, zero-overlap audit, Refutation934 substitution record | Merged in PR #7 |
| Phase 3 | `81-finite149-portable-verification` | Same table data; bounded semantic replay, provenance correction, and frozen-path edge validation | 789-cell streamed projection, full 149-task/transpose/overlap/historical-suffix semantic gate, 17 Lean-table comparisons, corrected Refutation934 source, 30-file path-source closure, and 405 edge-instance replay | Merged in PR #8; graph/path evidence extended after merge |
| Phase 4 | `90-payload-1487` | 1,470 + 17 → 1,487 embedded records | Exact inner-payload builder, canonical byte stream, current 2026-09-01 XZ/Base85 literal, static submitted-source comparison | Merged in PR #9 |
| Phase 4 | `100-opposite-closure-2901` | 1,487 + 1,414 missing strict transposes → 2,901 | Derivation ledger, exact-byte dedup report, historical first-seen joins, current 2026-09-01 submitted-code audit, runtime scan manifest | Merged in PR #9 |

The Phase boundaries keep evidence from different points in the data flow separate.
Phase 1 preserves historical accumulation; Phase 2 records pruning, frozen Fin4
residual validation, and coverage-based selection; Phase 3 isolates the finite149
augmentation and its portable correction; Phase 4 reconstructs the exact inner
finite-table payload and runtime opposite closure. It does not claim to rebuild the
complete outer solver launcher. `PR` in the final column refers only to the actual
GitHub pull request in which the evidence was merged; Phase numbers are independent
of PR numbers.

## Arithmetic checkpoints

```text
9,450 + 402                                      = 9,852
9,852 + (66 - 55) + (145 - 51)                 = 9,957
9,957 + 102                                     = 10,059
10,059 - 241 - 6,283                            = 3,535
324,157,667 - 40,006,076                        = 284,151,591
3,535 - 2,065                                   = 1,470
1,470 + 17                                      = 1,487
1,487 + 1,414                                   = 2,901
```

Values through 10,059 are reconstructed and verified in Phase 1. The 3,535-table
candidate bank, exact 324M-to-284M frozen-bitset transition, and 1,470-table core
are reconstructed or independently validated in Phase 2. Stage 60 now recovers the
standalone equations, mirror map, and singleton-mask support/upstream files byte for byte and
implements a new seed-free result-level Fin4 runner. Its complete 256-shard `2^32`
run finished without retries and reproduced the committed residual byte for byte;
the historical seed-generation/provenance chain remains missing. Phase 3 verifies
the separate 17-base finite149 augmentation and its 11
task-required transposes without constructing the cumulative 1,487-record payload.
Stage 81 supersedes only the portable verification, provenance, and frozen-path
edge-validation description; all Stage 80 arithmetic, raw history, and table
membership remain unchanged. It validates the recorded paths without rerunning
upstream graph extraction/building or shortest-path discovery. Phase 4 publishes and
verifies the exact 1,487-record inner payload, then derives 1,414 missing exact
transposes to form the 2,901-record runtime scan. The derived records are not extra
embedded payload entries. The Stage 100 delta is relative to Stage 90 membership:
17 of those exact records have earlier history (6 in Stage 10 and 11 in Stage 80),
while 1,397 are first seen in Stage 100. `CLAIMS.csv` is authoritative for claim
status.

## Source routing

Paths below are relative to the sibling `math-distill-equational-stage2` checkout.
Stages 10–40 are fixed by the raw snapshots in Phase 1, Stages 50–70 by the raw
snapshots in Phase 2, and Stage 80 by the deterministic raw snapshot in Phase 3.
Stages 81, 90, and 100 consume only immutable artifacts already committed to this
repository during normal rebuild. Stage 81's one-time companion capture used the
hash-pinned upstream graph files and the 13 missing Lean files from the matching
sibling checkout; neither input is needed by the maintained rebuild command.

| Stage | Audited starting point |
| --- | --- |
| `10-primary-9450` | `members/wubing/data/processed/rulebooks/order5_rule_registry/false/selected_false_finmodel_rule_scripts/` and `members/wubing/data/324M_remaining_pairs/order5_equations.csv` |
| `20-registered-9852` | `members/wubing/data/processed/rulebooks/order5_rule_registry/false/` and `members/wubing/experiments/solvers/false_solver/drafts/d3/` |
| `30-early-deltas-9957` | `members/wubing/experiments/solvers/false_solver/drafts/` subdirectories `d1`, `d2`, `d4`, `d6`, and `d8` |
| `40-delivery-10059` | `members/wubing/data/processed/jiaming/` and `members/wubing/experiments/solvers/false_solver/drafts/d11/` |
| `50-generator-prune-3535` | `members/wubing/experiments/solvers/false_solver/drafts/d15/`, `members/wubing/experiments/solvers/false_solver/drafts/d17/`, and `solvers/false/20260812_d17/` |
| `60-fin4-residual-284151591` | `members/wubing/data/324M_remaining_pairs/`, `members/wubing/data/284M_remaining_pairs/`, and the `d17-fin4-exhaustive-full-20260818` / `d17-fin4-exhaustive-full-bitslice-opposite-20260818` run directories |
| `70-positive-marginal-core-1470` | `members/wubing/artifacts/runs/d17-finite-model-284m-pair-coverage-20260818/` and `members/wubing/artifacts/runs/d17-finite-model-order5-law-counts-20260817/` |
| `80-finite149` | `research_best/20260821_solo_v2_order4_full_generated/finite_not_generated_lean/`, its 789-direction audit, the exact finite-outcome matrix, and `research_best/20260825_solo_v5_finite149_static_library/` Refutation934 reduction record |
| `81-finite149-portable-verification` | Immutable Stage 80 evidence plus the committed companion snapshot of the pinned finite graph, graph consumer, duals, license, and 13 path-only Lean sources |
| `90-payload-1487` | Committed Stage 70 core, Stage 80 base records, Stage 81 corrected provenance, and the four current 2026-09-01 Stage 00 submitted solver anchors |
| `100-opposite-closure-2901` | Exact Stage 90 payload, its transitive historical table indexes (including Stage 80 required transposes), and the generic transpose-closure functions statically parsed from the current 2026-09-01 Stage 00 false engine |

Many source paths listed above are ignored by the sibling repository. A file copied
from such a path must be labeled as a captured local snapshot with capture time and
hash, not represented as content from a Git commit unless the bytes are actually
reachable from that commit.

Stage 60's captured package contains sufficient row-level source data to
reconstruct `singleton_family_mask.u8`, `singleton_primary.u8`, Fin4
`equations.bin`, the mirror map, and equation text with their historical bytes.
The maintained runner consumes the equation binary and mirror map, not the upstream
singleton masks. The snapshot does not contain the complete 6,173-model
seed-generation/provenance chain; the runner therefore uses a new seed-free
result-level schedule rather than replaying the historical execution order.

## Stage acceptance contract

A stage is complete only when all applicable items are present:

1. `stage.json` records sources, dependencies, claim IDs, and every immutable artifact.
2. `raw/` preserves the files as received; normalization never rewrites these files.
3. `normalized/` uses the canonical table encoding defined in `schemas/README.md`.
4. Ordered `delta` records explain every add, duplicate, removal, replacement, or derivation.
5. `SHA256SUMS` agrees with the manifest and all sizes/hashes verify in a bounded stream.
6. The stage README gives exact commands, expected counts, tool versions, and known gaps.
7. A claim moves from `planned` only when its evidence is committed in the same or an earlier stage.

Status vocabulary:

- `planned`: expected from the submission note or audit, but evidence is not merged.
- `captured`: an immutable source snapshot is present and hash-verified.
- `reproduced`: committed commands regenerate the claimed output from committed inputs.
- `verified`: an independently checkable invariant has passed on committed artifacts.
- `blocked`: the named source needed for reproduction is known to be unavailable.
