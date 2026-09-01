# Provenance and rights notice

Copyright 2026 Finite Countermodel Bank contributors.

This project is licensed under the Apache License, Version 2.0, as set out in the
root `LICENSE` file. That license applies only to material for which the project
contributors hold the necessary rights. It does not relicense third-party or
source-specific material. A source record marked `not-specified` remains a record
of unconfirmed rights status and is not converted into an open-source license by
the repository's primary license.

The artifacts in `reproduction/00-submission-anchor/raw/` are archive copies of
solver source files submitted by team `EQT02-T00037` to the SAIR Mathematics
Distillation Challenge — Equational Theories Stage 2. Four were downloaded from
the authenticated team submission page on 2026-08-31 and are retained as
historical evidence; four current replacements were downloaded on 2026-09-01. The
archive does not copy the SAIR site, its interface, or third-party page content.

Each later stage must record its source and rights status in `stage.json`.
Third-party files must retain applicable copyright, attribution, and license
notices. If the relevant rights are unknown, the manifest must say so; uncertainty
must not be converted into an assumed open-source license.

Public-facing descriptions use neutral stage and artifact labels rather than
contributor names. Personal identifiers remain only when they are literal parts of
immutable upstream paths, historical archive filenames, or other provenance
locators; those strings are retained so the recorded source location stays exact.

Phase 1 raw archives are local filesystem snapshots from ignored member paths in
the sibling `math-distill-equational-stage2` checkout. The surrounding Git revision
is recorded only as context and does not identify those ignored bytes.
Each deterministic archive and every derived artifact is identified by its own
SHA-256. No source-specific license grant was found, so the corresponding stage
manifests use `not-specified; no license grant inferred`.

Raw capture is deliberately minimal. Historical d4/d6/d8/d11 manifests, the d11
model-audit summary, and a redundant Stage 10 narrative report were not included
because their relevant counts are recomputed from retained evidence and the files
contain host-specific absolute paths. They are not silently sanitized or presented
as raw bytes. A selected-member scan found no email address or host-specific
absolute path in the committed Phase 1 raw archives.

Phase 2 raw archives are likewise deterministic local snapshots from the sibling
checkout. They contain the d15/d17 pruning evidence, frozen 324M/284M pair
packages and Fin4 shard records, and frozen coverage/law-count reports. Several
historical scripts and manifests retain repository-relative provenance paths
because raw evidence is not silently rewritten. A bounded scan of captured text
members, including the nested Stage 70 ZIP, found no email-like strings,
credential markers, private-key blocks, or host-specific absolute paths. As with
Phase 1, the manifests record `not-specified; no license grant inferred` for these
sources.

The Stage 81 companion finite149 graph/path snapshot contains files from
`teorth/equational_theories`. That upstream repository identifies the material as
Apache-2.0. The exact upstream license text is retained as
`source/license/LICENSE` inside
`reproduction/81-finite149-portable-verification/raw/finite149-path-source-snapshot.tar.gz`
with SHA-256
`c6be243aa954228fc83b68a08e769bf3c561a64fb515cbbd470046d006c18bbf`.
No upstream `NOTICE` or `NOTICE.txt` file was present at the pinned revision; the
Stage 81 metadata records that absence rather than inventing a notice.

See `LICENSES/README.md` for the primary-license scope and how future
source-specific license texts will be recorded.
