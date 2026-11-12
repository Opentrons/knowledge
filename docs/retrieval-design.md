# Design: Shipping Chunks, Indexes, and Retrieval Experiments

Status: **accepted** for `10.0.0-k3` (BM25 only) and still what `10.0.0-k5` ships. Results and the reasoning
behind the shipped configuration are in
[retrieval-experiments.md](retrieval-experiments.md).

## Problem

Every consumer of the Opentrons Knowledge corpus was rebuilding retrieval for
itself, and nobody had measured which chunking and which index actually answer
Opentrons questions. A single BM25 index also mixes two jobs that interfere:
looking up `ProtocolContext.load_module` and answering "how do I load a module
on a Flex". In one index the shorter page that merely mentions the method
outranks the reference section.

Knowledge now ships, for each release:

1. The **retrievable documents**: the records a search returns and an agent cites.
2. **Chunks** derived from those documents.
3. **Two BM25 indexes**: `api/` for the Python API reference, `docs/` for
   everything else.
4. A **reproducible experiment report** for how the docs index is cut, and an
   audit that every documented symbol resolves to its own section.

## Decisions

| Question | Decision |
|----------|----------|
| Embeddings | None in `10.0.0-k3`. BM25 first, so the lexical baseline is measured before dense retrieval is added. |
| Two indexes | API reference sections (those with `api_name`) are their own index. Names are stored untokenized and matched before the prose, so `Class.method` returns that section. Narrative docs and shared-data entities stay in the docs index. A third index for labware was considered and not taken: load names are already rare tokens, and removing entities from the docs index costs 0.051 curated MRR. |
| Docs index | The configuration the decision rule selected: structured chunking, heading-path context plus identifier terms, Tantivy default tokenizer (lowercase, split on punctuation, no stemming). |
| API index | One chunk per symbol section. Query `symbol` first; search the section text only when the name matches nothing. |
| Evaluation set | 105 curated questions drafted in `eval/retrieval/curated.yaml`, awaiting docs-owner review, plus 240 structural queries generated from the records. The symbol audit covers every documented API name. |

## What changes and what does not

- `9.1.2-k3` removed `indexes/` and embeddings because they were unmeasured and
  partly fake (hash embeddings). `10.0.0-k3` brings two BM25 indexes back with
  an evaluation behind the docs chunking and an audit behind the API index.
  Published revisions are not rebuilt.
- `corpus/*.jsonl.zst`, `raw/`, and `canonical/` are unchanged and remain the
  source of truth. `retrieval/` is derived from them and can be regenerated
  with `opentrons-knowledge retrieval build`.
- This package searches a local bundle as two tools, `search_api` and
  `search_docs`. The CLI `--index both` shows both lists. A hit's text is
  every chunk of the matched section. There is no hosted search service.

## Retrievable documents

`RetrievalDocument` (`schemas/retrieval-document.schema.json`) is what a search
returns. Every `retrieval_id` comes from a source path, never a title, and the
build fails on any duplicate.

| Kind | Source | Count (10.0.0 pins) | `retrieval_id` | Where it is searched |
|------|--------|--------------------:|----------------|---------------------|
| `doc_section` | `canonical/` rendered HTML | 1728 | `doc:<page_path>#<anchor>` | `api/` when `api_name` is set (325 sections); otherwise `docs/` |
| `entity` | `corpus/entities` (shared-data) | 188 | `labware:<load_name>`, `pipette:<channels>/<volume>/v<major>`, `module:<model>` | `docs/` |
| `api_symbol` | `corpus/code-symbols` | 358 | `symbol:<qualified_name>` | no: measured, slightly worse |
| `guide_section` | AI v1 guides | 401 | `guide:<source_path>#<anchor>` | no: measured, worse |

Construction rules, each chosen to remove a duplicate or noise source found in
the legacy records:

- **Doc sections**: skip pages with `search.exclude` and sections with no
  content (their titles live in their children's heading paths).
- **Entities**: labware keeps the newest definition per load name (the legacy
  corpus has one record per definition version, all sharing one id); pipettes
  collapse model revisions per channel count, volume, and major version; modules
  keep the newest schema per model. Schema files, decks, robots, and schema-1
  legacy labware are skipped because a protocol does not load them by name.
- **API symbols**: user-facing only (documented, no `_private` or `.core.`
  path parts). Property getters and setters share a qualified name and merge
  into one record. The public name (`opentrons.protocol_api.InstrumentContext.aspirate`)
  is derived from the module path so labels match the reference pages.
- **Guide sections**: repeated headings get `-2`, `-3` suffixes in document
  order.
- **Examples** are not a kind: every example's code already appears in a doc
  section, so indexing both would double-count the same text.

## Experiments

See [retrieval-experiments.md](retrieval-experiments.md) for the grid, the
pre-registered decision rule, results, ablations with confidence intervals, and
failure analysis.

Summary of the grid (51 configurations, about 12 seconds end to end):

- Composition: docs; docs plus entities; plus API symbols; plus AI guides.
- Chunking: `section` (one chunk per document), `structured` (tabs split out,
  block-boundary packing up to 400 words), `window` (200-word windows over a
  page, stride 160), `small` (80-word pieces mapped back to their parent).
- Enrichment: `plain`, `context` (heading path and tab label prefixed),
  `context_terms` (plus split camelCase identifiers and aliases as searchable,
  non-displayed terms).
- Tokenizer: `default` (lowercase, split on punctuation, no stemming) and
  `en_stem` (measured; it did not win, so it is not shipped).

## Artifact layout (`10.0.0-k3`)

```text
retrieval/
  manifest.json              # config, counts, sha256 per file, eval summary
  documents.jsonl.zst        # RetrievalDocument (shipped kinds only)
  chunks.jsonl.zst           # Chunk records for both indexes
  queries.jsonl.zst          # evaluation queries with resolved retrieval ids
  api/bm25/                  # symbol field (raw) + section text
  docs/bm25/                 # passage text; identifier terms are a second value
reports/
  retrieval-eval.json        # full grid results, ablations, winner misses
```

Identifier terms are a second value of the `text` field: they match, and they
are not part of the passage a result shows. A section may be stored as several
chunks (one per tab, or a long section split at a block boundary). A search hit
returns every chunk of that section, in order, so the passage includes the
content under the heading rather than only the piece that matched. The API
index adds a `symbol` field that keeps each public name as one token
(`ProtocolContext.load_module` does not split into `load` and `module`). Each
API section is already one chunk. Schema version is 2, because the bundle no
longer has a single index.

## Determinism

Every JSON and JSONL file in `retrieval/` is byte-reproducible (the fixture test
builds twice and compares digests). Tantivy names segment files with random ids,
so `api/bm25/` and `docs/bm25/` are verified functionally instead: one writer
thread and one commit give one segment; validation opens each index, checks the
document count against the chunk partition, and runs a query taken from its own
records. Tantivy creates `.tantivy-*.lock` files whenever an index is opened;
those are runtime state and are excluded from corpus checksums and archives.

## Consumer impact

- Register two tools. `search_api` reads `retrieval/api/bm25/`. `search_docs`
  reads `retrieval/docs/bm25/`. Query shapes are in [retrieval-tool.md](retrieval-tool.md).
  A consumer can create a fused search that returns documents from both indexes
  together, and would probably do that after its own embedding and re-ranking.
- Adding dense retrieval later means a vector file aligned to `chunks.jsonl.zst`,
  measured on the same questions before it ships.
- Chunk and retrieval ids are unique by construction.
- The legacy `corpus/entities`, `corpus/code-symbols`, and `corpus/sections`
  records still contain duplicate ids (465 entity records with 261 ids, 1658
  symbols with 1615 ids, 1470 sections with 1372 ids). Fixing them in place is a
  schema change and is tracked separately; the retrieval layer does not depend
  on those ids being unique.

## Remaining open decisions

1. Who on the docs team reviews and owns `eval/retrieval/curated.yaml`.
2. Which dense model to evaluate next, against the same evaluation set.

## Workstreams

1. Done: RetrievalDocument model and builders for each kind.
2. Done (draft): evaluation set, structural generator, curated file. Review pending.
3. Done: chunkers `section`, `structured`, `window`, `small`.
4. Done: two BM25 indexes. Dense indexes deferred.
5. Done: experiment runner, metrics, report, and `retrieval-experiments.md`.
6. Done: packaging and validation for `retrieval/`, the `10.0.0-k3` manifest, and
   release notes.
