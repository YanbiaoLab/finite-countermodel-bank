# Stage 90 — exact 1,487-record payload

This stage constructs the exact finite-table byte stream embedded in the current
2026-09-01 submitted False Solver:

```text
1,470 Stage 70 core records + 17 Stage 80 finite149 base records = 1,487
```

## Inputs and provenance

- `reproduction/70-positive-marginal-core-1470/normalized/tables.bin`:
  1,470 records, 101,870 bytes.
- `reproduction/80-finite149/normalized/base-tables.bin`:
  17 records, 9,139 bytes.
- `reproduction/81-finite149-portable-verification/normalized/base-table-provenance.jsonl.gz`:
  effective provenance for the 17 appended records, including the corrected
  order-22 `F149-014` source.
- the four current 2026-09-01 Stage 00 submission anchors, parsed only as data
  through restricted AST literal extraction.

There is no `raw/` directory. Every input byte is already immutable and manifested
in a dependency stage; recapturing the current sibling development checkout would
not reproduce the historical state.

## Exact payload and bundle

The reconstructed canonical stream is:

| Property | Value |
| --- | ---: |
| Records | 1,487 |
| Raw bytes | 111,009 |
| Raw SHA-256 | `17240427976219ef8da8b2ecb1bd14731b6c11d3be052711911443539e92a680` |
| Canonical-ID vector SHA-256 | `75596a4b3a08e651cf1c152923092b955a7f5cd6a81b65c2978a9cbfd091cd07` |

Each record is one nonzero order byte followed by exactly `order²` row-major entry
bytes, with every entry strictly below the order. The decoder rejects truncation,
duplicates, out-of-range entries, and trailing bytes.

The submitted literal is reproduced with:

```python
compressed = lzma.compress(
    raw,
    format=lzma.FORMAT_XZ,
    check=lzma.CHECK_CRC64,
    preset=9 | lzma.PRESET_EXTREME,
)
encoded = base64.b85encode(compressed)
```

| Layer | Bytes | SHA-256 |
| --- | ---: | --- |
| XZ | 28,808 | `a9b757ea978411ff982f0a1c0404e0b505be74b8c29481d7eeb81d97a6cd79cc` |
| Base85 | 36,010 | `2b34894f2da26c12476f88473cd4cb2dae77ddbfeeedb2c2d7147d6caf8abb42` |

Python's default LZMA preset and non-extreme preset 9 do not reproduce these bytes.
The required CI baseline is Python 3.11; Python 3.12 is an additional exact-output
check.

## Reproduce

From the repository root, using Python 3.11:

```bash
python3 tools/rebuild_phase4.py
python3 tools/verify_phase4.py
```

`verify_phase4.py` rebuilds both Phase 4 stages in a temporary directory, compares every
manifested artifact and manifest byte for byte, and then runs the repository-level
semantic verifier.

## Evidence boundary

This stage reconstructs the exact inner table stream and its XZ/Base85 literal. It
does not claim to regenerate the complete current outer solver launchers
(490,289-byte Solo and 499,149-byte Marathon) or to execute submitted code. All
four current launchers are statically inspected and contain the same false-engine
source and the same table payload.
