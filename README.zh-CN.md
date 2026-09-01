# 有限反模型库

[English](README.md) | 简体中文

本仓库以来源可追溯为第一原则，保存有限反模型以及筛选这些反模型的流水线。首个具体数据集
是 SAIR Mathematics Distillation Challenge — Equational Theories Stage 2
False Solver 的复现记录。

## 术语

- **Phase**：稳定的高层流水线分组，编号为 0–4。
- **Stage**：具体、可独立验证的证据单元，编号为 `00`、`10`、`20`……`100`。
- **PR**：仅指真实的 GitHub 开发历史，统一记录于 [TIMELINE.md](TIMELINE.md)。

| Phase | 包含的 Stage | 辅助说明 |
| --- | --- | --- |
| Phase 0 | Stage 00 | 提交锚点 |
| Phase 1 | Stage 10–40 | 历史累积 |
| Phase 2 | Stage 50–70 | 精简与核心筛选 |
| Phase 3 | Stage 80–81 | finite149 增补与可移植修正 |
| Phase 4 | Stage 90–100 | payload 与运行时闭包 |

## 当前状态

Phase 0 固定仓库规范，并保存从 SAIR 实际下载的四份提交文件。Phase 1 按四个独立阶段
复现历史表库累积：9,450 → 9,852 → 9,957 → 10,059；其中最后两批 102 个显式反模型
已逐题穷举复核 source 与 target。

Phase 2 复现 10,059 → 3,535 的稳定精简，验证冻结的 Fin4
324,157,667 → 284,151,591 有向对转移，并按固定顺序重放正边际筛选，得到 1,470 表核心库；
该核心与 Marathon 实际提交的前 1,470 条嵌入记录逐条一致。由于 singleton 输入和完整
种子链缺失，Fin4 阶段明确属于冻结产物回放，而非从零重跑。

Phase 3 已保存并复现 finite149 增补：789 个无提交方向筛到 149 个有限反模型方向，由
17 张稳定基表及 11 张必要转置覆盖（原方向使用 129 次，转置使用 20 次）；同时完成与
前 1,470 张核心表的规范字节零重叠检查，并验证 Refutation934 官方 order-24 表的
order-22 闭子表替代。累计 1,487 payload 与运行时 opposite closure 由 Phase 4 发布。
阶段安排见 [TIMELINE.md](TIMELINE.md)，各项数字及其验证状态见 [CLAIMS.csv](CLAIMS.csv)。

后继 `81-finite149-portable-verification` 阶段在不改动 Phase 3 数据和数量的前提下修正
复现路径：逐行流式扫描解压后 498,673,223 字节的 finite-outcomes JSON，解析并核对全部
17 份已保存 Lean 运算表，明确记录 Refutation934 order-22 表的实际来源，并将 149 条
ETP 路径准确标记为冻结清单而非已独立重放的证明图；同时继续重跑全部 149 项穷举检查、
11 个转置推导、零重叠及提交 1,470-prefix/17-suffix 比较，不降低原有 CI 语义覆盖。

Phase 4 按提交顺序精确连接 Stage 70 核心与 Stage 80 增补，重建
`1,470 + 17 = 1,487` 条、111,009 字节的内层有限表 payload，并逐字节复现提交中的
XZ/Base85 表字面量。随后静态重放已固定的通用 opposite-closure 算法：1,487 条嵌入记录
中有 1,414 条缺少严格转置，最终形成 2,901 条互异的运行时有向扫描记录。新增的 1,414
张表是相对于 Stage 90 的运行时派生表，不是额外嵌入记录；其中 6 张规范字节记录曾在
Stage 10 出现，另 11 张已作为 Stage 80 必要转置发布，故只有其余 1,397 张的历史
`first_seen_stage` 为 Stage 100。本仓库也不声称从零重建完整的 498,047 字节外层 solver
launcher。

## 复现范围

下表中的“重建”是指从本仓库已经提交的输入确定性地重新生成产物，并不自动表示重新执行
历史模型搜索或比赛环境。

| 层级 | 本仓库覆盖范围 | 证据边界 |
| --- | --- | --- |
| 从已提交快照确定性重建 | Stage 10–50 从已捕获输入重建 `9,450 → 10,059 → 3,535` 表库血缘；Stage 81、90、100 重新生成可移植 finite149 证据、精确 1,487 条 payload 及 2,901 条运行时闭包。 | 历史程序和已提交 solver 只作为数据解析，不执行。 |
| 冻结产物回放 | Stage 60、70 验证已固定的 324M/284M bitset，并从冻结覆盖报告重放固定的 `3,535 → 1,470` 筛选；149 条 ETP 路径仍是哈希固定的清单。 | 不重新执行历史 Fin4/C evaluator，也不重放 ETP 证明图。 |
| 独立语义与不变量校验 | 穷举检查 Stage 40 的 102 个反模型和全部 149 个 finite149 方向；重新计算表身份、转置、重叠、bitset、提交前后缀及 payload 不变量。 | 这些检查验证已提交的表和结果，不复现原始搜索如何发现它们。 |
| 从最早输入完整重跑历史发现流程 | **当前保留的输入不足，无法完整重跑。** | 缺失内容包括 Stage 10 挖掘/generator 输入、Stage 40 SAT 日志、Stage 50 d16.2、Stage 60 singleton masks/`equations.bin`/完整种子链及完整 finite149 图与路径来源；本仓库也不重跑 Judge v3，不重新生成完整外层 solver 和 Lean 证书。 |

因此，本仓库支持从已提交证据出发的制品级复现，不支持从零重跑完整发现与比赛流水线。

## 校验当前 checkout

复现脚本要求 **Python 3.10+**，推荐并测试于 **Python 3.11**；3.11 与比赛官方
[`python:3.11-slim` 评测沙箱](https://github.com/SAIRcompetition/equational-theories-lean-stage2/blob/main/README.md#sandbox-python-environment)
一致，3.12 仅作为额外 CI 兼容性测试。校验器只使用 Python 标准库，并以有界流或固定
大小数据块处理大文件：

```bash
python3 tools/verify_all.py
```

统一入口会在 Python 低于 3.10 时立即失败，并使用同一解释器依次运行仓库校验器、有界的
Stage 81 校验器、精确 Phase 4 校验器及单元测试。各校验器仍可单独执行，以便按阶段
review。

从已提交输入重建 Phase 1、Phase 2、修正后的 Phase 3 校验层及两个 Phase 4 阶段：

```bash
python3 tools/rebuild_phase1.py
python3 tools/rebuild_phase2.py
python3 tools/rebuild_phase3.py
python3 tools/rebuild_phase4.py
git diff --exit-code
```

Phase 2 重建器以有界流处理两份解压后各 489,598,720 字节的 pair bitset；修正后的
Phase 3 重建器以 256 KiB 应用层缓冲上限扫描全部 498,673,223 个 finite-outcomes
解压字节，只保留 789 个目标单元。两者都不会将大输入整体载入内存。
Phase 4 只处理 111,009 字节的嵌入流及 215,433 字节的运行时闭包；提交的 Python 文件
始终作为数据静态解析，不会被导入或执行。

## 仓库结构

| 路径 | 用途 |
| --- | --- |
| `docs/submission-notes/` | 面向读者的提交说明源文件 |
| `reproduction/` | 按顺序排列的证据阶段及各阶段说明 |
| `schemas/` | 带版本的机器可读记录规范 |
| `tools/` | 流式验证与重建辅助工具 |
| `CLAIMS.csv` | 每项数字或来源声明一行 |
| `TIMELINE.md` | Phase 分组、Stage 顺序、GitHub PR 历史与验收标准 |
| `NOTICE.md`、`LICENSES/` | 来源与权利状态说明 |

## 证据规范

每个已完成阶段都应提供 manifest、不可变原始输入、明确的派生输出或成员变更记录、
校验和及可执行验证命令。运算表按精确字节去重，不按同构去重：`n` 阶表的规范字节为
一个阶数字节加上 `n²` 个行优先表项，其稳定标识符为该字节串的 SHA-256。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。该许可证适用于项目贡献者拥有必要权利的
材料；具有独立许可或权利状态尚未确认的来源产物，继续遵循各阶段 manifest 中记录的
状态。详见 [NOTICE.md](NOTICE.md) 与 [LICENSES/README.md](LICENSES/README.md)。
