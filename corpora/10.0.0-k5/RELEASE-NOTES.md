# Opentrons Knowledge 10.0.0-k5

Target Opentrons release: **v10.0.0**

## Source pins

| Source | Pin |
|--------|-----|
| Protocol API + shared-data | `v10.0.0` @ `e8c6d0a424c25fff1604e2a02e4ccaedac95b9af` |
| Official docs | `mkdocs-2026-09-30` @ `00f1431babdf36a11ec68143c009d5fc889b2478` |
| Opentrons AI v1 guides | `ai-server@0.0.22` @ `0b6a6ecd2d6e040e02f40bd1d44193cfc42b33dc` (`pd/` excluded) |
| Protocol Designer | `protocol-designer@9.0.1` @ `677274a40c5d22044c4efe7365d4904a56eeefd4` |

On 2026-11-10 the latest production `protocol-designer@X.Y.Z` tag was resolved
from the remote again, and it is still `protocol-designer@9.0.1`. Tags matching
`staging-protocol-designer@*`, `pd-test*`, or `protocol-designer@*` with
`-alpha`, `-beta`, or `-rc` are ignored. The pin is independent of the
robot-stack `v10.0.0` pin.

## What changed in k5

Same source commits as **10.0.0-k4**. The Protocol Designer source now includes
every compatibility module the JSON is evaluated from, and the build publishes
that JSON.

### Raw files and evaluated JSON

`raw/protocol_designer/` keeps the TypeScript. `corpus/protocol-designer/` is
the same modules imported and evaluated (Vite, Node.js >= 24.22.1, the
Opentrons `edge` pin). The Flex Stacker allowlist entry is a spread of
`RECOMMENDED_LABWARE_BY_MODULE`, so the raw file alone does not list its 18
load names; the JSON does.

Raw paths:

```text
protocol-designer/src/constants.ts
protocol-designer/src/modules/moduleData.ts
protocol-designer/src/pages/Designer/DeckSetup/constants.ts
protocol-designer/src/pages/Designer/DeckSetup/utils.ts
protocol-designer/src/pages/Onboarding/constants.ts
protocol-designer/src/utils/labwareModuleCompatibility.ts
```

JSON:

| File | Contents |
|------|----------|
| `labware-allowlist.json` | `COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE`, Flex Stacker spread resolved |
| `labware-compatible.json` | `getLabwareCompatibleWithModule`, `getLabwareCompatibleWithAdapter`, and `ADAPTER_96_CHANNEL`, over the 154 current Opentrons labware definitions in shared-data `v10.0.0` |
| `recommended-labware.json` | `RECOMMENDED_LABWARE_BY_MODULE` and `getLabwareIsRecommended` (by module model, plus the vacuum-module and vacuum-dock cases) |
| `module-models.json` | Flex and OT-2 model lists, onboarding subsets, supported types, multiple-of-a-model lists, deck fixtures |
| `module-slots.json` | OT-2 slots, `getAllModuleSlotsByTypeOt2`, `getModuleModelsBySlot` for Flex and OT-2, default slots |
| `module-limits.json` | `MIN_*` and `MAX_*` module bounds, plus the module-count limits |
| `pipette-options.json` | `PIPETTE_GENS`, `PIPETTE_TYPES`, `PIPETTE_VOLUMES` |
| `manifest.json` | File list, Protocol Designer pin, shared-data pin |

Each table file has a `source` object with the repository, tag, commit, and the
exports it came from. Keys are runtime strings such as `temperatureModuleType`
and `heaterShakerModuleV1`, never TypeScript identifiers. Keys and arrays are
sorted. `vacuumModuleTypeWithLabware` is its own key.

Use `labware-allowlist.json` for the names Protocol Designer lists for a module.
Use `labware-compatible.json` for what it accepts. These differ for predicate
modules: the absorbance reader allowlist is only the plate reader lid, but the
predicate accepts any 96-well, non-tiprack plate up to 16 mm tall.

Names Protocol Designer lists that are not in shared-data `v10.0.0` (the vacuum
collars) are in the allowlist JSON and absent from the predicate results.
Functions that need the protocol currently on the deck are not exported.

The tables are not turned into entities, relationships, retrieval documents, or
chunks.

### Unchanged from k4

- Source commits and tags
- Entity, relationship, and retrieval counts
- `canonical/`, `retrieval/`, and `corpus_schema_version: 1`

`raw_files` and `source_files` grow by the five added Protocol Designer paths.

## Build

The build needs Node.js >= 24.22.1 (Opentrons `edge`) and npm, because it runs
`npm ci` in `tools/protocol-designer-export` when `node_modules/` is missing.

```bash
uv run opentrons-knowledge build \
  --manifest corpora/10.0.0-k5/source-manifest.yaml \
  --opentrons-repo ../opentrons \
  --output dist
uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-10.0.0-k5
uv run opentrons-knowledge pack --corpus dist/opentrons-knowledge-10.0.0-k5
```

Git tag for release: `knowledge-v10.0.0-k5`
