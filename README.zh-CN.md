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

PR 3 已保存并复现 finite149 增补：789 个无提交方向筛到 149 个有限反模型方向，由
17 张稳定基表及 11 张必要转置覆盖（原方向使用 129 次，转置使用 20 次）；同时完成与
前 1,470 张核心表的规范字节零重叠检查，并验证 Refutation934 官方 order-24 表的
order-22 闭子表替代。累计 1,487 payload 与 2,901 张运行时 opposite closure 仍留给
PR 4。阶段安排见 [TIMELINE.md](TIMELINE.md)，各项数字及其验证状态见 [CLAIMS.csv](CLAIMS.csv)。

后继 `81-finite149-portable-verification` 阶段在不改动 PR 3 数据和数量的前提下修正
复现路径：逐行流式扫描解压后 498,673,223 字节的 finite-outcomes JSON，解析并核对全部
17 份已保存 Lean 运算表，明确记录 Refutation934 order-22 表的实际来源，并将 149 条
ETP 路径准确标记为冻结清单而非已独立重放的证明图；同时继续重跑全部 149 项穷举检查、
11 个转置推导、零重叠及提交 1,470-prefix/17-suffix 比较，不降低原有 CI 语义覆盖。

## 校验当前 checkout

复现脚本要求 **Python 3.10+**，推荐并测试于 **Python 3.11**；3.11 与比赛官方
[`python:3.11-slim` 评测沙箱](https://github.com/SAIRcompetition/equational-theories-lean-stage2/blob/main/README.md#sandbox-python-environment)
一致，3.12 仅作为额外 CI 兼容性测试。校验器只使用 Python 标准库，并以有界流或固定
大小数据块处理大文件：

```bash
python3 tools/verify_repository.py
python3 reproduction/81-finite149-portable-verification/scripts/verify.py
python3 -m unittest discover -s tests -v
```

从已提交 raw 快照重建 PR 1、PR 2 的产物及修正后的 PR 3 校验层：

```bash
python3 tools/rebuild_pr1.py
python3 tools/rebuild_pr2.py
python3 reproduction/81-finite149-portable-verification/scripts/rebuild.py
git diff --exit-code
```

PR 2 重建器以有界流处理两份解压后各 489,598,720 字节的 pair bitset；修正后的 PR 3
重建器以 256 KiB 应用层缓冲上限扫描全部 498,673,223 个 finite-outcomes 解压字节，
只保留 789 个目标单元。两者都不会将大输入整体载入内存。

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
