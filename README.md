# Finite Countermodel Bank

[English](#english) | [简体中文](#简体中文)

## English

This repository is a provenance-first archive for finite countermodels and the
pipeline that selected them. Its first concrete dataset is the reproduction record
for the SAIR Mathematics Distillation Challenge — Equational Theories Stage 2
False Solver.

### Current status

PR 0 establishes the repository contract and captures the four solver files that
were actually submitted to SAIR. Those immutable files are the final comparison
anchors for later reconstruction work; they are not, by themselves, a reproduction
of the table-generation process or a proof of mathematical correctness.

The remaining evidence will be added in chronological, reviewable stages. See
[TIMELINE.md](TIMELINE.md) for the planned sequence and [CLAIMS.csv](CLAIMS.csv)
for the claim ledger.

### Verify this checkout

The verifier uses only the Python standard library and hashes files in bounded
chunks:

```bash
python3 tools/verify_repository.py
python3 -m unittest discover -s tests -v
```

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

PR 0 先固定仓库规范，并保存从 SAIR 实际下载的四份提交文件。它们是后续重建结果的最终
逐字节比对锚点；仅有这些文件并不等于已经复现表生成过程，也不构成数学正确性证明。

后续证据将严格按时间顺序、一次一个 PR 加入。阶段安排见
[TIMELINE.md](TIMELINE.md)，各项数字及其验证状态见 [CLAIMS.csv](CLAIMS.csv)。

### 校验当前 checkout

校验器仅使用 Python 标准库，并以固定大小的数据块计算哈希，避免一次性加载大文件：

```bash
python3 tools/verify_repository.py
python3 -m unittest discover -s tests -v
```

### 证据规范

每个已完成阶段都应提供 manifest、不可变原始输入、明确的派生输出或成员变更记录、
校验和及可执行验证命令。运算表按精确字节去重，不按同构去重：`n` 阶表的规范字节为
一个阶数字节加上 `n²` 个行优先表项，其稳定标识符为该字节串的 SHA-256。

### 许可证

仓库尚未选择统一许可证。详见 [NOTICE.md](NOTICE.md) 与
[LICENSES/README.md](LICENSES/README.md)。仅将内容放入本仓库不自动授予复制、修改或
再分发权限。
