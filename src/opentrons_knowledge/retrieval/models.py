"""Retrieval records: what a search returns, what gets indexed, and the evaluation set.

A ``RetrievalDocument`` is the unit a search result points at and an agent cites.
A ``Chunk`` is the unit the index matches; every chunk names the retrieval
documents it was cut from. Both are derived from the canonical and normalized
corpus records and can always be rebuilt from them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

RETRIEVAL_SCHEMA_ID: Final = "opentrons-knowledge.retrieval"
RETRIEVAL_SCHEMA_VERSION = 2


class RetrievalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetrievalKind(StrEnum):
    DOC_SECTION = "doc_section"
    API_SYMBOL = "api_symbol"
    ENTITY = "entity"
    GUIDE_SECTION = "guide_section"


class ChunkingStrategy(StrEnum):
    """How retrieval documents are cut into indexed chunks."""

    SECTION = "section"
    STRUCTURED = "structured"
    WINDOW = "window"
    SMALL = "small"


class Enrichment(StrEnum):
    """What, besides the body, goes into a chunk's indexed text."""

    PLAIN = "plain"
    CONTEXT = "context"
    CONTEXT_TERMS = "context_terms"


class Segment(RetrievalModel):
    """A block-boundary piece of a retrieval document; ``label`` is set for a tab."""

    label: str | None = None
    text: str


class RetrievalDocument(RetrievalModel):
    """A record a search returns: displayable text plus citation and filter fields."""

    retrieval_id: str
    kind: RetrievalKind
    group_id: str = Field(
        description="Records from one page or definition share a group (used by window chunking)."
    )
    title: str
    heading_path: list[str]
    text: str
    segments: list[Segment]
    url: str | None = None
    source_url: str | None = None
    source_path: str
    source_record_ids: list[str] = Field(
        description="Corpus record ids this document was built from (canonical section, "
        "symbol, entity, or guide section ids)."
    )
    authority_level: str
    doc_type: str = Field(
        description="Page kind: api_reference, user_manual, labware_spec, module_guide, and so on."
    )
    project: str | None = None
    page_path: str | None = None
    anchor: str | None = None
    robot_types: list[str] = Field(default_factory=list)
    api_name: str | None = None
    api_version_min: str | None = None
    load_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    content_hash: str


class Chunk(RetrievalModel):
    """An indexed unit. ``text`` is returned; ``index_terms`` is searchable but not shown."""

    chunk_id: str
    retrieval_id: str
    covers: list[str] = Field(description="Every retrieval document this chunk contains text from.")
    ordinal: int
    label: str | None = None
    text: str
    index_terms: str = ""
    content_hash: str


class EvalQuery(RetrievalModel):
    """A labeled question. ``relevant`` holds labels that resolve to retrieval ids."""

    query_id: str
    query: str
    category: str
    source: Literal["curated", "structural"]
    relevant: list[str]
    notes: str | None = None


class RetrievalConfig(RetrievalModel):
    """One point in the experiment grid, and the shipped configuration."""

    kinds: list[RetrievalKind]
    chunking: ChunkingStrategy
    enrichment: Enrichment
    tokenizer: Literal["default", "en_stem"] = "default"

    @property
    def name(self) -> str:
        kinds = "+".join(k.value for k in self.kinds)
        return f"{kinds}|{self.chunking.value}|{self.enrichment.value}|{self.tokenizer}"

    @property
    def selectable(self) -> bool:
        """Whether this configuration can ship.

        The text we return has to be the passage a reader sees, so the 80-word
        fragment chunking is out. The tokenizer stays the default one: stemming
        was measured and did not win, and it changes which word forms a query
        must use.
        """
        return self.tokenizer == "default" and self.chunking != ChunkingStrategy.SMALL
