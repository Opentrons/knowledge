# Search tools for an Opentrons Knowledge corpus

From `10.0.0-k3`, a corpus ships two indexes under `retrieval/`: the Python API
reference (`api/bm25/`) and everything else (`docs/bm25/`). Register three
tools over them:

| Tool | Reads | Use it for |
|---|---|---|
| `search_api` | `retrieval/api/bm25/` | One symbol: a class, method, parameter, or return value. |
| `search_docs` | `retrieval/docs/bm25/` | A procedure, hardware fact, labware load name, or module. |
| `search_all` | Both indexes, merged | When you do not know which one answers the question. |

Each tool returns passages. Cite `url` and `source_url` from the document, and
the corpus version from `manifest.yaml`.

A hit's `text` is the whole section under that heading. Tabs and long pages
are stored as more than one chunk; the text you read still includes every
chunk of the section that matched.

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

## `search_all`

Use this when the question could be a signature or a procedure, or when you
want the first answer without choosing an index. It runs both searches and
returns one ranked list. Each hit has an `index` field: `api` for a reference
section, `docs` for a how-to page or a labware, pipette, or module record.

```text
name: search_all
description: |
  Search the Opentrons Python Protocol API reference and the how-to docs
  together for this corpus version, and return one ranked list. Each hit has
  an index field: "api" is a reference section, "docs" is a how-to page or a
  labware, pipette, or module record.
  For a symbol, pass Class.method alone (InstrumentContext.blow_out). That
  symbol's reference section comes first.
  For a question, pass a few words from a heading or a load name, not a
  sentence. Drop "how do I" and "what is".
  Do not mix a symbol and a question in one query. Read the heading path on
  each hit. Cite url.
parameters:
  query: string, required. One symbol, or a few words from a heading.
```

How the order works, so you can read it:

- A single token that names a symbol (`InstrumentContext.blow_out`, `blow_out`)
  puts that symbol's reference section first.
- A query of several words ranks how-to docs first. Reference sections follow
  below them.
- A bare member name (`load_labware`) can match more than one class. The first
  hit is one of them, so call `search_api` with `Class.method` for a specific
  class.
- Scores are fused ranks. Compare order within one result list, not the number
  across calls.

Examples:

| You need | Query | Expect |
|---|---|---|
| The blow-out method | `InstrumentContext.blow_out` | `api` first |
| The labware with a load name | `opentrons_96_tiprack_300ul` | `docs` first |
| A procedure with no known name | `blow out extra air` | `docs` first |

## Which tool

| Question | Tool |
|---|---|
| What arguments does `aspirate` take? | `search_api`: `InstrumentContext.aspirate` |
| How do I pick up one column of tips? | `search_docs`: `partial tip pickup column` |
| Not sure whether the answer is a signature or a how-to | `search_all` with a few heading words |
| Both the steps and the signature | Call `search_docs` and `search_api` separately. The how-to and the reference are different pages, and one merged list can show only one of them near the top. |
| Does this labware exist, and what is its load name? | `search_docs` with the load name or the product name |

Do not send a paragraph. Do not combine a symbol and a procedure in one query.
If the first hit is a how-to and you needed the signature, call `search_api`.
</contents>
