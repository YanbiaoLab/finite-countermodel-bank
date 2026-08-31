# Stage 10 — primary 9,450 / 主表 9,450

This stage freezes the historical first-witness output at the point where 9,452
models had nonzero marginal coverage and 9,450 model tables were recoverable. It
does not rerun the earlier model-mining campaign.

本阶段固定“首次见证归因”后的历史结果：9,452 个模型具有非零边际贡献，其中 9,450
张表能够从冻结脚本恢复。本阶段不重跑更早的模型挖掘过程。

## Result / 结果

- `false_model_primary_coverage_9722317.csv`: 229,666 model identities,
  9,722,317 attributed directed pairs, and 9,452 nonzero contributors.
- `false_model_coverage_9722317.csv`: the same 229,666 model identities ranked
  by pre-attribution coverage multiplicity (sum 181,011,287). A disk-backed join
  verifies identical model keys and metadata, and checks primary coverage never
  exceeds total model coverage. The multiplicity sum is not the directed-pair
  universe cardinality.
- 9,450 indexed scripts decode to 9,450 byte-distinct valid operation tables.
- Historical ranks 3496 and 8142 are the two unrecoverable contributors; they
  account for 14 and 1 pairs. They remain in `skipped-models.jsonl` and are not
  silently renumbered.
- The canonical binary bank is 340,211 bytes with SHA-256
  `66c2f19b5c59f359f14524cee5ec9cfc7d527ff09e4aeb84cac13666cd5cf9e3`.

`raw/primary-recovery-snapshot.tar.gz` is a deterministic, metadata-normalized
archive of the 9,450 original scripts, recovery reports/indexes, and the 62,576-row
equation map. Keeping one archive avoids adding 9,450 Git objects while preserving
every original member byte and compressed source/target bitset.

## Reproduce / 复现

From the repository root:

```bash
python3 tools/rebuild_pr1.py
python3 tools/verify_repository.py --stage 10-primary-9450
```

The rebuild parser uses `ast.parse` and `ast.literal_eval` only to locate the
single `RULE = json.loads(<literal>)` assignment. It never imports or executes a
historical script. For every record it validates the table shape/range, all index
fields, strict Base64, bounded zlib decompression to 7,822 bytes, complementary
source/target bitsets, and their declared popcounts.

重建器只静态解析 `RULE` 字面量，不 import 或执行历史脚本；逐条检查表的形状和值域、
索引字段、Base64/zlib 边界、source/target 位图互补性及计数。

The commands use only the Python standard library and are verified in CI with
CPython 3.12.

## Evidence boundary / 证据边界

The historical `models.jsonl.gz`, the generator that created these scripts, and
the directed-pair/witness inputs named `directed_unique_false_pairs_9715951.csv`
and `out*/false_pairs.csv.gz` were not found. Therefore this is a verified
historical snapshot and deterministic normalization, not a complete replay of
mining, universe deduplication, or first-witness selection.

历史 `models.jsonl.gz`、脚本 generator，以及 directed-pair/witness 输入
`directed_unique_false_pairs_9715951.csv`、`out*/false_pairs.csv.gz` 均未找到。
因此本阶段可以验证冻结快照及其规范化结果，但不能声称完整重放挖掘、pair universe
去重和首次见证选择。
