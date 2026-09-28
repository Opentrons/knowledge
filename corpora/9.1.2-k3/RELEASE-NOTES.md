# Opentrons Knowledge 9.1.2-k3

Target Opentrons release: **v9.1.2**

## Source pins (unchanged vs 9.1.2-k2)

| Source | Pin |
|--------|-----|
| Protocol API + shared-data | `v9.1.2` @ `1fb64381ce23a053768e472065bd14e2c6d4c3a0` |
| Official docs | `mkdocs-2026-09-01` @ `b38ab22d64e9a9cc24c678f1c79ff667139d1729` |
| Opentrons AI v1 guides | `ai-server@0.0.22` @ `0b6a6ecd2d6e040e02f40bd1d44193cfc42b33dc` (`pd/` excluded) |

## What changed in k3

This revision rebuilds the **same pinned sources** with an updated builder and
artifact contract focused on raw corpus data for downstream consumers.

### Removed from the published artifact

- `indexes/lexical/` (pre-built term lookup maps)
- `indexes/vector/` and `embeddings.jsonl.zst` (including fake-hash embeddings)
- `reports/indexing-report.json`
- `embedding` configuration in `manifest.yaml`

### Unchanged

- `corpus/*.jsonl.zst` record shapes and `corpus_schema_version: 1`
- Source commit pins and compatibility records (same as 9.1.2-k2)
- Authority precedence and provenance fields on records

### Consumer impact

- Search, lexical indexes, vector indexes, embeddings, and ranking are **out of
  scope** for this package. Build those in your own tool on top of
  `corpus/*.jsonl.zst`.
- If you depended on `indexes/` from 9.1.2-k1/k2, regenerate indexes locally or
  in your retrieval service from the JSONL streams.

## Publish

```bash
uv run opentrons-knowledge build \
  --manifest corpora/9.1.2-k3/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist
uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-9.1.2-k3
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-9.1.2-k3
```

Git tag for release: `knowledge-v9.1.2-k3`
