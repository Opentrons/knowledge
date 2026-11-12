# Search tools for an Opentrons Knowledge corpus

From `10.0.0-k3`, a corpus ships two indexes under `retrieval/`. Register **two
tools**, one per index. Each tool's description below is what you give the
agent: the data that index holds, and the query that index expects.

| Tool | Reads | Holds |
|---|---|---|
| `search_api` | `retrieval/api/bm25/` | One section per documented Python Protocol API symbol. |
| `search_docs` | `retrieval/docs/bm25/` | How-to sections, manuals, and labware, pipette, and module records. |

Do not register a third tool that merges them. When a question needs both a
signature and a procedure, call `search_api` and `search_docs` separately.
Each list is best first. A score from one list is BM25 for that index only.
Do not compare a number from `search_api` with a number from `search_docs`.

Join every hit to `retrieval/documents.jsonl.zst` on `retrieval_id` for
`url`, `source_url`, `heading_path`, `api_name`, and `load_name`. Cite `url`
and `source_url`, and the corpus version from `manifest.yaml`.

A hit's `text` is the whole section under that heading. Tabs and long pages
are stored as more than one chunk; the text you read still includes every
chunk of the section that matched. The scored unit is a row in
`retrieval/chunks.jsonl.zst`.

The tokenizer lowercases and splits on punctuation and underscores. It does not
stem: `loading` and `load` are different words. CamelCase is also stored split
(`InstrumentContext` matches `instrument context`), but the reliable API query
is the documented name, not the split words.

These two indexes do not contain the curated AI v1 guides or the raw
code-symbol records. Those were measured and left out of search. Protocol
Designer compatibility tables (`corpus/protocol-designer/`, from `10.0.0-k5`)
are JSON files, not search chunks. Read them directly.

## `search_api`

Use this for a class, method, property, parameter, or return value in the
Python Protocol API.

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

Examples that hit the defining section:

| You need | Query |
|---|---|
| The blow-out method | `InstrumentContext.blow_out` |
| Every `load_labware` | `load_labware` |
| The pipette class | `InstrumentContext` |
| The Heater-Shaker class, not its methods | `HeaterShakerContext` |
| `Location`, which is also an ordinary word | `opentrons.types.Location` |

If you do not know the method name either, a short description still searches
the section text (`blow out extra air`). When a hit shows the name, call the
tool again with that method name, or with `Class.method`, and use that hit.

## `search_docs`

Use this for a procedure, a robot or hardware fact, a labware load name, or a
module.

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

Examples:

| You need | Query |
|---|---|
| Load a Flex pipette | `load pipette Flex left mount` |
| 96-channel load name | `flex 96 channel pipette load name` |
| A tip rack's load name | `opentrons_96_tiprack_300ul` |
| Heater-shaker latch | `heater shaker latch` |
| The Heater-Shaker module page | `heater shaker module` |

## Which tool

| Question | Tool |
|---|---|
| What arguments does `aspirate` take? | `search_api`: `InstrumentContext.aspirate` |
| How do I pick up one column of tips? | `search_docs`: `partial tip pickup column` |
| Both the steps and the signature | Call `search_docs` and `search_api` as two calls. |
| Does this labware exist, and what is its load name? | `search_docs` with the load name or the product name |

Do not send a paragraph. Do not combine a symbol and a procedure in one query.
If the first docs hit is a how-to and you needed the signature, call `search_api`.

## For consumers

A consumer can create a fused search that returns documents from both indexes
together, and would probably do that after its own embedding and re-ranking.
