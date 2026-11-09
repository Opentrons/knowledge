"""Render canonical content blocks to Markdown for display and indexing."""

from __future__ import annotations

from collections.abc import Sequence

from opentrons_knowledge.models.canonical import (
    AdmonitionBlock,
    Block,
    CodeBlock,
    FigureBlock,
    HeadingBlock,
    HtmlBlock,
    ImageBlock,
    ListBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TabsBlock,
)
from opentrons_knowledge.retrieval.models import Segment


def render_blocks(blocks: Sequence[Block]) -> str:
    """Render blocks as Markdown separated by blank lines.

    Args:
        blocks: Canonical blocks in document order.

    Returns:
        Markdown text; empty when the blocks carry no text.
    """
    return "\n\n".join(part for block in blocks if (part := render_block(block)))


def render_block(block: Block) -> str:
    """Render one block as Markdown.

    Args:
        block: Any canonical block.

    Returns:
        Markdown text for the block.
    """
    match block:
        case ParagraphBlock():
            return block.text
        case HeadingBlock():
            return f"{'#' * block.level} {block.text}"
        case CodeBlock():
            title = f"{block.title}\n" if block.title else ""
            return f"{title}```{block.language or ''}\n{block.code.rstrip()}\n```"
        case ListBlock():
            return _render_list(block)
        case TableBlock():
            return _render_table(block)
        case AdmonitionBlock():
            heading = block.title or block.kind.capitalize()
            body = render_blocks(block.blocks)
            quoted = "\n".join(f"> {line}" if line else ">" for line in body.splitlines())
            return f"> **{heading}**\n{quoted}" if quoted else f"> **{heading}**"
        case TabsBlock():
            return "\n\n".join(
                f"**{tab.label}**\n\n{render_blocks(tab.blocks)}" for tab in block.tabs
            )
        case ImageBlock():
            return f"![{block.alt}]({block.url})" if block.alt else ""
        case FigureBlock():
            body = render_blocks(block.blocks)
            return f"{body}\n\n{block.caption}" if block.caption else body
        case QuoteBlock():
            return "\n".join(f"> {line}" for line in render_blocks(block.blocks).splitlines())
        case HtmlBlock():
            return block.text
    return ""


def section_segments(blocks: Sequence[Block]) -> list[Segment]:
    """Split a section's blocks into segments at top-level block boundaries.

    Each tab of a tab set becomes its own labeled segment, so a chunker can
    index "Flex" and "OT-2" variants separately.

    Args:
        blocks: The section's top-level blocks.

    Returns:
        Non-empty segments in document order.
    """
    segments: list[Segment] = []
    for block in blocks:
        if isinstance(block, TabsBlock):
            segments.extend(
                Segment(label=tab.label, text=text)
                for tab in block.tabs
                if (text := render_blocks(tab.blocks))
            )
        elif text := render_block(block):
            segments.append(Segment(text=text))
    return segments


def _render_list(block: ListBlock) -> str:
    lines: list[str] = []
    number = block.start or 1
    for item in block.items:
        marker = f"{number}." if block.ordered else "-"
        number += 1
        body = render_blocks(item.blocks).splitlines() or [""]
        lines.append(f"{marker} {body[0]}")
        indent = " " * (len(marker) + 1)
        lines.extend(f"{indent}{line}" if line else "" for line in body[1:])
    return "\n".join(lines)


def _render_table(block: TableBlock) -> str:
    rows = [
        [cell.text.replace("|", "\\|").replace("\n", " ") for cell in r.cells] for r in block.rows
    ]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header_count = sum(1 for r in block.rows if r.header)
    header = rows[0] if header_count else [""] * width
    body = rows[1:] if header_count else rows
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *("| " + " | ".join(row) + " |" for row in body),
    ]
    caption = f"{block.caption}\n\n" if block.caption else ""
    return caption + "\n".join(lines)
