"""Protocol API AST and shared-data parsing tests."""

from __future__ import annotations

from pathlib import Path

from opentrons_knowledge.python_api.ast_symbols import ingest_protocol_api
from opentrons_knowledge.shared_data.entities import ingest_shared_data

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mini_sources"


def test_ast_extracts_public_methods_and_version_gates() -> None:
    bundle = ingest_protocol_api(
        FIXTURES,
        repository="https://github.com/Opentrons/opentrons",
        commit="0" * 40,
        configured_paths=["api/src/opentrons/protocol_api"],
        release="v9.1.1",
    )
    names = {s.qualified_name for s in bundle.symbols}
    assert "opentrons.protocol_api.instrument_context.InstrumentContext" in names
    aspirate = next(
        s for s in bundle.symbols if s.qualified_name.endswith("InstrumentContext.aspirate")
    )
    assert aspirate.minimum_api_version == "2.0"
    assert aspirate.docstring
    assert "volume" in {p.name for p in aspirate.parameters}
    assert "#L" in aspirate.source_url
    assert any(r.relationship_type == "class_contains_method" for r in bundle.relationships)


def test_shared_data_labware_entity() -> None:
    bundle = ingest_shared_data(
        FIXTURES,
        repository="https://github.com/Opentrons/opentrons",
        commit="0" * 40,
        configured_paths=["shared-data/labware/definitions"],
        release="v9.1.1",
    )
    assert len(bundle.entities) == 1
    entity = bundle.entities[0]
    assert entity.canonical_name == "corning_96_wellplate_360ul_flat"
    assert entity.entity_type.value == "labware"
    assert entity.raw_source is not None
    assert entity.properties["schema_version"] == "2"
