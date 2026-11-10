# Opentrons Knowledge

Immutable, reproducible, versioned **Opentrons Knowledge Corpus** artifacts for
specific Opentrons software releases.

The product is the **corpus artifact** (a directory, shipped as `.tar.zst` and
as OCI on GHCR). Current corpus: **`10.0.0-k3`**, for Opentrons `v10.0.0`.

```text
opentrons-knowledge-10.0.0-k3.tar.zst
ghcr.io/opentrons/opentrons-knowledge:10.0.0-k3
```

`10.0.0-k3` contains:

- `raw/`: the pinned source trees, verbatim
- `corpus/`: normalized records (documents, sections, symbols, entities, …)
- `canonical/`: the pinned MkDocs site, rendered and extracted (sections, tabs,
  admonitions, tables, API reference)
- `retrieval/`: searchable documents and chunks, plus two BM25 indexes.
  `retrieval/api/bm25/` is the Python API reference. `retrieval/docs/bm25/` is
  everything else (how-tos, manuals, labware, pipettes, modules)
- `reports/retrieval-eval.json`: the experiment that chose the docs chunking

No embeddings ship. A search hit returns the whole section under the heading
that matched, including tabs and the rest of a long section. Searching both
indexes together (`--index all`, or the `search_all` tool) merges the two
rankings at query time. That merge is not a third index and needs no model.
See [docs/retrieval-tool.md](docs/retrieval-tool.md).

## Quick start

```bash
just sync
just ci            # lint, typecheck, test, fixture corpus
```

### Build the current corpus

Requires a local clone of [Opentrons/opentrons](https://github.com/Opentrons/opentrons)
with the tags pinned in `corpora/10.0.0-k3/source-manifest.yaml`
(`v10.0.0`, `mkdocs-2026-09-30`, `ai-server@0.0.22`).

```bash
just build-10-0-0-k3
# or:
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k3/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist

uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k3
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k3
```

That writes `dist/opentrons-knowledge-10.0.0-k3.tar.zst`.

Earlier manifests (`9.0.0-k1` through `10.0.0-k2`) build the same way. Each
`corpora/<version>/RELEASE-NOTES.md` says what that revision contains.
`10.0.0-k1` and `10.0.0-k2` use the same source pins as k3 and omit `canonical/`
and `retrieval/`.

OCI publish (requires [`oras`](https://oras.land/docs/installation) on PATH and
registry auth):

```bash
uv run opentrons-knowledge publish \
  --corpus dist/opentrons-knowledge-10.0.0-k3 \
  --registry ghcr.io/opentrons/opentrons-knowledge
```

### Consume a corpus

```bash
uv run opentrons-knowledge unpack dist/opentrons-knowledge-10.0.0-k3.tar.zst --output dist
uv run opentrons-knowledge inspect --corpus dist/opentrons-knowledge-10.0.0-k3

# From GHCR (requires oras):
uv run opentrons-knowledge pull 10.0.0-k3 --output dist
```

Agents: start at [AGENTS.md](AGENTS.md) and [docs/agent-usage.md](docs/agent-usage.md).
Those guides are copied into every packed corpus.

### Search the retrieval bundle

```bash
just retrieval-validate
just retrieval-search "InstrumentContext.blow_out" api
just retrieval-search "heater shaker latch" docs
just retrieval-search "blow out extra air" all    # one list from both indexes
just retrieval-explore                             # try queries interactively
just retrieval-audit                               # every documented symbol, rank 1
just retrieval-experiment                          # re-run the chunking grid
```

See [docs/retrieval-design.md](docs/retrieval-design.md),
[docs/retrieval-experiments.md](docs/retrieval-experiments.md), and
[docs/retrieval-tool.md](docs/retrieval-tool.md).

### Canonical docs alone

```bash
just docs-build       # dist/canonical-docs/{documents.jsonl.zst,manifest.json}
just docs-validate
just test-integration # slow; real MkDocs build and HTML fidelity checks
```

See [docs/canonical-docs.md](docs/canonical-docs.md).

## Documentation

**Agents start here:** [AGENTS.md](AGENTS.md) · [docs/agent-usage.md](docs/agent-usage.md) · [llms.txt](llms.txt)

- [Product architecture](docs/product-architecture.md)
- [Corpus format](docs/corpus-format.md)
- [Canonical docs](docs/canonical-docs.md)
- [Retrieval design](docs/retrieval-design.md) · [Retrieval experiments](docs/retrieval-experiments.md) · [Search tools](docs/retrieval-tool.md)
- [Source analysis](docs/source-analysis.md) (the `9.1.1-k1` pin study; current pins are in `corpora/10.0.0-k3/`)
- [Versioning](docs/versioning.md)
- [Release process](docs/release-process.md)
- [Implementation plan](docs/implementation-plan.md)

## CLI

```bash
opentrons-knowledge build --manifest corpora/10.0.0-k3/source-manifest.yaml --opentrons-repo ../opentrons
opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k3
opentrons-knowledge inspect --corpus dist/opentrons-knowledge-10.0.0-k3
opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k3
opentrons-knowledge unpack dist/opentrons-knowledge-10.0.0-k3.tar.zst
opentrons-knowledge publish --corpus dist/opentrons-knowledge-10.0.0-k3
opentrons-knowledge pull 10.0.0-k3
opentrons-knowledge verify --corpus dist/opentrons-knowledge-10.0.0-k3
opentrons-knowledge sources --corpus dist/opentrons-knowledge-10.0.0-k3
opentrons-knowledge diff 10.0.0-k2 10.0.0-k3 --json
opentrons-knowledge docs build --manifest corpora/10.0.0-k3/source-manifest.yaml --opentrons-repo ../opentrons
opentrons-knowledge docs validate --corpus dist/canonical-docs
opentrons-knowledge retrieval validate --bundle dist/opentrons-knowledge-10.0.0-k3/retrieval
opentrons-knowledge retrieval search "InstrumentContext.blow_out" --bundle dist/opentrons-knowledge-10.0.0-k3/retrieval --index api
opentrons-knowledge retrieval search "heater shaker latch" --bundle dist/opentrons-knowledge-10.0.0-k3/retrieval --index docs
opentrons-knowledge retrieval search "blow out extra air" --bundle dist/opentrons-knowledge-10.0.0-k3/retrieval --index all
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
`.github/**` changes. Releases publish the `.tar.zst` GitHub Release asset and
the OCI artifact on GHCR.

## License

Copyright 2026 Opentrons Labworks, Inc.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).
