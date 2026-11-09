"""Check that every documented symbol resolves to its own reference section."""

from __future__ import annotations

from dataclasses import dataclass

import tantivy

from opentrons_knowledge.retrieval.bm25 import lookup_query, search_api
from opentrons_knowledge.retrieval.models import Chunk, RetrievalDocument


@dataclass(frozen=True)
class SymbolCheck:
    """One symbol and where its lookup query ranked the defining section."""

    api_name: str
    query: str
    retrieval_id: str
    rank: int | None


@dataclass(frozen=True)
class ApiAudit:
    """Hit rates for the API index over every documented symbol."""

    checks: list[SymbolCheck]

    @property
    def total(self) -> int:
        return len(self.checks)

    def hit_rate(self, cutoff: int) -> float:
        """Return the fraction of symbols whose section ranks at or above ``cutoff``.

        Args:
            cutoff: Rank threshold, 1-based.

        Returns:
            The hit rate. Zero when there are no symbols.
        """
        if not self.checks:
            return 0.0
        hits = sum(1 for check in self.checks if check.rank is not None and check.rank <= cutoff)
        return hits / len(self.checks)

    @property
    def misses(self) -> list[SymbolCheck]:
        """Symbols that are not the top hit for their own name."""
        return [check for check in self.checks if check.rank != 1]


def audit_api(
    index: tantivy.Index,
    documents: list[RetrievalDocument],
    chunks: list[Chunk],
    *,
    limit: int = 5,
) -> ApiAudit:
    """Look up every documented symbol and record the rank of its section.

    Args:
        index: The API index.
        documents: Retrieval documents. Only those with ``api_name`` are checked.
        chunks: Chunks in that index, used to map a hit back to a document.
        limit: How deep to search for each symbol.

    Returns:
        One check per symbol, in document order.
    """
    by_chunk = {chunk.chunk_id: chunk for chunk in chunks}
    checks: list[SymbolCheck] = []
    for doc in documents:
        if not doc.api_name:
            continue
        query = lookup_query(doc.api_name)
        seen: list[str] = []
        rank: int | None = None
        for chunk_id, _score in search_api(index, query, limit):
            retrieval_id = by_chunk[chunk_id].retrieval_id
            if retrieval_id not in seen:
                seen.append(retrieval_id)
            if retrieval_id == doc.retrieval_id:
                rank = len(seen)
                break
        checks.append(
            SymbolCheck(
                api_name=doc.api_name,
                query=query,
                retrieval_id=doc.retrieval_id,
                rank=rank,
            )
        )
    return ApiAudit(checks)
