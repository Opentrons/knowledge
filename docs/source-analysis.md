# Source Analysis

Findings from inspecting the local Opentrons monorepo at
`/Users/joshmcvey/github/opentrons/opentrons` for the first corpus target
`9.1.1-k1` (Opentrons release `v9.1.1`).

## Summary

| Concern | Finding |
|---------|---------|
| Public docs build | **MkDocs** Material monorepo under `docs/` (colloquially "makedocs") |
| Protocol API docs | Authored Markdown in `docs/python-api/docs/` plus mkdocstrings stubs |
| Legacy Sphinx | `api/docs/v1/` and hardware Sphinx trees are not current Protocol API truth |
| Protocol API code | `api/src/opentrons/protocol_api/` |
| Shared data | `shared-data/{labware,pipette,module,deck,robot,...}` |
| Opentrons AI v1 guidance | Curated Markdown in `opentrons-ai-server/api/storage/docs/` (same monorepo) |
| Release tag | Annotated tag `v9.1.1` → commit `ad074b80e267084f08065b6d559b791140dfa671` |

There is no separate public "Opentrons AI v1" repository on this machine. The
v1 protocol-writing guides live inside the Opentrons monorepo AI server package.
The corpus treats that tree as a curated external-style source with explicit
compatibility records.

## Resolved Pins for `9.1.1-k1`

| Source | Pin | Commit | Compatibility |
|--------|-----|--------|---------------|
| Protocol API | tag `v9.1.1` | `ad074b80e267084f08065b6d559b791140dfa671` | `exact-release` |
| Shared data | same as release | `ad074b80e267084f08065b6d559b791140dfa671` | `exact-release` |
| Public docs | tag `mkdocs-2026-07-16` | `34bfc1870aff37bf90408a92ce19f30eea754aaf` | `validated` |
| Opentrons AI v1 guides | tag `ai-server@0.0.20` | `aa7bb9efe607a9b781b2b7e50bdc9af94ccc6fbf` | `validated` |

### Why docs are not the release commit

At `v9.1.1`, `docs/python-api/mkdocs.yml` still reports:

```text
apiLevel: 2.28
robot_stack_version: 9.0.0
```

The nearest MkDocs production tags after the release (`mkdocs-2026-07-14`,
`mkdocs-2026-07-16`) report:

```text
apiLevel: 2.29
robot_stack_version: 9.1.0
```

Docs deployment is intentionally decoupled from robot-stack tags (see
`docs/README.md`). For knowledge targeting software `v9.1.1`, we pin the
post-release MkDocs tag that documents the 9.1.x / API 2.29 surface, and record
that relationship as `validated` rather than `exact-release`.

## Source Repositories

Primary repository for all initial sources:

```text
https://github.com/Opentrons/opentrons
```

Optional future separate AI repository pins can be added to the source manifest
without changing corpus schema.

## Documentation Paths

```text
docs/
  mkdocs.yml                      # monorepo aggregator
  python-api/
    mkdocs.yml                    # nav, mkdocstrings, extra.apiLevel
    docs/                         # authored Markdown (primary)
      reference/*.md              # stubs with ::: directives
      liquid-class-tables/        # generated; often excluded from nav
  flex/docs/
  ot-2/docs/
  shared/                         # shared index / theme assets
```

### Build commands

```bash
cd docs
make setup
make build   # uv run mkdocs build -f ./mkdocs.yml
```

Output: `docs/site/`.

Deploy tags: `mkdocs-YYYY-MM-DD` → https://docs.opentrons.com

### Authored vs generated

| Content | Nature | Corpus handling |
|---------|--------|-----------------|
| Narrative guides | Authored Markdown | Ingest source `.md` |
| `reference/*.md` | Stub + `::: module.Class` | Expand via AST/docstrings from Protocol API pin |
| Liquid class tables | Generated from shared-data | Ingest committed generated MD; shared-data remains normative |
| Macro placeholders | `{{ apiLevel }}` etc. | Substitute from pinned mkdocs `extra:` |

### Source → rendered URL mapping

```text
docs/python-api/docs/<path>.md
  → https://docs.opentrons.com/python-api/<path>/
  → https://github.com/Opentrons/opentrons/blob/<commit>/docs/python-api/docs/<path>.md
```

Path rules:

- strip `.md` / `.html`
- treat `index` as directory root
- preserve `#fragment` anchors from headings / explicit `{ #anchor }`

## Protocol API Paths

```text
api/src/opentrons/protocol_api/
  protocol_context.py
  instrument_context.py
  labware.py
  module_contexts.py
  robot_context.py
  validation.py
  ...
api/docs/v2/example_protocols/   # useful example .py files
```

Public symbols are extracted with Python AST (not regex). Source URLs use
pinned commits and line ranges:

```text
https://github.com/Opentrons/opentrons/blob/<commit>/<path>#L100-L145
```

## Shared-Data Paths

```text
shared-data/
  labware/definitions/<schema>/
  labware/schemas/
  pipette/definitions/
  pipette/schemas/
  module/definitions/
  deck/definitions/
  robot/definitions/
  liquid-class/definitions/
  ...
```

Preserve original JSON plus normalized entities (`LabwareDefinition`,
`PipetteDefinition`, `ModuleDefinition`, `DeckDefinition`, `RobotDefinition`).

## Opentrons AI v1 Paths

Pinned to the latest `ai-server@*` tag (currently `ai-server@0.0.20`), not the
robot-stack release commit.

```text
opentrons-ai-server/api/storage/docs/
  deck_layout.md
  transfer_function_notes.md
  serial_dilution_examples.md
  ...
  pd/                    # Protocol Designer; excluded from corpus (required)
```

Exclude `pd/` always. Authority level: `curated_guidance`.

## Duplicate-Content Risks

- Narrative docs vs expanded API reference for the same method
- AI guides vs official docs (examples and transfer notes)
- Built `docs/site/` HTML vs source Markdown (do not index both)
- Sphinx leftovers under `api/docs/v1` vs MkDocs Python API

Conflicts are retained and reported; authority precedence decides preferred
source for consumers.

## Unsupported / Skipped File Types

- Images, fonts, CSS, JS under docs trees (metadata only if referenced)
- `node_modules`, `.venv`, `site/`, `__pycache__`
- Binary fixtures unrelated to definitions
- Protocol Designer AI subtree `pd/`

Every exclusion is recorded with a reason in build reports.

## Versioning Behavior Notes

- Robot software tags: `vX.Y.Z`
- Docs deploy tags: `mkdocs-*` (independent)
- Sphinx API docs tags: `docs@N` (legacy / parallel)
- Corpus public version: `<opentrons-release>-k<n>` (see `docs/versioning.md`)

Exact source identity always lives in the corpus source manifest, never in the
public version string alone.
