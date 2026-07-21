"""Embedding provider abstraction and vector index writing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from opentrons_knowledge.models.manifest import EmbeddingInfo
from opentrons_knowledge.models.records import CodeSymbol, Constraint, Entity, Example, Section
from opentrons_knowledge.normalization.ids import content_hash
from opentrons_knowledge.normalization.serialize import write_jsonl_zst, write_yaml


class EmbeddingProvider(Protocol):
    """Provider-neutral embedding interface."""

    name: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts; must return one vector per input."""


class EmbeddingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_id: str
    source_record_id: str
    record_type: str
    provider: str
    model: str
    dimensions: int
    preprocessing_version: int
    content_hash: str
    vector: list[float]


@dataclass
class FakeEmbeddingProvider:
    """Deterministic embedding provider for tests and offline builds."""

    name: str = "fake"
    model: str = "fake-hash-v1"
    dimensions: int = 32

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            # Expand digest into fixed dimensions deterministically.
            values: list[float] = []
            seed = digest
            while len(values) < self.dimensions:
                for byte in seed:
                    values.append((byte / 255.0) * 2.0 - 1.0)
                    if len(values) >= self.dimensions:
                        break
                seed = hashlib.sha256(seed).digest()
            vectors.append(values)
        return vectors


def build_vector_index(
    output_dir: Path,
    *,
    sections: list[Section],
    symbols: list[CodeSymbol],
    entities: list[Entity],
    constraints: list[Constraint],
    examples: list[Example],
    embedding: EmbeddingInfo,
    provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    """Generate embeddings for retrieval units when enabled."""
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_path = output_dir / "meta.yaml"

    if not embedding.enabled:
        write_yaml(
            meta_path,
            {
                "enabled": False,
                "reason": "embedding.disabled-in-manifest",
            },
        )
        return {"enabled": False, "embedding_count": 0}

    if provider is None:
        if embedding.provider in {None, "fake"}:
            provider = FakeEmbeddingProvider(
                dimensions=embedding.dimensions or 32,
                model=embedding.model or "fake-hash-v1",
            )
        else:
            write_yaml(
                meta_path,
                {
                    "enabled": False,
                    "reason": f"provider-not-configured:{embedding.provider}",
                },
            )
            return {
                "enabled": False,
                "embedding_count": 0,
                "warning": f"No provider implementation for {embedding.provider}",
            }

    units: list[tuple[str, str, str]] = []
    for section in sections:
        summary = f"{section.title}\n{section.content_plaintext}"[:4000]
        units.append((section.section_id, "section", summary))
    for symbol in symbols:
        summary = f"{symbol.qualified_name}\n{symbol.signature}\n{symbol.docstring or ''}"[:4000]
        units.append((symbol.symbol_id, "symbol", summary))
    for entity in entities:
        summary = f"{entity.entity_type}:{entity.canonical_name}\n{entity.display_name}"[:2000]
        units.append((entity.entity_id, "entity", summary))
    for constraint in constraints:
        units.append((constraint.constraint_id, "constraint", constraint.description[:2000]))
    for example in examples:
        summary = f"{example.title}\n{example.code}"[:4000]
        units.append((example.example_id, "example", summary))

    vectors = provider.embed([text for _, _, text in units])
    records: list[EmbeddingRecord] = []
    for (record_id, record_type, text), vector in zip(units, vectors, strict=True):
        records.append(
            EmbeddingRecord(
                embedding_id=f"emb:{record_id}",
                source_record_id=record_id,
                record_type=record_type,
                provider=provider.name,
                model=provider.model,
                dimensions=provider.dimensions,
                preprocessing_version=embedding.preprocessing_version,
                content_hash=content_hash(text),
                vector=vector,
            )
        )

    emb_path = output_dir / "embeddings.jsonl.zst"
    count, _digest = write_jsonl_zst(emb_path, records)
    write_yaml(
        meta_path,
        {
            "enabled": True,
            "provider": provider.name,
            "model": provider.model,
            "dimensions": provider.dimensions,
            "preprocessing_version": embedding.preprocessing_version,
            "embedding_count": count,
            "byte_identical_note": (
                "Canonical corpus files are deterministic. Vector bytes are deterministic "
                "only for the fake provider; external APIs may differ."
            ),
        },
    )
    return {
        "enabled": True,
        "embedding_count": count,
        "provider": provider.name,
        "model": provider.model,
        "dimensions": provider.dimensions,
    }
