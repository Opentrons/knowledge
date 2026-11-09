# Product Architecture

## Product

**Opentrons Knowledge** produces immutable, reproducible, versioned knowledge
corpus artifacts for specific Opentrons software releases.

The primary product is the **corpus artifact**, not a search service, agent,
MCP server, or lookup SDK. The same corpus directory is published as both a
`.tar.zst` archive and an OCI artifact.

Human-readable identity:

```text
opentrons-knowledge:9.1.1-k1
```

Published locations:

```text
opentrons-knowledge-9.1.1-k1.tar.zst
ghcr.io/opentrons/opentrons-knowledge:9.1.1-k1
ghcr.io/opentrons/opentrons-knowledge@sha256:<digest>
```

Immutable identity:

```text
sha256:<digest of the packed corpus / OCI manifest>
```

## Separation of Concerns

| Layer | Responsibility |
|-------|----------------|
| Source material | Pinned git trees and optional curated files |
| Normalized knowledge | Provider-neutral documents, sections, symbols, entities, relationships, constraints, examples |
| Build metadata | Builder version, OS, Python, lock digest, timestamps |
| Compatibility metadata | Explicit source-to-release relationships |
| Artifact identity | Directory checksums + `.tar.zst` digest + OCI digest |

Canonical corpus records must remain usable without any particular LLM provider,
vector database, agent framework, or runtime service. **Embeddings and query-time
ranking are out of scope** for this repository. A BM25 index is in scope from
`10.0.0-k3` because an evaluation shows which index to build
([retrieval-design.md](retrieval-design.md),
[retrieval-experiments.md](retrieval-experiments.md)); it is derived from the
corpus records and never replaces them.

## Package Layout

```text
src/opentrons_knowledge/
  builder/          # orchestration pipeline
  sources/          # clone/resolve/materialize pinned trees
  docs/             # Markdown / MkDocs ingestion; pinned MkDocs render + HTML extraction
  python_api/       # AST symbol extraction
  shared_data/      # definition parsing + entity normalization
  models/           # Pydantic canonical models + manifests
  normalization/    # IDs, hashing, deterministic JSONL
  relationships/    # relationship + constraint extraction
  retrieval/        # retrieval documents, chunkers, BM25 index, evaluation, bundle
  compatibility/    # compatibility validation
  artifacts/        # packaging, checksums, reports, tar.zst
  registry/         # ORAS publish/pull for OCI
  consumer/         # thin open/verify/inspect helpers
  cli/              # opentrons-knowledge CLI
```

## Pipeline Stages

1. Read and validate source manifest
2. Locate or clone repositories
3. Resolve tags to immutable commits
4. Verify source integrity
5. Materialize configured paths (prefer `git archive` / local checkout)
6. Parse authored documentation
7. Expand API-reference stubs from Protocol API symbols
8. Parse Protocol API with AST
9. Parse shared-data definitions
10. Normalize sections, symbols, entities, examples
11. Build relationships and constraints
12. Detect duplicates and conflicts
13. Write canonical corpus files (sorted, stable IDs)
    - optional, when `rendered_docs` is set: render the pinned MkDocs site in an
      isolated checkout and write `canonical/` from the HTML
      ([canonical-docs.md](canonical-docs.md))
    - optional, when `retrieval` is set: build `retrieval/` from `canonical/`
      and the entity records, evaluate it, and write `reports/retrieval-eval.json`
14. Write reports and checksums
15. Pack as `opentrons-knowledge-<version>.tar.zst`
16. Optionally publish OCI via ORAS to GHCR

## Authority Precedence

Recorded in corpus metadata:

1. Exact-release source code and machine-readable shared data (`normative`)
2. Official documentation for the documented release (`official_guidance`)
3. Generated API reference for the exact release (`generated` / normative symbols)
4. Validated curated Opentrons AI guidance (`curated_guidance`)
5. Examples (`example`)
6. Historical or deprecated content (`historical` / `deprecated`)

Conflicts are never silently deleted.

## Consumer Boundary

This package **builds, packs, and publishes** corpora. It does not provide a
search service, embeddings, or `get_symbol`-style lookup APIs. Downstream
systems unpack/pull the artifact and either search `retrieval/api/` and
`retrieval/docs/` or read `corpus/` and `canonical/` with their own stack.

Agent-facing usage instructions ship in the repository and inside every corpus
as `AGENTS.md`, `llms.txt`, and `docs/agent-usage.md`.

## Non-Goals (initial product)

- Lookup / query SDK
- Vector indexes in the artifact (BM25 ships from `10.0.0-k3`; dense retrieval
  needs its own evaluation first)
- Embeddings or re-ranking
- Full agent framework
- Production search SaaS
- Multiple artifact variants unless size forces them
- Coupling canonical models to one embedding vendor
