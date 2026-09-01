# Stage 40 — two deliveries to 10,059

This stage preserves the two explicit-table deliveries separately, then appends
them in their report chronology:

```text
2026-08-05T17:38:49Z: 50 tables
2026-08-05T23:38:59Z: 52 tables
9,957 + 50 + 52 = 10,059
```

## Independent mathematical check

The reconstruction parser reads each report section's source equation, target
equation, explicit operation table, reported compact-JSON hash, assignment counts,
failure count, and lexicographically first counterexample. It then independently
enumerates every source and target assignment and requires all reported values to
match. It also maps all 204 source/target formula references back to their Equation
IDs in the frozen 62,576-equation index: 195 distinct IDs, zero mismatches after
normalizing `◇`/`*` notation and whitespace. Results for all 102 tasks are in
`verification/task-evidence.jsonl.gz`.

The two batch binaries remain separate:

- batch 50: 1,414 bytes, SHA-256
  `405e6daacfa8af4390a5cdb7ac97c8fd3e63c8bf8eb7748f01139131e49f8abe`;
- batch 52: 2,499 bytes, SHA-256
  `4aff0008fca0cb1db268b578f4c95afdf38ec24692f4bdf1f15ce3a46dce50c5`.

Their concatenation is 3,913 bytes. The final 10,059-bank binary is 371,494 bytes
with SHA-256
`fcb18adf3ff344e51a8f46d3e8eb92f7bb5487f4a3ee5ef74836076d51f3c3d4`.
It also matches the finite-table payload decoded statically from the captured d11
formula solver.

## Reproduce

```bash
python3 tools/rebuild_phase1.py
python3 tools/verify_repository.py --stage 40-delivery-10059
```

## Evidence boundary

The reports' original `miss.md`, SAT journals, CNF files, and CaDiCaL event logs
were not captured beside d11. The explicit tables and formulas allow independent
certificate checking, but not replay of the original discovery run. A later
107-table report is outside this historical stage and is deliberately excluded.

The commands use only the Python standard library and are verified in CI with
CPython 3.12. The historical d11 manifest and model-audit summary are intentionally
omitted because their useful counts are recomputed here and they contain
host-specific absolute paths; the formula solver, integration scripts, evaluation,
and both explicit reports remain captured.
