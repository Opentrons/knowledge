# Opentrons Knowledge 10.0.0-k2

Target Opentrons release: **v10.0.0**

## Source pins (unchanged vs 10.0.0-k1)

| Source | Pin |
|--------|-----|
| Protocol API + shared-data | `v10.0.0` @ `e8c6d0a424c25fff1604e2a02e4ccaedac95b9af` |
| Official docs | `mkdocs-2026-09-30` @ `00f1431babdf36a11ec68143c009d5fc889b2478` |
| Opentrons AI v1 guides | `ai-server@0.0.22` @ `0b6a6ecd2d6e040e02f40bd1d44193cfc42b33dc` (`pd/` excluded) |

## What changed in k2

Same pinned sources as **10.0.0-k1**, with an expanded published artifact:

### Added: `raw/` verbatim sources

The tarball now includes **`raw/<source_key>/`** trees that mirror the Opentrons
monorepo paths at each source pin (Markdown, Python, JSON, and other files under
the configured paths). Consumers can chunk, index, or parse these files directly
without relying on normalized JSONL.

- Index file: `raw/manifest.yaml` (commits, paths, file counts)
- Normalized records remain under `corpus/*.jsonl.zst` (unchanged purpose)

### Unchanged

- Source commit pins and compatibility records
- `corpus_schema_version: 1` and JSONL record shapes

## Build

```bash
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k2/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist
uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k2
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k2
```

Git tag for release: `knowledge-v10.0.0-k2`
