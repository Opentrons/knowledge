"""Search the built corpus and require the whole section back.

The corpus is the highest version under ``corpora/``. These queries are ones
where the winning chunk is only part of its section: the heading piece, or a
later tab. The passage must still contain every chunk of that section. Skipped
when that corpus has not been built.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from opentrons_knowledge.corpora import highest_corpus_version
from opentrons_knowledge.normalization.serialize import read_jsonl_zst
from opentrons_knowledge.retrieval.bm25 import lookup_query, search, search_api
from opentrons_knowledge.retrieval.both import search_both
from opentrons_knowledge.retrieval.bundle import open_index
from opentrons_knowledge.retrieval.passages import chunk_body, passages_for_hits

ROOT = Path(__file__).resolve().parents[2]
VERSION = highest_corpus_version(ROOT / "corpora")
BUNDLE = ROOT / "dist" / f"opentrons-knowledge-{VERSION}" / "retrieval"

pytestmark = pytest.mark.skipif(
    not (BUNDLE / "docs" / "bm25").is_dir(),
    reason=f"build dist/opentrons-knowledge-{VERSION} to check full-section search results",
)

# (query, retrieval_id). Each query's top hit is this section, and that hit's
# chunk is not the whole section.
DOCS_CASES = [
    ("Flex exclusive features", "doc:flex/introduction/#flex-exclusive-features"),
    ("Heater Shaker Error Codes", "doc:heater-shaker/error-codes/"),
    (
        "Absorbance Plate Reader Module steps",
        "doc:protocol-designer/steps/module/#absorbance-plate-reader-module-steps",
    ),
    ("Module load names", "doc:python-api/adapting-ot2-flex/#module-load-names"),
    (
        "Pipettes and tip rack load names",
        "doc:python-api/adapting-ot2-flex/#pipettes-and-tip-rack-load-names",
    ),
    (
        "Creating a dummy protocol",
        "doc:python-api/advanced-control/jupyter/#creating-a-dummy-protocol",
    ),
    (
        "Aspirate by well or location",
        "doc:python-api/building-block-commands/liquids/#aspirate-by-well-or-location",
    ),
    (
        "Dispense by well or location",
        "doc:python-api/building-block-commands/liquids/#dispense-by-well-or-location",
    ),
    ("Blow out", "doc:python-api/complex-commands/parameters/#blow-out-complex"),
    ("Advanced method", "doc:python-api/examples/#advanced-method"),
    ("Basic method", "doc:python-api/examples/#basic-method"),
    ("Multiple air gaps", "doc:python-api/examples/#multiple-air-gaps"),
    ("Plate mapping", "doc:python-api/examples/#plate-mapping"),
    ("Liquid Class Properties", "doc:python-api/liquid-classes/properties/"),
    (
        "Loading modules onto the deck",
        "doc:python-api/modules/setup/#loading-modules-onto-the-deck",
    ),
    ("Temperature control", "doc:python-api/modules/temperature-module/#temperature-control"),
    ("Block max volume", "doc:python-api/modules/thermocycler/#block-max-volume"),
    ("Lid control", "doc:python-api/modules/thermocycler/#lid-control"),
    ("Ramp rate", "doc:python-api/modules/thermocycler/#ramp-rate"),
    ("Timing temperature holds", "doc:python-api/modules/thermocycler/#timing-temperature-holds"),
    ("API load names", "doc:python-api/pipettes/loading/#api-load-names"),
    (
        "Partial column layout",
        "doc:python-api/pipettes/partial-tip-pickup/#partial-column-layout",
    ),
    ("Version 2.14", "doc:python-api/versioning/#version-214"),
    ("Thermocycler Error Codes", "doc:thermocycler/error-codes/"),
    ("How the API works", "doc:python-api/#how-the-api-works"),
]

API_CASES = [
    (
        "FlexStackerContext.set_stored_labware",
        "doc:python-api/reference/flex-stacker/#opentrons.protocol_api.FlexStackerContext.set_stored_labware",
    ),
    (
        "InstrumentContext.dispense",
        "doc:python-api/reference/instruments/#opentrons.protocol_api.InstrumentContext.dispense",
    ),
    (
        "InstrumentContext.pick_up_tip",
        "doc:python-api/reference/instruments/#opentrons.protocol_api.InstrumentContext.pick_up_tip",
    ),
    (
        "ProtocolContext.load_labware",
        "doc:python-api/reference/protocols/#opentrons.protocol_api.ProtocolContext.load_labware",
    ),
    (
        "opentrons.simulate.simulate",
        "doc:python-api/reference/execute-simulate/#opentrons.simulate.simulate",
    ),
    (
        "InstrumentContext.dynamic_mix",
        "doc:python-api/reference/instruments/#opentrons.protocol_api.InstrumentContext.dynamic_mix",
    ),
    (
        "opentrons.execute.execute",
        "doc:python-api/reference/execute-simulate/#opentrons.execute.execute",
    ),
    (
        "FlexStackerContext.set_stored_labware_items",
        "doc:python-api/reference/flex-stacker/#opentrons.protocol_api.FlexStackerContext.set_stored_labware_items",
    ),
    (
        "ProtocolContext.load_lid_stack",
        "doc:python-api/reference/protocols/#opentrons.protocol_api.ProtocolContext.load_lid_stack",
    ),
    (
        "opentrons.simulate.get_protocol_api",
        "doc:python-api/reference/execute-simulate/#opentrons.simulate.get_protocol_api",
    ),
    (
        "ProtocolContext.move_lid",
        "doc:python-api/reference/protocols/#opentrons.protocol_api.ProtocolContext.move_lid",
    ),
    (
        "ThermocyclerContext.set_block_temperature",
        "doc:python-api/reference/thermocycler/#opentrons.protocol_api.ThermocyclerContext.set_block_temperature",
    ),
    (
        "Well.from_center_cartesian",
        "doc:python-api/reference/wells-liquids/#opentrons.protocol_api.Well.from_center_cartesian",
    ),
    (
        "Labware.set_offset",
        "doc:python-api/reference/labware/#opentrons.protocol_api.Labware.set_offset",
    ),
    (
        "AbsorbanceReaderContext.read",
        "doc:python-api/reference/absorbance-plate-reader/#opentrons.protocol_api.AbsorbanceReaderContext.read",
    ),
    (
        "FlexStackerContext.get_max_storable_labware_from_list",
        "doc:python-api/reference/flex-stacker/#opentrons.protocol_api.FlexStackerContext.get_max_storable_labware_from_list",
    ),
    (
        "ThermocyclerContext.start_set_block_temperature",
        "doc:python-api/reference/thermocycler/#opentrons.protocol_api.ThermocyclerContext.start_set_block_temperature",
    ),
    (
        "Labware.load_lid_stack",
        "doc:python-api/reference/labware/#opentrons.protocol_api.Labware.load_lid_stack",
    ),
    (
        "MagneticModuleContext.engage",
        "doc:python-api/reference/magnetic-module/#opentrons.protocol_api.MagneticModuleContext.engage",
    ),
    (
        "AbsorbanceReaderContext.initialize",
        "doc:python-api/reference/absorbance-plate-reader/#opentrons.protocol_api.AbsorbanceReaderContext.initialize",
    ),
    (
        "CSVParameter.parse_as_csv",
        "doc:python-api/reference/types/#opentrons.protocol_api.CSVParameter.parse_as_csv",
    ),
    (
        "Labware.parent",
        "doc:python-api/reference/labware/#opentrons.protocol_api.Labware.parent",
    ),
    (
        "ThermocyclerContext.start_execute_profile",
        "doc:python-api/reference/thermocycler/#opentrons.protocol_api.ThermocyclerContext.start_execute_profile",
    ),
    (
        "RobotContext.move_axes_to",
        "doc:python-api/reference/robot-motors/#opentrons.protocol_api.RobotContext.move_axes_to",
    ),
    (
        "RobotContext.move_to",
        "doc:python-api/reference/robot-motors/#opentrons.protocol_api.RobotContext.move_to",
    ),
]


@pytest.fixture(scope="module")
def corpus() -> dict[str, Any]:
    chunks = {row["chunk_id"]: row for row in read_jsonl_zst(BUNDLE / "chunks.jsonl.zst")}
    by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks.values():
        by_section[chunk["retrieval_id"]].append(chunk)
    return {
        "documents": {
            row["retrieval_id"]: row for row in read_jsonl_zst(BUNDLE / "documents.jsonl.zst")
        },
        "chunks": chunks,
        "by_section": by_section,
        "api": open_index(BUNDLE, "api"),
        "docs": open_index(BUNDLE, "docs"),
    }


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize(("query", "retrieval_id"), DOCS_CASES, ids=[q for q, _id in DOCS_CASES])
def test_docs_search_returns_every_chunk_of_the_section(
    query: str, retrieval_id: str, corpus: dict[str, Any]
) -> None:
    found = search(corpus["docs"], query, 8)
    passage = passages_for_hits(found, corpus["chunks"], limit=1)[0]
    assert passage.retrieval_id == retrieval_id
    flat = _flat(passage.text)
    section = corpus["by_section"][retrieval_id]
    assert len(section) > 1
    for chunk in section:
        assert _flat(chunk_body(chunk["text"])) in flat
    document = _flat(corpus["documents"][retrieval_id]["text"])
    assert document[:90] in flat
    assert document[-90:] in flat


@pytest.mark.parametrize(("query", "retrieval_id"), API_CASES, ids=[q for q, _id in API_CASES])
def test_api_search_returns_the_whole_symbol_section(
    query: str, retrieval_id: str, corpus: dict[str, Any]
) -> None:
    found = search_api(corpus["api"], query, 5)
    passage = passages_for_hits(found, corpus["chunks"], limit=1)[0]
    assert passage.retrieval_id == retrieval_id
    document = corpus["documents"][retrieval_id]
    assert document["text"] in passage.text
    assert len(corpus["by_section"][retrieval_id]) == 1


def test_search_both_keeps_each_index_in_its_own_list(corpus: dict[str, Any]) -> None:
    """Both lists come back, each within the limit, and each holds only its own index."""
    both = search_both(
        "blow out extra air", corpus["api"], corpus["docs"], corpus["chunks"], limit=5
    )
    assert 0 < len(both.api) <= 5
    assert 0 < len(both.docs) <= 5
    for passage in both.api:
        assert corpus["documents"][passage.retrieval_id].get("api_name")
    for passage in both.docs:
        assert not corpus["documents"][passage.retrieval_id].get("api_name")
    assert (
        both.api[0].retrieval_id
        == "doc:python-api/reference/instruments/#opentrons.protocol_api.InstrumentContext.blow_out"
    )


def test_search_both_puts_every_symbol_first_in_the_api_list(corpus: dict[str, Any]) -> None:
    """Every documented symbol, asked by name, is the first passage of the API list."""
    misses = []
    for document in corpus["documents"].values():
        api_name = document.get("api_name")
        if not api_name:
            continue
        query = lookup_query(api_name)
        both = search_both(query, corpus["api"], corpus["docs"], corpus["chunks"], limit=1)
        if not both.api or both.api[0].retrieval_id != document["retrieval_id"]:
            misses.append(query)
    assert misses == []
