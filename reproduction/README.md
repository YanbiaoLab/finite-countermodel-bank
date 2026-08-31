# Reproduction stages

Directories are ordered by the historical pipeline, not by the date on which they
are uploaded to GitHub. A stage should be independently reviewable and should not
rewrite an earlier stage.

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

## PR 1 capture and rebuild

PR 1 deliberately separates the one-time local capture from the portable rebuild.
If the matching historical sibling checkout is available, recreate the four raw
archives with:

```bash
python3 tools/capture_pr1_snapshots.py \
  --source-root ../math-distill-equational-stage2
```

The capture command selects an explicit file list, sorts archive paths, streams
file bytes, and normalizes tar ownership, modes, and timestamps plus the gzip
header. It does not edit the sibling checkout. Normal reviewers do not need that
checkout; they reproduce all normalized data from the committed archives:

```bash
python3 tools/rebuild_pr1.py
python3 tools/verify_repository.py
```

PR 1 uses deterministic `tar.gz`, JSONL gzip (`mtime=0`), and uncompressed
canonical table binaries so the workflow depends only on the Python standard
library. Historical `.py` inputs are parsed as data and never imported or run.

## PR 2 capture and rebuild

PR 2 adds three linked but separately reviewable stages:

| Stage | Exact transition | Reproduction level |
| --- | --- | --- |
| `50-generator-prune-3535` | `10,059 - 241 - 6,283 = 3,535` tables | Static reconstruction with exact d17 payload match |
| `60-fin4-residual-284151591` | `324,157,667 - 40,006,076 = 284,151,591` pairs | Frozen-artifact replay and independent validation |
| `70-positive-marginal-core-1470` | `3,535 - 2,065 = 1,470` tables | Deterministic selection replay with submission-prefix match |

The one-time capture reads an explicit, stage-specific file list from the sibling
development checkout:

```bash
python3 tools/capture_pr2_snapshots.py \
  --source-root ../math-distill-equational-stage2
```

Stage 60 capture sequentially reads two 489,598,720-byte bitsets, so it performs
substantial disk I/O even though its memory use is bounded. Normal reviewers do not
need the sibling checkout. Rebuild all three stages from the committed snapshots
with:

```bash
python3 tools/rebuild_pr2.py
python3 tools/verify_repository.py
```

The rebuild parses captured Python sources through a restricted AST literal reader
and never imports them. Pair bitsets are validated as forward-only gzip streams,
one 7,824-byte row from each bitset at a time. Stage 70 joins only 3,535 frozen CSV
rows to canonical table identities and does not materialize the residual pair set.
Stage-targeted verifier commands automatically include transitive dependencies, so
the cross-stage table identity and order checks are not skipped.

Stage 60 has an important boundary: the singleton masks, the Fin4 runner's
`equations.bin`, and the complete 6,173-model seed-generation chain are unavailable.
It therefore validates the exact frozen 324M/284M bitsets, per-source partitions,
and 256 completed shard records; it does not claim to regenerate the 324M universe
or rerun the historical Fin4 enumeration from scratch. Stage 70 likewise replays
the frozen coverage outputs by default; rerunning its historical C evaluator is
outside the portable standard-library workflow.

## PR 2 分阶段复现说明

Stage 50 静态解析 d15/d17 并重建两次稳定筛选；Stage 60 逐行流式验证冻结的 324M/284M
位图及 256 个 Fin4 分片账本；Stage 70 按冻结排序重放 3,535 个 keep/drop 决策，并与实际
提交 solver 的前 1,470 条记录逐条比较。由于 Stage 60 的 singleton 与完整种子链缺失，
这里的“复现”仅指冻结产物回放和独立校验，不代表从零重跑历史 Fin4 搜索。

## PR 3 capture and merged portable correction

Stage `80-finite149` preserves the immutable finite149 snapshot and the
`789 → 149 → 17 + 11` augmentation. Its merged historical builder materializes the
complete finite-outcomes JSON, so normal review now uses the append-only corrective
stage `81-finite149-portable-verification`:

```bash
python3 reproduction/81-finite149-portable-verification/scripts/rebuild.py
python3 reproduction/81-finite149-portable-verification/scripts/verify.py
```

Stage 81 validates all 4,694 equation names, streams all 4,694 matrix rows through
top-level EOF under a 256 KiB application-buffer cap, and retains only the 789
requested cells. It reproduces the exact Stage 80 screening ledger, parses all 17
captured Lean operator-table comments, and publishes the corrected effective source
for the order-22 `F149-014` table. The same portable command reruns all 149
exhaustive task checks, 11 transpose derivations, orientation/delta joins, exact
zero-overlap, and submitted prefix/suffix comparisons, so replacing the historical
high-memory command does not reduce CI semantic coverage.

The correction also makes the ETP evidence boundary explicit: the 149 paths are a
frozen inventory. The captured snapshot has the 17 table-source files but omits the
finite graph and 13 other referenced path-source files, so it cannot replay every
graph edge. Independent exhaustive finite-table semantics for all 149 directions
remain available in Stage 80.

Stage 81 has no `raw/` directory because it consumes the immutable Stage 80 archive,
and no delta because it changes no table membership.

## PR 3 流式修正说明

Stage 81 不改动 Stage 80 的任何 raw、规范表、delta 或数量结论。它把约 499 MB 的
finite-outcomes 解压 JSON 改为逐行扫描，只保留 789 个目标单元；同时补齐 17 份 Lean
表的直接解析核对、Refutation934 order-22 表的实际来源记录，以及 ETP 路径只能作为冻结
清单而不能从现有快照逐边重放的边界说明。其余 149 项穷举、11 个转置、零重叠及提交
前后缀检查也由同一低内存入口完整重跑。

## PR 4 exact payload and runtime closure

PR 4 adds two deterministic stages that consume only committed predecessors:

| Stage | Exact transition | Published boundary |
| --- | --- | --- |
| `90-payload-1487` | `1,470 + 17 = 1,487` embedded records | Exact inner canonical stream and submitted XZ/Base85 table literal |
| `100-opposite-closure-2901` | `1,487 + 1,414 = 2,901` runtime records | Static replay of the generic missing-transpose closure |

Rebuild and verify both stages with Python 3.11:

```bash
python3 tools/rebuild_pr4.py
python3 tools/verify_pr4.py
```

Stage 90 concatenates the Stage 70 core and Stage 80 base records in exact submitted
order, while taking the finite149 effective provenance from the merged Stage 81
correction. The resulting 111,009-byte stream is regenerated as the exact submitted
XZ payload using CRC64 and `9 | lzma.PRESET_EXTREME`, then Python Base85 encoded.
All four submitted launchers are parsed as data through restricted AST extraction;
none is imported or executed.

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
498,047-byte outer solver launcher, rerun the finite149 search, or revalidate Lean
certificate generation.

## PR 4 精确 payload 与运行时闭包

Stage 90 按实际提交顺序连接 Stage 70 的 1,470 张核心表和 Stage 80 的 17 张基表，并
使用已合并 Stage 81 的修正来源，得到 111,009 字节、1,487 条记录的内层 payload；随后
以 CRC64、`9 | lzma.PRESET_EXTREME` 和 Python Base85 逐字节复现提交字面量。

Stage 100 先保留全部 1,487 条嵌入记录，再按原索引生成尚不存在的严格转置。9 条记录
自转置，64 条记录组成 32 对已嵌入 opposite，因此净派生 1,414 条，形成 2,901 条互异的
运行时扫描记录。Stage 80 的 11 张任务所需转置只是这 1,414 张中的子集，不会再次追加。
`derive` 表示相对于 Stage 90 的重新加入：其中 6 张曾在 Stage 10 出现，11 张已在 Stage
80 发布；这 17 张保留历史 `first_seen_stage`，其余 1,397 张才首次出现于本阶段。

两个阶段均不需要新的 `raw/`。复现范围是精确内层表数据与已固定的通用变换，不包括从零
重建或执行完整的 498,047 字节外层 solver，也不重复 finite149 搜索或 Lean 证书验证。
