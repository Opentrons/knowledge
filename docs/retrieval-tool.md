# Search tools for an Opentrons Knowledge corpus

From `10.0.0-k3`, a corpus ships two indexes under `retrieval/`. Register them
as two tools. One blended search makes symbol lookup and how-to questions
compete, and the shorter page that merely mentions a method wins.

Both tools return passages. Cite `url` and `source_url` from the document, and
the corpus version from `manifest.yaml`.

The tokenizer lowercases and splits on punctuation and underscores. It does not
stem: `loading` and `load` are different words. CamelCase is also stored split
(`InstrumentContext` matches `instrument context`), but the reliable API query
is the documented name, not the split words.

## `search_api`

Use this for a class, method, parameter, or return value in the Python Protocol
API.

```text
name: search_api
description: |
  Look up one symbol in the Opentrons Python Protocol API reference for this
  corpus version. Pass the symbol, not a sentence.
  Best query: Class.method, for example InstrumentContext.blow_out or
  ProtocolContext.load_module. Also accepted: the full public name
  (opentrons.protocol_api.InstrumentContext.blow_out) or the member name alone
  (blow_out), which returns every class that defines it.
  Do not prefix opentrons.protocol_api. Do not ask "how do I".
  The first hit for Class.method is that reference section: signature,
  parameters, and version notes. Read text. Cite url.
parameters:
  query: string, required. The symbol, as Class.method when you know the class.
```

Examples that hit the defining section:

| You need | Query |
|---|---|
| The blow-out method | `InstrumentContext.blow_out` |
| Every `load_labware` | `load_labware` |
| The pipette class | `InstrumentContext` |
| `Location`, which is also an ordinary word | `opentrons.types.Location` |

If you do not know the name, a short description still searches the section
text (`blow out extra air`). When you learn the name from a result, call the
tool again with `Class.method` and use that hit.

## `search_docs`

Use this for a procedure, a robot or hardware fact, a labware load name, or a
module.

```text
name: search_docs
description: |
  Search Opentrons how-to docs and the labware, pipette, and module records
  for this corpus version. Pass the words a heading or a load name would use,
  not a full sentence. Drop "how do I", "what is", and "please".
  The index does not stem, so use the docs' own words: "load a pipette",
  "partial tip pickup", "heater shaker latch".
  For labware, include the load name when you know it
  (opentrons_96_tiprack_300ul) or the product name
  (NEST 12 well reservoir).
  One question per call. Read the heading path on each hit. Cite url.
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

## Which tool

| Question | Tool |
|---|---|
| What arguments does `aspirate` take? | `search_api`: `InstrumentContext.aspirate` |
| How do I pick up one column of tips? | `search_docs`: `partial tip pickup column` |
| Both the steps and the signature | Call both. The how-to and the reference are different pages. |
| Does this labware exist, and what is its load name? | `search_docs` with the load name or the product name |

Do not send a paragraph. Do not combine a symbol and a procedure in one query.
If the first hit is a how-to and you needed the signature, call `search_api`.
