# Reproduction stages

Directories are ordered by the historical pipeline, not by the date on which they
are uploaded to GitHub. A stage should be independently reviewable and should not
rewrite an earlier stage.

## Required stage files

- `README.md`: human reproduction guide, exact commands, expected counts, and gaps.
- `stage.json`: sources, dependencies, claim IDs, and immutable artifact metadata.
- `raw/`: source bytes as received, without normalization or deduplication.
- `normalized/`: canonical records produced deterministically from `raw/`, when applicable.
- `delta.jsonl` or a compressed equivalent: ordered membership decisions, when applicable.
- `SHA256SUMS`: hashes for every immutable artifact listed by `stage.json`.

Not every stage needs every optional directory. Omissions must be explained in its
README.

## Canonical table identity

For an operation table of order `n` (`1 <= n <= 255`):

1. validate that there are exactly `n²` entries;
2. validate every entry is in `0..n-1`;
3. encode one byte containing `n`, followed by the row-major entries as bytes;
4. set `table_id` to `sha256:` followed by the lowercase SHA-256 hex digest.

Deduplication uses this exact identifier. It does not quotient by isomorphism.

## Raw, normalized, and delta data

`raw/` answers “what bytes were available at that historical point?”
`normalized/` answers “what canonical tables do those bytes represent?”
The delta answers “why did each record enter, stay in, leave, replace, or derive
from the previous set?” This separation allows a reviewer to rerun normalization
without losing the original evidence.

Large files should be processed as streams or bounded chunks. Compressed future
artifacts should use deterministic settings documented in the stage README.

## PR 1 capture and rebuild

PR 1 deliberately separates the one-time local capture from the portable rebuild.
If the matching historical sibling checkout is available, recreate the four raw
archives with:

```bash
python3 tools/capture_pr1_snapshots.py \
  --source-root ../math-distill-equational-stage2
```

The capture command selects an explicit file list, sorts archive paths, streams
file bytes, and normalizes tar ownership, modes, and timestamps plus the gzip
header. It does not edit the sibling checkout. Normal reviewers do not need that
checkout; they reproduce all normalized data from the committed archives:

```bash
python3 tools/rebuild_pr1.py
python3 tools/verify_repository.py
```

PR 1 uses deterministic `tar.gz`, JSONL gzip (`mtime=0`), and uncompressed
canonical table binaries so the workflow depends only on the Python standard
library. Historical `.py` inputs are parsed as data and never imported or run.
