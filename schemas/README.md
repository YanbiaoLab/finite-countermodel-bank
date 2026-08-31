# Schema contracts

Schemas use JSON Schema draft 2020-12 and start at version `1.0.0`.

- `stage-manifest.schema.json` describes each `stage.json`.
- `submission-anchor.schema.json` describes each line of the PR 0 submission index.
- `table-record.schema.json` describes normalized finite operation tables.
- `delta-record.schema.json` describes ordered membership decisions between stages.

JSON Schema cannot express every relational invariant. The repository verifier also
checks path safety, file sizes, SHA-256 digests, uniqueness, and index/manifest
agreement. When table records are introduced, the verifier will additionally check
that the entry count is `order²`, every entry is below `order`, and `table_id`
matches the canonical bytes.

Schema changes are additive within a major version. A breaking change requires a
new major `schema_version` and an explicit migration note; historical raw files are
never rewritten merely to adopt a new schema.
