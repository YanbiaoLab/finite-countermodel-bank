# Reproduction timeline / 复现时间线

This file is the review order for reconstructing the False Solver data lineage.
Each numbered stage is append-only after merge. A later correction adds a new
manifested artifact or superseding stage; it does not silently replace historical
raw files.

本文档规定 False Solver 数据血缘的复现及 review 顺序。每个编号阶段合并后保持只追加；
如需修正，应增加带 manifest 的新文件或后继阶段，不静默覆盖历史原始文件。

## PR and stage order / PR 与阶段顺序

| PR | Stage | Transition or anchor | Required evidence | Status |
| --- | --- | --- | --- | --- |
| PR 0 | `00-submission-anchor` | Four SAIR submissions → two byte-distinct solver blobs | Four downloaded files, submission index, hashes, schema, verifier | Merged in PR #2 |
| PR 1 | `10-primary-9450` | 9,452 nonzero contributors → 9,450 recoverable exact tables | Historical inputs, recovery report, normalized tables, per-record provenance | Merged in PR #3 |
| PR 1 | `20-registered-9852` | 9,450 + 402 → 9,852 | Registry snapshot, exact-dedup delta | Merged in PR #3 |
| PR 1 | `30-early-deltas-9957` | 9,852 + (66 − 55) + (145 − 51) → 9,957 | Separate d1 and d2 snapshots and membership deltas | Merged in PR #3 |
| PR 1 | `40-delivery-10059` | 9,957 + 102 → 10,059 | Delivery snapshot, independent-check report, zero-overlap delta | Merged in PR #3 |
| PR 2 | `50-generator-prune-3535` | 10,059 − 241 − 6,283 → 3,535 | Affine witnesses, order-at-most-4 removal ledger, exact d17 match | Merged in PR #4 |
| PR 2 | `60-fin4-residual-284151591` | 324,157,667 − 40,006,076 → 284,151,591 directed pairs | Frozen bitsets, per-source partition, Fin4 shard ledger, bounded validation | Merged in PR #4; frozen-artifact replay |
| PR 2 | `70-positive-marginal-core-1470` | 3,535 − 2,065 → 1,470 | Residual coverage scores, fixed selection order, keep/drop delta, submission-prefix match | Merged in PR #4 |
| PR 3 | `80-finite149` | 789 no-submission directions → 149 finite directions → 17 base tables + 11 required opposite orientations | Official-path inventory, exhaustive task checks, zero-overlap audit, Refutation934 substitution record | Merged in PR #7 |
| PR 3 correction | `81-finite149-portable-verification` | Same Stage 80 data; bounded replay and provenance correction | 789-cell streamed projection, full 149-task/transpose/overlap/suffix semantic gate, 17 Lean-source comparisons, corrected Refutation934 source, explicit path boundary | Merged in PR #8 |
| PR 4 | `90-payload-1487` | 1,470 + 17 → 1,487 embedded records | Exact inner-payload builder, canonical byte stream, XZ/Base85 literal, static submitted-source comparison | Verified in this PR |
| PR 4 | `100-opposite-closure-2901` | 1,487 + 1,414 missing strict transposes → 2,901 | Derivation ledger, exact-byte dedup report, historical first-seen joins, submitted-code audit, runtime scan manifest | Verified in this PR |

The PR boundaries are intentional. PR 1 preserves historical accumulation; PR 2
records later pruning, frozen Fin4 residual validation, and coverage-based
selection; PR 3 isolates the independent finite149 augmentation; its Stage 81
correction fixes the review path without changing Stage 80 data; PR 4 reconstructs
the exact inner finite-table payload and its runtime opposite closure. It does not
claim to rebuild the complete outer solver launcher. Work does not advance to the
next PR until the previous PR has received human review.

这些 PR 边界用于避免把不同时间点的数据混在一起：PR 1 保存历史累积，PR 2 保存后续
精简及覆盖筛选，PR 3 单独保存 finite149 增补，Stage 81 只修正其复现与来源说明，PR 4
精确重建内层有限表 payload 及其运行时 opposite closure，但不声称重建完整外层 solver。
前一个 PR 未完成人工 review 前，不推进下一个 PR。

## Arithmetic checkpoints / 数量检查点

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

Values through 10,059 are reconstructed and verified in PR 1. The 3,535-table
candidate bank, exact 324M-to-284M frozen-bitset transition, and 1,470-table core
are reconstructed or independently validated in PR 2. Stage 60 does not claim a
from-scratch Fin4 rerun because required singleton and seed-chain inputs are
missing. PR 3 verifies the separate 17-base finite149 augmentation and its 11
task-required transposes without constructing the cumulative 1,487-record payload.
Stage 81 supersedes only the portable verification and provenance description; all
Stage 80 arithmetic and table membership remain unchanged. PR 4 now publishes and
verifies the exact 1,487-record inner payload, then derives 1,414 missing exact
transposes to form the 2,901-record runtime scan. The derived records are not extra
embedded payload entries. The Stage 100 delta is relative to Stage 90 membership:
17 of those exact records have earlier history (6 in Stage 10 and 11 in Stage 80),
while 1,397 are first seen in Stage 100. `CLAIMS.csv` is authoritative for claim
status.

## Source routing / 源文件入口

Paths below are relative to the sibling `math-distill-equational-stage2` checkout.
Stages 10–40 are fixed by the raw snapshots in PR 1, Stages 50–70 by the raw
snapshots in PR 2, and Stage 80 by the deterministic raw snapshot in PR 3. Stages
81, 90, and 100 consume only immutable artifacts already committed to this
repository; they require no new sibling-checkout capture.

以下路径相对于同级 `math-distill-equational-stage2` checkout。Stage 10–40 已由
PR 1 的 raw 快照固定，Stage 50–70 已由 PR 2 的 raw 快照固定，Stage 80 已由 PR 3 的
确定性 raw 快照固定；Stage 81、90 与 100 只使用本仓库已提交的不可变产物，不需要再次
从 sibling checkout 抓取数据。

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
| `81-finite149-portable-verification` | Immutable Stage 80 raw snapshot and normalized artifacts; no new sibling-checkout input |
| `90-payload-1487` | Committed Stage 70 core, Stage 80 base records, Stage 81 corrected provenance, and the four Stage 00 submitted solver anchors |
| `100-opposite-closure-2901` | Exact Stage 90 payload, its transitive historical table indexes (including Stage 80 required transposes), and the generic transpose-closure functions statically parsed from the committed Stage 00 false engine |

Many `members/wubing/` paths are ignored by the sibling repository. A file copied
from such a path must be labeled as a captured local snapshot with capture time and
hash, not represented as content from a Git commit unless the bytes are actually
reachable from that commit.

Stage 60's captured packages do not include the no-longer-present
`singleton_family_mask.u8`, `singleton_primary.u8`, Fin4 `equations.bin`, or the
complete 6,173-model seed-generation chain. Its evidence supports exact replay and
validation of the frozen bitsets and ledgers, not regeneration from those missing
earliest inputs.

## Stage acceptance contract / 阶段验收规范

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
