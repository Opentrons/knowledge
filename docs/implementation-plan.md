# Implementation Plan

Status: the current corpus is **`10.0.0-k5`** (tar.zst + OCI/ORAS). `10.0.0-k3`
added rendered docs (`canonical/`) and a retrieval bundle (`retrieval/`:
documents, chunks, `api/bm25/`, `docs/bm25/`) on the same source pins as
`10.0.0-k2`. `10.0.0-k4` added the Protocol Designer allowlist as a raw file.
`10.0.0-k5` copies the rest of those compatibility sources and publishes them
as evaluated JSON under `corpus/protocol-designer/`. Retrieval is unchanged.
The initial `9.1.1-k1` product (normalized `corpus/` only) is still the base
the later revisions build on.

On `10.0.0-k3`: 276 canonical documents, 1809 canonical sections, 1916
retrieval documents, 2063 chunks, 325 API symbols. No embeddings. Search of a
local bundle (including the merge of the two indexes) lives in this package;
nothing is hosted.

## Phase 1: Repository analysis (done)

## Phase 2: Manifest and models (done)

## Phase 3: Documentation ingestion (done)

## Phase 4: Protocol API extraction (done)

## Phase 5: Shared-data extraction (done)

## Phase 6: Corpus assembly (done)

## Phase 7: Packaging (done)

Publication formats are `opentrons-knowledge-<version>.tar.zst` (GitHub Releases)
and `ghcr.io/opentrons/opentrons-knowledge:<version>` (ORAS/OCI).
The on-disk layout is the interface. From `10.0.0-k3` it includes `canonical/`
and `retrieval/` (two BM25 indexes). No embeddings. The package searches a
local bundle (`search_api`, `search_docs`); it does not host
a query service. The docs chunking is the one measured in
[retrieval-experiments.md](retrieval-experiments.md).

## Phase 8: CI and release automation (done)

## Tradeoffs

- Docs pin uses `mkdocs-*` rather than the robot-software tag (documented in
  [source-analysis.md](source-analysis.md)).
- AI v1 guides are monorepo paths pinned to an `ai-server@*` tag; `pd/` is excluded.
- A full corpus build expects a local Opentrons checkout or a network clone.
  The current manifest is `corpora/10.0.0-k5/source-manifest.yaml`.
- CI builds the highest corpus version under `corpora/` and runs tests against that build.
