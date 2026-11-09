"""Write, validate, and open the shipped retrieval bundle.

Layout under ``<corpus>/retrieval/``::

    manifest.json            config, counts, sha256 per file, eval summary
    documents.jsonl.zst      RetrievalDocument records (what results point at)
    chunks.jsonl.zst         Chunk records for both indexes
    queries.jsonl.zst        evaluation queries with resolved retrieval ids
    api/bm25/                API reference index (exact symbol, then section text)
    docs/bm25/               passage index (how-tos, manuals, labware, pipettes, modules)

Tantivy names segment files with random ids, so each ``bm25/`` directory is
verified by opening it and checking its document set, not by byte digest.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Literal

import tantivy
from pydantic import Field

from opentrons_knowledge.__version__ import __version__
from opentrons_knowledge.normalization.serialize import (
    file_sha256,
    read_jsonl_zst,
    write_json,
    write_jsonl_zst,
)
from opentrons_knowledge.retrieval.bm25 import (
    api_schema,
    build_api_index,
    build_index,
    lookup_query,
    passage_schema,
    search,
    search_api,
)
from opentrons_knowledge.retrieval.chunking import chunk_documents
from opentrons_knowledge.retrieval.models import (
    RETRIEVAL_SCHEMA_ID,
    RETRIEVAL_SCHEMA_VERSION,
    Chunk,
    ChunkingStrategy,
    Enrichment,
    EvalQuery,
    RetrievalConfig,
    RetrievalDocument,
    RetrievalModel,
)

RETRIEVAL_DIR = "retrieval"
API_INDEX: Final[Literal["api"]] = "api"
DOCS_INDEX: Final[Literal["docs"]] = "docs"
_DIGESTED = ("documents.jsonl.zst", "chunks.jsonl.zst", "queries.jsonl.zst")


class RetrievalManifest(RetrievalModel):
    schema_id: str = RETRIEVAL_SCHEMA_ID
    schema_version: int = RETRIEVAL_SCHEMA_VERSION
    corpus_version: str
    builder_version: str
    config: RetrievalConfig
    tantivy_version: str
    document_count: int
    chunk_count: int
    query_count: int
    kind_counts: dict[str, int]
    index_counts: dict[str, int] = Field(description="Chunks in each shipped index.")
    files: dict[str, str] = Field(description="sha256 per file, relative to the bundle.")
    evaluation: dict[str, Any] | None = Field(
        default=None, description="Winner metrics and the selection rule, when evaluation ran."
    )


def write_bundle(
    output_dir: Path,
    documents: Sequence[RetrievalDocument],
    config: RetrievalConfig,
    *,
    corpus_version: str,
    queries: Sequence[EvalQuery] = (),
    relevant: dict[str, frozenset[str]] | None = None,
    evaluation: dict[str, Any] | None = None,
) -> RetrievalManifest:
    """Write the retrieval bundle for one configuration.

    Sections that document a symbol go to the API index, one chunk each. Every
    other selected document goes to the docs index, cut with ``config``.

    Args:
        output_dir: Bundle directory (replaced if it exists).
        documents: The full retrieval document set; filtered to ``config.kinds``.
        config: How the docs index is cut and enriched. The API index is always
            one chunk per symbol section.
        corpus_version: Corpus version the bundle belongs to.
        queries: Evaluation queries to ship.
        relevant: Resolved ids per query, from ``resolve_labels``.
        evaluation: Evaluation summary to record in the manifest.

    Returns:
        The written manifest.
    """
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    kinds = set(config.kinds)
    docs = [d for d in documents if d.kind in kinds]
    by_id = {d.retrieval_id: d for d in docs}
    api_docs = [d for d in docs if d.api_name]
    other_docs = [d for d in docs if not d.api_name]
    api_chunks = (
        chunk_documents(api_docs, ChunkingStrategy.SECTION, Enrichment.CONTEXT_TERMS)
        if api_docs
        else []
    )
    doc_chunks = chunk_documents(other_docs, config.chunking, config.enrichment)
    chunks = [*api_chunks, *doc_chunks]
    write_jsonl_zst(output_dir / "documents.jsonl.zst", docs)
    write_jsonl_zst(output_dir / "chunks.jsonl.zst", chunks)
    resolved = relevant or {}
    write_jsonl_zst(
        output_dir / "queries.jsonl.zst",
        [
            _ShippedQuery(**q.model_dump(), relevant_ids=sorted(resolved.get(q.query_id, ())))
            for q in queries
        ],
    )
    build_api_index(api_chunks, by_id, output_dir / API_INDEX / "bm25")
    build_index(doc_chunks, by_id, output_dir / DOCS_INDEX / "bm25", tokenizer=config.tokenizer)
    kind_counts: dict[str, int] = {}
    for doc in docs:
        kind_counts[doc.kind.value] = kind_counts.get(doc.kind.value, 0) + 1
    manifest = RetrievalManifest(
        corpus_version=corpus_version,
        builder_version=__version__,
        config=config,
        tantivy_version=_tantivy_version(),
        document_count=len(docs),
        chunk_count=len(chunks),
        query_count=len(queries),
        kind_counts=dict(sorted(kind_counts.items())),
        index_counts={API_INDEX: len(api_chunks), DOCS_INDEX: len(doc_chunks)},
        files={name: file_sha256(output_dir / name) for name in _DIGESTED},
        evaluation=evaluation,
    )
    write_json(output_dir / "manifest.json", manifest.model_dump(mode="json"))
    return manifest


class _ShippedQuery(EvalQuery):
    relevant_ids: list[str]


RETRIEVAL_JSON_SCHEMAS: Final = {
    "retrieval-document.schema.json": RetrievalDocument,
    "retrieval-chunk.schema.json": Chunk,
    "retrieval-manifest.schema.json": RetrievalManifest,
}


def validate_bundle(bundle_dir: Path) -> list[str]:
    """Check a bundle's digests, ids, and that both indexes open and search.

    Args:
        bundle_dir: A directory written by ``write_bundle``.

    Returns:
        Problems found; empty when the bundle is valid.
    """
    problems: list[str] = []
    manifest = RetrievalManifest.model_validate_json(
        (bundle_dir / "manifest.json").read_text(encoding="utf-8")
    )
    for name, digest in manifest.files.items():
        if file_sha256(bundle_dir / name) != digest:
            problems.append(f"{name}: sha256 does not match manifest")
    if problems:
        return problems
    docs = read_jsonl_zst(bundle_dir / "documents.jsonl.zst")
    chunks = read_jsonl_zst(bundle_dir / "chunks.jsonl.zst")
    doc_ids = [d["retrieval_id"] for d in docs]
    chunk_ids = [c["chunk_id"] for c in chunks]
    if len(set(doc_ids)) != len(doc_ids):
        problems.append("retrieval_id values are not unique")
    if len(set(chunk_ids)) != len(chunk_ids):
        problems.append("chunk_id values are not unique")
    known = set(doc_ids)
    if any(rid not in known for c in chunks for rid in c["covers"]):
        problems.append("a chunk covers a retrieval_id that is not in documents.jsonl.zst")
    if (manifest.document_count, manifest.chunk_count) != (len(docs), len(chunks)):
        problems.append("manifest counts do not match the record files")
    by_id = {d["retrieval_id"]: d for d in docs}
    api_chunks = [c for c in chunks if by_id[c["retrieval_id"]].get("api_name")]
    doc_chunks = [c for c in chunks if not by_id[c["retrieval_id"]].get("api_name")]
    if manifest.index_counts.get(API_INDEX) != len(api_chunks):
        problems.append("api index count does not match chunks for symbol sections")
    if manifest.index_counts.get(DOCS_INDEX) != len(doc_chunks):
        problems.append("docs index count does not match the remaining chunks")
    problems.extend(_check_index(bundle_dir, API_INDEX, api_chunks, docs))
    problems.extend(_check_index(bundle_dir, DOCS_INDEX, doc_chunks, docs))
    return problems


def open_index(bundle_dir: Path, name: Literal["api", "docs"] = "docs") -> tantivy.Index:
    """Open one of the bundle's indexes.

    Args:
        bundle_dir: A directory written by ``write_bundle``.
        name: ``api`` for the reference index, ``docs`` for the passage index.

    Returns:
        The index.
    """
    schema = api_schema() if name == API_INDEX else passage_schema(_tokenizer(bundle_dir))
    return tantivy.Index(schema, path=str(bundle_dir / name / "bm25"), reuse=True)


def _check_index(
    bundle_dir: Path,
    name: Literal["api", "docs"],
    chunks: list[dict[str, Any]],
    docs: list[dict[str, Any]],
) -> list[str]:
    index = open_index(bundle_dir, name)
    count = index.searcher().num_docs
    if count != len(chunks):
        return [f"{name} index has {count} documents, expected {len(chunks)}"]
    if not chunks:
        return []
    if name == API_INDEX:
        doc = next(d for d in docs if d["retrieval_id"] == chunks[0]["retrieval_id"])
        hits = search_api(index, lookup_query(doc["api_name"]), 5)
    else:
        probe = chunks[0]["text"].split("\n")[0][:80]
        hits = search(index, probe, 50) if probe else []
    if not hits:
        return [f"{name} index returned no hits for a query taken from its own records"]
    return []


def _tokenizer(bundle_dir: Path) -> Literal["default", "en_stem"]:
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["config"].get("tokenizer") == "en_stem":
        return "en_stem"
    return "default"


def _tantivy_version() -> str:
    from importlib.metadata import version

    return version("tantivy")
