# Source Analysis

Findings from inspecting the local Opentrons monorepo at
`/Users/joshmcvey/github/opentrons/opentrons` for the first corpus target
`9.1.1-k1` (Opentrons release `v9.1.1`).

Current pins are `corpora/10.0.0-k5/source-manifest.yaml` (`v10.0.0`,
`mkdocs-2026-09-30`, `ai-server@0.0.22`, `protocol-designer@9.0.1`). This page
records why the `9.1.1-k1` docs pin is not the release commit. That reason
still holds: the docs tag and the robot-software tag move on different
schedules. The Protocol Designer allowlist is pinned the same way as the
ai-server tag: latest production tag, independent of `v10.0.0`.

## Summary

| Concern | Finding |
|---------|---------|
| Public docs build | **MkDocs** Material monorepo under `docs/` (colloquially "makedocs") |
| Protocol API docs | Authored Markdown in `docs/python-api/docs/` plus mkdocstrings stubs |
| Legacy Sphinx | `api/docs/v1/` and hardware Sphinx trees are not current Protocol API truth |
| Protocol API code | `api/src/opentrons/protocol_api/` |
| Shared data | `shared-data/{labware,pipette,module,deck,robot,...}` |
| Opentrons AI v1 guidance | Curated Markdown in `opentrons-ai-server/api/storage/docs/` (same monorepo) |
| Protocol Designer tables | Raw compatibility sources plus evaluated JSON in `corpus/protocol-designer/` (`10.0.0-k5`) |
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

## Resolved Pins for `10.0.0-k1`

| Source | Pin | Commit | Compatibility |
|--------|-----|--------|---------------|
| Protocol API | tag `v10.0.0` | `e8c6d0a424c25fff1604e2a02e4ccaedac95b9af` | `exact-release` |
| Shared data | same as release | `e8c6d0a424c25fff1604e2a02e4ccaedac95b9af` | `exact-release` |
| Public docs | tag `mkdocs-2026-09-30` | `00f1431babdf36a11ec68143c009d5fc889b2478` | `validated` |
| Opentrons AI v1 guides | tag `ai-server@0.0.22` | `0b6a6ecd2d6e040e02f40bd1d44193cfc42b33dc` | `validated` |

At `v10.0.0`, `docs/python-api/mkdocs.yml` already reports:

```text
apiLevel: 2.30
robot_stack_version: 10.0.0
```

The post-release MkDocs deploy tag `mkdocs-2026-09-30` reports the same
metadata and includes doc updates after the stack release. We still pin the
deploy tag (relationship `docs-deploy-tag-for-10.0.x`) so the corpus tracks
production docs, not only the release commit snapshot.

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

Pinned to the latest `ai-server@*` tag (currently `ai-server@0.0.22` on
`9.1.2-k2` / `9.1.2-k3` / `10.0.0-k1`; earlier corpora remain on
`ai-server@0.0.20`), not the robot-stack release commit.

```text
opentrons-ai-server/api/storage/docs/
  deck_layout.md
  transfer_function_notes.md
  serial_dilution_examples.md
  ...
  pd/                    # Protocol Designer; excluded from corpus (required)
```

Exclude `pd/` always. Authority level: `curated_guidance`.

## Protocol Designer compatibility tables

Pinned since `10.0.0-k4` to the latest production `protocol-designer@X.Y.Z` tag,
currently `protocol-designer@9.0.1` at
`677274a40c5d22044c4efe7365d4904a56eeefd4`. This pin is independent of the
robot-stack `v10.0.0` commit and of the docs and ai-server pins. Eligible tags
are `protocol-designer@X.Y.Z` with no prerelease. `staging-protocol-designer@*`,
`pd-test*`, and any `protocol-designer@*` tag containing `-alpha`, `-beta`, or
`-rc` are ignored.

`10.0.0-k4` copied one file, `labwareModuleCompatibility.ts`. `10.0.0-k5` copies
every Protocol Designer module the tables are evaluated from:

```text
protocol-designer/src/constants.ts
protocol-designer/src/modules/moduleData.ts
protocol-designer/src/pages/Designer/DeckSetup/constants.ts
protocol-designer/src/pages/Designer/DeckSetup/utils.ts
protocol-designer/src/pages/Onboarding/constants.ts
protocol-designer/src/utils/labwareModuleCompatibility.ts
```

Those files land under `raw/protocol_designer/` at the same paths. `raw/manifest.yaml`
and `corpus/source-files.jsonl.zst` record the tag, commit, and each path. The
build does not parse the TypeScript, and it does not emit entities,
relationships, retrieval documents, or search chunks from it. The rest of
`protocol-designer/` is not copied into `raw/`. Step-generation is checked out
only so `DeckSetup/utils.ts` can be imported; it is not a corpus source.

### Evaluated tables (`10.0.0-k5` and later)

The raw file alone is not consumable: the Flex Stacker entry is
`...RECOMMENDED_LABWARE_BY_MODULE[FLEX_STACKER_MODULE_TYPE]`, so its load names
are not in the text. From k5, `protocol_designer_tables` in the source manifest
evaluates the tables instead of reading the source text.

`tools/protocol-designer-export` is a small Node package (locked with
`package-lock.json`; the build runs `npm ci` when `node_modules/` is missing).
It requires Node.js >= 24.22.1, the version pinned by Opentrons `edge`
(`.nvmrc` and `package.json` `engines`). The validate and publish workflows
install `24.22.1`.
The build checks out `ProtocolDesignerTablesConfig.sparse_paths` at the
`protocol_designer` commit, links the exporter's `node_modules/` into that
checkout, and runs `run.mjs`. `run.mjs` imports `export.ts` through Vite's
`runnerImport`, which is the bundler Protocol Designer ships with. That gives
the modules the same `import.meta.glob` and alias behavior they have in the
app:

- Aliases come from `protocol-designer/tsconfig.json` `paths`
  (`/protocol-designer/*` to `./src/*`), plus `@opentrons/shared-data` to
  `shared-data/js/index.ts`, as in `protocol-designer/vite.config.mts`. tsx was
  rejected because it does not map specifiers that start with `/`, and
  shared-data calls `import.meta.glob` at module load.
- `@opentrons/step-generation` resolves to `step-generation/src/index.ts`.
  `DeckSetup/utils.ts` imports it. `@opentrons/components` resolves to
  `stubs/opentrons-components.ts`. `DeckSetup/constants.ts` imports it only to
  build `DECK_CONTROLS_STYLE`.
- Predicates run against the pinned shared-data labware definitions. The filter
  is `namespace === "opentrons"`, keeping the newest `schemaVersion` and then
  the newest `version` per load name, and skipping `schema3test_*`. A name that
  Protocol Designer lists but that is not in that shared-data pin is absent
  from the predicate results. At `v10.0.0` that includes the vacuum collars.

| File | Contents |
|------|----------|
| `labware-allowlist.json` | `by_module_type`: `COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE`, Flex Stacker spread resolved |
| `labware-compatible.json` | `by_module_type` from `getLabwareCompatibleWithModule`; `by_adapter` from `getLabwareCompatibleWithAdapter`; `adapter_96_channel` |
| `recommended-labware.json` | `by_module_type` from `RECOMMENDED_LABWARE_BY_MODULE`; `by_module_model` from `getLabwareIsRecommended`, plus the vacuum-module and vacuum-dock cases |
| `module-models.json` | Flex and OT-2 model lists (deck setup and onboarding), supported module types, multiple-of-a-model lists, deck fixtures |
| `module-slots.json` | OT-2 supported slots, every OT-2 module slot, `getAllModuleSlotsByTypeOt2`, `getModuleModelsBySlot` for Flex and OT-2 slots (including empty staging slots), default slots |
| `module-limits.json` | `MIN_*` and `MAX_*` module bounds, including profile volume, plus `MAX_MOAM_MODULES` and `MAX_MAGNETIC_BLOCKS` |
| `pipette-options.json` | `PIPETTE_GENS`, `PIPETTE_TYPES`, `PIPETTE_VOLUMES` |
| `manifest.json` | File list, Protocol Designer pin, shared-data pin |

Each table file has a `source` object with `repository`, `tag`, `commit`, and
`exports` (module path and export name). Keys are the runtime strings (for
example `temperatureModuleType` or `heaterShakerModuleV1`), never TypeScript
identifiers. Keys are sorted, and so are load-name arrays and the model-list
fields. `models_by_slot` and `slots_by_module_type_ot2` keep Protocol
Designer's order. Slot options keep `value` and keep the dropdown `name` only
when it differs (OT-2 thermocycler: `7` shown as `7,8,10,11`).
`vacuumModuleTypeWithLabware` is a Protocol Designer-only key and stays
separate from `vacuumModuleType`. Robot keys are the runtime strings
`OT-3 Standard` and `OT-2 Standard`.

Functions that need the protocol currently on the deck (collision checks,
labware already placed, step-form errors) are not tables and are not exported.

The tables do not produce entities, relationships, retrieval documents, or
chunks. `tests/integration/test_protocol_designer_tables.py` reads the built
`dist/opentrons-knowledge-10.0.0-k5` package. A missing build fails the test.

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
