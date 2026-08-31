# Stage 80 — finite149 augmentation / finite149 增补

This stage isolates the finite-countermodel augmentation that follows the 1,470-table
positive-marginal core. It publishes the screening and proof-path evidence, the 17
effective base records, and the 11 task-required strict transposes. It does **not**
publish the cumulative 1,487-record payload or the 2,901-record runtime opposite
closure; those belong to PR 4.

本阶段只保存 1,470 张核心表之后的 finite149 增补：789→149 筛选、149 条官方
ETP 路径、17 张有效基表、11 张任务所需转置以及验证账本。最终累计 payload 和
运行时 opposite closure 均不在本阶段生成或提交。

> **Correction notice / 修正说明:** The merged Stage 80 data and counts remain
> valid, but its historical rebuild materializes the complete 498,673,223-byte
> finite-outcomes JSON and is not the portable review path. Use the bounded-memory
> verifier in [`81-finite149-portable-verification`](../81-finite149-portable-verification/)
> instead. Stage 81 also parses all 17 Lean table sources, corrects the effective
> `F149-014` provenance, reruns the 149-task/transpose/overlap/submission-suffix
> semantic gate, and records that the frozen ETP paths cannot be replayed edge by
> edge from the captured files.

## Frozen screening / 冻结筛选

The deterministic screening rule is replayed against the captured historical
`finite_outcomes.json.gz` matrix:

```text
789 not_generated directions
  = 149 official finite proof_false directions (retained)
  + 600 general-false directions requiring an infinite countermodel
  +   2 finite-unknown directions
  +  38 general-true directions
```

`normalized/screening-decisions.jsonl.gz` records all 789 decisions. The retained
set must exactly equal the 149 rows in the captured official-path manifest; the two
unknown rows must exactly equal the frozen semantic-type audit.

## Tables, stable IDs, and orientations / 表、稳定编号与方向

`normalized/table-id-map.csv` is the authoritative compact inventory. Stable IDs
`F149-001` through `F149-017` are fixed in the exact append order recovered from the
committed Marathon submission. Every embedded record is expected in the **direct**
orientation. `normalized/append-order.csv` records the corresponding submitted
record indexes 1,470 through 1,486 (zero-based).

Each canonical table is encoded as one order byte followed by `n²` row-major bytes;
its stable content identity is `sha256:` of those exact bytes. The uncompressed
`normalized/base-tables.bin` contains only the 17 augmentation records, never the
1,470-record prefix.

The official `Refutation934.lean` order-24 table is the historical source for
`F149-014`, but the effective record for that stable ID is its verified order-22
closed substructure. The other 16 effective base records are byte-exact official
tables. All 17 payload orientations remain direct.

Eleven bases are additionally needed in strict-transpose orientation for task
coverage. Their records are in `normalized/required-transposes.*`; they are not
embedded additions. The 149 uses partition exactly as:

```text
129 direct uses + 20 transpose uses = 149 directions
17 base records + 11 required transposes = 28 task-oriented assets
```

## ETP paths and exhaustive checks / ETP 路径与穷举检查

`normalized/etp-paths.jsonl.gz` contains all 149 captured finite-proof paths, their
source files, proof status, and direct/transpose use. `normalized/coverage.jsonl.gz`
joins each path to its stable base ID and effective canonical table ID.

The rebuild evaluates every assignment for both equations in all 149 directions:
the source equation must have zero violations and the target equation must have at
least one failure. The complete counts and first witnesses are stored in
`verification/coverage-exhaustive.jsonl.gz`.

For the five `Refutation934` directions, the verifier also checks that the selected
22-element subset is closed in the official order-24 table, reconstructs the
induced table byte for byte, checks its strict transpose, and exhaustively scans all
five tasks. The focused result is
`verification/refutation934-five-task-exhaustive.json`.

## Zero overlap and submitted order / 零重叠与提交顺序

Exact canonical-byte comparison proves zero overlap between the 17 effective bases
and the preceding 1,470 tables. The stronger audit also finds zero overlap for all
28 task-oriented assets. See `verification/zero-overlap-with-core1470.json`.

The committed Marathon solver is statically decoded in memory solely to verify that
its first 1,470 records equal Stage 70 and its final 17 records equal the Stage 80
inventory in order. The decoder never imports or executes submitted code and never
writes the cumulative payload. See `verification/submission-suffix-audit.json`.

## Files / 文件

- `raw/finite149-source-snapshot.tar.gz`: deterministic archive of the 789-row
  input ledger, the exact historical finite-outcomes matrix, the 149-path manifest,
  the 17/28/149 static-library source artifacts, 17 official table-source files,
  and the `Refutation934` reduction evidence.
- `normalized/screening-decisions.jsonl.gz`: all 789 keep/exclude decisions.
- `normalized/etp-paths.jsonl.gz`: 149 ETP paths.
- `normalized/base-tables.*`: the 17 effective augmentation records.
- `normalized/required-transposes.*`: the 11 necessary derived transposes.
- `normalized/table-id-map.csv`: stable IDs, canonical hashes, official sources,
  payload orientation, substitute marker, and record order.
- `normalized/append-order.csv`: final append order recovered from the committed
  solver.
- `normalized/coverage.jsonl.gz`: 149 direction-to-oriented-table assignments.
- `delta.jsonl.gz`: 17 additions followed by 11 task-required transpose derivations.
- `verification/`: exhaustive, substitution, zero-overlap, and suffix-order audits.
- `summary.json`, `stage.json`, and `SHA256SUMS`: counts, provenance, artifact
  manifest, and immutable hashes.

## Reproduce / 复现

The maintained reproduction path requires Python 3.10+; Python 3.11 is recommended
and is the required CI baseline, matching the official competition sandbox.

From the repository root:

```bash
python3 reproduction/81-finite149-portable-verification/scripts/rebuild.py
python3 reproduction/81-finite149-portable-verification/scripts/verify.py
```

The Stage 81 verifier streams the nested finite-outcomes matrix one row at a time,
compares every regenerated correction artifact, validates the Stage 80 evidence,
and finally invokes the repository verifier for the complete dependency chain. The
original Stage 80 scripts remain immutable, manifested historical code; normal
review and CI deliberately do not execute their high-memory matrix-loading path.

The one-time historical capture is separate from normal review. It requires the
matching sibling development checkout and the exact finite-outcomes download whose
SHA-256 is `257f9e97bac460e3dcdb74469d95783a640c797d8d3423b8e9dbef95e5db52d5`:

```bash
python3 reproduction/80-finite149/scripts/capture.py \
  --source-root ../math-distill-equational-stage2 \
  --finite-outcomes ../finite_outcomes.json.gz
```

Normal reconstruction never accesses the network.

## Evidence boundary / 证据边界

This is a frozen-artifact replay of the historical finite149 selection and a fresh
standard-library exhaustive validation of its effective tables. It does not rerun
the upstream ETP graph builder, the historical distributed search, or Judge v3.
Those external outcomes are preserved by exact source bytes, pinned revisions, and
hashes; the table semantics used here are checked independently over every finite
assignment.
