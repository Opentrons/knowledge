"""Retrieval documents, chunking, BM25 index, evaluation, and bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opentrons_knowledge.models.canonical import (
    AdmonitionBlock,
    ApiObject,
    CanonicalDocument,
    CanonicalSection,
    CodeBlock,
    ParagraphBlock,
    RenderedRef,
    SourceRef,
    Tab,
    TabsBlock,
)
from opentrons_knowledge.models.enums import AuthorityLevel, EntityType, SymbolType
from opentrons_knowledge.models.records import CodeSymbol, Document, Entity, Section
from opentrons_knowledge.retrieval.bm25 import build_api_index, build_index, search, search_api
from opentrons_knowledge.retrieval.bundle import validate_bundle, write_bundle
from opentrons_knowledge.retrieval.chunking import chunk_documents, identifier_terms
from opentrons_knowledge.retrieval.documents import (
    RetrievalInputs,
    build_retrieval_documents,
    public_api_name,
)
from opentrons_knowledge.retrieval.evaluation import (
    BASELINE,
    load_queries,
    paired_delta,
    resolve_labels,
    run_config,
    select_winner,
)
from opentrons_knowledge.retrieval.models import (
    ChunkingStrategy,
    Enrichment,
    EvalQuery,
    RetrievalConfig,
    RetrievalDocument,
    RetrievalKind,
    Segment,
)
from opentrons_knowledge.retrieval.render import render_blocks

REPO = "https://github.com/Opentrons/opentrons"
CURATED = Path(__file__).resolve().parents[2] / "eval" / "retrieval" / "curated.yaml"


def _section(
    page: str, ordinal: int, title: str, anchor: str | None, blocks: list[Any], **kw: Any
) -> CanonicalSection:
    path = kw.pop("heading_path", [title])
    return CanonicalSection(
        section_id=f"section:{page}#{anchor}",
        document_id=f"doc:{page}",
        ordinal=ordinal,
        level=len(path),
        title=title,
        anchor=anchor,
        url=f"https://docs.opentrons.com/{page}#{anchor or ''}",
        heading_path=path,
        parent_section_id=kw.pop("parent", None),
        blocks=blocks,
        content_hash=f"h{ordinal}",
        **kw,
    )


def _page(page: str, sections: list[CanonicalSection], **kw: Any) -> CanonicalDocument:
    return CanonicalDocument(
        document_id=f"doc:{page}",
        page_path=page,
        url=f"https://docs.opentrons.com/{page}",
        title=sections[0].title,
        project=page.split("/")[0],
        source=SourceRef(
            repository=REPO,
            commit="0" * 40,
            markdown_path=f"docs/{page.split('/')[0]}/docs/{page.rstrip('/')}.md",
        ),
        rendered=RenderedRef(html_path=f"{page}index.html", html_sha256="0"),
        sections=sections,
        content_hash="d",
        **kw,
    )


@pytest.fixture
def inputs() -> RetrievalInputs:
    root = "doc:python-api/pipettes/loading/"
    loading = _page(
        "python-api/pipettes/loading/",
        [
            _section(
                "python-api/pipettes/loading/",
                0,
                "Loading pipettes",
                None,
                [ParagraphBlock(text="Use load_instrument to load a pipette.")],
            ),
            _section(
                "python-api/pipettes/loading/",
                1,
                "Loading Flex pipettes",
                "loading-flex",
                [
                    ParagraphBlock(text="Choose a mount."),
                    TabsBlock(
                        tabs=[
                            Tab(label="Flex", blocks=[CodeBlock(code="load_instrument('flex')")]),
                            Tab(label="OT-2", blocks=[CodeBlock(code="load_instrument('p300')")]),
                        ]
                    ),
                ],
                heading_path=["Loading pipettes", "Loading Flex pipettes"],
                parent=root,
            ),
            _section(
                "python-api/pipettes/loading/",
                2,
                "Mounts",
                "mounts",
                [ParagraphBlock(text="Left or right mount.")],
                heading_path=["Loading pipettes", "Loading Flex pipettes", "Mounts"],
                parent=root,
            ),
            _section(
                "python-api/pipettes/loading/",
                3,
                "Empty heading",
                "empty",
                [],
                heading_path=["Loading pipettes", "Empty heading"],
                parent=root,
            ),
        ],
    )
    reference = _page(
        "python-api/reference/protocols/",
        [
            _section(
                "python-api/reference/protocols/",
                0,
                "load_instrument",
                "opentrons.protocol_api.ProtocolContext.load_instrument",
                [ParagraphBlock(text="Load a specific instrument for the protocol.")],
                api=ApiObject(
                    qualified_name="opentrons.protocol_api.ProtocolContext.load_instrument",
                    kind="method",
                ),
            )
        ],
    )
    hidden = _page(
        "flex/vacuum/",
        [_section("flex/vacuum/", 0, "Vacuum", None, [ParagraphBlock(text="secret")])],
        search_exclude=True,
    )
    symbol = {
        "qualified_name": "opentrons.protocol_api.instrument_context.InstrumentContext.flow_rate",
        "symbol_type": SymbolType.PROPERTY,
        "module_path": "opentrons.protocol_api.instrument_context",
        "source_path": "api/src/opentrons/protocol_api/instrument_context.py",
        "source_url": f"{REPO}/blob/x/api/src/opentrons/protocol_api/instrument_context.py",
        "signature": "def flow_rate(self) -> FlowRates",
        "content_hash": "s",
    }
    symbols = [
        CodeSymbol(symbol_id="symbol:flow_rate", docstring="Getter docs.", line_start=1, **symbol),
        CodeSymbol(symbol_id="symbol:flow_rate", docstring="Setter docs.", line_start=9, **symbol),
        CodeSymbol(
            symbol_id="symbol:private",
            **{**symbol, "qualified_name": "opentrons.protocol_api._liquid.Liquid.name"},
            docstring="Private.",
        ),
    ]

    def labware(version: int, display: str) -> Entity:
        return Entity(
            entity_id="entity:labware:nest_12_reservoir_15ml:schema-2",
            entity_type=EntityType.LABWARE,
            canonical_name="nest_12_reservoir_15ml",
            display_name=display,
            source_ids=[
                f"shared_data:shared-data/labware/definitions/2/nest_12_reservoir_15ml/{version}.json"
            ],
            properties={"namespace": "opentrons"},
            content_hash=f"l{version}",
            raw_source={"metadata": {"displayName": display}, "wells": {"A1": {}}},
        )

    entities = [
        labware(1, "Old Reservoir"),
        labware(2, "NEST 12 Well Reservoir 15 mL"),
        Entity(
            entity_id="entity:module:1:10.0.0",
            entity_type=EntityType.MODULE,
            canonical_name="1",
            display_name="1",
            source_ids=["shared_data:shared-data/module/schemas/1.json"],
            content_hash="m",
        ),
    ]
    guide = Document(
        document_id="doc:guide",
        title="Guide",
        source_repository=REPO,
        source_commit="0" * 40,
        source_path="opentrons-ai-server/api/storage/docs/tips.md",
        source_url=f"{REPO}/blob/x/tips.md",
        source_type="ai_guidance",
        authority_level=AuthorityLevel.CURATED_GUIDANCE,
        content_hash="g",
    )
    guide_sections = [
        Section(
            section_id=f"section:guide:{i}",
            document_id="doc:guide",
            title="Example",
            heading_path=["Guide", "Example"],
            content="",
            content_markdown=f"## Example\n\nTip example {i}.",
            content_plaintext="",
            anchor="example",
            content_hash=f"gs{i}",
        )
        for i in range(2)
    ]
    return RetrievalInputs(
        canonical_documents=[loading, reference, hidden],
        symbols=symbols,
        entities=entities,
        guide_documents=[guide],
        guide_sections=guide_sections,
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def test_documents_are_keyed_by_path_and_skip_hidden_and_empty(inputs: RetrievalInputs) -> None:
    ids = {d.retrieval_id for d in build_retrieval_documents(inputs)}
    assert ids == {
        "doc:python-api/pipettes/loading/",
        "doc:python-api/pipettes/loading/#loading-flex",
        "doc:python-api/pipettes/loading/#mounts",
        "doc:python-api/reference/protocols/",
        "symbol:opentrons.protocol_api.instrument_context.InstrumentContext.flow_rate",
        "labware:nest_12_reservoir_15ml",
        "guide:opentrons-ai-server/api/storage/docs/tips.md#example",
        "guide:opentrons-ai-server/api/storage/docs/tips.md#example-2",
    }


def test_symbol_getter_and_setter_merge_under_the_public_name(inputs: RetrievalInputs) -> None:
    docs = build_retrieval_documents(inputs, [RetrievalKind.API_SYMBOL])
    (symbol,) = docs
    assert symbol.api_name == "opentrons.protocol_api.InstrumentContext.flow_rate"
    assert "Getter docs." in symbol.text and "Setter docs." in symbol.text


def test_entities_keep_the_latest_definition_and_drop_schema_files(
    inputs: RetrievalInputs,
) -> None:
    (labware,) = build_retrieval_documents(inputs, [RetrievalKind.ENTITY])
    assert labware.title == "NEST 12 Well Reservoir 15 mL"
    assert labware.source_path.endswith("nest_12_reservoir_15ml/2.json")


def test_doc_types_follow_path_rules(inputs: RetrievalInputs) -> None:
    types = {d.retrieval_id: d.doc_type for d in build_retrieval_documents(inputs)}
    assert types["doc:python-api/reference/protocols/"] == "api_reference"
    assert types["labware:nest_12_reservoir_15ml"] == "labware_spec"
    assert types["guide:opentrons-ai-server/api/storage/docs/tips.md#example"] == "internal_guide"


def test_duplicate_retrieval_ids_fail(inputs: RetrievalInputs) -> None:
    page = inputs.canonical_documents[0]
    twice = RetrievalInputs(canonical_documents=[page, page])
    with pytest.raises(ValueError, match="Duplicate retrieval ids"):
        build_retrieval_documents(twice)


@pytest.mark.parametrize(
    ("qualified", "public"),
    [
        (
            "opentrons.protocol_api.instrument_context.InstrumentContext.aspirate",
            "opentrons.protocol_api.InstrumentContext.aspirate",
        ),
        ("opentrons.protocol_api.Labware", "opentrons.protocol_api.Labware"),
        ("opentrons.types.Location", "opentrons.types.Location"),
    ],
)
def test_public_api_name(qualified: str, public: str) -> None:
    assert public_api_name(qualified) == public


def test_render_blocks_keeps_tabs_admonitions_and_code() -> None:
    text = render_blocks(
        [
            AdmonitionBlock(kind="note", blocks=[ParagraphBlock(text="Careful.")]),
            TabsBlock(
                tabs=[Tab(label="Flex", blocks=[CodeBlock(language="python", code="x = 1")])]
            ),
        ]
    )
    assert "> **Note**\n> Careful." in text
    assert "**Flex**\n\n```python\nx = 1\n```" in text


# ---------------------------------------------------------------------------
# Chunking and index
# ---------------------------------------------------------------------------


def test_structured_chunking_splits_tabs_with_labels(inputs: RetrievalInputs) -> None:
    docs = build_retrieval_documents(inputs, [RetrievalKind.DOC_SECTION])
    chunks = chunk_documents(docs, ChunkingStrategy.STRUCTURED, Enrichment.CONTEXT)
    flex = [c for c in chunks if c.retrieval_id.endswith("#loading-flex")]
    assert [c.label for c in flex] == [None, "Flex", "OT-2"]
    assert flex[1].text.startswith("Loading pipettes > Loading Flex pipettes > Flex\n\n")
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_window_chunks_record_every_covered_document(inputs: RetrievalInputs) -> None:
    docs = build_retrieval_documents(inputs, [RetrievalKind.DOC_SECTION])
    chunks = chunk_documents(docs, ChunkingStrategy.WINDOW, Enrichment.PLAIN)
    page = [c for c in chunks if c.chunk_id.startswith("doc:python-api/pipettes/loading/::")]
    assert page[0].covers[:2] == [
        "doc:python-api/pipettes/loading/",
        "doc:python-api/pipettes/loading/#loading-flex",
    ]


def test_identifier_terms_split_camel_case() -> None:
    assert identifier_terms("call loadLabware on InstrumentContext") == (
        "instrument context load labware"
    )


def test_index_terms_are_searchable_but_not_returned(inputs: RetrievalInputs) -> None:
    docs = build_retrieval_documents(inputs, [RetrievalKind.ENTITY])
    chunks = chunk_documents(docs, ChunkingStrategy.SECTION, Enrichment.CONTEXT_TERMS)
    index = build_index(chunks, {d.retrieval_id: d for d in docs})
    hits = search(index, "nest_12_reservoir_15ml")
    assert [chunk_id for chunk_id, _ in hits] == ["labware:nest_12_reservoir_15ml::0"]
    stored = index.searcher().doc(
        index.searcher().search(index.parse_query("reservoir"), 1).hits[0][1]
    )
    assert stored.get_first("text") == chunks[0].text


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _query(query_id: str, *labels: str) -> EvalQuery:
    return EvalQuery(
        query_id=query_id,
        query="load a pipette",
        category="t",
        source="curated",
        relevant=list(labels),
    )


def test_labels_resolve_to_sections_descendants_and_api(inputs: RetrievalInputs) -> None:
    docs = build_retrieval_documents(inputs)
    resolved = resolve_labels(
        [
            _query("page", "doc:python-api/pipettes/loading/"),
            _query("anchor", "doc:python-api/pipettes/loading/#loading-flex"),
            _query("api", "api:opentrons.protocol_api.InstrumentContext.flow_rate"),
            _query("guide", "guide:tips.md"),
        ],
        docs,
    )
    assert len(resolved["page"]) == 3
    assert resolved["anchor"] == {
        "doc:python-api/pipettes/loading/#loading-flex",
        "doc:python-api/pipettes/loading/#mounts",
    }
    assert resolved["api"] == {
        "symbol:opentrons.protocol_api.instrument_context.InstrumentContext.flow_rate"
    }
    assert len(resolved["guide"]) == 2


def test_unresolved_labels_fail(inputs: RetrievalInputs) -> None:
    with pytest.raises(ValueError, match="doc:nope/"):
        resolve_labels([_query("q", "doc:nope/")], build_retrieval_documents(inputs))


def test_curated_set_parses() -> None:
    queries = load_queries(CURATED)
    assert len(queries) >= 60
    assert len({q.query_id for q in queries}) == len(queries)
    assert all(q.relevant for q in queries)


def test_run_config_scores_and_selects(inputs: RetrievalInputs) -> None:
    docs = build_retrieval_documents(inputs)
    queries = [
        _query("q1", "doc:python-api/pipettes/loading/"),
        EvalQuery(
            query_id="s1",
            query="Mounts",
            category="heading",
            source="structural",
            relevant=["doc:python-api/pipettes/loading/#mounts"],
        ),
    ]
    relevant = resolve_labels(queries, docs)
    context = RetrievalConfig(
        kinds=list(RetrievalKind),
        chunking=ChunkingStrategy.SECTION,
        enrichment=Enrichment.CONTEXT,
    )
    results = [run_config(c, docs, queries, relevant) for c in (BASELINE, context)]
    assert results[1].metrics["curated"]["hit@10"] == 1.0
    winner, notes = select_winner(results)
    assert winner.config in (BASELINE, context)
    assert len(notes) == 3
    delta = paired_delta(results[1], results[0], queries, resamples=50)
    assert delta["n"] == 1


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


def test_bundle_writes_separate_indexes_and_validates(
    inputs: RetrievalInputs, tmp_path: Path
) -> None:
    docs = build_retrieval_documents(inputs)
    config = RetrievalConfig(
        kinds=[RetrievalKind.DOC_SECTION, RetrievalKind.ENTITY],
        chunking=ChunkingStrategy.STRUCTURED,
        enrichment=Enrichment.CONTEXT_TERMS,
    )
    bundle = tmp_path / "retrieval"
    manifest = write_bundle(bundle, docs, config, corpus_version="0.0.0-k1")
    assert validate_bundle(bundle) == []
    assert manifest.kind_counts == {"doc_section": 4, "entity": 1}
    assert manifest.index_counts["api"] == 1
    assert manifest.index_counts["docs"] == manifest.chunk_count - 1
    assert (bundle / "api" / "bm25").is_dir()
    assert (bundle / "docs" / "bm25").is_dir()
    (bundle / "chunks.jsonl.zst").write_text("", encoding="utf-8")
    assert "chunks.jsonl.zst: sha256 does not match manifest" in validate_bundle(bundle)


def test_api_name_lookup_beats_a_page_that_only_mentions_it() -> None:
    """A method name resolves to its reference section, not a page that cites it."""
    mention = _retrieval_doc(
        "doc:python-api/modules/loading/#loading-modules",
        "Loading modules",
        "Call ProtocolContext.load_module to load a module. " * 8,
        doc_type="module_guide",
    )
    method = _retrieval_doc(
        "doc:python-api/reference/protocols/#opentrons.protocol_api.ProtocolContext.load_module",
        "load_module",
        "load_module(module_name, location) -> ModuleContext",
        api_name="opentrons.protocol_api.ProtocolContext.load_module",
        doc_type="api_reference",
    )
    docs = {doc.retrieval_id: doc for doc in (mention, method)}
    chunks = chunk_documents([method], ChunkingStrategy.SECTION, Enrichment.CONTEXT_TERMS)
    index = build_api_index(chunks, docs)
    hits = search_api(index, "ProtocolContext.load_module", 5)
    assert [chunk_id for chunk_id, _score in hits] == [chunks[0].chunk_id]
    assert search_api(index, "load_module", 5)[0][0] == chunks[0].chunk_id


def _retrieval_doc(
    retrieval_id: str,
    title: str,
    text: str,
    *,
    doc_type: str,
    api_name: str | None = None,
) -> RetrievalDocument:
    return RetrievalDocument(
        retrieval_id=retrieval_id,
        kind=RetrievalKind.DOC_SECTION,
        group_id=retrieval_id.split("#", 1)[0],
        title=title,
        heading_path=[title],
        text=text,
        segments=[Segment(text=text)],
        source_path="docs/python-api/docs/reference.md",
        source_record_ids=[retrieval_id],
        authority_level="official_guidance",
        doc_type=doc_type,
        api_name=api_name,
        aliases=[api_name.rsplit(".", 1)[-1]] if api_name else [],
        content_hash="h",
    )
