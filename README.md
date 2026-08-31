# Finite Countermodel Bank

[English](#english) | [简体中文](#简体中文)

## English

This repository is a provenance-first archive for finite countermodels and the
pipeline that selected them. Its first concrete dataset is the reproduction record
for the SAIR Mathematics Distillation Challenge — Equational Theories Stage 2
False Solver.

### Current status

PR 0 establishes the repository contract and captures the four solver files that
were actually submitted to SAIR. PR 1 reconstructs the historical finite-table
accumulation as four separately reviewable stages: 9,450 primary tables, 9,852
after registry deduplication, 9,957 after the d1/d2 deltas, and 10,059 after the two
JiaMing deliveries. The final 102 explicit report countermodels are independently
rechecked by exhaustive assignment enumeration.

PR 2 reconstructs the stable pruning from 10,059 to 3,535 tables, validates the
frozen Fin4 transition from 324,157,667 targeted pairs to a 284,151,591-pair
residual, and replays the fixed-order positive-marginal selection of the 1,470-table
core. The core matches the first 1,470 embedded records of the submitted Marathon
solver exactly. The Fin4 stage is explicitly a frozen-artifact replay: missing
singleton and seed-chain inputs prevent a from-scratch rerun.

The finite149 augmentation and final payload integration will be added in later
chronological, reviewable stages. See
[TIMELINE.md](TIMELINE.md) for the planned sequence and [CLAIMS.csv](CLAIMS.csv)
for the claim ledger.

### Verify this checkout

The verifier uses only the Python standard library and hashes files in bounded
chunks:

```bash
python3 tools/verify_repository.py
python3 -m unittest discover -s tests -v
```

To regenerate the PR 1 and PR 2 normalized outputs, deltas, summaries, manifests,
and checksums from the committed raw snapshots:

```bash
python3 tools/rebuild_pr1.py
python3 tools/rebuild_pr2.py
git diff --exit-code
```

The PR 2 rebuild uses bounded streams for the two 489,598,720-byte uncompressed
pair bitsets; it does not load them into memory.

### Repository layout

| Path | Purpose |
| --- | --- |
| `docs/submission-notes/` | Human-facing submission-note source |
| `reproduction/` | Ordered evidence stages and stage-level instructions |
| `schemas/` | Versioned machine-readable record contracts |
| `tools/` | Streaming validation and reconstruction helpers |
| `CLAIMS.csv` | One row per numerical or provenance claim |
| `TIMELINE.md` | PR boundaries, stage order, and acceptance criteria |
| `NOTICE.md`, `LICENSES/` | Provenance and rights-status notices |

### Evidence model

Every completed stage contains a manifest, immutable raw inputs, explicit derived
outputs or membership deltas, checksums, and a bounded verification command. Exact
table identity is byte identity, not isomorphism: for a table of order `n`, the
canonical bytes are the one-byte order followed by the `n²` row-major entries, and
the stable table identifier is the SHA-256 digest of those bytes.

### License

No repository-wide license has been selected. See [NOTICE.md](NOTICE.md) and
[LICENSES/README.md](LICENSES/README.md). Repository publication alone does not
grant permission to copy, modify, or redistribute the contents.

## 简体中文

本仓库以来源可追溯为第一原则，保存有限反模型以及筛选这些反模型的流水线。首个具体数据集
是 SAIR Mathematics Distillation Challenge — Equational Theories Stage 2
False Solver 的复现记录。

### 当前状态

PR 0 固定仓库规范，并保存从 SAIR 实际下载的四份提交文件。PR 1 按四个独立阶段复现
历史表库累积：9,450 → 9,852 → 9,957 → 10,059；其中最后两批 102 个显式反模型已逐题
穷举复核 source 与 target。

PR 2 复现 10,059 → 3,535 的稳定精简，验证冻结的 Fin4
324,157,667 → 284,151,591 有向对转移，并按固定顺序重放正边际筛选，得到 1,470 表核心库；
该核心与 Marathon 实际提交的前 1,470 条嵌入记录逐条一致。由于 singleton 输入和完整
种子链缺失，Fin4 阶段明确属于冻结产物回放，而非从零重跑。

finite149 增补及最终 payload 集成仍按时间顺序、一次一个 PR 加入。阶段安排见
[TIMELINE.md](TIMELINE.md)，各项数字及其验证状态见 [CLAIMS.csv](CLAIMS.csv)。

### 校验当前 checkout

校验器仅使用 Python 标准库，并以固定大小的数据块计算哈希，避免一次性加载大文件：

```bash
python3 tools/verify_repository.py
python3 -m unittest discover -s tests -v
```

从已提交 raw 快照重建 PR 1 与 PR 2 的全部规范输出、delta、summary、manifest 与校验和：

```bash
python3 tools/rebuild_pr1.py
python3 tools/rebuild_pr2.py
git diff --exit-code
```

PR 2 重建器以有界流处理两份解压后各 489,598,720 字节的 pair bitset，不会将其整体载入内存。

### 证据规范

每个已完成阶段都应提供 manifest、不可变原始输入、明确的派生输出或成员变更记录、
校验和及可执行验证命令。运算表按精确字节去重，不按同构去重：`n` 阶表的规范字节为
一个阶数字节加上 `n²` 个行优先表项，其稳定标识符为该字节串的 SHA-256。

### 许可证

仓库尚未选择统一许可证。详见 [NOTICE.md](NOTICE.md) 与
[LICENSES/README.md](LICENSES/README.md)。仅将内容放入本仓库不自动授予复制、修改或
再分发权限。
