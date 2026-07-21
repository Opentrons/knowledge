# Opentrons Knowledge — Agent Entrypoint

You are working with **Opentrons Knowledge**, which publishes immutable
**Opentrons Knowledge Corpus** artifacts for specific Opentrons software
releases.

Read the full guide:

- In this repository: [`docs/agent-usage.md`](docs/agent-usage.md)
- Inside a packed/unpacked corpus: `AGENTS.md` and `docs/agent-usage.md`

## Product in one sentence

The product is the **corpus artifact** (same bytes as a directory, shipped as
`.tar.zst` and/or OCI on GHCR), not a search SDK, MCP server, or lookup library.

## How to use a corpus

1. Obtain the corpus:
   - `opentrons-knowledge-<version>.tar.zst` (GitHub Release or local `pack`), or
   - `ghcr.io/opentrons/opentrons-knowledge:<version>` via `opentrons-knowledge pull`
2. Open the unpacked directory.
3. Read `manifest.yaml`, then `corpus/*.jsonl.zst` and `indexes/` with your own
   retrieval stack.

```bash
opentrons-knowledge unpack opentrons-knowledge-9.1.1-k1.tar.zst --output dist
# or: opentrons-knowledge pull 9.1.1-k1 --output dist
```

The on-disk layout is the API. Downstream apps define search/ranking.

## Authority order (highest first)

1. Protocol API source + shared-data (`normative`)
2. Official docs (`official_guidance`)
3. Generated API reference
4. Curated AI v1 guides (`curated_guidance`; `pd/` excluded)
5. Examples
6. Historical / deprecated

Examples and AI guides must not override symbols or shared-data.

## Cite sources

Prefer commit-pinned `source_url` fields on records, plus the corpus version
(`9.1.1-k1`). See `docs/agent-usage.md`.
