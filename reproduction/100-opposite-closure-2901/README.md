# Stage 100 — generic opposite closure to 2,901

This stage statically replays the submitted False Solver's generic runtime table
transformation over the exact Stage 90 payload:

```text
1,487 embedded records + 1,414 missing strict transposes = 2,901 runtime records
```

## Exact runtime order

The submitted algorithm, inspected as source through static AST parsing, performs
these operations:

1. seed exact-byte membership with all 1,487 embedded records;
2. yield all embedded records in payload order;
3. scan embedded source indexes `0..1486`;
4. transpose each square table with `new[row,column] = old[column,row]`;
5. append the transpose only if its exact canonical record bytes are absent.

There is no isomorphism quotient, sorting, reranking, or problem-ID branch.

## Closure arithmetic

| Disposition of 1,487 embedded sources | Count |
| --- | ---: |
| Self-transpose | 9 |
| Nontrivial transpose already embedded | 64 records = 32 pairs |
| Missing transpose derived at runtime | 1,414 |
| Distinct runtime records | 2,901 |

“Derived at runtime” is a transition relative to the 1,487-record Stage 90 bank,
not a claim that every resulting byte string is new to the repository history.
Seventeen of the 1,414 exact records appeared earlier: six were already present in
Stage 10 (and were later pruned before Stage 70), while the eleven task-required
transposes were published in Stage 80. Their historical `first_seen_stage` values
are preserved; the remaining 1,397 exact records are first seen in Stage 100.

The 1,414-record derived suffix has 104,424 bytes and SHA-256
`992318b8e336cc8cd232b4012d02a43d906d18d8397b2d67880a533406377f9e`.
The complete runtime stream has 215,433 bytes and SHA-256
`b38ffe73f45ae8780c6cbcbd7904bcc1a5b2947b15789d6c9972394fe695afb7`.
Its canonical-ID vector SHA-256 is
`42c21dfecfaca35451ad1bc7f1216456ef682aadc6eb7edbf498417d81ae530e`.

The 17-record finite149 suffix contributes 15 new generic transposes; two of its
records are mutual transposes. All 11 task-required Stage 80 transposes occur among
those generic derivations and are verified as a subset, not appended again.

## Artifacts

- `normalized/opposite-decisions.jsonl.gz`: one classification for each embedded
  source record.
- `delta.jsonl.gz`: 1,487 retained embedded records followed by 1,414 explicit
  transpose derivations.
- `normalized/runtime-scan.csv.gz`: exact 2,901-record scan order and source index.
- `verification/opposite-closure-audit.json`: arithmetic, hashes, deduplication,
  finite149, historical reintroduction, and required-transpose joins.
- `verification/submitted-runtime-code-audit.json`: hashes and line ranges of the
  statically parsed submitted decoder/key/transpose/closure functions.

There is no new `raw/` directory. The complete committed inputs are the Stage 90
payload, its transitive historical table indexes (including the Stage 80 required
transposes used for `first_seen_stage` joins), and the pinned Stage 00 submitted
algorithm source.

## Reproduce

From the repository root, using Python 3.11:

```bash
python3 tools/rebuild_phase4.py
python3 tools/verify_phase4.py
```

## Evidence boundary

The 2,901 records are runtime-derived oriented scan tables, not embedded payload
records. This stage statically replays the pinned table transformation; it does not
execute the complete solver, rerun the 149-task semantic audit already supplied by
Stage 81, or revalidate Lean certificate generation. Exact-byte-distinct tables are
not claimed to be non-isomorphic mathematical models.
