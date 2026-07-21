"""Lexical index generation for exact lookup."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from opentrons_knowledge.models.records import CodeSymbol, Entity, Section
from opentrons_knowledge.normalization.serialize import write_json


def build_lexical_index(
    output_dir: Path,
    *,
    symbols: list[CodeSymbol],
    entities: list[Entity],
    sections: list[Section],
) -> dict[str, Any]:
    """Write lexical lookup JSON files and return index stats."""
    output_dir.mkdir(parents=True, exist_ok=True)

    symbol_index: dict[str, list[str]] = defaultdict(list)
    for symbol in symbols:
        for term in {
            symbol.qualified_name,
            symbol.qualified_name.rsplit(".", 1)[-1],
            *(p.name for p in symbol.parameters),
        }:
            if term:
                symbol_index[term.lower()].append(symbol.symbol_id)

    entity_index: dict[str, list[str]] = defaultdict(list)
    for entity in entities:
        for term in {entity.canonical_name, entity.display_name, *entity.aliases}:
            if term:
                entity_index[term.lower()].append(entity.entity_id)

    terms: dict[str, list[str]] = defaultdict(list)
    for section in sections:
        for token in section.title.replace("/", " ").split():
            cleaned = token.strip(".,:;()[]{}").lower()
            if len(cleaned) >= 3:
                terms[cleaned].append(section.section_id)

    # Also index common API version / error-ish tokens from section plaintext
    for section in sections:
        text = section.content_plaintext.lower()
        for needle in ("api version", "deprecated", "flex", "ot-2", "tip rack", "labware"):
            if needle in text:
                terms[needle].append(section.section_id)

    symbols_path = output_dir / "symbols.json"
    entities_path = output_dir / "entities.json"
    terms_path = output_dir / "terms.json"
    write_json(symbols_path, {k: sorted(set(v)) for k, v in sorted(symbol_index.items())})
    write_json(entities_path, {k: sorted(set(v)) for k, v in sorted(entity_index.items())})
    write_json(terms_path, {k: sorted(set(v)) for k, v in sorted(terms.items())})

    return {
        "symbol_terms": len(symbol_index),
        "entity_terms": len(entity_index),
        "section_terms": len(terms),
        "files": [
            "indexes/lexical/symbols.json",
            "indexes/lexical/entities.json",
            "indexes/lexical/terms.json",
        ],
    }
