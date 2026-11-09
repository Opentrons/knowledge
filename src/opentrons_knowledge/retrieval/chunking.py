"""Cut retrieval documents into indexed chunks.

Strategies (see ``docs/retrieval-experiments.md`` for how they compare):

- ``section``: one chunk per retrieval document.
- ``structured``: tab variants become their own chunks; other content is
  packed at block boundaries up to ``MAX_WORDS``.
- ``window``: fixed word windows over a whole page, ignoring structure.
- ``small``: small pieces that map back to their parent document, so a
  consumer must expand hits to the parent before showing them.

Enrichment changes only what is indexed: ``context`` prefixes the heading path
(and tab label or API name) to the chunk text; ``context_terms`` also adds
split camelCase identifiers and aliases as searchable, non-displayed terms.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import groupby

from opentrons_knowledge.normalization.ids import content_hash
from opentrons_knowledge.normalization.serialize import dumps_canonical_json
from opentrons_knowledge.retrieval.models import (
    Chunk,
    ChunkingStrategy,
    Enrichment,
    RetrievalDocument,
    Segment,
)

MAX_WORDS = 400
WINDOW_WORDS = 200
WINDOW_STRIDE = 160
SMALL_WORDS = 80

_CAMEL = re.compile(r"\b[A-Za-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b")
_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def chunk_documents(
    documents: Sequence[RetrievalDocument],
    strategy: ChunkingStrategy,
    enrichment: Enrichment = Enrichment.CONTEXT_TERMS,
) -> list[Chunk]:
    """Cut documents into chunks.

    Args:
        documents: Retrieval documents in source order.
        strategy: How to cut them.
        enrichment: What to add to each chunk's indexed text.

    Returns:
        Chunks in source order with unique ``chunk_id`` values.
    """
    if strategy == ChunkingStrategy.WINDOW:
        return [
            chunk
            for _group, docs in groupby(documents, key=lambda d: d.group_id)
            for chunk in _window_chunks(list(docs), enrichment)
        ]
    chunks: list[Chunk] = []
    for doc in documents:
        match strategy:
            case ChunkingStrategy.SECTION:
                pieces = [Segment(text=doc.text)]
            case ChunkingStrategy.STRUCTURED:
                pieces = _structured_pieces(doc.segments)
            case ChunkingStrategy.SMALL:
                pieces = _small_pieces(doc.segments)
        chunks.extend(
            _make_chunk(doc, ordinal, piece, enrichment) for ordinal, piece in enumerate(pieces)
        )
    return chunks


def context_line(doc: RetrievalDocument, label: str | None = None) -> str:
    """Return the breadcrumb prefixed to a chunk under ``context`` enrichment.

    Args:
        doc: The chunk's retrieval document.
        label: Tab label, when the chunk is one tab variant.

    Returns:
        ``Page > Section > Tab`` style text.
    """
    parts = [*doc.heading_path, *([label] if label else [])]
    line = " > ".join(parts)
    if doc.api_name and doc.api_name not in doc.text[:200]:
        line += f"\n`{doc.api_name}`"
    return line


def identifier_terms(text: str, extra: Sequence[str] = ()) -> str:
    """Return split camelCase identifiers and extra aliases as one string.

    Tantivy's default tokenizer already splits on ``_`` and ``.``, so only
    camelCase needs help: ``loadLabware`` adds ``load labware``.

    Args:
        text: Chunk text to scan.
        extra: Aliases to include verbatim.

    Returns:
        Space-separated terms, sorted for determinism.
    """
    terms = {_CAMEL_SPLIT.sub(" ", word).lower() for word in _CAMEL.findall(text)}
    terms.update(extra)
    return " ".join(sorted(t for t in terms if t))


def _make_chunk(
    doc: RetrievalDocument, ordinal: int, piece: Segment, enrichment: Enrichment
) -> Chunk:
    text = piece.text
    if enrichment != Enrichment.PLAIN:
        text = f"{context_line(doc, piece.label)}\n\n{text}"
    terms = ""
    if enrichment == Enrichment.CONTEXT_TERMS:
        terms = identifier_terms(text, [*doc.aliases, *([doc.load_name] if doc.load_name else [])])
    chunk_id = f"{doc.retrieval_id}::{ordinal}"
    return Chunk(
        chunk_id=chunk_id,
        retrieval_id=doc.retrieval_id,
        covers=[doc.retrieval_id],
        ordinal=ordinal,
        label=piece.label,
        text=text,
        index_terms=terms,
        content_hash=_chunk_hash(chunk_id, text, terms),
    )


def _structured_pieces(segments: Sequence[Segment]) -> list[Segment]:
    pieces: list[Segment] = []
    buffer: list[str] = []
    words = 0
    for segment in segments:
        size = len(segment.text.split())
        if segment.label is not None or (buffer and words + size > MAX_WORDS):
            if buffer:
                pieces.append(Segment(text="\n\n".join(buffer)))
            buffer, words = [], 0
        if segment.label is not None:
            pieces.append(segment)
            continue
        buffer.append(segment.text)
        words += size
    if buffer:
        pieces.append(Segment(text="\n\n".join(buffer)))
    return pieces


def _small_pieces(segments: Sequence[Segment]) -> list[Segment]:
    pieces: list[Segment] = []
    for segment in _structured_pieces(segments):
        words = segment.text.split()
        if len(words) <= SMALL_WORDS:
            pieces.append(segment)
            continue
        pieces.extend(
            Segment(label=segment.label, text=" ".join(words[start : start + SMALL_WORDS]))
            for start in range(0, len(words), SMALL_WORDS)
        )
    return pieces


def _window_chunks(docs: list[RetrievalDocument], enrichment: Enrichment) -> list[Chunk]:
    words: list[str] = []
    owners: list[str] = []
    for doc in docs:
        doc_words = doc.text.split()
        words.extend(doc_words)
        owners.extend([doc.retrieval_id] * len(doc_words))
    if not words:
        return []
    title = docs[0].heading_path[0] if docs[0].heading_path else docs[0].title
    chunks: list[Chunk] = []
    for ordinal, start in enumerate(range(0, len(words), WINDOW_STRIDE)):
        end = min(start + WINDOW_WORDS, len(words))
        covers = list(dict.fromkeys(owners[start:end]))
        text = " ".join(words[start:end])
        if enrichment != Enrichment.PLAIN:
            text = f"{title}\n\n{text}"
        terms = identifier_terms(text) if enrichment == Enrichment.CONTEXT_TERMS else ""
        chunk_id = f"{docs[0].group_id}::w{ordinal}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                retrieval_id=covers[0],
                covers=covers,
                ordinal=ordinal,
                text=text,
                index_terms=terms,
                content_hash=_chunk_hash(chunk_id, text, terms),
            )
        )
        if end == len(words):
            break
    return chunks


def _chunk_hash(chunk_id: str, text: str, terms: str) -> str:
    return content_hash(dumps_canonical_json({"id": chunk_id, "text": text, "terms": terms}))
