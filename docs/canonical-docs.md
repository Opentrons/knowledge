# Canonical Docs Corpus (rendered MkDocs HTML)

Opentrons owns documentation authoring and rendering. Knowledge owns turning
that rendered documentation into reusable, machine-readable records.

The canonical docs corpus is built from the **fully rendered MkDocs site** of
[Opentrons/opentrons](https://github.com/Opentrons/opentrons) at a pinned commit,
so it contains what readers actually see: macro output, `--8<--` snippets,
mkdocstrings API reference, tabs, admonitions, and resolved icons. Nothing in the
Opentrons repository, its MkDocs config, or its deploy workflow is changed.

## Dependencies

- Knowledge: `beautifulsoup4` and `lxml` (HTML parsing). Extraction itself uses
  no indexing, embedding, or vector libraries; the separate retrieval step uses
  `tantivy` (see [retrieval-design.md](retrieval-design.md)).
- Rendering (same tools as the Opentrons docs workflow): `git`, `uv`, `make`.
  `uv` downloads the pinned Python if needed.
- A local clone of Opentrons/opentrons with tags (`--opentrons-repo`), or network
  access for a blobless mirror clone under `dist/.work/mirrors`.

## Quick start

```bash
just docs-build      # render mkdocs-2026-09-30 and write dist/canonical-docs
just docs-validate   # checksums, inventory, section graph, content hashes
DOC=python-api/pipettes/loading/ just docs-inspect
just test-integration  # checks canonical/ in the latest built package
```

Direct CLI:

```bash
uv run opentrons-knowledge docs build \
  --manifest corpora/10.0.0-k2/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist/canonical-docs

# Pick a revision without a manifest (tag, branch, or SHA)
uv run opentrons-knowledge docs build --ref mkdocs-2026-09-30 --opentrons-repo ../opentrons

# Extract from an already rendered site (no build)
uv run opentrons-knowledge docs build --site ../opentrons/docs/site --opentrons-repo ../opentrons

uv run opentrons-knowledge docs inspect --corpus dist/canonical-docs --document python-api/pipettes/loading/ --json
```

`docs build-site` renders only. `--rebuild` ignores a cached render.
`--in-place` builds the clone's current checkout (dirty state is recorded); use
it only for local iteration.

## Revision selection

1. `--ref` on the command line, else the `opentrons_docs` source in `--manifest`
   (its tag, else its commit).
2. The ref is resolved to an exact 40-character SHA. With a manifest, the
   resolved SHA must equal the manifest's pinned `commit`, or the build fails.
3. Both the ref and the SHA are written to `manifest.json` (`source.ref`,
   `source.commit`).

## How the build is invoked

`opentrons_knowledge.docs.mkdocs_build.build_site` reproduces the
`docs-build-deploy` workflow without touching your clone:

1. `git clone --shared --no-checkout` into `dist/.work/mkdocs/<sha12>/checkout`,
   sparse to `docs/`, `api/`, and `shared-data/` (the docs uv project installs
   `../api` and `../shared-data` editable; they use hatch-vcs, so tags are kept).
2. `git checkout --detach <sha>`.
3. In `docs/`: `uv sync --frozen`, then `make build` with `CI=true` (which adds
   `--strict`) and `UV_PYTHON=3.12` (the CI Python). Caller virtualenv variables
   (`VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT`, `PYTHONPATH`, ...) are scrubbed.
   The Playwright install from `make setup` is skipped; it only serves PDF output.
4. Output is `docs/site/`; the full log is `mkdocs-build.log` next to the
   checkout. Failures raise `DocsBuildError` with the command, exit code, and
   last 40 log lines.
5. `git diff --name-only HEAD` must list only `allowed_modifications`.
6. A build stamp lets later runs reuse the site for the same SHA and settings.

All of this is configurable per manifest with an optional block (defaults shown):

```yaml
rendered_docs:
  source: opentrons_docs
  mkdocs_config: docs/mkdocs.yml
  working_directory: docs
  setup_command: [uv, sync, --frozen]
  build_command: [make, build]
  site_dir: docs/site
  python: "3.12"
  strict: true
  sparse_paths: [docs, api, shared-data]
  base_url: https://docs.opentrons.com/
  allowed_modifications: [docs/uv.lock]
```

Findings from the `mkdocs-2026-09-30` pin:

- `docs/uv.lock` is stale relative to `docs/pyproject.toml`, so `uv run` inside
  `make build` re-locks it (production does the same). That is why
  `docs/uv.lock` is an allowed modification, and it is recorded in
  `build.modified_files`. Because `exclude-newer` is relative ("1 week"), that
  re-lock is time-dependent; fixing the lock upstream would make renders fully
  hermetic.
- A local `~/.config/uv/.python-version` would otherwise change the Python used;
  `UV_PYTHON` pins it.

## HTML processing

`opentrons_knowledge.docs.html_extract.extract_page` parses each page with
BeautifulSoup + lxml and reads only `article.md-content__inner`. Header, nav,
search, TOC, footer, edit buttons, permalink anchors, feedback widgets, scripts,
and styles are excluded.

- **Sections**: each article heading starts a section. Content before the first
  heading becomes a level-0 root section titled with the page title. Headings
  inside tabs, admonitions, or lists stay inline as `heading` blocks so the
  container is not split.
- **Blocks**: `paragraph`, `heading`, `code` (language, filename title,
  `role: signature` for mkdocstrings signatures), `list` (ordered, start,
  nested), `table` (header rows, rowspan/colspan), `admonition` (kind, title,
  collapsible `<details>`), `tabs` (labels and per-tab blocks), `image`,
  `figure` (caption), `quote`, and `html`.
- **Inline text** is Markdown-like: `` `code` ``, `**bold**`, `*em*`,
  `[text](href)`, `![alt](src)`. Material/Twemoji SVG icons are mapped back to
  their shortcodes (`:octicons-check-16:`) using the icon sets in the docs venv
  and `custom_icons` from `mkdocs.yml`.
- **API reference**: mkdocstrings `doc-object` sections carry
  `api.qualified_name`, `api.kind`, and `api.labels`.
- **Fallback**: unrecognized structures (iframes, inline SVG diagrams,
  definition lists, unknown tab markup) become `html` blocks with the raw HTML,
  plain text, and a `reason`, so content is never silently dropped.
- **Inventories**: every link (`internal`, resolved `target_page_path` and
  `target_anchor`) and image (resolved `site_path` and `source_path`) with its
  `section_id`.

## Provenance

Each document records:

- `source`: repository, commit, ref, Markdown path (resolved through the
  `mkdocs-monorepo` `!include` tree), commit-pinned `markdown_url`, Markdown
  SHA-256, and front matter.
- `rendered`: HTML path, HTML SHA-256, and MkDocs generator.
- `url`, `nav_path` (breadcrumb from the rendered nav), `project`.
- Section `anchor` (the HTML heading `id`) and absolute `url`.
- `content_hash` for every section and document. The hash includes
  `document_id` (repository, commit, and Markdown path) and `section_id`, so
  the same paragraph on two pages is two records.

## Schema

Models live in `opentrons_knowledge.models.canonical`; JSON Schemas are
generated into `schemas/canonical-document.schema.json` and
`schemas/canonical-manifest.schema.json` (`just schemas`, kept in sync by a unit
test). `schema_id: opentrons-knowledge.canonical-docs`, `schema_version: 1`.

Stable identifiers:

| Record | Pattern |
|--------|---------|
| Document | `doc:<repo-slug>:<commit12>:<markdown path>` (equal to the legacy `corpus/documents` id) |
| Root section | `section:<document_id>` |
| Section | `section:<document_id>#<anchor>` |

Duplicate or missing anchors get deterministic `-2`, `-3` suffixes.

Sections are linked by `parent_id`, `child_ids`, `previous_id`, `next_id`,
`ordinal`, and `heading_path`, so a later chunker can split, merge, or window
sections without re-parsing HTML. Chunking is intentionally not part of this
package.

## Artifact layout

```text
<output>/
  documents.jsonl.zst   # one CanonicalDocument per line, sorted by document_id
  manifest.json         # CanonicalManifest
```

`manifest.json` holds the schema id and version, corpus version, source repo,
ref, commit, and dirty flag, MkDocs `extra` (docs version values such as
`apiLevel`), build settings and modified files, extractor and builder versions,
dependency versions, document, section, and block counts, the per-document
inventory, excluded pages with reasons, and each artifact's path, format,
compression, record count, SHA-256, and uncompressed SHA-256.

Output is deterministic: rebuilding the same pin from a fresh clone produces
byte-identical files.

## Compatibility decision

- Existing `corpus/*.jsonl.zst` records, schemas, and IDs are unchanged.
- The canonical corpus is **additive**. In a knowledge corpus it is written to
  `canonical/` only when the source manifest includes `rendered_docs`, and
  `manifest.yaml` gains `metadata.canonical_docs` and
  `counts.canonical_documents`. Already published versions are not rebuilt.
- To adopt: create a new knowledge revision (for example `10.0.0-k3`) whose
  source manifest adds `rendered_docs: {}`, and note it in release notes.
  Consumers that ignore unknown directories are unaffected.
- Replacing the Markdown-derived `corpus/documents` and `corpus/sections` with
  canonical records would be a breaking change and requires a
  `corpus_schema_version` bump and a migration note.

## Chunking and indexing

`10.0.0-k3` chunks these records in `retrieval/`. Symbol sections are one chunk
each, in `retrieval/api/bm25/`. Other sections use structured chunking in
`retrieval/docs/bm25/`: each tab is its own chunk, other blocks pack at a
boundary of 400 words, and a search hit returns every chunk of the matched
section. See [retrieval-design.md](retrieval-design.md).

The rules that bundle follows:

- Prefix with `heading_path` joined by ` > `. Add `api.qualified_name` when the
  section has one and the name is not already in the opening of the text.
  Parent titles are already on `heading_path`, so a heading-only parent is
  context, not its own chunk.
- Keep each tab as its own chunk and put the tab label in the prefix. Tabs on
  one page often describe different robots (Flex and OT-2).
- Keep a code block, including an API `signature`, with the section it belongs to.
- Skip a document when `search_exclude` is true. That flag mirrors MkDocs
  `search.exclude`. On this pin it marks two unpublished Vacuum Module pages
  whose body is placeholder text.
- The retrieval id is `doc:<page_path>#<anchor>`, from the page path and the
  heading anchor, and the build fails if any id repeats.

Section size on the `mkdocs-2026-09-30` pin, for anyone adding embeddings
later: median about 500 characters, 99th percentile about 4,000, and four
sections above 6,000. No embeddings ship today. Use `content_hash` to skip
re-embedding a section whose path and body are unchanged.

Also useful as filters: `project`, `nav_path`, `source.markdown_path`,
`api.kind`, and `api.labels`. Cite `url` and `source.markdown_url`.

## Consuming

```python
from pathlib import Path
from opentrons_knowledge.docs.canonical import (
    find_document, iter_blocks, load_canonical_documents, validate_canonical_corpus,
)

root = Path("dist/canonical-docs")
validate_canonical_corpus(root)
docs = load_canonical_documents(root)
page = find_document(docs, "python-api/pipettes/loading/")
for section in page.sections:
    code = [b.code for b in iter_blocks(section.blocks) if b.type == "code"]
```

Without this package: decompress with zstd, read one JSON document per line,
and validate against the schemas.

## Validation

`tests/integration/test_opentrons_docs.py` reads `canonical/` from the latest
built package (`dist/opentrons-knowledge-<version>`, the highest version under
`corpora/`). It checks the docs pin, that every page maps to Markdown, that
unpublished pages stay out of search, and that major page structures are still
there: pipette tabs, the `InstrumentContext.aspirate` signature, liquid-class
tables, and note, warning, and tip callouts. It does not rebuild MkDocs or
compare records to a fixture site. A missing package fails the test.

`just test` runs that check with the rest of the suite. `just test-integration`
runs only the package checks. Build the corpus first.

At `mkdocs-2026-09-30`: 276 documents, all mapped to Markdown, 1809 sections,
no `html` fallback blocks, and no unresolved icons.

## Limitations

- Icon shortcodes need the docs `.venv` from the build; with `--site` and no
  venv, unknown icons render as `:icon:`.
- Inline text is Markdown-like and not escaped; table cells are text only and
  spans are recorded, not expanded.
- Horizontal rules and presentational wrappers (instruction lists, parts lists,
  grid cards) are flattened.
- Headings are not mapped to Markdown source line numbers.
- mkdocstrings parameter tables or lists are kept as rendered, not parsed into
  structured parameters (the Protocol API symbols in `corpus/` cover that).
