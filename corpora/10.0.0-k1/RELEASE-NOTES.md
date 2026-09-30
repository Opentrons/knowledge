# Opentrons Knowledge 10.0.0-k1

Target Opentrons release: **v10.0.0**

## Source pins

| Source | Pin |
|--------|-----|
| Protocol API + shared-data | `v10.0.0` @ `e8c6d0a424c25fff1604e2a02e4ccaedac95b9af` |
| Official docs | `mkdocs-2026-09-30` @ `00f1431babdf36a11ec68143c009d5fc889b2478` |
| Opentrons AI v1 guides | `ai-server@0.0.22` @ `0b6a6ecd2d6e040e02f40bd1d44193cfc42b33dc` (`pd/` excluded) |

## Highlights

- First knowledge corpus for Opentrons software **10.0.0** (Protocol API **2.30**).
- Normative Protocol API and shared-data from release tag `v10.0.0`.
- Official docs from MkDocs deploy tag `mkdocs-2026-09-30` (post-release production docs).
- Published artifact matches the **9.1.2-k3** contract: raw `corpus/*.jsonl.zst` only (no
  shipped lexical/vector indexes or embeddings).

## Build

```bash
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k1/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist
uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k1
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k1
```

Git tag for release: `knowledge-v10.0.0-k1`
