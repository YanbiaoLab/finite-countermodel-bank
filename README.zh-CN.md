# 有限反模型库

[English](README.md) | 简体中文

本仓库以来源可追溯为第一原则，保存有限反模型以及筛选这些反模型的流水线。首个具体数据集
是 SAIR Mathematics Distillation Challenge — Equational Theories Stage 2
False Solver 的复现记录。

## 当前状态

PR 0 固定仓库规范，并保存从 SAIR 实际下载的四份提交文件。PR 1 按四个独立阶段复现
历史表库累积：9,450 → 9,852 → 9,957 → 10,059；其中最后两批 102 个显式反模型已逐题
穷举复核 source 与 target。

PR 2 复现 10,059 → 3,535 的稳定精简，验证冻结的 Fin4
324,157,667 → 284,151,591 有向对转移，并按固定顺序重放正边际筛选，得到 1,470 表核心库；
该核心与 Marathon 实际提交的前 1,470 条嵌入记录逐条一致。由于 singleton 输入和完整
种子链缺失，Fin4 阶段明确属于冻结产物回放，而非从零重跑。

finite149 增补及最终 payload 集成仍按时间顺序、一次一个 PR 加入。阶段安排见
[TIMELINE.md](TIMELINE.md)，各项数字及其验证状态见 [CLAIMS.csv](CLAIMS.csv)。

## 校验当前 checkout

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

## 仓库结构

| 路径 | 用途 |
| --- | --- |
| `docs/submission-notes/` | 面向读者的提交说明源文件 |
| `reproduction/` | 按顺序排列的证据阶段及各阶段说明 |
| `schemas/` | 带版本的机器可读记录规范 |
| `tools/` | 流式验证与重建辅助工具 |
| `CLAIMS.csv` | 每项数字或来源声明一行 |
| `TIMELINE.md` | PR 边界、阶段顺序与验收标准 |
| `NOTICE.md`、`LICENSES/` | 来源与权利状态说明 |

## 证据规范

每个已完成阶段都应提供 manifest、不可变原始输入、明确的派生输出或成员变更记录、
校验和及可执行验证命令。运算表按精确字节去重，不按同构去重：`n` 阶表的规范字节为
一个阶数字节加上 `n²` 个行优先表项，其稳定标识符为该字节串的 SHA-256。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。该许可证适用于项目贡献者拥有必要权利的
材料；具有独立许可或权利状态尚未确认的来源产物，继续遵循各阶段 manifest 中记录的
状态。详见 [NOTICE.md](NOTICE.md) 与 [LICENSES/README.md](LICENSES/README.md)。
