# Stage 00 — SAIR submission anchor

This stage freezes the four solver files shown on the authenticated SAIR Stage 2
team submission page on 2026-08-31. Later payload reconstruction must compare its
output against these bytes.

本阶段固定 2026-08-31 在 SAIR Stage 2 团队提交页显示的四份 solver。后续构建出的载荷
必须与这些文件逐字节比较。

## Captured participations

| Track | Model shown by SAIR | Displayed submission time | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| Solo | Google: Gemma 4 31B | Aug 31, 2026, 10:47 AM | 490,327 | `f8b845e42a0007fc576d22235597fcccc85316d581c72c758f3f35cc9b65ec19` |
| Solo | OpenAI: gpt-oss-120b | Aug 31, 2026, 10:47 AM | 490,327 | `f8b845e42a0007fc576d22235597fcccc85316d581c72c758f3f35cc9b65ec19` |
| Marathon | Google: Gemma 4 31B | Aug 31, 2026, 10:48 AM | 498,047 | `e301cbd091df1376c21ac297e1afb05decb70c34879cd6e485744d09e017c809` |
| Marathon | OpenAI: gpt-oss-120b | Aug 31, 2026, 10:48 AM | 498,047 | `e301cbd091df1376c21ac297e1afb05decb70c34879cd6e485744d09e017c809` |

The SAIR page did not display a timezone beside participation timestamps. The
capture host and browser used Asia/Shanghai; `submissions.jsonl` preserves the
literal display string and records that timezone only as context, not as an
assertion about SAIR's server timezone.

The two files within each track are byte-identical. All four are retained because
they are distinct participation records. Git stores identical content efficiently,
while the separate paths preserve track/model provenance.

## Files

- `raw/`: filenames observed in Chrome after each SAIR download; no content changes were made.
- `submissions.jsonl`: one machine-readable record per participation.
- `stage.json`: source and artifact manifest.
- `SHA256SUMS`: exact hashes for the index and all four raw files.

## Verification

From the repository root:

```bash
python3 tools/verify_repository.py --stage 00-submission-anchor
```

This checks safe paths, byte counts, SHA-256 hashes, source references, checksum
agreement, unique participation IDs, and complete index coverage. It does not run
the downloaded solvers.

## What this stage proves—and does not prove

It proves that the committed files match the four captured downloads and records
the metadata displayed by the submission page. It does not establish how the
embedded tables were generated, whether every submission was evaluated, or whether
the solvers are mathematically correct. Those are separate claims for later stages.
