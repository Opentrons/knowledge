"""Build cross-cutting relationships, constraints, and duplicate reports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from opentrons_knowledge.models.enums import ConstraintSeverity, DerivationMethod
from opentrons_knowledge.models.records import (
    CodeSymbol,
    Constraint,
    Document,
    Entity,
    Example,
    Relationship,
    Section,
)
from opentrons_knowledge.normalization.ids import constraint_id, relationship_id


@dataclass
class GraphBundle:
    relationships: list[Relationship] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    duplicates: list[dict[str, str]] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)


def build_knowledge_graph(
    *,
    documents: list[Document],
    sections: list[Section],
    symbols: list[CodeSymbol],
    entities: list[Entity],
    examples: list[Example],
    existing_relationships: list[Relationship],
) -> GraphBundle:
    """Derive relationships/constraints and detect simple duplicates."""
    bundle = GraphBundle(relationships=list(existing_relationships))

    symbols_by_name = {s.qualified_name: s for s in symbols}
    sections_by_doc: dict[str, list[Section]] = {}
    for section in sections:
        sections_by_doc.setdefault(section.document_id, []).append(section)

    # Link symbols mentioned in section plaintext / titles
    for section in sections:
        haystack = f"{section.title}\n{section.content_plaintext}"
        for qname, symbol in symbols_by_name.items():
            short = qname.rsplit(".", 1)[-1]
            if short in haystack or qname in haystack:
                rel = Relationship(
                    relationship_id=relationship_id(
                        "symbol_documented_by_section",
                        symbol.symbol_id,
                        section.section_id,
                    ),
                    source_id=symbol.symbol_id,
                    target_id=section.section_id,
                    relationship_type="symbol_documented_by_section",
                    confidence=0.7 if short in haystack else 1.0,
                    derivation_method=DerivationMethod.INFERRED,
                )
                bundle.relationships.append(rel)
                if section.section_id not in symbol.related_document_sections:
                    symbol.related_document_sections.append(section.section_id)

    # Examples using symbols
    for example in examples:
        for qname, symbol in symbols_by_name.items():
            short = qname.rsplit(".", 1)[-1]
            if re.search(rf"\b{re.escape(short)}\b", example.code):
                example.symbols_used.append(symbol.symbol_id)
                bundle.relationships.append(
                    Relationship(
                        relationship_id=relationship_id(
                            "example_uses_symbol",
                            example.example_id,
                            symbol.symbol_id,
                        ),
                        source_id=example.example_id,
                        target_id=symbol.symbol_id,
                        relationship_type="example_uses_symbol",
                        derivation_method=DerivationMethod.INFERRED,
                        confidence=0.6,
                    )
                )

    # Deprecated / version constraints from symbols
    for symbol in symbols:
        if symbol.deprecated:
            bundle.constraints.append(
                Constraint(
                    constraint_id=constraint_id("deprecated_symbol", [symbol.symbol_id]),
                    constraint_type="deprecated_symbol",
                    description=symbol.deprecation_message
                    or f"{symbol.qualified_name} is deprecated",
                    severity=ConstraintSeverity.WARNING,
                    subject_ids=[symbol.symbol_id],
                    derivation_method=DerivationMethod.DIRECT,
                    source_ids=[symbol.symbol_id],
                )
            )
        if symbol.minimum_api_version:
            bundle.constraints.append(
                Constraint(
                    constraint_id=constraint_id(
                        "minimum_api_version",
                        [symbol.symbol_id, symbol.minimum_api_version],
                    ),
                    constraint_type="minimum_api_version",
                    description=(
                        f"{symbol.qualified_name} requires API version "
                        f">= {symbol.minimum_api_version}"
                    ),
                    severity=ConstraintSeverity.ERROR,
                    subject_ids=[symbol.symbol_id],
                    condition={"minimum_api_version": symbol.minimum_api_version},
                    version_scope=symbol.minimum_api_version,
                    derivation_method=DerivationMethod.DIRECT,
                    source_ids=[symbol.symbol_id],
                )
            )

    # Duplicate detection by content hash
    seen_docs: dict[str, str] = {}
    for doc in documents:
        if doc.content_hash in seen_docs:
            bundle.duplicates.append(
                {
                    "record_type": "document",
                    "hash": doc.content_hash,
                    "left": seen_docs[doc.content_hash],
                    "right": doc.document_id,
                }
            )
        else:
            seen_docs[doc.content_hash] = doc.document_id

    seen_sections: dict[str, str] = {}
    for section in sections:
        if not section.content_plaintext:
            continue
        if section.content_hash in seen_sections:
            bundle.duplicates.append(
                {
                    "record_type": "section",
                    "hash": section.content_hash,
                    "left": seen_sections[section.content_hash],
                    "right": section.section_id,
                }
            )
        else:
            seen_sections[section.content_hash] = section.section_id

    # Deduplicate relationships by id
    unique: dict[str, Relationship] = {}
    for rel in bundle.relationships:
        unique[rel.relationship_id] = rel
    bundle.relationships = sorted(unique.values(), key=lambda r: r.relationship_id)

    # Entity load-name availability
    for entity in entities:
        if entity.entity_type.value in {"labware", "tip_rack"}:
            bundle.relationships.append(
                Relationship(
                    relationship_id=relationship_id(
                        "labware_available_by_load_name",
                        entity.entity_id,
                        entity.canonical_name,
                    ),
                    source_id=entity.entity_id,
                    target_id=entity.canonical_name,
                    relationship_type="labware_available_by_load_name",
                    derivation_method=DerivationMethod.DIRECT,
                )
            )

    return bundle
