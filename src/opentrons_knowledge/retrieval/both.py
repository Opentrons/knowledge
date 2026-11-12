"""The top passages from each index, kept apart: ``search_both``.

Each index scores with its own BM25 statistics, so a score from the API index
is not comparable with a score from the docs index. This search does not try
to merge them. It returns the best ``limit`` sections from each index, and the
caller shows them as two lists.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import tantivy

from opentrons_knowledge.retrieval.bm25 import search, search_api
from opentrons_knowledge.retrieval.passages import Passage, passages_for_hits

# Longest section in the 10.0.0-k3 docs index is 6 chunks. Fetching this many
# chunks per requested hit keeps `limit` a count of sections, not chunks.
CHUNKS_PER_SECTION = 8


@dataclass(frozen=True)
class BothResults:
    """Passages from each index, each list best first and at most ``limit`` long."""

    api: list[Passage]
    docs: list[Passage]


def search_both(
    query: str,
    api_index: tantivy.Index,
    docs_index: tantivy.Index,
    chunks: Mapping[str, Mapping[str, Any]],
    *,
    limit: int,
) -> BothResults:
    """Search the API index and the docs index, and return each one's own top sections.

    Args:
        query: The caller's query, used unchanged by both indexes.
        api_index: The API index from ``build_api_index``.
        docs_index: The docs index from ``build_index``.
        chunks: Every chunk in the bundle, keyed by ``chunk_id``.
        limit: Maximum sections to return from each index.

    Returns:
        Passages from the API index and from the docs index, kept separate.
    """
    fetch = limit * CHUNKS_PER_SECTION
    api = passages_for_hits(search_api(api_index, query, fetch), chunks, limit=limit)
    docs = passages_for_hits(search(docs_index, query, fetch), chunks, limit=limit)
    return BothResults(api=api, docs=docs)
