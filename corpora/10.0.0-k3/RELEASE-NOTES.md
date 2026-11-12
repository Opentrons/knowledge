# Opentrons Knowledge 10.0.0-k3

Target Opentrons release: **v10.0.0**

## Source pins (unchanged vs 10.0.0-k2)

| Source | Pin |
|--------|-----|
| Protocol API + shared-data | `v10.0.0` @ `e8c6d0a424c25fff1604e2a02e4ccaedac95b9af` |
| Official docs | `mkdocs-2026-09-30` @ `00f1431babdf36a11ec68143c009d5fc889b2478` |
| Opentrons AI v1 guides | `ai-server@0.0.22` @ `0b6a6ecd2d6e040e02f40bd1d44193cfc42b33dc` (`pd/` excluded) |

## What changed in k3

Same pinned sources as **10.0.0-k2**. Two additions, both derived from the
pinned sources and both optional for consumers:

### Added: `canonical/` rendered documentation

The pinned docs commit is rendered with MkDocs, the same way the docs deploy
workflow does it, and extracted into 276 structured documents with 1809
sections. These include tabs, admonitions, macro-generated tables, and the API
reference pages that the Markdown sources alone miss. See
`docs/canonical-docs.md` in the Knowledge repository.

### Added: `retrieval/` documents, chunks, and two BM25 indexes

This reverses the `9.1.2-k3` "no shipped indexes" policy, now that an
evaluation stands behind the index.

- `retrieval/documents.jsonl.zst`: 1916 searchable documents (1728 doc sections
  and 188 labware, pipette, and module entities). Every `retrieval_id` is derived
  from a source path and is unique.
- `retrieval/chunks.jsonl.zst`: 2063 chunks. Each of the 325 API symbols is one
  chunk; the other documents use structured chunking with heading-path context
  and identifier terms.
- `retrieval/api/bm25/`: the Python API reference. Each public name is an exact
  token, so `Class.method` returns that section. 325 symbols.
- `retrieval/docs/bm25/`: how-to and manual passages, plus labware, pipette, and
  module records.
- No embeddings are shipped.
- `retrieval/queries.jsonl.zst`: the 345 evaluation queries with resolved
  retrieval ids, so consumers can measure their own stacks on the same set.
- `reports/retrieval-eval.json`: the full 51-configuration experiment.

Compared with one chunk per section and no context, the docs index improves
curated MRR@10 from 0.501 to 0.601 and structural Hit@10 from 0.533 to 0.975.
That comparison is what selected the docs chunking. Symbol sections then move
to the API index, where all 325 documented names return their own section at
rank 1 (`retrieval audit`). The two indexes stay separate. A consumer can
create a fused search that returns documents from both indexes together, and
would probably do that after its own embedding and re-ranking.
The curated questions are a draft awaiting docs-owner review. See
`docs/retrieval-experiments.md`.

### Unchanged

- `corpus/*.jsonl.zst` record shapes and `corpus_schema_version: 1`
- `raw/` verbatim sources

### Known issues carried from k2

`corpus/entities`, `corpus/code-symbols`, and `corpus/sections` still contain
duplicate ids (one entity record per labware definition version, property getter
and setter pairs, repeated AI guide headings). `retrieval/` does not depend on
those ids. Fixing them in place needs a schema version bump.

## Build

```bash
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k3/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist
uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k3
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k3
```

Git tag for release: `knowledge-v10.0.0-k3`
