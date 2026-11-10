"""Protocol API AST and shared-data parsing tests."""

from __future__ import annotations

import json
from pathlib import Path

from opentrons_knowledge.python_api.ast_symbols import ingest_protocol_api
from opentrons_knowledge.retrieval.documents import entity_documents
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
    assert entity.robot_scope == ["flex", "ot-2"]


def _write_json(root: Path, relative: str, payload: dict[str, object]) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_schema_files_and_labware_fixtures_are_not_entities(tmp_path: Path) -> None:
    """Schema documents and schema3test fixtures must not become entities."""
    for schema in ("1", "2", "3"):
        _write_json(tmp_path, f"shared-data/module/schemas/{schema}.json", {"title": schema})
    for schema in ("1", "2", "3", "4", "5"):
        _write_json(tmp_path, f"shared-data/deck/schemas/{schema}.json", {"title": schema})
    _write_json(tmp_path, "shared-data/robot/schemas/1.json", {"title": "robot"})
    _write_json(
        tmp_path,
        "shared-data/pipette/schemas/1/pipetteModelSpecsSchema.json",
        {"title": "pipetteModelSpecsSchema"},
    )
    _write_json(
        tmp_path,
        "shared-data/module/definitions/1.json",
        {"magdeck": {"displayName": "Magnetic Module", "loadName": "magdeck"}},
    )
    _write_json(
        tmp_path,
        "shared-data/labware/definitions/3/schema3test_96_wellplate_360ul_flat/999.json",
        {
            "metadata": {"displayName": "Schema 3 Test Plate"},
            "parameters": {
                "loadName": "schema3test_96_wellplate_360ul_flat",
                "isTiprack": False,
            },
            "namespace": "opentrons",
            "version": 999,
            "wells": {"A1": {}},
        },
    )
    _write_json(
        tmp_path,
        "shared-data/labware/definitions/2/nest_12_reservoir_15ml/1.json",
        {
            "metadata": {"displayName": "NEST 12 Well Reservoir 15 mL"},
            "parameters": {"loadName": "nest_12_reservoir_15ml", "isTiprack": False},
            "namespace": "opentrons",
            "version": 1,
            "wells": {"A1": {}},
        },
    )
    _write_json(
        tmp_path,
        "shared-data/labware/definitions/2/opentrons_96_tiprack_300ul/1.json",
        {
            "metadata": {"displayName": "Opentrons 96 Tip Rack 300 µL"},
            "parameters": {"loadName": "opentrons_96_tiprack_300ul", "isTiprack": True},
            "namespace": "opentrons",
            "version": 1,
            "wells": {"A1": {}},
        },
    )
    _write_json(
        tmp_path,
        "shared-data/labware/definitions/2/opentrons_flex_96_tiprack_1000ul/1.json",
        {
            "metadata": {"displayName": "Opentrons Flex 96 Tip Rack 1000 µL"},
            "parameters": {"loadName": "opentrons_flex_96_tiprack_1000ul", "isTiprack": True},
            "namespace": "opentrons",
            "version": 1,
            "wells": {"A1": {}},
        },
    )
    _write_json(
        tmp_path,
        "shared-data/pipette/definitions/2/general/eight_channel_em/p1000/3_1.json",
        {
            "displayName": "FLEX 8-Channel EM 1000 µL",
            "displayCategory": "FLEX",
            "channels": 8,
        },
    )
    _write_json(
        tmp_path,
        "shared-data/pipette/definitions/2/general/ninety_six_channel/p1000/1_0.json",
        {
            "displayName": "P1000 96-Channel",
            "displayCategory": "GEN1",
            "channels": 96,
        },
    )
    _write_json(
        tmp_path,
        "shared-data/pipette/definitions/2/general/single_channel/p300/2_0.json",
        {
            "displayName": "P300 Single-Channel GEN2",
            "displayCategory": "GEN2",
            "channels": 1,
        },
    )
    _write_json(
        tmp_path,
        "shared-data/module/definitions/3/heaterShakerModuleV1.json",
        {
            "model": "heaterShakerModuleV1",
            "displayName": "Heater-Shaker Module GEN1",
            "moduleType": "heaterShakerModuleType",
            "incompatibleWithDecks": [],
            "orientation": {"1": "left", "11": "center", "A1": "left", "D4": "right"},
        },
    )
    _write_json(
        tmp_path,
        "shared-data/module/definitions/3/magneticBlockV1.json",
        {
            "model": "magneticBlockV1",
            "displayName": "Magnetic Block GEN1",
            "incompatibleWithDecks": [],
            "orientation": {"A1": "center", "D3": "center"},
        },
    )
    _write_json(
        tmp_path,
        "shared-data/module/definitions/3/thermocyclerModuleV1.json",
        {
            "model": "thermocyclerModuleV1",
            "displayName": "Thermocycler Module GEN1",
            "incompatibleWithDecks": ["ot3_standard"],
            "orientation": {"7": "left"},
        },
    )
    _write_json(
        tmp_path,
        "shared-data/module/definitions/2/temperatureModuleV1.json",
        {
            "model": "temperatureModuleV1",
            "displayName": "Temperature Module GEN1",
            "moduleType": "temperatureModuleType",
        },
    )
    _write_json(
        tmp_path,
        "shared-data/deck/definitions/3/ot2_standard.json",
        {"otId": "ot2_standard", "robot": {"model": "OT-2 Standard"}},
    )
    _write_json(tmp_path, "shared-data/robot/definitions/1/ot2.json", {"displayName": "OT-2"})

    bundle = ingest_shared_data(
        tmp_path,
        repository="https://github.com/Opentrons/opentrons",
        commit="0" * 40,
        configured_paths=["shared-data"],
        release="v10.0.0",
    )
    names = {entity.canonical_name for entity in bundle.entities}
    assert names.isdisjoint(
        {
            "1",
            "2",
            "3",
            "4",
            "5",
            "pipetteModelSpecsSchema",
            "schema3test_96_wellplate_360ul_flat",
        }
    )
    assert "heaterShakerModuleV1" in names
    assert "ot2_standard" in names
    excluded = {record.path for record in bundle.source_files if record.status == "excluded"}
    assert "shared-data/module/definitions/1.json" in excluded
    assert "shared-data/pipette/schemas/1/pipetteModelSpecsSchema.json" in excluded
    assert (
        "shared-data/labware/definitions/3/schema3test_96_wellplate_360ul_flat/999.json" in excluded
    )

    scopes = {entity.canonical_name: entity.robot_scope for entity in bundle.entities}
    assert scopes["nest_12_reservoir_15ml"] == ["flex", "ot-2"]
    assert scopes["opentrons_96_tiprack_300ul"] == ["flex", "ot-2"]
    assert scopes["opentrons_flex_96_tiprack_1000ul"] == ["flex"]
    assert scopes["heaterShakerModuleV1"] == ["flex", "ot-2"]
    assert scopes["magneticBlockV1"] == ["flex"]
    assert scopes["thermocyclerModuleV1"] == ["ot-2"]
    assert scopes["temperatureModuleV1"] == ["flex", "ot-2"]

    by_display = {entity.display_name: entity.robot_scope for entity in bundle.entities}
    assert by_display["FLEX 8-Channel EM 1000 µL"] == ["flex"]
    assert by_display["P1000 96-Channel"] == ["flex"]
    assert by_display["P300 Single-Channel GEN2"] == ["ot-2"]

    documents = {doc.retrieval_id: doc for doc in entity_documents(bundle.entities)}
    em = documents["pipette:eight_channel_em/p1000/v3"]
    assert em.robot_types == ["flex"]
    assert "Opentrons Flex" in em.text
    assert "OT-2" not in em.text
    assert documents["pipette:ninety_six_channel/p1000/v1"].robot_types == ["flex"]
    assert documents["pipette:single_channel/p300/v2"].robot_types == ["ot-2"]
    assert documents["labware:opentrons_flex_96_tiprack_1000ul"].robot_types == ["flex"]
    assert documents["labware:opentrons_96_tiprack_300ul"].robot_types == ["flex", "ot-2"]
    assert documents["module:magneticBlockV1"].robot_types == ["flex"]
    assert documents["module:heaterShakerModuleV1"].robot_types == ["flex", "ot-2"]
