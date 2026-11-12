# Agent Guide: Using an Opentrons Knowledge Corpus

This document tells agents and agent authors how to consume an Opentrons
Knowledge Corpus. The corpus is a **versioned data package** of pinned Opentrons
source material (docs, Protocol API, shared-data, curated AI guides, and
from `10.0.0-k5` Protocol Designer compatibility tables). From `10.0.0-k3` it
also ships rendered docs (`canonical/`) and two BM25 indexes (`retrieval/`).
No embeddings ship, and there is no hosted search service. The current corpus
is `10.0.0-k5`.

Canonical copies:

- Repository: `docs/agent-usage.md`
- Repo entrypoint: `AGENTS.md`
- Inside every corpus: `AGENTS.md` and `docs/agent-usage.md`

## What this artifact is

An immutable, versioned, source-linked compilation of:

- Official MkDocs documentation
- Protocol API source symbols (AST-extracted)
- Shared-data definitions (labware, pipettes, modules, decks, robots, …)
- Curated Opentrons AI v1 protocol guides (`pd/` excluded)

Distribution formats:

```text
opentrons-knowledge-10.0.0-k5.tar.zst
ghcr.io/opentrons/opentrons-knowledge:10.0.0-k5
```

A current artifact has four layers for the same pins:

- **`raw/`**: verbatim source files (monorepo paths under each manifest source key).
  `raw/protocol_designer/` is the Protocol Designer compatibility sources.
- **`corpus/`**: normalized JSONL records (sections, symbols, entities, …).
  `corpus/protocol-designer/*.json` (from `10.0.0-k5`) is the same compatibility,
  evaluated. It is not turned into entities or search chunks.
- **`canonical/`**: the pinned MkDocs site, rendered and extracted (from `10.0.0-k3`)
- **`retrieval/`**: documents, chunks, and two BM25 indexes (from `10.0.0-k3`)

`10.0.0-k2` has `raw/` and `corpus/`, and no `canonical/` or `retrieval/`.
Earlier revisions are described in their own `corpora/<version>/RELEASE-NOTES.md`.

## How to obtain and open

```bash
# From a local build
opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k5

# Unpack a GitHub Release / local archive
opentrons-knowledge unpack dist/opentrons-knowledge-10.0.0-k5.tar.zst --output dist

# Or pull from GHCR (requires oras on PATH)
opentrons-knowledge pull 10.0.0-k5 --output dist

opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k5
```

Pin the corpus version to the Opentrons software release you target.

## On-disk layout (the interface)

```text
manifest.yaml
AGENTS.md
llms.txt
docs/agent-usage.md
checksums.txt
raw/
  README.md
  manifest.yaml
  <source_key>/...
corpus/
  documents.jsonl.zst
  sections.jsonl.zst
  code-symbols.jsonl.zst
  entities.jsonl.zst
  relationships.jsonl.zst
  examples.jsonl.zst
  constraints.jsonl.zst
  source-files.jsonl.zst
  protocol-designer/  # from 10.0.0-k5: evaluated compatibility JSON, not records
canonical/            # optional; rendered MkDocs HTML as structured documents
  documents.jsonl.zst
  manifest.json
retrieval/            # optional (10.0.0-k3+); documents, chunks, two BM25 indexes
  documents.jsonl.zst
  chunks.jsonl.zst
  queries.jsonl.zst
  manifest.json
  api/bm25/           # Python API reference (exact symbol, then section text)
  docs/bm25/          # how-tos, manuals, labware, pipettes, modules
schemas/
reports/
```

Records are deterministic JSONL (zstd), sorted by primary id.

## What to read for which question

| Question type | Start with |
|---------------|------------|
| Verbatim source file at a pin | `raw/<source_key>/...` or `raw/manifest.yaml` |
| API method / class behavior | `corpus/code-symbols.jsonl.zst` |
| Labware / pipette / module identity | `corpus/entities.jsonl.zst` (+ `raw_source`) |
| How-to / narrative | `corpus/sections.jsonl.zst` / `documents.jsonl.zst` |
| Docs exactly as rendered (tabs, admonitions, macro tables, API reference) | `canonical/documents.jsonl.zst` when present |
| Restrictions / version gates | `corpus/constraints.jsonl.zst` |
| Provenance / pins | `manifest.yaml`, `sources` in reports |
| Python API symbol, signature, parameters | `retrieval/api/bm25/` (exact name, then section text) |
| Procedure, hardware, labware, module | `retrieval/docs/bm25/` (BM25). Resolve hits through `retrieval/documents.jsonl.zst` |

When `retrieval/` is present, register two search tools. The descriptions to
copy into the tool registry are in [retrieval-tool.md](retrieval-tool.md).

| Tool | Index | What a hit is | Query |
|---|---|---|---|
| `search_api` | `retrieval/api/bm25/` | One documented symbol: signature, parameters, returns, version notes. | `Class.method`, for example `InstrumentContext.blow_out`. Not a sentence. |
| `search_docs` | `retrieval/docs/bm25/` | One how-to section, or one labware, pipette, or module record. The page intro and each heading are separate hits. | The words a heading or a load name would use. Not a sentence. |

Call the two tools separately. A score belongs to the index that produced it.
Do not register a tool that merges the lists. Cite `url` and `source_url` from
`retrieval/documents.jsonl.zst`. A hit's `text` is the whole section (every
chunk of it, in order). Every `retrieval_id` is unique and derived from a
source path. No embeddings ship. Search runs against the local bundle; this
repo does not host a query service.

A consumer can create a fused search that returns documents from both indexes
together, and would probably do that after its own embedding and re-ranking.

## Authority precedence (required)

When sources disagree, prefer higher authority. Do not silently drop conflicts.

1. `normative`: Protocol API source + shared-data
2. `official_guidance`: official MkDocs docs
3. `generated`: generated API reference material
4. `curated_guidance`: Opentrons AI v1 guides
5. `example`: code examples
6. `historical` / `deprecated`

Rules of thumb:

- Signatures and version gates: trust symbols / source
- Load names and definition fields: trust entities (+ `raw_source`)
- Procedure narrative: documentation sections
- AI guides and examples: patterns only; never override normative data

## Provenance and citations

Cite:

- `source_url` (commit-pinned GitHub blob, often with line range)
- `rendered_url` when present
- corpus version from `manifest.yaml`
- content hash when asserting exact text

## Recommended workflow

1. Confirm corpus version matches the target Opentrons release.
2. Classify the question (symbol / entity / procedure / constraint).
3. When `retrieval/` is present, call `search_api`, `search_docs`, or both
   as separate calls. Otherwise read the relevant JSONL.
4. Apply authority precedence.
5. Cite `source_url` and corpus version.
6. If evidence is missing or conflicting, say so.

## What not to do

- Do not scrape docs.opentrons.com when the corpus covers the topic.
- Do not assume AI guide text is release-exact without checking symbols/entities.
- Do not expect a hosted search service. Search the local `retrieval/` bundle
  with the CLI or `opentrons_knowledge.retrieval` (`search_api`, `search_docs`).
- Do not mix corpus versions in one session unless doing an explicit diff/migration.
