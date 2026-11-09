"""One ranked list from the API index and the docs index.

Each index scores with its own BM25 statistics, so a score from one index is
not comparable with a score from the other. Reciprocal rank fusion uses only
positions: a section scores ``weight / (RRF_K + rank)`` in each list where it
appears, and the sums decide the order. Nothing runs at query time except the
two BM25 searches, and nothing extra is stored in the bundle.

Weights come from one measured rule (``docs/retrieval-experiments.md``):

- A query that names a symbol (one token that matches the API ``symbol`` field)
  gives the API list full weight. Its section is then first, as ``search_api``
  intends.
- Any other query gives the API list half weight. The docs list keeps the top
  place, and API sections fill in below it.
- On a tie, the list with the higher weight is ranked first: the API list for a
  symbol name, the docs list for a question.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import tantivy

from opentrons_knowledge.retrieval.bm25 import names_symbol, search, search_api
from opentrons_knowledge.retrieval.passages import Passage, passages_for_hits

RRF_K = 60
API_WEIGHT_PROSE = 0.5
API_WEIGHT_SYMBOL = 1.0
DOCS_WEIGHT = 1.0


@dataclass(frozen=True)
class FusedPassage:
    """A fused result: the passage, and the index it came from.

    Each section lives in exactly one index, because only API sections carry
    ``api_name``. So the index label is the section's own index.
    """

    index: Literal["api", "docs"]
    passage: Passage


def section_ranking(
    found: Sequence[tuple[str, float]],
    chunks: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return section ids in rank order, keeping each section's first chunk.

    Args:
        found: ``(chunk_id, score)`` pairs, best first, from one index.
        chunks: Every chunk in the bundle, keyed by ``chunk_id``.

    Returns:
        Unique ``retrieval_id`` values, best first.
    """
    seen: dict[str, None] = {}
    for chunk_id, _score in found:
        chunk = chunks.get(chunk_id)
        if chunk is not None:
            seen.setdefault(str(chunk["retrieval_id"]), None)
    return list(seen)


def reciprocal_rank_fusion(
    rankings: Sequence[tuple[Sequence[str], float]], *, k: int = RRF_K
) -> list[tuple[str, float]]:
    """Fuse ranked id lists by weighted sum of reciprocal ranks.

    Args:
        rankings: ``(ids, weight)`` pairs. Each ``ids`` is in rank order, best first,
            with no repeats. Earlier lists win ties.
        k: Damping constant. Larger values flatten the advantage of rank 1.

    Returns:
        ``(id, fused_score)`` pairs, best first.
    """
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    for ids, weight in rankings:
        for position, item in enumerate(ids, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + position)
            first_seen.setdefault(item, len(first_seen))
    return sorted(scores.items(), key=lambda pair: (-pair[1], first_seen[pair[0]]))


def fused_search(
    query: str,
    api_index: tantivy.Index,
    docs_index: tantivy.Index,
    chunks: Mapping[str, Mapping[str, Any]],
    *,
    limit: int,
    fetch: int = 80,
) -> list[FusedPassage]:
    """Search both indexes and return one ranked list of sections.

    Args:
        query: The caller's query, used unchanged by both indexes.
        api_index: The API index from ``build_api_index``.
        docs_index: The docs index from ``build_index``.
        chunks: Every chunk in the bundle, keyed by ``chunk_id``.
        limit: Maximum sections to return.
        fetch: Chunks to read from each index before grouping by section.

    Returns:
        Passages in fused order. Each passage is assembled from every chunk of its
        section, and its ``score`` is the fused score.
    """
    api_found = search_api(api_index, query, fetch)
    docs_found = search(docs_index, query, fetch)
    api_ids = section_ranking(api_found, chunks)
    docs_ids = section_ranking(docs_found, chunks)
    api_weight = API_WEIGHT_SYMBOL if names_symbol(api_index, query) else API_WEIGHT_PROSE
    # Equal weights happen for a symbol name, where both lists may rank a page
    # first. The API list must win that tie, so it goes first in the list order.
    lists = [(api_ids, api_weight), (docs_ids, DOCS_WEIGHT)]
    if api_weight < DOCS_WEIGHT:
        lists.reverse()
    fused = reciprocal_rank_fusion(lists)
    scores = dict(fused)
    best_chunk: dict[str, tuple[str, float]] = {}
    for chunk_id, score in [*api_found, *docs_found]:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        rid = str(chunk["retrieval_id"])
        if rid not in best_chunk or score > best_chunk[rid][1]:
            best_chunk[rid] = (chunk_id, score)
    ordered = [(best_chunk[rid][0], scores[rid]) for rid, _score in fused if rid in best_chunk]
    passages = passages_for_hits(ordered, chunks, limit=limit)
    api_sections = set(api_ids)
    return [
        FusedPassage(
            index="api" if passage.retrieval_id in api_sections else "docs",
            passage=passage,
        )
        for passage in passages
    ]
