# Stage 50 — generator and Fin4 pruning to 3,535 / 生成器与 Fin4 精简至 3,535

This stage reconstructs the stable, ordered transition from the Stage 40 bank to
the published d17 candidate payload:

```text
10,059 - 241 scalar-affine - 6,283 order-at-most-4 = 3,535
```

本阶段按历史顺序重建从 10,059 表库到公开 d17 候选 payload 的两次稳定筛选；筛选后
保留表的相对顺序不变。

## Static reconstruction / 静态重建

The raw snapshot contains five files: the d15 solver, the historical direct-affine
audit script and inventory, the published d17 change report, and the published d17
solver. Historical solvers are parsed as data and are never imported or executed.
The decoded d15 payload is exactly the Stage 40 bank; its 371,494 canonical bytes
have SHA-256
`fcb18adf3ff344e51a8f46d3e8eb92f7bb5487f4a3ee5ef74836076d51f3c3d4`.

The first filter classifies 241 tables as scalar affine:

- 227 satisfy `t(x,y) = a*x + b*y + c (mod n)` in the natural carrier labels and
  agree row-for-row with the captured historical inventory;
- 14 have an explicit bijection from their carrier labels to `Z/nZ`. The verifier
  checks the bijection and the affine identity in every table cell.

After those 241 positions are removed, 9,818 tables remain. The second filter
removes all 6,283 remaining tables of order at most 4, leaving 3,535 tables, all of
order greater than 4. `delta.jsonl.gz` records every removal in that order, and
`verification/scalar-affine-witnesses.jsonl.gz` records all 241 witnesses.

第一次筛选由 227 个自然坐标仿射见证和 14 个载体重标号见证组成；每个见证都逐格
验证。第二次筛选再从剩余表中删除 6,283 张阶数不超过 4 的表，因此两个删除数字不会
重复计数。

The resulting 237,631-byte canonical stream has SHA-256
`7cb270a88641bb5ac6c43ddc22afd7395f54321afa3925454fe15f60d02de02b`
and matches the decoded published d17 payload byte for byte. The 102-table Stage 40
delivery is also audited separately: its first appended table (Stage 40 position
9,957, table ID
`sha256:2e712dea158c17cb284b0e6fa1defac16b8ec1523861724856361e533da4db8c`)
is order 4 and is removed; the other 101 occur in the 3,535-table candidate bank.

## Reproduce / 复现

Normal review starts from the committed raw snapshot and earlier Stage 40 output:

The commands require CPython 3.9 or newer and were tested with CPython 3.9.6;
only the standard library is used.

```bash
python3 tools/rebuild_pr2.py
python3 tools/verify_repository.py --stage 50-generator-prune-3535
```

Only the one-time evidence capture requires the historical sibling checkout:

```bash
python3 tools/capture_pr2_snapshots.py \
  --source-root ../math-distill-equational-stage2 \
  --stage 50-generator-prune-3535
```

## Evidence boundary / 证据边界

The d17 report names d16.2 as the immediate historical build baseline, but that
file was unavailable for capture. Consequently this stage does not claim to rerun
the lost d16.2 builder. It reconstructs the complete 241-table classification from
the 227 captured direct-affine rows, 14 explicit relabeling witnesses, and the exact
d15-to-d17 payload transition. All five captured files are identified by the raw
archive hash in `stage.json`; ignored `members/wubing` paths are not represented as
Git-tracked history.

d16.2 文件缺失，因此本阶段的主张是“从冻结输入静态、确定性地重建并逐字节匹配 d17”，
而不是重跑已经丢失的历史构建过程。
