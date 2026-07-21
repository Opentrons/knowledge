"""Thin helpers for opening a local corpus directory.

The product is the packaged corpus artifact. Retrieval/search belongs in
downstream consumers, not this library.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opentrons_knowledge.artifacts.package import inspect_corpus, validate_corpus_dir
from opentrons_knowledge.models.manifest import CorpusManifest
from opentrons_knowledge.normalization.serialize import read_jsonl_zst


class Corpus:
    """Opened local corpus directory (already built or unpacked from tar.zst)."""

    def __init__(self, root: Path, manifest: CorpusManifest) -> None:
        self.root = root
        self.manifest = manifest

    @classmethod
    def open(cls, path: str | Path) -> Corpus:
        root = Path(path)
        manifest = validate_corpus_dir(root)
        return cls(root, manifest)

    def verify(self) -> CorpusManifest:
        return validate_corpus_dir(self.root)

    def inspect(self) -> dict[str, Any]:
        return inspect_corpus(self.root)

    def sources(self) -> list[dict[str, Any]]:
        return [s.model_dump() for s in self.manifest.sources]


def diff_corpora(left: Path, right: Path) -> dict[str, Any]:
    """Compare two corpus directories; return structured diff."""
    left_c = Corpus.open(left)
    right_c = Corpus.open(right)

    def map_by(filename: str, key: str, root: Path) -> dict[str, dict[str, Any]]:
        return {row[key]: row for row in read_jsonl_zst(root / "corpus" / filename)}

    result: dict[str, Any] = {
        "left": left_c.manifest.version,
        "right": right_c.manifest.version,
        "sources": {
            "left": left_c.sources(),
            "right": right_c.sources(),
        },
        "builder": {
            "left": left_c.manifest.builder.model_dump(),
            "right": right_c.manifest.builder.model_dump(),
        },
        "schema_version": {
            "left": left_c.manifest.corpus_schema_version,
            "right": right_c.manifest.corpus_schema_version,
        },
        "embedding": {
            "left": left_c.manifest.embedding.model_dump(),
            "right": right_c.manifest.embedding.model_dump(),
        },
    }

    for filename, key, label in [
        ("documents.jsonl.zst", "document_id", "documents"),
        ("code-symbols.jsonl.zst", "symbol_id", "symbols"),
        ("entities.jsonl.zst", "entity_id", "entities"),
        ("relationships.jsonl.zst", "relationship_id", "relationships"),
        ("constraints.jsonl.zst", "constraint_id", "constraints"),
        ("examples.jsonl.zst", "example_id", "examples"),
    ]:
        left_map = map_by(filename, key, left_c.root)
        right_map = map_by(filename, key, right_c.root)
        added = sorted(set(right_map) - set(left_map))
        removed = sorted(set(left_map) - set(right_map))
        changed = sorted(
            item
            for item in set(left_map) & set(right_map)
            if json.dumps(left_map[item], sort_keys=True)
            != json.dumps(right_map[item], sort_keys=True)
        )
        result[label] = {"added": added, "removed": removed, "changed": changed}

    return result
