# Provenance and rights notice

This repository currently has no repository-wide license. The presence of a file
in this repository is not, by itself, a grant of permission to copy, modify, or
redistribute it.

The artifacts in `reproduction/00-submission-anchor/raw/` are archive copies of
solver source files submitted by team `EQT02-T00037` to the SAIR Mathematics
Distillation Challenge — Equational Theories Stage 2. They were downloaded from
the authenticated team submission page on 2026-08-31. The archive does not copy
the SAIR site, its interface, or third-party page content.

Each later stage must record its source and rights status in `stage.json`.
Third-party files must retain applicable copyright, attribution, and license
notices. If the relevant rights are unknown, the manifest must say so; uncertainty
must not be converted into an assumed open-source license.

PR 1 raw archives are local filesystem snapshots from ignored `members/wubing/`
paths in the sibling `math-distill-equational-stage2` checkout. The surrounding Git
revision is recorded only as context and does not identify those ignored bytes.
Each deterministic archive and every derived artifact is identified by its own
SHA-256. No source-specific license grant was found, so the corresponding stage
manifests use `not-specified; no license grant inferred`.

Raw capture is deliberately minimal. Historical d4/d6/d8/d11 manifests, the d11
model-audit summary, and a redundant Stage 10 narrative report were not included
because their relevant counts are recomputed from retained evidence and the files
contain host-specific absolute paths. They are not silently sanitized or presented
as raw bytes. A selected-member scan found no email address or host-specific
absolute path in the committed PR 1 raw archives.

PR 2 raw archives are likewise deterministic local snapshots from the sibling
checkout. They contain the d15/d17 pruning evidence, frozen 324M/284M pair
packages and Fin4 shard records, and frozen coverage/law-count reports. Several
historical scripts and manifests retain repository-relative provenance paths
because raw evidence is not silently rewritten. A bounded scan of captured text
members, including the nested Stage 70 ZIP, found no email-like strings,
credential markers, private-key blocks, or host-specific absolute paths. As with
PR 1, the manifests record `not-specified; no license grant inferred` for these
sources.

See `LICENSES/README.md` for how future source-specific license texts will be
recorded.
