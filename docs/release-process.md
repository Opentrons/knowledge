# Release Process

1. Create or update `corpora/<version>/source-manifest.yaml`.
2. Validate pinned sources and compatibility records.
3. Build the corpus (`opentrons-knowledge build --manifest ...`).
4. Review build, source, compatibility, duplication, and indexing reports.
5. Run lint, typecheck, and tests (`just ci`).
6. Run `opentrons-knowledge validate` / `verify`.
7. Pack: `opentrons-knowledge pack --corpus dist/opentrons-knowledge-<version>`.
8. Ensure clean Git state; create annotated tag `knowledge-v<version>`.
9. Attach `opentrons-knowledge-<version>.tar.zst` (and its sha256) to the GitHub Release.
10. Publish OCI: `opentrons-knowledge publish --corpus dist/opentrons-knowledge-<version>`
    (refuses overwrite of an existing tag unless `--overwrite`).
11. Publish release notes summarizing sources, builder, schema, and changes.

## Release Notes Checklist

- Target Opentrons version
- Corpus version
- Source commits
- Builder version
- Corpus schema version
- Major knowledge additions / corrections / removals
- Index or embedding changes
- Compatibility status
- Artifact filename and sha256
- OCI reference and digest (`ghcr.io/opentrons/opentrons-knowledge:<version>`)

## CI

- **Validation workflow**: every PR (lint, mypy, unit tests, fixture corpus, zizmor on `.github/**`)
- **Corpus build workflow**: builds from a manifest; uploads directory + packed `.tar.zst`
- **Publication workflow**: manual/approved release; packs `.tar.zst` to GitHub Releases and pushes OCI to GHCR via ORAS

### Publish via GitHub Actions

After `main` is green:

```bash
gh workflow run publish.yml \
  --repo Opentrons/knowledge \
  -f corpus_version=9.1.1-k1 \
  -f confirm=publish
```

The workflow builds from the pinned source manifest, uploads
`opentrons-knowledge-<version>.tar.zst` (+ `.sha256`) to GitHub Release tag
`knowledge-v<version>`, and pushes
`ghcr.io/opentrons/opentrons-knowledge:<version>` via ORAS.

Existing OCI tags are not overwritten (immutability). Bump the knowledge
revision for corrections.
