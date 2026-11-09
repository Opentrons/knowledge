"""Turn chunk hits into the section a caller should read.

The docs index stores a long section as more than one chunk: one chunk per tab,
and a split at a block boundary once a section passes 400 words. Those pieces
exist so search can tell them apart. The text we return is all of them, in
order. A match on the heading must not stop at the first piece and drop the
rest of the section.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Passage:
    """One section assembled from the chunk that matched and its siblings."""

    retrieval_id: str
    chunk_id: str
    score: float
    text: str


def chunk_body(text: str) -> str:
    """Return the chunk text without the heading breadcrumb.

    Args:
        text: Stored chunk text. The breadcrumb is the first paragraph.

    Returns:
        The body. The whole string, when there is no breadcrumb.
    """
    _heading, separator, body = text.partition("\n\n")
    return body if separator else text


def section_passage(chunks: Sequence[Mapping[str, Any]]) -> str:
    """Join every chunk of one section into the passage a result shows.

    Args:
        chunks: Chunks that share a ``retrieval_id``.

    Returns:
        The breadcrumb once, then each body in ordinal order. A single chunk is
        returned unchanged.
    """
    ordered = sorted(chunks, key=lambda chunk: int(chunk["ordinal"]))
    if len(ordered) == 1:
        return str(ordered[0]["text"])
    context, separator, _body = str(ordered[0]["text"]).partition("\n\n")
    parts = [context] if separator else []
    for chunk in ordered:
        body = chunk_body(str(chunk["text"]))
        label = chunk.get("label")
        parts.append(f"**{label}**\n\n{body}" if label else body)
    return "\n\n".join(part for part in parts if part)


def passages_for_hits(
    found: Sequence[tuple[str, float]],
    chunks: Mapping[str, Mapping[str, Any]],
    *,
    limit: int,
) -> list[Passage]:
    """Collapse ranked chunks to one passage per section.

    Args:
        found: ``(chunk_id, score)`` pairs, best first.
        chunks: Every chunk in the bundle, keyed by ``chunk_id``.
        limit: Maximum sections to return.

    Returns:
        Passages in rank order. A later chunk of a section already returned is
        skipped, and the score kept is the best chunk of that section.
    """
    by_section: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for chunk in chunks.values():
        by_section[str(chunk["retrieval_id"])].append(chunk)
    passages: list[Passage] = []
    seen: set[str] = set()
    for chunk_id, score in found:
        matched = chunks.get(chunk_id)
        if matched is None:
            continue
        retrieval_id = str(matched["retrieval_id"])
        if retrieval_id in seen:
            continue
        seen.add(retrieval_id)
        passages.append(
            Passage(
                retrieval_id=retrieval_id,
                chunk_id=chunk_id,
                score=score,
                text=section_passage(by_section[retrieval_id]),
            )
        )
        if len(passages) >= limit:
            break
    return passages
