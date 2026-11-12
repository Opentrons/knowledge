"""Check Protocol Designer tables in the built corpus.

The corpus is the highest version under ``corpora/``. This reads that build.
It does not rebuild the tables and it does not substitute example data. A
missing package, a dropped key, or a changed value fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from opentrons_knowledge.corpora import highest_corpus_version
from opentrons_knowledge.normalization.serialize import load_yaml
from opentrons_knowledge.protocol_designer.tables import validate_tables

ROOT = Path(__file__).resolve().parents[2]
VERSION = highest_corpus_version(ROOT / "corpora")
CORPUS = ROOT / "dist" / f"opentrons-knowledge-{VERSION}"
TABLES = CORPUS / "corpus" / "protocol-designer"
RAW = CORPUS / "raw" / "protocol_designer"

_IDENTIFIER = re.compile(r"^[A-Z0-9_]+$|_TYPE$|_V\d+$")

FILES = [
    "labware-allowlist.json",
    "labware-compatible.json",
    "manifest.json",
    "module-limits.json",
    "module-models.json",
    "module-slots.json",
    "pipette-options.json",
    "recommended-labware.json",
]
RAW_PATHS = [
    "protocol-designer/src/constants.ts",
    "protocol-designer/src/modules/moduleData.ts",
    "protocol-designer/src/pages/Designer/DeckSetup/constants.ts",
    "protocol-designer/src/pages/Designer/DeckSetup/utils.ts",
    "protocol-designer/src/pages/Onboarding/constants.ts",
    "protocol-designer/src/utils/labwareModuleCompatibility.ts",
]
PIN = "677274a40c5d22044c4efe7365d4904a56eeefd4"
TAG = "protocol-designer@9.0.1"
SHARED_COMMIT = "e8c6d0a424c25fff1604e2a02e4ccaedac95b9af"

FLEX_STACKER = [
    "biorad_384_wellplate_50ul",
    "biorad_96_wellplate_200ul_pcr",
    "corning_24_wellplate_3.4ml_flat",
    "nest_96_wellplate_100ul_pcr_full_skirt",
    "nest_96_wellplate_200ul_flat",
    "nest_96_wellplate_2ml_deep",
    "opentrons_96_wellplate_200ul_pcr_full_skirt",
    "opentrons_flex_96_filtertiprack_1000ul",
    "opentrons_flex_96_filtertiprack_200ul",
    "opentrons_flex_96_filtertiprack_20ul",
    "opentrons_flex_96_filtertiprack_50ul",
    "opentrons_flex_96_tiprack_1000ul",
    "opentrons_flex_96_tiprack_200ul",
    "opentrons_flex_96_tiprack_20ul",
    "opentrons_flex_96_tiprack_50ul",
    "opentrons_tough_12_reservoir_22ml",
    "opentrons_tough_1_reservoir_300ml",
    "opentrons_tough_4_reservoir_72ml",
]
MODULE_TYPES = [
    "absorbanceReaderType",
    "flexStackerModuleType",
    "heaterShakerModuleType",
    "magneticBlockType",
    "magneticModuleType",
    "temperatureModuleType",
    "thermocyclerModuleType",
    "vacuumModuleType",
    "vacuumModuleTypeWithLabware",
]
LIMITS = {
    "MAX_ENGAGE_HEIGHT_V1": 45,
    "MAX_ENGAGE_HEIGHT_V2": 25,
    "MAX_HEATER_SHAKER_DURATION_SECONDS": 60,
    "MAX_HEATER_SHAKER_MODULE_RPM": 3000,
    "MAX_HEATER_SHAKER_MODULE_TEMP": 95,
    "MAX_MAGNETIC_BLOCKS": 10,
    "MAX_MOAM_MODULES": 7,
    "MAX_TC_BLOCK_TEMP": 99,
    "MAX_TC_DURATION_SECONDS": 60,
    "MAX_TC_LID_TEMP": 110,
    "MAX_TC_PROFILE_VOLUME": 100,
    "MAX_TEMP_MODULE_TEMP": 95,
    "MIN_ENGAGE_HEIGHT_V1": 0,
    "MIN_ENGAGE_HEIGHT_V2": -2.5,
    "MIN_HEATER_SHAKER_DURATION_SECONDS": 0,
    "MIN_HEATER_SHAKER_MODULE_RPM": 200,
    "MIN_HEATER_SHAKER_MODULE_TEMP": 20,
    "MIN_TC_BLOCK_TEMP": 4,
    "MIN_TC_DURATION_SECONDS": 0,
    "MIN_TC_LID_TEMP": 37,
    "MIN_TC_PROFILE_VOLUME": 0,
    "MIN_TEMP_MODULE_TEMP": 4,
}


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((TABLES / name).read_text(encoding="utf-8"))
    return data


def test_package_contains_the_raw_sources_and_the_json() -> None:
    assert sorted(path.name for path in TABLES.iterdir() if path.is_file()) == FILES
    manifest = _load("manifest.json")
    assert manifest["files"] == FILES
    assert manifest["schema_version"] == 1
    assert manifest["protocol_designer"] == {
        "commit": PIN,
        "repository": "https://github.com/Opentrons/opentrons",
        "tag": TAG,
    }
    assert manifest["labware_definitions"]["commit"] == SHARED_COMMIT
    assert manifest["labware_definitions"]["tag"] == "v10.0.0"
    packaged = sorted(path.relative_to(RAW).as_posix() for path in RAW.rglob("*.ts"))
    assert packaged == RAW_PATHS
    for rel in RAW_PATHS:
        assert (RAW / rel).stat().st_size > 0
    assert validate_tables(TABLES) == []


def test_flex_stacker_is_resolved_only_in_the_json() -> None:
    """The raw allowlist spreads the stacker list. The JSON has the 18 names."""
    tiprack = "opentrons_flex_96_filtertiprack_1000ul"
    allowlist_source = (
        RAW / "protocol-designer/src/utils/labwareModuleCompatibility.ts"
    ).read_text(encoding="utf-8")
    deck_source = (RAW / "protocol-designer/src/pages/Designer/DeckSetup/constants.ts").read_text(
        encoding="utf-8"
    )
    assert tiprack not in allowlist_source
    assert "RECOMMENDED_LABWARE_BY_MODULE[FLEX_STACKER_MODULE_TYPE]" in allowlist_source
    assert tiprack in deck_source
    allowlist = _load("labware-allowlist.json")["by_module_type"]
    recommended = _load("recommended-labware.json")["by_module_type"]
    assert list(allowlist) == MODULE_TYPES
    assert allowlist["flexStackerModuleType"] == FLEX_STACKER
    assert recommended["flexStackerModuleType"] == FLEX_STACKER


def test_allowlist_and_predicate_keep_their_differences() -> None:
    allowlist = _load("labware-allowlist.json")["by_module_type"]
    compatible = _load("labware-compatible.json")
    by_module = compatible["by_module_type"]
    assert list(by_module) == MODULE_TYPES
    assert allowlist["heaterShakerModuleType"] == [
        "opentrons_96_deep_well_adapter",
        "opentrons_96_flat_bottom_adapter",
        "opentrons_96_pcr_adapter",
        "opentrons_universal_flat_adapter",
        "opentrons_universal_flat_adapter_type_b",
    ]
    assert len(allowlist["temperatureModuleType"]) == 25
    assert "corning_96_wellplate_360ul_flat" in allowlist["temperatureModuleType"]
    assert allowlist["thermocyclerModuleType"] == [
        "biorad_96_wellplate_200ul_pcr",
        "nest_96_wellplate_100ul_pcr_full_skirt",
        "opentrons_96_wellplate_200ul_pcr_full_skirt",
    ]
    assert allowlist["vacuumModuleType"] == [
        "opentrons_96_wellplate_200ul_pcr_full_skirt",
        "opentrons_vacuum_module_gen1_collar_short",
        "opentrons_vacuum_module_gen1_collar_tall",
        "opentrons_vacuum_module_spacer_thingamajig",
    ]
    assert allowlist["absorbanceReaderType"] == [
        "opentrons_flex_lid_absorbance_plate_reader_module"
    ]
    assert len(by_module["absorbanceReaderType"]) == 23
    assert by_module["absorbanceReaderType"] != allowlist["absorbanceReaderType"]
    assert len(by_module["flexStackerModuleType"]) == 71
    assert set(FLEX_STACKER) <= set(by_module["flexStackerModuleType"])
    assert compatible["labware_definitions"]["count"] == 154
    assert compatible["adapter_96_channel"] == "opentrons_flex_96_tiprack_adapter"
    assert "opentrons_flex_96_tiprack_adapter" in compatible["by_adapter"]
    assert len(compatible["by_adapter"]) == 55


def test_models_slots_limits_and_pipettes() -> None:
    models = _load("module-models.json")
    assert models["flex"] == [
        "absorbanceReaderV1",
        "flexStackerModuleV1",
        "heaterShakerModuleV1",
        "magneticBlockV1",
        "temperatureModuleV2",
        "thermocyclerModuleV2",
        "vacuumModuleV1",
    ]
    assert models["flex_supported_models"] == [
        "absorbanceReaderV1",
        "heaterShakerModuleV1",
        "magneticBlockV1",
        "temperatureModuleV2",
        "thermocyclerModuleV2",
    ]
    assert "flexStackerModuleV1" not in models["flex_supported_models"]
    assert models["fixtures"] == [
        "stagingArea",
        "trashBin",
        "wasteChute",
        "wasteChuteAndStagingArea",
    ]
    assert models["moam_models_with_feature_flag"] == ["temperatureModuleV2"]
    slots = _load("module-slots.json")
    assert list(slots["models_by_slot"]) == ["OT-2 Standard", "OT-3 Standard"]
    flex = slots["models_by_slot"]["OT-3 Standard"]
    assert list(flex) == [
        "A1",
        "A2",
        "A3",
        "A4",
        "B1",
        "B2",
        "B3",
        "B4",
        "C1",
        "C2",
        "C3",
        "C4",
        "D1",
        "D2",
        "D3",
        "D4",
    ]
    assert [slot for slot, models_in_slot in flex.items() if not models_in_slot] == [
        "A4",
        "B4",
        "C4",
        "D4",
    ]
    assert flex["B1"] == [
        "heaterShakerModuleV1",
        "magneticBlockV1",
        "temperatureModuleV2",
        "thermocyclerModuleV2",
        "flexStackerModuleV1",
    ]
    assert slots["supported_slots_ot2"]["thermocyclerModuleType"] == [
        {"name": "7,8,10,11", "value": "7"}
    ]
    heater_shaker = [
        option["value"] for option in slots["slots_by_module_type_ot2"]["heaterShakerModuleType"]
    ]
    assert heater_shaker == ["1", "3", "4", "6", "7", "10"]
    assert "absorbanceReaderType" not in slots["slots_by_module_type_ot2"]
    assert slots["default_slots_flex"]["thermocyclerModuleV2"] == "B1"
    assert slots["default_slots_ot2"]["thermocyclerModuleType"] == "7"
    assert _load("module-limits.json")["limits"] == LIMITS
    pipettes = _load("pipette-options.json")
    assert pipettes["gens"] == ["GEN1", "GEN2"]
    assert [option["value"] for option in pipettes["by_robot"]["OT-3 Standard"]] == [
        "single",
        "multi",
        "96",
    ]
    assert [option["value"] for option in pipettes["by_robot"]["OT-2 Standard"]] == [
        "single",
        "multi",
    ]
    flex_volumes = pipettes["volumes"]["OT-3 Standard"][0]
    assert [item["value"] for item in flex_volumes["96"]] == ["p1000", "p200"]


def test_every_table_cites_the_pin_and_uses_runtime_keys() -> None:
    for name in FILES:
        if name == "manifest.json":
            continue
        source = _load(name)["source"]
        assert source["commit"] == PIN
        assert source["tag"] == TAG
        assert source["exports"]
    slots = _load("module-slots.json")
    models = _load("module-models.json")
    keys = set(MODULE_TYPES)
    keys |= set(slots["supported_slots_ot2"])
    keys |= set(slots["default_slots_flex"])
    keys |= set(slots["default_slots_ot2"])
    keys |= set(models["flex"]) | set(models["ot2"]) | set(models["supported_module_types"])
    assert not [key for key in keys if _IDENTIFIER.search(key)]


def test_record_counts_match_the_k5_package() -> None:
    """Entity, relationship, and retrieval counts stay at the k4 baseline."""
    manifest = load_yaml(CORPUS / "manifest.yaml")
    counts = manifest["record_counts"]
    assert counts["entities"] == 445
    assert counts["relationships"] == 29046
    assert counts["retrieval_documents"] == 1916
    assert counts["retrieval_chunks"] == 2063
    assert counts["raw_files"] == 1235
    assert counts["source_files"] == 1268
