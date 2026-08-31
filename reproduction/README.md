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
