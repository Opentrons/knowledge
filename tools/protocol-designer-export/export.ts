// Evaluates Protocol Designer compatibility tables and writes their runtime
// values as JSON. run.mjs loads this module through Vite with the pinned
// checkout's aliases.
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import {
  FLEX_ROBOT_TYPE,
  FLEX_SINGLE_SLOT_ADDRESSABLE_AREAS,
  FLEX_STAGING_AREA_SLOT_ADDRESSABLE_AREAS,
  getLabwareDefURI,
  OT2_ROBOT_TYPE,
  OT2_SINGLE_SLOT_ADDRESSABLE_AREAS,
} from '@opentrons/shared-data'

import * as pdConstants from '/protocol-designer/constants'
import {
  ALL_MODULE_SLOTS_OT2,
  getAllModuleSlotsByTypeOt2,
  SUPPORTED_MODULE_SLOTS_OT2,
  SUPPORTED_MODULE_TYPES,
} from '/protocol-designer/modules/moduleData'
import {
  FIXTURES,
  FLEX_MODULE_MODELS,
  MAX_MAGNETIC_BLOCKS,
  MAX_MOAM_MODULES,
  MOAM_MODELS,
  MOAM_MODELS_WITH_FF,
  OT2_MODULE_MODELS,
  RECOMMENDED_LABWARE_BY_MODULE,
} from '/protocol-designer/pages/Designer/DeckSetup/constants'
import {
  getLabwareCompatibleWithAdapter,
  getLabwareIsRecommended,
  getModuleModelsBySlot,
} from '/protocol-designer/pages/Designer/DeckSetup/utils'
import {
  DEFAULT_SLOT_MAP_FLEX,
  DEFAULT_SLOT_MAP_OT2,
  FLEX_SUPPORTED_MODULE_MODELS,
  OT2_SUPPORTED_MODULE_MODELS,
  PIPETTE_GENS,
  PIPETTE_TYPES,
  PIPETTE_VOLUMES,
} from '/protocol-designer/pages/Onboarding/constants'
import {
  ADAPTER_96_CHANNEL,
  COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE,
  getLabwareCompatibleWithModule,
} from '/protocol-designer/utils/labwareModuleCompatibility'

import type { LabwareDefinition2, RobotType } from '@opentrons/shared-data'
import type { ModuleModel } from '@opentrons/shared-data'

const PD_CONSTANTS_LIMITS = [
  'MIN_ENGAGE_HEIGHT_V1',
  'MAX_ENGAGE_HEIGHT_V1',
  'MIN_ENGAGE_HEIGHT_V2',
  'MAX_ENGAGE_HEIGHT_V2',
  'MIN_TEMP_MODULE_TEMP',
  'MAX_TEMP_MODULE_TEMP',
  'MIN_HEATER_SHAKER_MODULE_TEMP',
  'MAX_HEATER_SHAKER_MODULE_TEMP',
  'MIN_HEATER_SHAKER_MODULE_RPM',
  'MAX_HEATER_SHAKER_MODULE_RPM',
  'MIN_HEATER_SHAKER_DURATION_SECONDS',
  'MAX_HEATER_SHAKER_DURATION_SECONDS',
  'MIN_TC_BLOCK_TEMP',
  'MAX_TC_BLOCK_TEMP',
  'MIN_TC_LID_TEMP',
  'MAX_TC_LID_TEMP',
  'MIN_TC_DURATION_SECONDS',
  'MAX_TC_DURATION_SECONDS',
  'MIN_TC_PROFILE_VOLUME',
  'MAX_TC_PROFILE_VOLUME',
] as const

const VACUUM_MODULE_MODEL = 'vacuumModuleV1'
const LABWARE_COMPATIBILITY =
  'protocol-designer/src/utils/labwareModuleCompatibility.ts'
const DECK_SETUP = 'protocol-designer/src/pages/Designer/DeckSetup/constants.ts'
const DECK_SETUP_UTILS = 'protocol-designer/src/pages/Designer/DeckSetup/utils.ts'
const PD_CONSTANTS_MODULE = 'protocol-designer/src/constants.ts'
const MODULE_DATA = 'protocol-designer/src/modules/moduleData.ts'
const ONBOARDING = 'protocol-designer/src/pages/Onboarding/constants.ts'

type CompatibilityKey = keyof typeof COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE

interface Candidate {
  schemaVersion: number
  version: number
  definition: LabwareDefinition2
}

function latestOpentronsLabware(root: string): LabwareDefinition2[] {
  const latest = new Map<string, Candidate>()
  // Schema 1 definitions are flat files without a namespace; only
  // <schema>/<loadName>/<version>.json layouts can be Opentrons labware here.
  for (const schemaDir of readdirSync(root)) {
    const entries = readdirSync(join(root, schemaDir), { withFileTypes: true })
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.name.startsWith('schema3test_')) {
        continue
      }
      const dir = join(root, schemaDir, entry.name)
      for (const file of readdirSync(dir)) {
        if (!file.endsWith('.json')) {
          continue
        }
        const definition = JSON.parse(readFileSync(join(dir, file), 'utf8'))
        if (definition.namespace !== 'opentrons') {
          continue
        }
        const loadName: string = definition.parameters.loadName
        const candidate: Candidate = {
          schemaVersion: definition.schemaVersion,
          version: definition.version,
          definition,
        }
        const current = latest.get(loadName)
        if (
          current == null ||
          candidate.schemaVersion > current.schemaVersion ||
          (candidate.schemaVersion === current.schemaVersion &&
            candidate.version > current.version)
        ) {
          latest.set(loadName, candidate)
        }
      }
    }
  }
  return [...latest.values()].map(candidate => candidate.definition)
}

function pick<T extends Record<string, unknown>>(
  source: T,
  names: readonly string[]
): Record<string, unknown> {
  return Object.fromEntries(
    names.map(name => {
      if (!(name in source)) {
        throw new Error(`Export ${name} is missing`)
      }
      return [name, source[name]]
    })
  )
}

function loadNames(
  definitions: LabwareDefinition2[],
  predicate: (definition: LabwareDefinition2) => boolean
): string[] {
  return definitions
    .filter(predicate)
    .map(definition => definition.parameters.loadName)
}

function modelsBySlot(robotType: RobotType, slots: readonly string[]): Record<string, string[]> {
  return Object.fromEntries(
    slots.map(slot => [slot, getModuleModelsBySlot(robotType, slot as never)])
  )
}

export function exportTables(options: { labware: string; out: string }): void {
  const definitions = latestOpentronsLabware(options.labware)
  const definitionsByUri = Object.fromEntries(
    definitions.map(definition => [getLabwareDefURI(definition), definition])
  )
  const moduleTypes = Object.keys(
    COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE
  ) as CompatibilityKey[]
  const moduleModels = [
    ...new Set<ModuleModel>([...FLEX_MODULE_MODELS, ...OT2_MODULE_MODELS]),
  ]
  const adapterLoadNames = [
    ...new Set(
      definitions.flatMap(definition =>
        Object.keys(definition.stackingOffsetWithLabware ?? {})
      )
    ),
  ]
  const slotsByModuleType = Object.fromEntries(
    Object.entries(SUPPORTED_MODULE_SLOTS_OT2)
      .filter(([, slots]) => slots.length > 0)
      .map(([moduleType]) => [
        moduleType,
        getAllModuleSlotsByTypeOt2(moduleType as never),
      ])
  )

  const result = {
    exports: {
      [LABWARE_COMPATIBILITY]: {
        COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE,
        ADAPTER_96_CHANNEL,
      },
      [DECK_SETUP]: {
        RECOMMENDED_LABWARE_BY_MODULE,
        FLEX_MODULE_MODELS,
        OT2_MODULE_MODELS,
        FIXTURES,
        MOAM_MODELS,
        MOAM_MODELS_WITH_FF,
        MAX_MOAM_MODULES,
        MAX_MAGNETIC_BLOCKS,
      },
      [PD_CONSTANTS_MODULE]: pick(pdConstants, PD_CONSTANTS_LIMITS),
      [MODULE_DATA]: {
        SUPPORTED_MODULE_TYPES,
        SUPPORTED_MODULE_SLOTS_OT2,
        ALL_MODULE_SLOTS_OT2,
      },
      [ONBOARDING]: {
        FLEX_SUPPORTED_MODULE_MODELS,
        OT2_SUPPORTED_MODULE_MODELS,
        DEFAULT_SLOT_MAP_FLEX,
        DEFAULT_SLOT_MAP_OT2,
        PIPETTE_GENS,
        PIPETTE_TYPES,
        PIPETTE_VOLUMES,
      },
    },
    getLabwareCompatibleWithModule: {
      module: LABWARE_COMPATIBILITY,
      definition_count: definitions.length,
      by_module_type: Object.fromEntries(
        moduleTypes.map(moduleType => [
          moduleType,
          loadNames(definitions, definition =>
            getLabwareCompatibleWithModule(definition, moduleType)
          ),
        ])
      ),
    },
    getLabwareIsRecommended: {
      module: DECK_SETUP_UTILS,
      by_module_model: Object.fromEntries(
        moduleModels.map(model => [
          model,
          loadNames(definitions, definition =>
            getLabwareIsRecommended(definition, model)
          ),
        ])
      ),
      vacuum_module_with_labware: loadNames(definitions, definition =>
        getLabwareIsRecommended(definition, VACUUM_MODULE_MODEL, true)
      ),
      vacuum_dock_without_collar: loadNames(definitions, definition =>
        getLabwareIsRecommended(definition, VACUUM_MODULE_MODEL, false, true, false)
      ),
      vacuum_dock_with_collar: loadNames(definitions, definition =>
        getLabwareIsRecommended(definition, VACUUM_MODULE_MODEL, false, true, true)
      ),
    },
    getLabwareCompatibleWithAdapter: {
      module: DECK_SETUP_UTILS,
      by_adapter: Object.fromEntries(
        adapterLoadNames.map(adapter => [
          adapter,
          getLabwareCompatibleWithAdapter(definitionsByUri, adapter).map(
            uri => definitionsByUri[uri].parameters.loadName
          ),
        ])
      ),
    },
    getModuleModelsBySlot: {
      module: DECK_SETUP_UTILS,
      by_robot: {
        [FLEX_ROBOT_TYPE]: modelsBySlot(FLEX_ROBOT_TYPE, [
          ...FLEX_SINGLE_SLOT_ADDRESSABLE_AREAS,
          ...FLEX_STAGING_AREA_SLOT_ADDRESSABLE_AREAS,
        ]),
        [OT2_ROBOT_TYPE]: modelsBySlot(
          OT2_ROBOT_TYPE,
          OT2_SINGLE_SLOT_ADDRESSABLE_AREAS
        ),
      },
    },
    getAllModuleSlotsByTypeOt2: {
      module: MODULE_DATA,
      by_module_type: slotsByModuleType,
    },
  }
  writeFileSync(options.out, `${JSON.stringify(result, null, 2)}\n`)
}
