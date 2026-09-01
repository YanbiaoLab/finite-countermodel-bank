# Stage 30 — early d1/d2 deltas to 9,957

This stage keeps the two early inputs separate and applies them in timeline order:

```text
d1: 66 input - 55 existing = 11 new
d2: 145 input - 51 existing = 94 new
9,852 + 11 + 94 = 9,957
```

## Two intentional orders

`delta.jsonl.gz` is the narrative ingestion order: all d1 records in portfolio
order, then all d2 frozen-dictionary records. The historical d6/d8 payload was
rebuilt after set union and sorted by `(order, historical compact-JSON SHA-256)`.
`normalized/tables.*` preserves that payload order.

The reconstructed 9,957 payload is 367,581 bytes with SHA-256
`c032654b7674ed3386b7700ccf7f4ed7344d1e0791c851d2bf5a5cf16ce8902c`.
It exactly matches the independently decoded d6 and d8 XZ/Base85 payloads. Their
historical ordered alias-vector hash is
`094743ce81e80958039b285c2451f5415cfbe979b016842b861b60b606807657`.

## Static reconstruction

The new tool never imports a solver:

- d1: extracts seven explicit tables, seven n=9 digit tables, two later explicit
  tables, and 50 affine parameter tuples;
- d2: literal-evaluates `_OFFLINE_FALSE244_FINITE_TABLES` and verifies all 145
  historical aliases;
- d4/d6/d8: extracts and decodes only their frozen string payloads for exact
  comparison.

```bash
python3 tools/rebuild_phase1.py
python3 tools/verify_repository.py --stage 30-early-deltas-9957
```

All captured member files were ignored in the sibling checkout, so the archive
hash—not the surrounding Git revision—is their immutable identity.

## Evidence boundary

The commands use only the Python standard library and are verified in CI with
CPython 3.12. Historical builders are not rerun. The d4/d6/d8 build manifests are
intentionally omitted because their useful summaries are independently
recomputed and the files contain host-specific absolute paths; the frozen solver
payloads, builders, and model audits remain captured.
