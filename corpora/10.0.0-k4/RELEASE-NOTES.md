# Opentrons Knowledge 10.0.0-k4

Target Opentrons release: **v10.0.0**

## Source pins

| Source | Pin |
|--------|-----|
| Protocol API + shared-data | `v10.0.0` @ `e8c6d0a424c25fff1604e2a02e4ccaedac95b9af` |
| Official docs | `mkdocs-2026-09-30` @ `00f1431babdf36a11ec68143c009d5fc889b2478` |
| Opentrons AI v1 guides | `ai-server@0.0.22` @ `0b6a6ecd2d6e040e02f40bd1d44193cfc42b33dc` (`pd/` excluded) |
| Protocol Designer allowlist | `protocol-designer@9.0.1` @ `677274a40c5d22044c4efe7365d4904a56eeefd4` |

The Protocol Designer pin is the latest production `protocol-designer@X.Y.Z` tag
resolved from the remote on 2026-11-10. It is independent of the robot-stack
`v10.0.0` pin and of the docs and ai-server pins. Tags matching
`staging-protocol-designer@*`, `pd-test*`, or `protocol-designer@*` with
`-alpha`, `-beta`, or `-rc` are ignored.

## What changed in k4

Same pinned sources as **10.0.0-k3**, plus one raw file.

### Added: Protocol Designer module-labware allowlist

`protocol-designer/src/utils/labwareModuleCompatibility.ts` is copied verbatim to:

```text
raw/protocol_designer/protocol-designer/src/utils/labwareModuleCompatibility.ts
```

`raw/manifest.yaml` records tag `protocol-designer@9.0.1`, commit
`677274a40c5d22044c4efe7365d4904a56eeefd4`, and the path. `corpus/source-files.jsonl.zst`
lists that one file as included. The exported constant is
`COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE`. The build does not read or parse
the TypeScript, and it does not create entities, relationships, retrieval
documents, or search chunks from it.

### Unchanged from k3

- Protocol API, shared-data, docs, and AI guide pins
- `canonical/` and `retrieval/` (entity, relationship, and retrieval counts)
- `corpus_schema_version: 1`

## Build

```bash
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k4/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist
uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k4
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k4
```

Git tag for release: `knowledge-v10.0.0-k4`
