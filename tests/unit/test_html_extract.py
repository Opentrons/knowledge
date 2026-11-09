"""Rendered MkDocs HTML -> canonical sections and blocks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentrons_knowledge.docs.html_extract import (
    ExtractedPage,
    PageContext,
    extract_page,
    section_content_hash,
)
from opentrons_knowledge.docs.icons import IconIndex
from opentrons_knowledge.models.canonical import (
    AdmonitionBlock,
    CanonicalSection,
    CodeBlock,
    FigureBlock,
    HeadingBlock,
    HtmlBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    TabsBlock,
)

SITE = Path(__file__).resolve().parents[1] / "fixtures" / "rendered_site" / "site"
ICONS = Path(__file__).resolve().parents[1] / "fixtures" / "rendered_site" / "checkout"
DOC_ID = "doc:Opentrons_opentrons:000000000000:docs/python-api/docs/pipettes/loading.md"


def _context(page_path: str, *, icons: IconIndex | None = None) -> PageContext:
    return PageContext(
        document_id=DOC_ID,
        page_path=page_path,
        base_url="https://docs.opentrons.com/",
        site_name="Opentrons Documentation",
        icons=icons or IconIndex(),
    )


def _page(rel: str, page_path: str, *, icons: IconIndex | None = None) -> ExtractedPage:
    page = extract_page((SITE / rel).read_text(encoding="utf-8"), _context(page_path, icons=icons))
    assert page is not None
    return page


def _article(body: str) -> ExtractedPage:
    html = (
        f'<html><body><article class="md-content__inner md-typeset">{body}</article></body></html>'
    )
    page = extract_page(html, _context("python-api/x/"))
    assert page is not None
    return page


@pytest.fixture(scope="module")
def loading() -> ExtractedPage:
    icons = IconIndex()
    icons.add_icon_set(ICONS / "docs" / "shared" / "icons")
    return _page(
        "python-api/pipettes/loading/index.html", "python-api/pipettes/loading/", icons=icons
    )


def _by_title(page: ExtractedPage, title: str) -> CanonicalSection:
    return next(s for s in page.sections if s.title == title)


def test_page_metadata(loading: ExtractedPage) -> None:
    assert loading.title == "Loading Pipettes"
    assert loading.page_title == "Python API: Loading Pipettes"
    assert loading.description and loading.description.startswith("Load single-channel")
    assert loading.generator == "mkdocs-1.6.1, mkdocs-material-9.7.0"
    assert loading.nav_path == ["Python API", "Pipettes", "Loading Pipettes"]


def test_theme_chrome_is_excluded(loading: ExtractedPage) -> None:
    dumped = json.dumps([s.model_dump() for s in loading.sections])
    for leaked in ("TOC ENTRY", "EDIT BUTTON", "FOOTER NEXT", "SCRIPT SHOULD", "Search", "¶"):
        assert leaked not in dumped
    assert "min-width" not in dumped


def test_nested_heading_hierarchy_and_ids(loading: ExtractedPage) -> None:
    titles = [(s.level, s.title) for s in loading.sections]
    assert titles == [
        (1, "Loading Pipettes"),
        (2, "API load names"),
        (3, "Steps"),
        (2, "Compatibility"),
        (3, "Water"),
    ]
    root, load_names, steps, compat, water = loading.sections
    assert root.section_id == f"section:{DOC_ID}"
    assert root.url == "https://docs.opentrons.com/python-api/pipettes/loading/"
    assert load_names.section_id == f"section:{DOC_ID}#api-load-names"
    assert load_names.url.endswith("/loading/#api-load-names")
    assert steps.heading_path == ["Loading Pipettes", "API load names", "Steps"]
    assert steps.parent_section_id == load_names.section_id
    assert water.parent_section_id == compat.section_id
    assert root.child_section_ids == [load_names.section_id, compat.section_id]
    assert steps.previous_section_id == load_names.section_id
    assert steps.next_section_id == compat.section_id
    assert [s.ordinal for s in loading.sections] == list(range(5))
    assert all(len(s.content_hash) == 64 for s in loading.sections)


def test_content_order_within_section(loading: ExtractedPage) -> None:
    blocks = _by_title(loading, "API load names").blocks
    assert [type(b) for b in blocks] == [ParagraphBlock, TabsBlock, AdmonitionBlock]


def test_code_tabs_keep_labels_and_complete_code(loading: ExtractedPage) -> None:
    tabs = _by_title(loading, "API load names").blocks[1]
    assert isinstance(tabs, TabsBlock)
    assert [t.label for t in tabs.tabs] == ["Flex", "OT-2"]
    flex_code = tabs.tabs[0].blocks[0]
    assert isinstance(flex_code, CodeBlock)
    assert flex_code.language == "python"
    assert flex_code.code == (
        "# Flex 1-Channel in the left mount\n"
        'pipette = protocol.load_instrument("flex_1channel_1000", "left")'
    )
    ot2 = tabs.tabs[1].blocks
    assert isinstance(ot2[0], CodeBlock) and "p300_single_gen2" in ot2[0].code
    assert ot2[1] == HeadingBlock(level=4, text="OT-2 notes", anchor="ot-2-notes")
    assert isinstance(ot2[2], ParagraphBlock)


def test_admonition_with_code(loading: ExtractedPage) -> None:
    warning = _by_title(loading, "API load names").blocks[2]
    assert isinstance(warning, AdmonitionBlock)
    assert (warning.kind, warning.title, warning.collapsible) == ("warning", "Warning", False)
    assert isinstance(warning.blocks[0], ParagraphBlock)
    code = warning.blocks[1]
    assert isinstance(code, CodeBlock)
    assert code.code.endswith("# second load fails")


def test_collapsible_details(loading: ExtractedPage) -> None:
    details = _by_title(loading, "Water").blocks[1]
    assert isinstance(details, AdmonitionBlock)
    assert (details.kind, details.title, details.collapsible) == ("tip", "Need more help?", True)


def test_ordered_list_with_nested_list(loading: ExtractedPage) -> None:
    (steps,) = _by_title(loading, "Steps").blocks
    assert isinstance(steps, ListBlock)
    assert steps.ordered and steps.start == 3
    first, second = steps.items
    assert first.blocks[0] == ParagraphBlock(text="Attach the pipette.")
    nested = first.blocks[1]
    assert isinstance(nested, ListBlock) and not nested.ordered
    assert [i.blocks[0] for i in nested.items] == [
        ParagraphBlock(text="Check the mount."),
        ParagraphBlock(text="Run **calibration**."),
    ]
    assert second.blocks == [ParagraphBlock(text="Load it in your protocol.\nThen simulate.")]


def test_table_structure_spans_and_icons(loading: ExtractedPage) -> None:
    table = _by_title(loading, "Compatibility").blocks[0]
    assert isinstance(table, TableBlock)
    header, first, second = table.rows
    assert header.header and [c.text for c in header.cells] == ["Pipette", "Flex", "OT-2"]
    assert [(c.text, c.rowspan) for c in first.cells] == [
        ("GEN2", 2),
        (":opentrons-check:", 1),
        ("`p300_single_gen2`", 1),
    ]
    assert second.cells[0].colspan == 2
    assert second.cells[0].text == "- Single\n- Multi"


def test_unresolved_icon_placeholder() -> None:
    page = _article('<h1>T</h1><p>Yes <span class="twemoji"><svg><path d="M0 0"/></svg></span></p>')
    assert page.sections[0].blocks == [ParagraphBlock(text="Yes :icon:")]


def test_figure_image_and_inventory(loading: ExtractedPage) -> None:
    figure = _by_title(loading, "Compatibility").blocks[1]
    assert isinstance(figure, FigureBlock)
    assert figure.caption == "A Flex pipette in the *left* mount."
    (image,) = figure.blocks
    assert image.type == "image"
    assert image.alt == "Flex pipette mounted on the left"
    assert image.url == "https://docs.opentrons.com/python-api/images/pipette.png"
    (ref,) = loading.images
    assert ref.site_path == "python-api/images/pipette.png"
    assert ref.section_id.endswith("#compatibility")


def test_links_inline_and_inventory(loading: ExtractedPage) -> None:
    intro = loading.sections[0].blocks[0]
    assert isinstance(intro, ParagraphBlock)
    assert (
        "[`InstrumentContext`](../../reference/instruments/"
        "#opentrons.protocol_api.InstrumentContext)" in intro.text
    )
    internal, external = loading.links
    assert internal.internal
    assert internal.target_page_path == "python-api/reference/instruments/"
    assert internal.target_anchor == "opentrons.protocol_api.InstrumentContext"
    assert not external.internal and external.url == "https://opentrons.com/pipettes"


def test_plugin_expanded_content_is_kept(loading: ExtractedPage) -> None:
    water = _by_title(loading, "Water")
    table = water.blocks[0]
    assert isinstance(table, TableBlock)
    assert [c.text for c in table.rows[1].cells] == ["Aspirate flow rate", "478 µL/s"]


def test_unsupported_markup_preserved_as_html(loading: ExtractedPage) -> None:
    blocks = _by_title(loading, "Water").blocks
    iframe = blocks[2]
    assert isinstance(iframe, HtmlBlock)
    assert iframe.reason == "unsupported-element:iframe"
    assert "youtube.com/embed" in iframe.html
    assert blocks[3] == ParagraphBlock(text="*Loose inline text* after the video.")


def test_mkdocstrings_api_sections() -> None:
    page = _page("python-api/reference/instruments/index.html", "python-api/reference/instruments/")
    titles = [s.heading_path for s in page.sections]
    assert titles == [
        ["Instruments"],
        ["Instruments", "InstrumentContext"],
        ["Instruments", "InstrumentContext", "aspirate"],
        ["Instruments", "InstrumentContext", "channels"],
    ]
    cls, aspirate, channels = page.sections[1:]
    assert cls.api is not None and cls.api.kind == "class"
    assert aspirate.api is not None
    assert aspirate.api.qualified_name == "opentrons.protocol_api.InstrumentContext.aspirate"
    assert (aspirate.api.kind, aspirate.api.labels) == ("function", ["v2.0"])
    assert channels.api is not None and channels.api.labels == ["property", "v2.0"]
    signature = aspirate.blocks[0]
    assert isinstance(signature, CodeBlock) and signature.role == "signature"
    assert signature.code == "aspirate(\n    volume: float | None = None,\n) -> InstrumentContext"
    params = aspirate.blocks[3]
    assert isinstance(params, ListBlock)
    assert params.items[0].blocks[0] == ParagraphBlock(
        text="**`volume`** (`float`, default: `None` ) \u2013"
    )


def test_preamble_before_first_heading_becomes_root() -> None:
    page = _article("<p>Intro.</p><h2 id='a'>A</h2><p>Body.</p>")
    root, child = page.sections
    assert (root.level, root.title, root.blocks) == (
        0,
        "python-api/x/",
        [ParagraphBlock(text="Intro.")],
    )
    assert child.parent_section_id == root.section_id


def test_page_without_headings_has_single_root() -> None:
    page = _article("<p>Only text.</p>")
    assert len(page.sections) == 1
    assert page.sections[0].blocks == [ParagraphBlock(text="Only text.")]


def test_same_prose_on_two_paths_has_distinct_hashes() -> None:
    def section(path: str, anchor: str) -> CanonicalSection:
        document_id = f"doc:Opentrons_opentrons:000000000000:{path}"
        return CanonicalSection(
            section_id=f"section:{document_id}#{anchor}",
            document_id=document_id,
            ordinal=1,
            level=2,
            title="Warranty",
            anchor="warranty",
            url=f"https://docs.opentrons.com/{path}#warranty",
            heading_path=["Warranty"],
            blocks=[ParagraphBlock(text="Covered for one year.")],
            content_hash="pending",
        )

    flex = section("docs/flex/docs/additional-info.md", "warranty")
    ot2 = section("docs/ot-2/docs/additional-info.md", "warranty")
    assert section_content_hash(flex) != section_content_hash(ot2)
    again = section("docs/flex/docs/additional-info.md", "warranty-2")
    assert section_content_hash(flex) != section_content_hash(again)


def test_missing_and_duplicate_anchors_get_unique_ids() -> None:
    page = _article("<h1>T</h1><h2>Same</h2><h2>Same</h2>")
    ids = [s.section_id.rsplit("#", 1)[-1] for s in page.sections[1:]]
    assert ids == ["same", "same-2"]
    assert all(s.anchor is None for s in page.sections[1:])


def test_page_without_article_is_skipped() -> None:
    assert extract_page("<html><body><pre>info</pre></body></html>", _context("info/")) is None
