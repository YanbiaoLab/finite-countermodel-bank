# External Recovery Register

This register lists the external inputs and execution environments still needed
to reproduce the historical discovery and competition workflow beyond the
artifact-level evidence already committed here. It is an acquisition and
acceptance checklist, not a statement that the repository's current verified
claims are invalid.

The work items below are intentionally not called phases or stages. `Phase` and
`Stage` are reserved for the stable repository pipeline described in
[`TIMELINE.md`](TIMELINE.md). Each recovered package should become either new
evidence in the relevant existing stage or an append-only corrective stage; it
must not silently replace historical bytes.

## Current boundary

The repository already rebuilds or independently checks the committed table
lineage, finite-table semantics, frozen Fin4 transition, finite149 frozen paths,
inner solver payload, and runtime transpose closure. Stage 60 also has a completed
seed-free, result-level full run that reaches the committed 284,151,591-pair
residual. That result does not recreate the original seeded scheduling order or
the missing seed-generation/provenance chain.

The following six external work packages remain:

| Work item | External material still required | Completion unlocks |
| --- | --- | --- |
| `ER-10` | Stage 10 mining and export inputs | Replay from the pre-mining model universe to the first-witness snapshot |
| `ER-40` | Stage 40 SAT runner inputs and raw journals | Replay of the two explicit-table discovery deliveries |
| `ER-50` | Stage 50 d16.2 baseline and build transition | Direct historical replay of the d16.2-to-d17 build |
| `ER-JUDGE` | Complete Judge v3 cases, certificates, results, and environment | Independent competition-judge rerun |
| `ER-OUTER` | Complete outer-solver inputs, template, and builder | Byte-exact regeneration of the submitted launcher blobs |
| `ER-LEAN` | Aggregate/submission certificate generator and exact Lean toolchain | Regeneration and kernel checking of the complete Lean certificate set |

## Common capture and acceptance rules

Every recovered package must include:

1. an explicit source inventory with acquisition date, source revision or other
   stable locator, byte size, SHA-256, and redistribution status;
2. immutable raw bytes separated from normalized or generated outputs;
3. the exact command, configuration, seeds when applicable, dependency versions,
   and operating-system or container description needed to run it;
4. a bounded-memory capture/replay script that runs from a clean directory and
   does not rely on unrecorded absolute paths, shell state, or network access;
5. a machine-readable comparison against the applicable committed artifacts,
   including every mismatch rather than only aggregate counts;
6. wall time, peak memory, disk use, exit status, and complete hash-pinned logs for
   any substantial run; and
7. an updated stage manifest, checksums, evidence boundary, and claim ledger in
   the same change that publishes the recovered evidence.

Maintained prose and normalized metadata should not expose personal names or
host-specific home-directory paths. If either is inseparable from immutable raw
evidence, keep the original byte stream unchanged, restrict the maintained
locator to a neutral description, and document why the raw record must be
retained.

Recovery and reproduction are separate acceptance levels. A package is
**captured** once its external bytes and provenance are hash-pinned. It is
**reproduced** only after a clean execution regenerates the expected outputs. A
captured log that cannot be rerun is valuable historical evidence, but it must not
be labeled as a reproduced workflow.

## ER-10 — Stage 10 mining and export

Current evidence: Stage 10 preserves and validates 9,450 recoverable table scripts,
the recovery indexes/reports, the equation map, and the two missing-contributor
records. See the [Stage 10 evidence boundary](reproduction/10-primary-9450/README.md#evidence-boundary).

Recover, as one internally consistent snapshot:

- the historical `models.jsonl.gz` model inventory;
- the generator and export programs that produced the indexed table scripts;
- `directed_unique_false_pairs_9715951.csv` and every consumed
  `out*/false_pairs.csv.gz` input, or a losslessly equivalent earlier source with
  a demonstrated conversion;
- model-family configurations, enumeration bounds, ordering rules, random seeds,
  deduplication rules, and first-witness attribution logic; and
- raw run logs plus the exact interpreter, native tools, and dependency versions.

Acceptance requires a clean replay that explains all 229,666 model identities,
reproduces the 9,452 nonzero contributors, emits the same 9,450 recoverable tables
in historical order, preserves the two unrecoverable ranks and their pair counts,
and matches the committed Stage 10 normalized bank byte for byte. If the original
search is nondeterministic, the recovery must separately distinguish an exact
historical log replay from a fresh semantic rerun.

## ER-40 — Stage 40 SAT discovery

Current evidence: the 102 explicit countermodels and their source/target formulas
are preserved, and every reported assignment count and counterexample is
independently rechecked. See the
[Stage 40 evidence boundary](reproduction/40-delivery-10059/README.md#evidence-boundary).

Recover, for both the 50-table and 52-table deliveries:

- the original `miss.md`, SAT journals, CNF files, and solver event logs;
- the runner, CNF encoder, table decoder, report generator, and all configuration
  files they consumed;
- the exact formula/case inventory and its ordering at each run boundary;
- solver binary hashes, command-line options, seeds, timeout and resource limits,
  and the Python/SAT-library environment; and
- raw stdout, stderr, exit status, intermediate checkpoints, and final reports.

Acceptance requires a clean run whose case mapping is complete and whose two
report batches reproduce the preserved formulas, explicit tables, hashes,
assignment counts, and first counterexamples. A different but valid SAT model is
not a byte-exact historical replay; it may be published as an additional semantic
rerun if the distinction is explicit.

## ER-50 — Stage 50 d16.2 transition

Current evidence: the repository reconstructs the full 10,059-to-3,535 transition,
independently regenerates all 241 scalar-affine classifications, removes the 6,283
remaining order-at-most-4 tables, and matches the published d17 payload exactly.
See the [Stage 50 evidence boundary](reproduction/50-generator-prune-3535/README.md#evidence-boundary).

Recover:

- the exact d16.2 source or built launcher named as the immediate historical
  baseline;
- the complete patch, builder, or generation script that transformed d16.2 into
  d17;
- every non-generated template, configuration file, and input report consumed by
  that build; and
- the interpreter/compiler versions, build command, environment variables, and
  raw build log.

Acceptance requires pinning the d16.2 bytes and demonstrating the transition in a
clean directory. The replay must regenerate the same ordered 3,535-table canonical
stream and d17 payload, account for the 241 and 6,283 removals without an
unexplained input, and match every already-committed Stage 50 delta and witness.

## ER-JUDGE — Judge v3 rerun

Current evidence checks finite countermodel semantics independently, but it does
not execute Judge v3 or preserve a complete per-case judge transcript.

Recover:

- the exact Judge v3 source revision and all rule/configuration files;
- the complete evaluated case inventory and original solver inputs;
- solver stdout or certificate bytes for every case, including failures,
  timeouts, and empty results;
- the authoritative per-case and aggregate result files;
- the container image or equivalent environment, including dependency hashes,
  locale, resource limits, and invocation command; and
- unabridged judge stdout/stderr and machine-readable timing/resource records.

Acceptance requires a clean, isolated rerun with a one-to-one join across case
inputs, certificates, and judge results. Every outcome must match the preserved
authoritative record, and every accepted certificate must be checked by the pinned
Judge v3 implementation. Report any environment-dependent divergence per case;
do not collapse it into a single pass/fail total.

## ER-OUTER — complete outer solver regeneration

Current evidence extracts and rebuilds the exact inner finite-table payload, and
it hash-pins the two byte-distinct outer launcher blobs found in the four current
2026-09-01 submitted anchors: 490,289-byte Solo and 499,149-byte Marathon. The four
superseded 2026-08-31 launcher files are retained as separately indexed historical
evidence. The repository does not regenerate the complete launcher source. The
current hashes and sizes are recorded in the
[submitted-payload audit](reproduction/90-payload-1487/verification/submitted-payload-audit.json).

Recover:

- the canonical outer-solver template or source tree for each distinct submitted
  launcher variant;
- the complete builder and all non-table generated fragments, embedded assets,
  configuration, and version metadata;
- the exact input-to-submission mapping for all four current anchors; and
- deterministic formatting, compression, encoding, newline, and build-environment
  settings.

Acceptance requires a clean build that produces the exact launcher bytes for all
four current submission anchors, including both distinct blob hashes and sizes.
Historical replay may separately target the four superseded 2026-08-31 anchors.
Matching only the embedded table literal is insufficient. The comparison must also
prove that no unrecorded post-build edit is needed.

## ER-LEAN — aggregate and submission certificates

Current evidence captures the Lean table sources needed for finite149 provenance
and path validation, but normal replay neither compiles the complete source set nor
regenerates aggregate/submission certificates. See the
[Stage 81 evidence boundary](reproduction/81-finite149-portable-verification/README.md#evidence-boundary).

Recover:

- the aggregate/submission certificate generator, templates, and complete input
  mapping from cases and graph paths to generated Lean declarations;
- all referenced Lean source modules and generated certificate outputs;
- `lean-toolchain`, project/package manifests, dependency lock data, and any
  required vendored cache or immutable dependency revisions;
- the exact generation, formatting, build, and kernel-check commands; and
- build logs, per-file outcomes, resource limits, and the environment used for
  the submitted certificates.

Acceptance requires deterministic regeneration of the complete certificate source
set followed by a clean Lean build with the pinned toolchain. Generated bytes and
module/case mappings must match the preserved submission record, and all
certificates must pass kernel checking. If formatting or generated names are not
byte-deterministic, preserve both the historical byte comparison and an explicitly
separate semantic compilation result.

## Adjacent historical gaps

The six work packages above are the current external restoration queue. Two
boundaries remain relevant but do not invalidate the completed result-level
checks:

- Stage 60's original 6,173-model seed-generation/provenance chain is still
  unavailable. Recovering it would enable historical seeded-order replay; it is
  not required to rerun and validate the committed residual with the seed-free
  runner.
- Stage 81 validates every edge of the frozen finite149 paths against captured
  graph and source bytes, but it does not rerun upstream graph extraction/building
  or shortest-path discovery. Recovering those discovery inputs would extend the
  provenance chain beyond the frozen-path replay.

Until the relevant package satisfies its acceptance gate, documentation must use
the narrower existing claim (`captured`, `reproduced` from committed snapshots, or
independently `verified`) and must not describe the full historical workflow as
reproduced.
