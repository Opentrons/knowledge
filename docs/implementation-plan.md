# Implementation Plan

Status for the initial `9.1.1-k1` product: **implemented** (tar.zst + OCI/ORAS).

Built corpus counts (local directory before pack):

```text
documents 190 | sections ~1400+ | symbols ~1600 | entities ~450
relationships | examples | constraints | source_files
```

## Phase 1: Repository analysis — done

## Phase 2: Manifest and models — done

## Phase 3: Documentation ingestion — done

## Phase 4: Protocol API extraction — done

## Phase 5: Shared-data extraction — done

## Phase 6: Corpus assembly — done

## Phase 7: Indexes — done

## Phase 8: Packaging — done

Publication formats are `opentrons-knowledge-<version>.tar.zst` (GitHub Releases)
and `ghcr.io/opentrons/opentrons-knowledge:<version>` (ORAS/OCI).
No lookup consumer API; on-disk JSONL + indexes are the interface.

## Phase 9: CI and release automation — done

## Tradeoffs

- Docs pin uses `mkdocs-*` rather than `v9.1.1` commit (documented).
- AI v1 guides are monorepo paths pinned to the latest `ai-server@*` tag; `pd/` is excluded.
- Full 9.1.1 corpus build expects a local Opentrons checkout or network clone.
- CI default path builds a tiny fixture corpus for determinism.
- Vector indexes from remote embedding APIs are not guaranteed byte-identical.
