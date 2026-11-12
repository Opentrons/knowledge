# Opentrons Knowledge

Immutable, reproducible, versioned **Opentrons Knowledge Corpus** artifacts for
specific Opentrons software releases.

The product is the **corpus artifact** (a directory, shipped as `.tar.zst` and
as OCI on GHCR). Current corpus: **`10.0.0-k5`**, for Opentrons `v10.0.0`.

```text
opentrons-knowledge-10.0.0-k5.tar.zst
ghcr.io/opentrons/opentrons-knowledge:10.0.0-k5
```

`10.0.0-k5` contains:

- `raw/`: the pinned source trees, verbatim: `opentrons_docs/`, `protocol_api/`,
  `shared_data/` (labware, pipette, module, deck, and robot definitions with
  their schemas), `opentrons_ai_v1/`, and `protocol_designer/`. `raw/protocol_designer/`
  holds the Protocol Designer compatibility sources, pinned to the latest
  production Protocol Designer tag (`protocol-designer@9.0.1`, not `v10.0.0`).
  They are copied, not parsed.
- `corpus/protocol-designer/`: those same tables evaluated to JSON (labware
  allowlists, module and adapter compatibility, slots, limits, pipette options)
- `corpus/`: normalized records (documents, sections, symbols, and entities).
  Entities come from `shared_data/`: labware, pipettes, modules, decks, and robots.
- `canonical/`: the pinned MkDocs site, rendered and extracted (sections, tabs,
  admonitions, tables, API reference)
- `retrieval/`: searchable documents and chunks, plus two BM25 indexes.
  `retrieval/api/bm25/` is the Python API reference. `retrieval/docs/bm25/` is
  everything else (how-tos, manuals, labware, pipettes, modules)
- `reports/retrieval-eval.json`: the experiment that chose the docs chunking

No embeddings ship. A search hit returns the whole section under the heading
that matched, including tabs and the rest of a long section.

## Agent tools

Register two tools against the local `retrieval/` bundle. Copy each block
below into the tool registry. The `description` is the verbatim text the
agent should see. The same text is in
[docs/retrieval-tool.md](docs/retrieval-tool.md), which is copied into every
packed corpus.

```text
name: search_api
description: |
  Search the Python Protocol API reference for this corpus version.
  Data: retrieval/api/bm25/. One section per documented symbol (a class, a
  method, or a property). A hit is that section: signature, parameters,
  returns, and version notes. Join the hit to retrieval/documents.jsonl.zst
  on retrieval_id for url, source_url, api_name, and heading_path. The score
  is BM25 from this index only.
  Not in this index: how-to pages, manuals, labware, pipettes, and modules.
  Those are search_docs.
  Pass one symbol, not a sentence.
  If you know the method but not the class, pass the method name alone:
  aspirate, load_module, set_temperature. Every class that defines it comes
  back, and api_name on the hit is Class.method. Call again with that
  Class.method (InstrumentContext.aspirate) when you need one class.
  If you already know both, pass Class.method directly
  (InstrumentContext.blow_out, ProtocolContext.load_module).
  If you need the class overview, pass the class name as one token. Classes
  in this corpus: ProtocolContext, InstrumentContext, Labware, Well,
  RobotContext, HeaterShakerContext, TemperatureModuleContext,
  ThermocyclerContext, MagneticModuleContext, MagneticBlockContext,
  AbsorbanceReaderContext, FlexStackerContext, TrashBin, WasteChute, Liquid,
  LiquidClass, Task, Location. Also present: OFF_DECK, OffDeckType,
  StringAxisMap, GroupedSteps.
  A phrase with a space, such as "heater shaker" or "blow out", does not
  match a symbol. It searches section text and can rank methods above the
  class intro.
  Do not prefix opentrons.protocol_api. Do not ask "how do I".
  Read text. Cite url and the corpus version.
parameters:
  query: string, required. One symbol: a method name, Class.method, or a class name.
```

```text
name: search_docs
description: |
  Search Opentrons how-to docs and the labware, pipette, and module records
  for this corpus version.
  Data: retrieval/docs/bm25/. One section per heading, plus one record per
  labware, pipette, and module. The page intro is its own hit
  (doc:<page>/). Each heading under it is a separate hit
  (doc:<page>#<anchor>). A hit's text is that section. Join the hit to
  retrieval/documents.jsonl.zst on retrieval_id for url, source_url,
  heading_path, and load_name. The score is BM25 from this index only.
  Do not compare it with a search_api score.
  Not in this index: per-symbol API reference sections. Those are search_api.
  Query with the words a heading or a load name would use, not a sentence.
  Drop "how do I", "what is", and "please". The index does not stem, so
  "loading" and "load" are different words. Use the docs' own words:
  "load a pipette", "partial tip pickup", "heater shaker latch".
  For labware, pass the load name (opentrons_96_tiprack_300ul) or the
  product name (NEST 12 well reservoir).
  A child section can outrank its page intro when the query words appear
  more often in the child. "load heater shaker" ranks Loading labware above
  the Heater-Shaker Module intro. Read the heading path.
  One question per call. Cite url and the corpus version.
parameters:
  query: string, required. A few words from the heading or the load name.
```

Call the two tools separately. A BM25 score from one index is not comparable
with a score from the other. Do not register a merged tool.

## Further enhancement

This package stops at lexical search. The two BM25 indexes are the search
this repository builds and evaluates. A consumer that wants semantic search
adds it beside those indexes.

Embed the passages in `retrieval/documents.jsonl.zst` and
`retrieval/chunks.jsonl.zst`. Those files are the sections the lexical search
already returns, and each row has a `retrieval_id`. Store the vectors in a
new index keyed by that same id. Leave `retrieval/api/bm25/` and
`retrieval/docs/bm25/` as they are. The raw files under `raw/` and `corpus/`
are the source those passages were built from. Embed the passages.

A separate search then queries the lexical indexes and the vector index, and
reranks the candidates with a cross-encoder or an LLM. A single list that
mixes documents from both indexes comes after that reranking.

The docs index includes every Opentrons doc on purpose, so an agent can
answer a question about any of them. A reranker has to use that scope. When
the task is building or editing a Python protocol, drop Quick Transfer hits
and Protocol Designer hits. Quick Transfer is a feature of the Flex
touchscreen. Protocol Designer is a separate way to author a protocol. When
the question is about Quick Transfer or Protocol Designer, keep those hits.

## Quick start

```bash
just sync
just ci            # lint, typecheck, test, fixture corpus
```

### Build the current corpus

Requires a local clone of [Opentrons/opentrons](https://github.com/Opentrons/opentrons)
with the tags pinned in `corpora/10.0.0-k5/source-manifest.yaml`
(`v10.0.0`, `mkdocs-2026-09-30`, `ai-server@0.0.22`, `protocol-designer@9.0.1`).
Evaluating the Protocol Designer tables needs Node.js >= 24.22.1, the version
on Opentrons `edge`.

```bash
just build-10-0-0-k5
# or:
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k5/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist

uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k5
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k5
```

That writes `dist/opentrons-knowledge-10.0.0-k5.tar.zst`.

Earlier manifests (`9.0.0-k1` through `10.0.0-k4`) build the same way. Each
`corpora/<version>/RELEASE-NOTES.md` says what that revision contains.
`10.0.0-k1` and `10.0.0-k2` use the same source pins as k3 and omit `canonical/`
and `retrieval/`. `10.0.0-k4` adds the Protocol Designer allowlist as one raw
file. `10.0.0-k5` adds the rest of those raw sources and the evaluated JSON.

OCI publish (requires [`oras`](https://oras.land/docs/installation) on PATH and
registry auth):

```bash
uv run opentrons-knowledge publish \
  --corpus dist/opentrons-knowledge-10.0.0-k5 \
  --registry ghcr.io/opentrons/opentrons-knowledge
```

### Consume a corpus

```bash
uv run opentrons-knowledge unpack dist/opentrons-knowledge-10.0.0-k5.tar.zst --output dist
uv run opentrons-knowledge inspect --corpus dist/opentrons-knowledge-10.0.0-k5

# From GHCR (requires oras):
uv run opentrons-knowledge pull 10.0.0-k5 --output dist
```

Agents: start at [AGENTS.md](AGENTS.md) and [docs/agent-usage.md](docs/agent-usage.md).
Those guides are copied into every packed corpus.

### Search the retrieval bundle

```bash
just retrieval-validate
just retrieval-search "InstrumentContext.blow_out" api
just retrieval-search "heater shaker latch" docs
just retrieval-search "blow out extra air" both   # top hits from each index
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
just test-integration # checks canonical/ in the latest built package
```

See [docs/canonical-docs.md](docs/canonical-docs.md).

## Documentation

**Agents start here:** [AGENTS.md](AGENTS.md) · [docs/agent-usage.md](docs/agent-usage.md) · [llms.txt](llms.txt)

- [Product architecture](docs/product-architecture.md)
- [Corpus format](docs/corpus-format.md)
- [Canonical docs](docs/canonical-docs.md)
- [Retrieval design](docs/retrieval-design.md) · [Retrieval experiments](docs/retrieval-experiments.md) · [Search tools](docs/retrieval-tool.md)
- [Source analysis](docs/source-analysis.md) (the `9.1.1-k1` pin study; current pins are in `corpora/10.0.0-k5/`)
- [Versioning](docs/versioning.md)
- [Release process](docs/release-process.md)
- [Implementation plan](docs/implementation-plan.md)

## CLI

```bash
opentrons-knowledge build --manifest corpora/10.0.0-k5/source-manifest.yaml --opentrons-repo ../opentrons
opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k5
opentrons-knowledge inspect --corpus dist/opentrons-knowledge-10.0.0-k5
opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k5
opentrons-knowledge unpack dist/opentrons-knowledge-10.0.0-k5.tar.zst
opentrons-knowledge publish --corpus dist/opentrons-knowledge-10.0.0-k5
opentrons-knowledge pull 10.0.0-k5
opentrons-knowledge verify --corpus dist/opentrons-knowledge-10.0.0-k5
opentrons-knowledge sources --corpus dist/opentrons-knowledge-10.0.0-k5
opentrons-knowledge diff 10.0.0-k4 10.0.0-k5 --json
opentrons-knowledge docs build --manifest corpora/10.0.0-k5/source-manifest.yaml --opentrons-repo ../opentrons
opentrons-knowledge docs validate --corpus dist/canonical-docs
opentrons-knowledge retrieval validate --bundle dist/opentrons-knowledge-10.0.0-k5/retrieval
opentrons-knowledge retrieval search "InstrumentContext.blow_out" --bundle dist/opentrons-knowledge-10.0.0-k5/retrieval --index api
opentrons-knowledge retrieval search "heater shaker latch" --bundle dist/opentrons-knowledge-10.0.0-k5/retrieval --index docs
opentrons-knowledge retrieval search "blow out extra air" --bundle dist/opentrons-knowledge-10.0.0-k5/retrieval --index both
opentrons-knowledge retrieval explore --bundle dist/opentrons-knowledge-10.0.0-k5/retrieval
opentrons-knowledge retrieval audit --bundle dist/opentrons-knowledge-10.0.0-k5/retrieval
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

## Why the recent changes

The corpus used to index the Markdown files authors edit, but much of what readers
see is produced only when MkDocs builds the site: included tables, tabbed Flex
and OT-2 procedures, and the Python API reference, generated from one-line stubs.
The build also produces structure that is not in the source text at all: site
navigation that places each page, breadcrumbs, links resolved to pages and
anchors, and parent and child relationships among headings. Answering from the
unbuilt files meant missing content, a flat heading structure, lost
relationships, and records that shared an id.

From `10.0.0-k3` on, we fully build the how-to docs and the API reference and
parse that HTML into JSON documents with a stable id hierarchy: a page, its
sections, and the parent and child links between them. The package ships those
documents in `canonical/`, so a consumer can read the rendered pages directly.
The indexes are a second set of JSON records derived from those documents, and
any retrieval mechanism built against the indexes uses those records: one API
section per public symbol, heading path and tab label on the docs side, and a
build that fails if any id repeats.

### TL;DR

**The API reference lives only in the rendered page.** `reference/instruments.md`
is front matter plus `::: opentrons.protocol_api.InstrumentContext`. Rendering
that stub produces the class page: 325 symbol sections, each with a signature,
parameters, returns, and version notes. Reading the file records the directive.
The AST extract has the docstrings and misses the page readers actually see.

**Generated docs and tabs collapse when the site is not built.** The liquid
class page is three `{% include %}` lines. The rendered page has more than ten
pipette and tip tables. Flex and OT-2 load names are tabs under one heading.
The Markdown parse stored both tables as one unlabeled blob. The HTML extract
keeps each tab, and the docs index prefixes the heading path (`Loading
Pipettes > API load names > Flex Pipettes`).

**Shared ids made two records one record.** The legacy section file has 1,470
records and 1,372 ids, because a section id was a slug of the heading titles
and a repeated title replaced the section before it. A property getter and its
setter shared a symbol id (1,658 records, 1,615 ids), and every version of a
labware load name shared one id (465 records, 261 ids). Ids are now the page
path plus the HTML anchor. A repeated anchor gets a `-2` suffix, and a
duplicate retrieval id fails the build.

Those pages ship as the JSON documents in `canonical/`. The indexes read
retrieval records built from them. The API index is one chunk per symbol, so a
hit is the whole symbol section. The docs index gives each tab its own chunk
and packs other blocks to 400 words on a block boundary, and a hit returns
every chunk of that section. Fixed
200-word windows scored 0.178 MRR worse. Curated MRR@10 is 0.601, up from
0.501. Tests check the extract against the rendered HTML (code kept verbatim,
structure counts matched, more than 99.5% of words kept), reject duplicate ids,
and require a search hit to contain every chunk of the section: 25 docs
sections and 25 API symbols on a built corpus.
