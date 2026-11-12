"""Tantivy indexes for the two searches this corpus ships.

``docs`` is BM25 over passages: how-to pages, manuals, and shared-data entities
(labware, pipettes, modules). Each stored ``text`` value is one chunk.
Identifier terms are a second value of the same field, so they match without
becoming part of the text. A result assembles every chunk of the matched
section; see ``passages.section_passage``.

``api`` is the Python API reference, one section per documented symbol. Names
are stored untokenized on ``symbol``. A query searches ``symbol`` first and
returns those hits immediately, because mixing the name field with the prose
field lets a short page that merely mentions a method outscore the method
itself. When the name matches nothing, the section text is searched instead,
for questions that describe a behavior without naming the symbol.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import tantivy

from opentrons_knowledge.retrieval.models import Chunk, RetrievalDocument

WRITER_HEAP_BYTES = 50_000_000
IndexName = Literal["api", "docs"]


def passage_schema(tokenizer: Literal["default", "en_stem"] = "default") -> tantivy.Schema:
    """Return the schema for a passage index.

    Args:
        tokenizer: Tokenizer for the passage field. ``default`` lowercases and
            splits on punctuation, and does not stem.

    Returns:
        The Tantivy schema.
    """
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("chunk_id", stored=True, tokenizer_name="raw")
    builder.add_text_field("text", stored=True, tokenizer_name=tokenizer)
    return builder.build()


def api_schema() -> tantivy.Schema:
    """Return the schema for the API reference index.

    Returns:
        The Tantivy schema. ``symbol`` keeps each name as one token.
    """
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("chunk_id", stored=True, tokenizer_name="raw")
    builder.add_text_field("symbol", stored=True, tokenizer_name="raw")
    builder.add_text_field("text", stored=True, tokenizer_name="default")
    return builder.build()


def symbol_values(api_name: str) -> list[str]:
    """Return the exact names stored for one documented symbol.

    Each name is stored in its documented capitalization and in lowercase, so a
    query matches either form. The bare member name is included. ``Class.member``
    is included when the owner is a class, which is the form a caller should use
    for a method.

    Args:
        api_name: Public qualified name, as written in the reference.

    Returns:
        Names, without duplicates.
    """
    parts = api_name.split(".")
    member = parts[-1]
    names = [api_name, member]
    if len(parts) >= 2 and parts[-2][:1].isupper() and parts[-2] != member:
        names.append(f"{parts[-2]}.{member}")
    values: list[str] = []
    for name in names:
        for form in (name, name.lower()):
            if form not in values:
                values.append(form)
    return values


def lookup_query(api_name: str) -> str:
    """Return the query that should resolve to this symbol and no other.

    Args:
        api_name: Public qualified name.

    Returns:
        ``Class.member`` when the owner is a class, otherwise the qualified name.
    """
    parts = api_name.split(".")
    if len(parts) >= 2 and parts[-2][:1].isupper():
        return f"{parts[-2]}.{parts[-1]}"
    return api_name


def build_index(
    chunks: Sequence[Chunk],
    documents: dict[str, RetrievalDocument],
    path: Path | None = None,
    *,
    tokenizer: Literal["default", "en_stem"] = "default",
) -> tantivy.Index:
    """Index passage chunks in one commit with one writer thread.

    Args:
        chunks: Chunks to index, in order.
        documents: Retrieval documents by id. Accepted so callers can pass the
            same arguments they use for the API index; passage indexing reads
            the chunk itself.
        path: Directory to write; in memory when omitted.
        tokenizer: Tokenizer for the passage field.

    Returns:
        The reloaded index.
    """
    del documents
    schema = passage_schema(tokenizer)
    index, writer = _writer(schema, path)
    for chunk in chunks:
        record = tantivy.Document()
        record.add_text("chunk_id", chunk.chunk_id)
        record.add_text("text", chunk.text)
        if chunk.index_terms:
            record.add_text("text", chunk.index_terms)
        writer.add_document(record)
    return _finish(index, writer, path)


def build_api_index(
    chunks: Sequence[Chunk],
    documents: dict[str, RetrievalDocument],
    path: Path | None = None,
) -> tantivy.Index:
    """Index API reference sections, one chunk per symbol.

    Args:
        chunks: One chunk per reference section. The chunk text is what a hit
            returns.
        documents: Retrieval documents by id. Each must have ``api_name`` set.
        path: Directory to write; in memory when omitted.

    Returns:
        The reloaded index.
    """
    schema = api_schema()
    index, writer = _writer(schema, path)
    for chunk in chunks:
        doc = documents[chunk.retrieval_id]
        if not doc.api_name:
            msg = f"{chunk.retrieval_id} is in the API index but has no api_name"
            raise ValueError(msg)
        record = tantivy.Document()
        record.add_text("chunk_id", chunk.chunk_id)
        record.add_text("text", chunk.text)
        if chunk.index_terms:
            record.add_text("text", chunk.index_terms)
        for name in symbol_values(doc.api_name):
            record.add_text("symbol", name)
        writer.add_document(record)
    return _finish(index, writer, path)


def search(index: tantivy.Index, query: str, limit: int = 10) -> list[tuple[str, float]]:
    """Search a passage index.

    Args:
        index: An index built by ``build_index``.
        query: Free-text query. It is lowercased and split on punctuation.
        limit: Maximum hits.

    Returns:
        ``(chunk_id, score)`` pairs, best first. Empty when the query has no
        searchable terms.
    """
    parsed, _errors = index.parse_query_lenient(query, ["text"])
    return _hits(index, parsed, limit)


def search_api(index: tantivy.Index, query: str, limit: int = 10) -> list[tuple[str, float]]:
    """Search the API index: exact names first, then the section text.

    Args:
        index: An index built by ``build_api_index``.
        query: A symbol (``Class.method``, a qualified name, or a member name)
            or a short description of what the symbol does.
        limit: Maximum hits.

    Returns:
        ``(chunk_id, score)`` pairs, best first. Name matches are returned on
        their own; the prose is searched only when the name matches nothing.
    """
    names, _errors = index.parse_query_lenient(query, ["symbol"])
    exact = _hits(index, names, limit)
    if exact:
        return exact
    prose, _errors = index.parse_query_lenient(query, ["text"])
    return _hits(index, prose, limit)


def _writer(schema: tantivy.Schema, path: Path | None) -> tuple[tantivy.Index, tantivy.IndexWriter]:
    if path is not None:
        path.mkdir(parents=True, exist_ok=True)
    index = tantivy.Index(schema, path=str(path) if path else None)
    return index, index.writer(heap_size=WRITER_HEAP_BYTES, num_threads=1)


def _finish(index: tantivy.Index, writer: tantivy.IndexWriter, path: Path | None) -> tantivy.Index:
    writer.commit()
    writer.wait_merging_threads()
    del writer
    index.reload()
    if path is not None:
        for lock in path.glob(".tantivy-*.lock"):
            lock.unlink()
    return index


def _hits(index: tantivy.Index, parsed: tantivy.Query, limit: int) -> list[tuple[str, float]]:
    searcher = index.searcher()
    found = searcher.search(parsed, limit).hits
    ranked = [(str(searcher.doc(address).get_first("chunk_id")), score) for score, address in found]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked
