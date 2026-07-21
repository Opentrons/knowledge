# Versioning

Four independent version axes:

| Axis | Example | Meaning |
|------|---------|---------|
| Opentrons release | `v9.1.1` / `9.1.1` | Target robot software |
| Knowledge revision | `k1`, `k2` | Corpus rebuild for that release |
| Corpus schema version | `1` | Shape/meaning of canonical records |
| Builder version | `0.1.0` | Semantic version of this toolchain |

## Public Corpus Version

```text
<opentrons-release>-k<knowledge-revision>
```

Examples: `9.1.1-k1`, `9.1.1-k2`, `9.2.0-k1`.

Do **not** encode source commits in the public version. Exact source identity
belongs in the source manifest and corpus manifest.

Bump the knowledge revision when ingestion, chunking, relationships, indexes,
embeddings, annotations, or compatibility validation change the published
artifact for the same Opentrons release.

## Git Release Tag

```text
knowledge-v9.1.1-k1
```

## Published artifacts

```text
opentrons-knowledge-9.1.1-k1.tar.zst
ghcr.io/opentrons/opentrons-knowledge:9.1.1-k1
```

Published tags and release assets are immutable. Replacing a released filename
or OCI tag must not happen silently; bump the knowledge revision instead.
