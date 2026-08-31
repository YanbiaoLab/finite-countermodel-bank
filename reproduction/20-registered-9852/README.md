# Stage 20 — registered 9,852 / 注册表累积至 9,852

This stage adds the registered finite tables to Stage 10 using exact byte identity:

```text
9,450 primary + 402 registered = 9,852
```

本阶段按精确字节身份把 registry 中的表加入 Stage 10，得到 9,852 张表；不按同构归并。

## Input classification / 输入分类

The historical d3 builder visited 476 manifests in lexicographic path order. One
manifest has `model_table: null`. The remaining 475 table-bearing manifests yield
402 first occurrences and 73 repeated occurrences. None of the 402 registered
identities overlaps the 9,450 primary bank. Six root representative scripts all
repeat registered identities and add zero tables.

`normalized/input-decisions.jsonl.gz` records all 476 manifest decisions. The
no-table manifest does not receive a fabricated delta record because the delta
schema requires a real `table_id`; `delta.jsonl.gz` therefore has 475 records.

历史 d3 按 manifest 路径字典序处理 476 个 manifest：1 个无表，剩余 475 个产生
402 次首次加入和 73 次重复；402 张注册表与主表零重合。无表输入只进入 input
decision，不伪造 `table_id`。

## Ordering and identities / 排序与身份

The 9,852-bank order is the 9,450 primary script order followed by each registered
table's first manifest occurrence. Every normalized record contains both:

- canonical `table_id`: SHA-256 of the order byte plus row-major entries;
- historical alias: SHA-256 of compact nested-table JSON.

These hashes identify the same exact table but are not interchangeable. The
historical 9,852 alias-vector hash is
`0e39adb599a9c7162bede403a32ae3901c5b87f6c33d1a5d2108a5a2a4cc32f4`.

## Reproduce / 复现

```bash
python3 tools/rebuild_pr1.py
python3 tools/verify_repository.py --stage 20-registered-9852
```

The registry archive also preserves all 476 rule scripts and the d3 README,
builder, manifest, and audit. Rebuilding table membership reads manifests as data;
it does not execute the historical builder or rules.

## Evidence boundary / 证据边界

The commands use only the Python standard library and are verified in CI with
CPython 3.12. The historical builder is retained as evidence but is not rerun;
the modern rebuild statically reads the frozen manifests and tables.
