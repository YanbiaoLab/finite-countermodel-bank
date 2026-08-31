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
| PR 1 | `10-primary-9450` | 9,452 nonzero contributors → 9,450 recoverable exact tables | Historical inputs, recovery report, normalized tables, per-record provenance | Verified in this PR |
| PR 1 | `20-registered-9852` | 9,450 + 402 → 9,852 | Registry snapshot, exact-dedup delta | Verified in this PR |
| PR 1 | `30-early-deltas-9957` | 9,852 + (66 − 55) + (145 − 51) → 9,957 | Separate d1 and d2 snapshots and membership deltas | Verified in this PR |
| PR 1 | `40-delivery-10059` | 9,957 + 102 → 10,059 | Delivery snapshot, independent-check report, zero-overlap delta | Verified in this PR |
| PR 2 | `50-generator-prune-3535` | 10,059 − 241 − 6,283 → 3,535 | Generator-reproducible and order-at-most-4 removal ledgers | Planned |
| PR 2 | `60-fin4-residual-284151591` | 324,157,667 − 40,006,076 → 284,151,591 directed pairs | Universe manifest, Fin4 coverage bitset, residual bitset, cardinality checks | Planned |
| PR 2 | `70-positive-marginal-core-1470` | 3,535 − 2,065 → 1,470 | Residual coverage scores, deterministic selection order, keep/drop delta | Planned |
| PR 3 | `80-finite149` | 149 directions → 17 base tables + 11 required opposite orientations | Official-path inventory, exhaustive task checks, Refutation934 substitution record | Planned; source snapshot required |
| PR 4 | `90-payload-1487` | 1,470 + 17 → 1,487 embedded records | Payload builder, byte stream, Base85/LZMA bundle, exact solver comparison | Planned |
| PR 4 | `100-opposite-closure-2901` | 1,487 + 1,414 missing strict transposes → 2,901 | Derivation ledger, dedup report, runtime scan manifest | Planned |

The PR boundaries are intentional. PR 1 preserves historical accumulation; PR 2
records later pruning and coverage-based selection; PR 3 isolates the independent
finite149 augmentation; PR 4 rebuilds and compares the final submission. Work does
not advance to the next PR until the previous PR has received human review.

这些 PR 边界用于避免把不同时间点的数据混在一起：PR 1 保存历史累积，PR 2 保存后续
精简及覆盖筛选，PR 3 单独保存 finite149 增补，PR 4 才构建最终提交并逐字节比较。前一个
PR 未完成人工 review 前，不推进下一个 PR。

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

Values through 10,059 are reconstructed and verified in PR 1; later values remain
expected claims until their corresponding stage is merged and verified.
`CLAIMS.csv` is authoritative for claim status.

## Source routing / 源文件入口

Paths below are relative to the sibling `math-distill-equational-stage2` checkout.
Stages 10–40 are fixed by the raw snapshots in PR 1; paths for Stage 50 and later
identify audited or expected starting points whose evidence is not yet published.

以下路径相对于同级 `math-distill-equational-stage2` checkout。Stage 10–40 已由
PR 1 的 raw 快照固定；Stage 50 及后续路径仍只是已审计或预期的入口，证据尚未发布。

| Stage | Audited starting point |
| --- | --- |
| `10-primary-9450` | `members/wubing/data/processed/rulebooks/order5_rule_registry/false/selected_false_finmodel_rule_scripts/` and `members/wubing/data/324M_remaining_pairs/order5_equations.csv` |
| `20-registered-9852` | `members/wubing/data/processed/rulebooks/order5_rule_registry/false/` and `members/wubing/experiments/solvers/false_solver/drafts/d3/` |
| `30-early-deltas-9957` | `members/wubing/experiments/solvers/false_solver/drafts/` subdirectories `d1`, `d2`, `d4`, `d6`, and `d8` |
| `40-delivery-10059` | `members/wubing/data/processed/jiaming/` and `members/wubing/experiments/solvers/false_solver/drafts/d11/` |
| `50-generator-prune-3535` | `members/wubing/experiments/solvers/false/20260812_d17/` |
| `60-fin4-residual-284151591` | `members/wubing/data/324M_remaining_pairs/`, `members/wubing/data/284M_remaining_pairs/` |
| `70-positive-marginal-core-1470` | `members/wubing/artifacts/runs/d17-finite-model-284m-pair-coverage-20260818/` |
| `80-finite149` | Expected historical package must be supplied and captured before reconstruction |

Many `members/wubing/` paths are ignored by the sibling repository. A file copied
from such a path must be labeled as a captured local snapshot with capture time and
hash, not represented as content from a Git commit unless the bytes are actually
reachable from that commit.

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
