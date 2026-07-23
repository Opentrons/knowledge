# Opentrons Knowledge

Immutable, reproducible, versioned **Opentrons Knowledge Corpus** artifacts for
specific Opentrons software releases.

The primary product is the **corpus artifact**, not a search service or lookup
SDK. Downstream tools read the files and define their own retrieval.

Distribution channels:

```text
opentrons-knowledge-9.1.1-k1.tar.zst
ghcr.io/opentrons/opentrons-knowledge:9.1.1-k1
```

## Quick start

```bash
just sync
just ci            # lint, typecheck, test, fixture corpus
just fixture-corpus
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-0.0.0-k1
```

### Build a release corpus

Requires a local clone of [Opentrons/opentrons](https://github.com/Opentrons/opentrons)
with the tags pinned in the chosen source manifest.

```bash
# 9.0.0-k1: v9.0.0 + mkdocs-2026-06-02 + ai-server@0.0.20
uv run opentrons-knowledge build \
  --manifest corpora/9.0.0-k1/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist

# 9.1.1-k1: v9.1.1 + mkdocs-2026-07-16 + ai-server@0.0.20
uv run opentrons-knowledge build \
  --manifest corpora/9.1.1-k1/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist

uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-9.1.1-k1
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-9.1.1-k1
```

That writes `dist/opentrons-knowledge-<version>.tar.zst`.

OCI publish (requires [`oras`](https://oras.land/docs/installation) on PATH and
registry auth):

```bash
uv run opentrons-knowledge publish \
  --corpus dist/opentrons-knowledge-9.1.1-k1 \
  --registry ghcr.io/opentrons/opentrons-knowledge
```

### Consume a corpus

From a GitHub Release `.tar.zst`:

```bash
uv run opentrons-knowledge unpack dist/opentrons-knowledge-9.1.1-k1.tar.zst --output dist
uv run opentrons-knowledge inspect --corpus dist/opentrons-knowledge-9.1.1-k1
```

From GHCR (requires `oras`):

```bash
uv run opentrons-knowledge pull 9.1.1-k1 --output dist
```

See [AGENTS.md](AGENTS.md) and [docs/agent-usage.md](docs/agent-usage.md) for how
agents should treat the files (`corpus/*.jsonl.zst`, `indexes/`, `manifest.yaml`).

## Documentation

**Agents start here:** [AGENTS.md](AGENTS.md) · [docs/agent-usage.md](docs/agent-usage.md) · [llms.txt](llms.txt)

These guides are packaged into every corpus directory and thus into both
distribution formats.

- [Source analysis](docs/source-analysis.md)
- [Product architecture](docs/product-architecture.md)
- [Corpus format](docs/corpus-format.md)
- [Versioning](docs/versioning.md)
- [Release process](docs/release-process.md)
- [Implementation plan](docs/implementation-plan.md)

## CLI

```bash
opentrons-knowledge build --manifest corpora/9.1.1-k1/source-manifest.yaml
opentrons-knowledge validate --corpus dist/opentrons-knowledge-9.1.1-k1
opentrons-knowledge inspect --corpus dist/opentrons-knowledge-9.1.1-k1
opentrons-knowledge pack --corpus dist/opentrons-knowledge-9.1.1-k1
opentrons-knowledge unpack dist/opentrons-knowledge-9.1.1-k1.tar.zst
opentrons-knowledge publish --corpus dist/opentrons-knowledge-9.1.1-k1
opentrons-knowledge pull 9.1.1-k1
opentrons-knowledge verify --corpus dist/opentrons-knowledge-9.1.1-k1
opentrons-knowledge sources --corpus dist/opentrons-knowledge-9.1.1-k1
opentrons-knowledge diff 9.1.1-k1 9.1.1-k2 --json
```

## Development

Use [just](https://github.com/casey/just) (`brew install just`):

```bash
just sync
just ci
just zizmor
just zizmor-online
```

GitHub Actions are SHA-pinned; CI runs [zizmor](https://docs.zizmor.sh/) on
`.github/**` changes. Releases publish both the `.tar.zst` GitHub Release asset
and the OCI artifact on GHCR.

## License

Copyright 2026 Opentrons Labworks, Inc.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).
