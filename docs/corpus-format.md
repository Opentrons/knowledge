# Corpus Format

## Layout

```text
dist/opentrons-knowledge-<version>/
  AGENTS.md                 # agent entrypoint (also in repo root)
  llms.txt                  # LLM/agent discovery file for this artifact
  docs/
    agent-usage.md          # full agent consumption guide
  manifest.yaml
  checksums.txt
  raw/
    README.md
    manifest.yaml
    <source_key>/          # verbatim monorepo paths for that pin
  corpus/
    documents.jsonl.zst
    sections.jsonl.zst
    code-symbols.jsonl.zst
    entities.jsonl.zst
    relationships.jsonl.zst
    examples.jsonl.zst
    constraints.jsonl.zst
    source-files.jsonl.zst
    protocol-designer/     # optional: evaluated Protocol Designer JSON (10.0.0-k5+)
  canonical/               # optional: only when the source manifest sets rendered_docs
    documents.jsonl.zst    # rendered-HTML canonical documents (see canonical-docs.md)
    manifest.json
  retrieval/               # optional: only when the source manifest sets retrieval
    manifest.json          # config, counts, sha256 per file, evaluation summary
    documents.jsonl.zst    # RetrievalDocument: what a search returns
    chunks.jsonl.zst       # Chunk: what the index matches
    queries.jsonl.zst      # evaluation queries with resolved retrieval ids
    api/bm25/              # API reference: exact symbol, then section text
    docs/bm25/             # passages: how-tos, manuals, labware, pipettes, modules
  schemas/
    *.schema.json
  reports/
    build-report.json
    source-report.json
    compatibility-report.json
    duplication-report.json
    retrieval-eval.json    # when retrieval.run_experiments is set
```

Logical separation is stable even if compression formats evolve:

- verbatim pinned sources under `raw/` (monorepo layout per manifest source key)
- canonical normalized data under `corpus/`
- optional rendered-docs canonical corpus under `canonical/`, with its own
  `schema_id`/`schema_version` (see [canonical-docs.md](canonical-docs.md))
- schemas under `schemas/`
- reports under `reports/`
- provenance in `manifest.yaml` + `checksums.txt`

- optional retrieval bundle under `retrieval/`, with its own `schema_id`/
  `schema_version` (see [retrieval-design.md](retrieval-design.md))

There is no embeddings file. From `10.0.0-k3` the bundle ships two BM25 indexes,
`retrieval/api/bm25/` and `retrieval/docs/bm25/`. A search hit returns every
chunk of the matched section. The indexes stay separate. A consumer can create
a fused search that returns documents from both indexes together, and would
probably do that after its own embedding and re-ranking. See
[retrieval-design.md](retrieval-design.md),
[retrieval-experiments.md](retrieval-experiments.md), and
[retrieval-tool.md](retrieval-tool.md). Tantivy names its segment
files randomly, so those directories are checked by opening them, not by byte
digest; every other retrieval file is byte-reproducible. Tantivy's
`.tantivy-*.lock` runtime files are excluded from `checksums.txt`.

## Published archives

The corpus directory is distributed in two equivalent channels:

```text
opentrons-knowledge-<version>.tar.zst
ghcr.io/opentrons/opentrons-knowledge:<version>
```

- **tar.zst**: `opentrons-knowledge pack` / `unpack` (GitHub Releases)
- **OCI**: `opentrons-knowledge publish` / `pull` via ORAS (GHCR)

Both carry the same on-disk layout after unpack/pull.

## Schema Version

```yaml
corpus_schema_version: 1
```

Increment only for incompatible record shape/meaning changes. Independent of
Opentrons release, knowledge revision, and builder version.

## Stable Identifiers

IDs are deterministic functions of stable inputs. No random UUIDs for canonical
records.

| Record | Pattern |
|--------|---------|
| Document | `doc:<repo-slug>:<commit12>:<path>` |
| Section | `section:<document_id>:<heading-path-slug>` |
| Symbol | `symbol:<qualified-name>:<release>` |
| Entity | `entity:<type>:<canonical-name>:<scope>` |
| Example | `example:<repo-slug>:<commit12>:<path>:<anchor>` |
| Relationship | `rel:<type>:<source_id>:<target_id>` |
| Constraint | `constraint:<type>:<subject_digest>` |

Long IDs may include a short hash suffix; readable keys remain on the record.

## Serialization Rules

- JSONL records sorted by primary ID
- UTF-8, LF newlines
- Compact JSON separators `(",", ":")` with sorted object keys where applicable
- zstd compression for corpus streams
- Content hashes: SHA-256 of normalized payload bytes

Canonical corpus files must be deterministic across machines for a given source
manifest and builder version.

## Manifest Fields (high level)

See `schemas/corpus-manifest.schema.json` and `models.manifest.CorpusManifest`.

Required concepts:

- corpus name / version / target release / schema version
- resolved source commits
- builder identity
- processing versions (parser, normalization, relationships, chunking)
- authority precedence
- checksum inventory
- optional future `variants` list (unused initially)

## Checksums

`checksums.txt` lists SHA-256 digests for every packaged file except itself,
sorted by path. Artifact verification recomputes and compares.
