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

# 9.1.2-k1: v9.1.2 + mkdocs-2026-08-12 + ai-server@0.0.20
uv run opentrons-knowledge build \
  --manifest corpora/9.1.2-k1/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist

# 9.1.2-k3: same pins as k2; artifact drops shipped indexes/embeddings (see RELEASE-NOTES)
uv run opentrons-knowledge build \
  --manifest corpora/9.1.2-k3/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist

uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-9.1.2-k3
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-9.1.2-k3

# 10.0.0-k1: v10.0.0 + mkdocs-2026-09-30 + ai-server@0.0.22
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k1/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist

uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k1
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k1

# 10.0.0-k2: same pins as k1; adds raw/ verbatim source trees (see RELEASE-NOTES)
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k2/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist

uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k2
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k2

# 9.1.2-k2 (superseded by k3 for new consumers)
# uv run opentrons-knowledge build --manifest corpora/9.1.2-k2/source-manifest.yaml ...
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
agents should treat the files (`corpus/*.jsonl.zst`, `manifest.yaml`). From
`10.0.0-k3` the artifact also ships `retrieval/`: searchable documents, chunks,
and two BM25 indexes (`api/` for the Python API reference, `docs/` for the
rest). Ranking and embeddings remain consumer concerns.

### Canonical docs from rendered MkDocs HTML

Render the pinned Opentrons docs site in an isolated checkout and extract
structured documents (sections, code, tabs, admonitions, tables, API reference):

```bash
just docs-build       # dist/canonical-docs/{documents.jsonl.zst,manifest.json}
just docs-validate
just test-integration # slow; real build + HTML fidelity checks
```

See [docs/canonical-docs.md](docs/canonical-docs.md).

### Retrieval bundle (documents, chunks, BM25)

```bash
just build-10-0-0-k3          # corpus with canonical/, retrieval/, reports/retrieval-eval.json
just retrieval-validate
just retrieval-search "InstrumentContext.blow_out"   # API index
just retrieval-explore                                 # try queries interactively
just retrieval-audit                                   # every documented symbol
just retrieval-experiment     # re-run the 51-configuration grid
```

See [docs/retrieval-design.md](docs/retrieval-design.md),
[docs/retrieval-experiments.md](docs/retrieval-experiments.md), and
[docs/retrieval-tool.md](docs/retrieval-tool.md).

## Documentation

**Agents start here:** [AGENTS.md](AGENTS.md) · [docs/agent-usage.md](docs/agent-usage.md) · [llms.txt](llms.txt)

These guides are packaged into every corpus directory and thus into both
distribution formats.

- [Source analysis](docs/source-analysis.md)
- [Product architecture](docs/product-architecture.md)
- [Corpus format](docs/corpus-format.md)
- [Canonical docs corpus](docs/canonical-docs.md)
- [Retrieval design](docs/retrieval-design.md) · [Retrieval experiments](docs/retrieval-experiments.md) · [Search tool guidance](docs/retrieval-tool.md)
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
opentrons-knowledge docs build --manifest corpora/10.0.0-k2/source-manifest.yaml --opentrons-repo ../opentrons
opentrons-knowledge docs validate --corpus dist/canonical-docs
opentrons-knowledge docs inspect --corpus dist/canonical-docs --document python-api/pipettes/loading/
opentrons-knowledge retrieval experiment --corpus dist/opentrons-knowledge-10.0.0-k3
opentrons-knowledge retrieval build --corpus dist/opentrons-knowledge-10.0.0-k3 --output dist/retrieval
opentrons-knowledge retrieval validate --bundle dist/opentrons-knowledge-10.0.0-k3/retrieval
opentrons-knowledge retrieval search "InstrumentContext.blow_out" --bundle dist/opentrons-knowledge-10.0.0-k3/retrieval --index api
opentrons-knowledge retrieval explore --bundle dist/opentrons-knowledge-10.0.0-k3/retrieval
opentrons-knowledge retrieval audit --bundle dist/opentrons-knowledge-10.0.0-k3/retrieval
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
