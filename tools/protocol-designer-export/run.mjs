// Evaluates export.ts through Vite against a pinned Protocol Designer checkout.
//
//   node run.mjs --package <checkout>/protocol-designer \
//     --labware <shared-data/labware/definitions> --out <file.json>
//
// Aliases come from the package's tsconfig.json paths ("/protocol-designer/*")
// plus the @opentrons/shared-data source alias from its vite.config.mts.
// @opentrons/components is replaced by a stub: the evaluated modules import it
// only to style deck controls.
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

import { runnerImport } from 'vite'

const here = dirname(fileURLToPath(import.meta.url))

const { values } = parseArgs({
  options: {
    package: { type: 'string' },
    labware: { type: 'string' },
    out: { type: 'string' },
  },
})
if (values.package == null || values.labware == null || values.out == null) {
  throw new Error(
    'Usage: run.mjs --package <dir> --labware <definitions dir> --out <file>'
  )
}

const packageDir = resolve(values.package)
const tsconfig = JSON.parse(
  readFileSync(join(packageDir, 'tsconfig.json'), 'utf8')
)
const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const tsconfigAliases = Object.entries(tsconfig.compilerOptions.paths).map(
  ([pattern, [target]]) => {
    const star = pattern.indexOf('*')
    if (star === -1) {
      return { find: pattern, replacement: resolve(packageDir, target) }
    }
    return {
      find: new RegExp(
        `^${escape(pattern.slice(0, star))}(.*)${escape(pattern.slice(star + 1))}$`
      ),
      replacement: resolve(packageDir, target).replace('*', '$1'),
    }
  }
)

const { module } = await runnerImport(join(here, 'export.ts'), {
  configFile: false,
  root: packageDir,
  logLevel: 'error',
  resolve: {
    alias: [
      ...tsconfigAliases,
      {
        find: /^@opentrons\/shared-data$/,
        replacement: resolve(packageDir, '../shared-data/js/index.ts'),
      },
      {
        find: /^@opentrons\/step-generation$/,
        replacement: resolve(packageDir, '../step-generation/src/index.ts'),
      },
      {
        find: /^@opentrons\/components$/,
        replacement: join(here, 'stubs', 'opentrons-components.ts'),
      },
    ],
  },
})

module.exportTables({ labware: values.labware, out: values.out })
