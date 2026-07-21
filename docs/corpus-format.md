# Corpus Format

## Layout

```text
dist/opentrons-knowledge-<version>/
  AGENTS.md                 # agent entrypoint (also in repo root)
  llms.txt                  # LLM/agent discovery index for this artifact
  docs/
    agent-usage.md          # full agent consumption guide
  manifest.yaml
  checksums.txt
  corpus/
    documents.jsonl.zst
    sections.jsonl.zst
    code-symbols.jsonl.zst
    entities.jsonl.zst
    relationships.jsonl.zst
    examples.jsonl.zst
    constraints.jsonl.zst
    source-files.jsonl.zst
  indexes/
    lexical/
      symbols.json
      entities.json
      terms.json
    vector/
      embeddings.jsonl.zst   # optional
      meta.yaml
  schemas/
    *.schema.json
  reports/
    build-report.json
    source-report.json
    compatibility-report.json
    duplication-report.json
    indexing-report.json
```

Logical separation is stable even if compression or index formats evolve:

- canonical normalized data under `corpus/`
- derived indexes under `indexes/`
- schemas under `schemas/`
- reports under `reports/`
- provenance in `manifest.yaml` + `checksums.txt`

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

Canonical corpus files must be deterministic across machines when embeddings are
disabled or use a deterministic fake provider. External embedding APIs may make
vector indexes non-byte-identical; that limitation is recorded in reports.

## Manifest Fields (high level)

See `schemas/corpus-manifest.schema.json` and `models.manifest.CorpusManifest`.

Required concepts:

- corpus name / version / target release / schema version
- resolved source commits
- builder identity
- processing versions
- embedding configuration (or `enabled: false`)
- authority precedence
- checksum inventory
- optional future `variants` list (unused initially)

## Checksums

`checksums.txt` lists SHA-256 digests for every packaged file except itself,
sorted by path. Artifact verification recomputes and compares.
