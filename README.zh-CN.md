# 有限反模型库

[English](README.md) | 简体中文

本仓库以来源可追溯为第一原则，保存有限反模型以及筛选这些反模型的流水线。首个具体数据集
是 SAIR Mathematics Distillation Challenge — Equational Theories Stage 2
False Solver 的复现记录。

## 1,487 条嵌入表是如何构成的

提交的 False Solver 精确嵌入 **1,487 条有限表记录**：先按覆盖率筛选出 1,470 条核心表，
再追加 17 条 finite149 直接基表记录。本仓库可重建其 111,009 字节的规范 payload，并与
提交中的 XZ/Base85 表字面量逐字节一致。下列数量按规范记录的精确字节统计，不按同构类统计。

| 流水线步骤 | 数量变化 | 含义与主要核验 |
| --- | --- | --- |
| **Phase 1 · Stages 10–40** | `9,450 → 9,852 → 9,957 → 10,059` | 通过精确成员增量加入 402 条注册表记录、净增 105 条早期增量记录及 102 条交付记录；穷举核验最后 102 个反模型。 |
| **Phase 2 · Stage 50** | `10,059 − 241 个标量仿射表 − 6,283 个 order≤4 表 = 3,535` | 核验显式仿射见证与低阶表删除清单；与历史 d17 表库精确一致。 |
| **Phase 2 · Stages 60–70** | `3,535 − 2,065 个零边际表 = 1,470` | 针对已验证的 284,151,591-pair residual 按固定顺序筛选；与历史提交 solver 前缀精确一致。 |
| **Phase 3 · Stages 80–81** | `789 个无提交方向 → 149 个有限反模型方向 → 17 条直接基表记录` | 穷举核验全部 149 项任务；确认与核心库零重叠，并与历史提交 solver 后缀精确一致。 |
| **Phase 4 · Stage 90** | `1,470 + 17 = 1,487 条嵌入记录` | 重建精确的 111,009 字节规范流及提交中的 XZ/Base85 表字面量。 |
| **Phase 4 · Stage 100** | `1,487 + 1,414 个缺失转置 = 2,901 条运行时记录` | 重放通用 opposite closure；1,414 条记录是运行时派生方向，不是额外嵌入的 payload。 |

只有 17 条 finite149 直接基表记录被追加到 payload。149 个任务方向中有 20 次使用转置，
涉及 11 个不同的严格转置；它们不追加到 payload，而是包含在通用运行时闭包派生的 1,414
个转置中。

Phase 0 以哈希固定用于核验上述血缘的当前及历史提交 solver 文件，但不改变表成员。
完整阶段顺序、证据要求及 GitHub 历史继续记录于 [TIMELINE.md](TIMELINE.md)，
[CLAIMS.csv](CLAIMS.csv) 是权威结论台账。本仓库重建内层表 payload 及其运行时变换，
不重建完整的外层 solver launcher。

## 术语

- **Phase**：稳定的高层流水线分组，编号为 0–4。
- **Stage**：具体、可独立验证的证据单元，编号为 `00`、`10`、`20`……`100`。
- **PR**：仅指真实的 GitHub 开发历史，统一记录于 [TIMELINE.md](TIMELINE.md)。

## 复现范围

下表中的“重建”是指从本仓库已经提交的输入确定性地重新生成产物，并不自动表示重新执行
历史模型搜索或比赛环境。

| 层级 | 本仓库覆盖范围 | 证据边界 |
| --- | --- | --- |
| 从已提交快照确定性重建 | Stage 10–50 从已捕获输入重建 `9,450 → 10,059 → 3,535` 表库血缘；Stage 60 逐字节重建五项历史支持/上游文件；Stage 81、90、100 重新生成可移植 finite149 证据、精确 1,487 条 payload 及 2,901 条运行时闭包。 | 常规流程只把历史程序和已提交 solver 作为数据解析；Stage 81 只重建冻结路径所需的图边。 |
| 冻结产物回放 | Stage 60、70 验证已固定的 324M/284M bitset，并从冻结覆盖报告重放固定的 `3,535 → 1,470` 筛选；Stage 81 根据已捕获图条目和源文件逐边验证 149 条哈希固定 ETP 路径。 | 常规 rebuild 不重跑 Fin4 枚举、上游图提取/构建、路径发现或最短路径搜索；Stage 60 另提供可选的新无种子结果级 C runner。 |
| 独立语义与不变量校验 | 穷举检查 Stage 40 的 102 个反模型和全部 149 个 finite149 方向；重新计算表身份、转置、重叠、bitset、提交前后缀及 payload 不变量。 | 这些检查验证已提交的表和结果，不复现原始搜索如何发现它们。 |
| 独立 Stage 60 结果级重跑 | **已完成并提交可验证证据。** | 新的无种子结果级方法以 256 个 shard 穷举全部 `2^32` 张四阶表，在无重试的情况下逐字节复现 284,151,591-pair residual。证据包括全部 shard 摘要、清洗日志、精确输入/实现哈希、资源记录及独立流式 bitset 校验；该结果不恢复历史种子生成/provenance 链。 |
| 逐字节重放历史发现与比赛工作流 | **仍受未找回的历史输入和环境阻塞。** | 尚缺 Stage 10 挖掘/export 输入、Stage 40 SAT runner 输入与原始 journals、Stage 50 d16.2 源文件及构建 patch、Stage 60 原始种子生成/provenance 链、完整逐题 Judge v3 证书/结果文件及精确历史执行环境、完整外层 solver 的独立输入/模板/builder，以及 aggregate/submission Lean 证书生成器和精确工具链。 |

因此，本仓库当前支持从已提交证据出发的制品级复现。关键独立重跑组件现已实现，但完整
端到端重建尚未实际证明；历史工作流的逐字节重放仍受未找回的输入
与环境阻塞。待恢复的外部输入、环境及逐项验收门槛统一记录于英文
[External Recovery Register](EXTERNAL_RECOVERY.md)。

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
Phase 4 只处理 111,009 字节的嵌入流及 215,433 字节的运行时闭包；2026-09-01 的当前
提交 Python 文件始终作为数据静态解析，不会被导入或执行。

## 仓库结构

| 路径 | 用途 |
| --- | --- |
| `docs/submission-notes/` | 面向读者的提交说明源文件 |
| `reproduction/` | 按顺序排列的证据阶段及各阶段说明 |
| `schemas/` | 带版本的机器可读记录规范 |
| `tools/` | 流式验证与重建辅助工具 |
| `CLAIMS.csv` | 每项数字或来源声明一行 |
| `TIMELINE.md` | Phase 分组、Stage 顺序、GitHub PR 历史与验收标准 |
| `EXTERNAL_RECOVERY.md` | 外部恢复工作项及逐项验收门槛 |
| `NOTICE.md`、`LICENSES/` | 来源与权利状态说明 |

## 证据规范

每个已完成阶段都应提供 manifest、不可变原始输入、明确的派生输出或成员变更记录、
校验和及可执行验证命令。运算表按精确字节去重，不按同构去重：`n` 阶表的规范字节为
一个阶数字节加上 `n²` 个行优先表项，其稳定标识符为该字节串的 SHA-256。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。该许可证适用于项目贡献者拥有必要权利的
材料；具有独立许可或权利状态尚未确认的来源产物，继续遵循各阶段 manifest 中记录的
状态。详见 [NOTICE.md](NOTICE.md) 与 [LICENSES/README.md](LICENSES/README.md)。
