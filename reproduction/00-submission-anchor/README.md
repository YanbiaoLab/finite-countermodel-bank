# Stage 00 — SAIR submission anchor

This stage freezes both the current four solver files shown on the authenticated
SAIR Stage 2 team submission page on 2026-09-01 and the superseded four-file
capture from 2026-08-31. Later current-payload reconstruction compares against
the 2026-09-01 bytes; historical Stages 70–81 retain their original 2026-08-31
anchor references.

## Current participations

| Track | Model shown by SAIR | Displayed submission time | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| Solo | Google: Gemma 4 31B | Sep 1, 2026, 02:21 PM | 490,289 | `cdec40c1a31db314d94dd079a51064fa284627f7641749132e1787e85fd3971e` |
| Solo | OpenAI: gpt-oss-120b | Sep 1, 2026, 02:22 PM | 490,289 | `cdec40c1a31db314d94dd079a51064fa284627f7641749132e1787e85fd3971e` |
| Marathon | Google: Gemma 4 31B | Sep 1, 2026, 02:22 PM | 499,149 | `18c1ccec4724837440362b8f08433d2eb73296d71e1e81054fc9cca6f3f07284` |
| Marathon | OpenAI: gpt-oss-120b | Sep 1, 2026, 02:22 PM | 499,149 | `18c1ccec4724837440362b8f08433d2eb73296d71e1e81054fc9cca6f3f07284` |

## Superseded 2026-08-31 capture

| Track | Model shown by SAIR | Displayed submission time | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| Solo | Google: Gemma 4 31B | Aug 31, 2026, 10:47 AM | 490,327 | `f8b845e42a0007fc576d22235597fcccc85316d581c72c758f3f35cc9b65ec19` |
| Solo | OpenAI: gpt-oss-120b | Aug 31, 2026, 10:47 AM | 490,327 | `f8b845e42a0007fc576d22235597fcccc85316d581c72c758f3f35cc9b65ec19` |
| Marathon | Google: Gemma 4 31B | Aug 31, 2026, 10:48 AM | 498,047 | `e301cbd091df1376c21ac297e1afb05decb70c34879cd6e485744d09e017c809` |
| Marathon | OpenAI: gpt-oss-120b | Aug 31, 2026, 10:48 AM | 498,047 | `e301cbd091df1376c21ac297e1afb05decb70c34879cd6e485744d09e017c809` |

The SAIR page did not display a timezone beside participation timestamps. The
capture host and browser used Asia/Shanghai; both JSONL indexes preserve the
literal display strings and record that timezone only as context, not as an
assertion about SAIR's server timezone.

Within each capture, the two files for a track are byte-identical. The current
and historical captures differ at the outer-launcher and false-engine-source
levels, while Phase 4 verifies that their 1,487-record embedded table payload is
identical.

## Files

- `submissions.jsonl`: the authoritative current four-participation index.
- `submissions-20260831.jsonl`: the superseded four-participation index.
- `raw/2026-09-01_*`: current downloaded solver bytes.
- `raw/2026-08-31_*`: superseded downloaded solver bytes retained unchanged.
- `stage.json`: source and artifact manifest for both captures.
- `SHA256SUMS`: exact hashes for both indexes and all eight raw files.

## Verification

From the repository root:

```bash
python3 tools/verify_repository.py --stage 00-submission-anchor
```

This checks safe paths, byte counts, SHA-256 hashes, current source references,
checksum agreement, unique current participation IDs, and complete current-index
coverage. Historical files and their index are hash-verified as manifested
artifacts. No downloaded solver is executed.

## What this stage proves—and does not prove

It proves that the committed current files match the four 2026-09-01 downloads,
and separately preserves the four 2026-08-31 downloads and their displayed
metadata. It does not establish how the embedded tables were generated, whether
every submission was evaluated, or whether the solvers are mathematically
correct. Those are separate claims for later stages.
