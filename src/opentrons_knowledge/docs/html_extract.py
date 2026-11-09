"""Extract structured content from a rendered MkDocs Material page.

Only the article (``article.md-content__inner``) is read; Material's header,
navigation, search, table of contents, and footer are outside it. Headings at
the article's flow level (including mkdocstrings object headings) start
sections. Everything between headings becomes ordered content blocks.
Containers that cannot hold a section boundary (tabs, admonitions, lists,
tables, figures) keep their children as nested blocks.

Markup without a faithful structured form is kept as an ``html`` block rather
than dropped. Theme-only elements (permalink anchors, edit buttons, scripts,
styles, form controls) are skipped.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, PreformattedString, Tag

from opentrons_knowledge.docs.icons import IconIndex, icon_key
from opentrons_knowledge.models.canonical import (
    AdmonitionBlock,
    ApiObject,
    Block,
    CanonicalSection,
    CodeBlock,
    FigureBlock,
    HeadingBlock,
    HtmlBlock,
    ImageBlock,
    ImageRef,
    LinkRef,
    ListBlock,
    ListItem,
    ParagraphBlock,
    QuoteBlock,
    Tab,
    TableBlock,
    TableCell,
    TableRow,
    TabsBlock,
)
from opentrons_knowledge.normalization.ids import content_hash, slugify
from opentrons_knowledge.normalization.serialize import dumps_canonical_json

HTML_PARSER = "lxml"
ARTICLE_SELECTOR = "article.md-content__inner"

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "form",
    "nav",
    "button",
    "input",
    "select",
    "textarea",
}
_RAW_TAGS = {
    "iframe",
    "video",
    "audio",
    "object",
    "embed",
    "canvas",
    "svg",
    "math",
    "dl",
    "picture",
    "map",
}
_TRANSPARENT_TAGS = {"div", "section", "article", "main", "header", "footer", "aside", "center"}
_STRUCTURED_TAGS = {"p", "ul", "ol", "pre", "table", "figure", "blockquote", "hr", "details", "img"}
_BLOCK_TAGS = _HEADINGS | _SKIP_TAGS | _RAW_TAGS | _TRANSPARENT_TAGS | _STRUCTURED_TAGS
_THEME_CLASSES = {
    "headerlink",
    "md-content__button",
    "md-source-file",
    "md-tags",
    "md-feedback",
    "md-top",
    "linenos",
}
_API_KINDS = ("doc-module", "doc-class", "doc-function", "doc-attribute", "doc-method")
_WS_RE = re.compile(r"\s+")
_LINE_WS_RE = re.compile(r"[ \t]*\n[ \t]*")


@dataclass(frozen=True)
class PageContext:
    """Identity of the page being extracted.

    Attributes:
        document_id: Stable document ID used to derive section IDs.
        page_path: Site-relative page path (``python-api/labware/``).
        base_url: Published site root, with trailing slash.
        site_name: MkDocs ``site_name``, stripped from ``<title>`` suffixes.
        icons: Reverse index for inline SVG icons.
        asset_source: Maps a site-relative asset path to its repository path.
    """

    document_id: str
    page_path: str
    base_url: str
    site_name: str | None = None
    icons: IconIndex = field(default_factory=IconIndex)
    asset_source: Callable[[str], str | None] = lambda _path: None

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.page_path}"


@dataclass
class ExtractedPage:
    """Page content and metadata, before source provenance is attached."""

    title: str
    page_title: str | None
    description: str | None
    generator: str | None
    nav_path: list[str]
    sections: list[CanonicalSection]
    links: list[LinkRef]
    images: list[ImageRef]


def extract_page(html: str, context: PageContext) -> ExtractedPage | None:
    """Parse one rendered page.

    Args:
        html: Full HTML document produced by MkDocs.
        context: Page identity and resolution helpers.

    Returns:
        The extracted page, or ``None`` when the page has no Material article
        (for example a bare partial or a build-info page).
    """
    soup = BeautifulSoup(html, HTML_PARSER)
    article = soup.select_one(ARTICLE_SELECTOR)
    if article is None:
        return None
    page_title = _page_title(soup, context.site_name)
    first_h1 = article.find("h1")
    title = (
        (_plain_text(first_h1) if isinstance(first_h1, Tag) else "")
        or page_title
        or context.page_path
    )
    extractor = _ArticleExtractor(context, title)
    extractor.run(article)
    return ExtractedPage(
        title=title,
        page_title=page_title,
        description=_meta(soup, "description"),
        generator=_meta(soup, "generator"),
        nav_path=_nav_path(soup),
        sections=extractor.sections,
        links=extractor.links,
        images=extractor.images,
    )


def section_content_hash(section: CanonicalSection) -> str:
    """SHA-256 of a section bound to the page path it came from.

    ``document_id`` contains the Markdown path, so the same prose on two pages
    (a Flex page and its OT-2 copy, for example) does not share a hash.
    ``section_id`` separates two headings on one page that share a body.
    Neighbor links stay out of the hash, so an edit to the section graph does
    not change it.
    """
    payload = section.model_dump(
        mode="json",
        include={"document_id", "section_id", "title", "level", "anchor", "api", "blocks"},
    )
    return content_hash(dumps_canonical_json(payload))


class _ArticleExtractor:
    def __init__(self, context: PageContext, page_title: str) -> None:
        self.context = context
        self.page_title = page_title
        self.sections: list[CanonicalSection] = []
        self.links: list[LinkRef] = []
        self.images: list[ImageRef] = []
        self._stack: list[CanonicalSection] = []
        self._preamble: list[Block] = []
        self._anchors: set[str] = set()

    # -- sections ---------------------------------------------------------

    @property
    def _current_blocks(self) -> list[Block]:
        return self._stack[-1].blocks if self._stack else self._preamble

    @property
    def _current_section_id(self) -> str:
        return self._stack[-1].section_id if self._stack else self._root_id

    @property
    def _root_id(self) -> str:
        return f"section:{self.context.document_id}"

    def run(self, article: Tag) -> None:
        self._flow(article, None)
        if not self.sections:
            self._open_root_from_preamble()
        self._finish()

    def _open_root_from_preamble(self) -> None:
        root = self._new_section(
            section_id=self._root_id,
            level=0,
            title=self.page_title,
            anchor=None,
            parent=None,
            api=None,
        )
        root.blocks.extend(self._preamble)
        self._preamble = []
        self._stack = [root]

    def _start_section(self, heading: Tag) -> None:
        level = int(heading.name[1])
        title = _plain_text(heading)
        anchor = _attr(heading, "id")
        if not self.sections:
            if self._preamble:
                self._open_root_from_preamble()
            else:
                self._anchors.add(anchor or "")
                self._stack = [
                    self._new_section(
                        section_id=self._root_id,
                        level=level,
                        title=title,
                        anchor=anchor,
                        parent=None,
                        api=self._api_object(heading),
                    )
                ]
                return
        while self._stack and self._stack[-1].level >= level:
            self._stack.pop()
        parent = self._stack[-1] if self._stack else None
        key = self._unique_anchor(anchor or slugify(title))
        section = self._new_section(
            section_id=f"{self._root_id}#{key}",
            level=level,
            title=title,
            anchor=anchor,
            parent=parent,
            api=self._api_object(heading),
        )
        self._stack.append(section)

    def _new_section(
        self,
        *,
        section_id: str,
        level: int,
        title: str,
        anchor: str | None,
        parent: CanonicalSection | None,
        api: ApiObject | None,
    ) -> CanonicalSection:
        section = CanonicalSection(
            section_id=section_id,
            document_id=self.context.document_id,
            ordinal=len(self.sections),
            level=level,
            title=title,
            anchor=anchor,
            url=f"{self.context.url}#{anchor}" if anchor else self.context.url,
            heading_path=[*parent.heading_path, title] if parent else [title],
            parent_section_id=parent.section_id if parent else None,
            api=api,
            content_hash="",
        )
        if parent is not None:
            parent.child_section_ids.append(section_id)
        self.sections.append(section)
        return section

    def _unique_anchor(self, anchor: str) -> str:
        candidate, n = anchor, 2
        while candidate in self._anchors:
            candidate = f"{anchor}-{n}"
            n += 1
        self._anchors.add(candidate)
        return candidate

    def _api_object(self, heading: Tag) -> ApiObject | None:
        parent = heading.parent
        if not isinstance(parent, Tag) or "doc-object" not in _classes(parent):
            return None
        kind = next((k.removeprefix("doc-") for k in _API_KINDS if k in _classes(parent)), "object")
        labels = [
            _WS_RE.sub(" ", label.get_text()).strip()
            for label in heading.select(".doc-labels .doc-label")
        ]
        return ApiObject(
            qualified_name=_attr(heading, "id") or _plain_text(heading),
            kind=kind,
            labels=labels,
        )

    def _finish(self) -> None:
        for index, section in enumerate(self.sections):
            if index > 0:
                section.previous_section_id = self.sections[index - 1].section_id
            if index + 1 < len(self.sections):
                section.next_section_id = self.sections[index + 1].section_id
            section.content_hash = section_content_hash(section)

    # -- block flow -------------------------------------------------------

    def _flow(
        self, container: Tag, out: list[Block] | None, *, exclude: Tag | None = None
    ) -> list[Block]:
        """Convert a container's children to blocks.

        ``out=None`` means section-flow mode: headings open sections and blocks
        go to the current section. Otherwise blocks are appended to ``out``.
        """
        run: list[PageElement] = []

        def emit(blocks: Iterable[Block]) -> None:
            target = self._current_blocks if out is None else out
            target.extend(blocks)

        def flush() -> None:
            if run:
                emit(self._inline_run(run))
                run.clear()

        for child in container.children:
            if child is exclude:
                continue
            if isinstance(child, NavigableString):
                if not isinstance(child, PreformattedString):
                    run.append(child)
                continue
            if not isinstance(child, Tag) or _is_theme_ui(child):
                continue
            if child.name not in _BLOCK_TAGS:
                run.append(child)
                continue
            flush()
            if child.name in _SKIP_TAGS:
                continue
            if child.name in _HEADINGS:
                if out is None:
                    self._start_section(child)
                else:
                    out.append(
                        HeadingBlock(
                            level=int(child.name[1]),
                            text=_plain_text(child),
                            anchor=_attr(child, "id"),
                        )
                    )
                continue
            if child.name in _TRANSPARENT_TAGS and not self._is_structured_div(child):
                self._flow(child, out)
                continue
            emit(self._block(child))
        flush()
        return out if out is not None else []

    def _is_structured_div(self, tag: Tag) -> bool:
        classes = _classes(tag)
        return tag.name == "div" and (
            "highlight" in classes or "tabbed-set" in classes or "admonition" in classes
        )

    def _block(self, tag: Tag) -> list[Block]:
        name = tag.name
        classes = _classes(tag)
        if name == "p":
            return self._inline_run(list(tag.children))
        if name in {"ul", "ol"}:
            return [self._list(tag)]
        if name == "pre" or "highlight" in classes:
            return [self._code(tag)]
        if name == "table":
            if "highlighttable" in classes:
                return [self._code(tag)]
            return [self._table(tag)]
        if "tabbed-set" in classes:
            return [self._tabs(tag)]
        if "admonition" in classes or name == "details":
            return [self._admonition(tag)]
        if name == "figure":
            caption_tag = tag.find("figcaption", recursive=False)
            caption = (
                self._inline_text(list(caption_tag.children))
                if isinstance(caption_tag, Tag)
                else None
            )
            exclude = caption_tag if isinstance(caption_tag, Tag) else None
            return [
                FigureBlock(caption=caption or None, blocks=self._flow(tag, [], exclude=exclude))
            ]
        if name == "blockquote":
            return [QuoteBlock(blocks=self._flow(tag, []))]
        if name == "img":
            return [self._image_block(tag)]
        if name == "hr":
            return []
        return [
            HtmlBlock(
                html=str(tag),
                text=_plain_text(tag),
                reason=f"unsupported-element:{name}",
            )
        ]

    def _list(self, tag: Tag) -> ListBlock:
        ordered = tag.name == "ol"
        start = _attr(tag, "start")
        items = [
            ListItem(blocks=self._flow(li, []))
            for li in tag.find_all("li", recursive=False)
            if isinstance(li, Tag)
        ]
        return ListBlock(
            ordered=ordered,
            start=int(start) if ordered and start and start.isdigit() else None,
            items=items,
        )

    def _code(self, tag: Tag) -> CodeBlock:
        classes = _classes(tag)
        pre: Tag | None = tag if tag.name == "pre" else None
        if pre is None:
            code_cell = tag.select_one("td.code pre")
            found = code_cell or tag.find("pre")
            pre = found if isinstance(found, Tag) else None
        code_tag = pre.find("code") if pre is not None else None
        source = code_tag if isinstance(code_tag, Tag) else pre
        language = _language(classes) or (
            _language(_classes(source)) if isinstance(source, Tag) else None
        )
        title_tag = tag.select_one(".filename")
        text = _code_text(source) if isinstance(source, Tag) else ""
        return CodeBlock(
            language=language,
            code=text.rstrip("\n"),
            title=_plain_text(title_tag) if isinstance(title_tag, Tag) else None,
            role="signature" if "doc-signature" in classes else None,
        )

    def _table(self, tag: Tag) -> TableBlock:
        rows: list[TableRow] = []
        for tr in tag.find_all("tr"):
            if not isinstance(tr, Tag) or tr.find_parent("table") is not tag:
                continue
            cells = [
                TableCell(
                    text=self._cell_text(cell),
                    header=cell.name == "th",
                    rowspan=_int_attr(cell, "rowspan"),
                    colspan=_int_attr(cell, "colspan"),
                )
                for cell in tr.find_all(["th", "td"], recursive=False)
                if isinstance(cell, Tag)
            ]
            in_head = isinstance(tr.parent, Tag) and tr.parent.name == "thead"
            rows.append(
                TableRow(
                    header=in_head or (bool(cells) and all(c.header for c in cells)), cells=cells
                )
            )
        caption = tag.find("caption", recursive=False)
        return TableBlock(
            caption=self._inline_text(list(caption.children)) or None
            if isinstance(caption, Tag)
            else None,
            rows=rows,
        )

    def _cell_text(self, cell: Tag) -> str:
        return "\n".join(t for t in (_blocks_text(b) for b in self._flow(cell, [])) if t)

    def _tabs(self, tag: Tag) -> Block:
        labels_div = tag.find("div", class_="tabbed-labels", recursive=False)
        if isinstance(labels_div, Tag):
            labels = [lab for lab in labels_div.find_all("label", recursive=False)]
            content = tag.find("div", class_="tabbed-content", recursive=False)
            bodies = (
                [b for b in content.find_all("div", class_="tabbed-block", recursive=False)]
                if isinstance(content, Tag)
                else []
            )
        else:
            labels = [lab for lab in tag.find_all("label", recursive=False)]
            bodies = [b for b in tag.find_all("div", class_="tabbed-content", recursive=False)]
        if not labels or len(labels) != len(bodies):
            return HtmlBlock(html=str(tag), text=_plain_text(tag), reason="unrecognized-tab-set")
        return TabsBlock(
            tabs=[
                Tab(label=_plain_text(label), blocks=self._flow(body, []))
                for label, body in zip(labels, bodies, strict=True)
                if isinstance(label, Tag) and isinstance(body, Tag)
            ]
        )

    def _admonition(self, tag: Tag) -> AdmonitionBlock:
        if tag.name == "details":
            title_tag = tag.find("summary", recursive=False)
            kinds = _classes(tag)
            kind = kinds[0] if kinds else "details"
        else:
            title_tag = tag.find("p", class_="admonition-title", recursive=False)
            kinds = [c for c in _classes(tag) if c != "admonition"]
            kind = kinds[0] if kinds else "note"
        title = self._inline_text(list(title_tag.children)) if isinstance(title_tag, Tag) else None
        return AdmonitionBlock(
            kind=kind,
            title=title or None,
            collapsible=tag.name == "details",
            blocks=self._flow(tag, [], exclude=title_tag if isinstance(title_tag, Tag) else None),
        )

    # -- inline -----------------------------------------------------------

    def _inline_run(self, nodes: list[PageElement]) -> list[Block]:
        meaningful = [n for n in nodes if not (isinstance(n, NavigableString) and not n.strip())]
        if meaningful and all(isinstance(n, Tag) and n.name == "img" for n in meaningful):
            return [self._image_block(n) for n in meaningful if isinstance(n, Tag)]
        text = self._inline_text(nodes)
        return [ParagraphBlock(text=text)] if text else []

    def _inline_text(self, nodes: Iterable[PageElement]) -> str:
        text = "".join(self._inline(node) for node in nodes)
        text = _LINE_WS_RE.sub("\n", text)
        return re.sub(r" {2,}", " ", text).strip()

    def _inline(self, node: PageElement) -> str:
        if isinstance(node, NavigableString):
            return "" if isinstance(node, PreformattedString) else _WS_RE.sub(" ", str(node))
        if not isinstance(node, Tag) or _is_theme_ui(node) or node.name in _SKIP_TAGS:
            return ""
        name = node.name
        if name == "br":
            return "\n"
        if name == "code":
            code = _WS_RE.sub(" ", node.get_text())
            fence = "``" if "`" in code else "`"
            return f"{fence}{code}{fence}" if code.strip() else ""
        if name == "img":
            ref = self._record_image(node)
            return f"![{ref.alt}]({ref.src})"
        if name == "svg" or (name == "span" and "twemoji" in _classes(node)):
            return self._icon(node)
        inner = "".join(self._inline(child) for child in node.children)
        if name in {"strong", "b"}:
            return _wrap(inner, "**")
        if name in {"em", "i"}:
            return _wrap(inner, "*")
        if name in {"del", "s"}:
            return _wrap(inner, "~~")
        if name == "a":
            href = _attr(node, "href")
            if not href or not inner.strip():
                return inner
            self._record_link(inner.strip(), href)
            return f"[{inner.strip()}]({href})"
        if name in _BLOCK_TAGS:
            return f"\n{inner}\n"
        return inner

    def _icon(self, node: Tag) -> str:
        svg = node if node.name == "svg" else node.find("svg")
        if isinstance(svg, Tag):
            key = icon_key(
                str(p.get("d") or "") for p in svg.find_all("path") if isinstance(p, Tag)
            )
            shortcode = self.context.icons.lookup(key)
            if shortcode:
                return shortcode
        title = _attr(node, "title")
        return f":{slugify(title)}:" if title else ":icon:"

    def _image_block(self, tag: Tag) -> ImageBlock:
        ref = self._record_image(tag)
        return ImageBlock(src=ref.src, url=ref.url, alt=ref.alt, title=_attr(tag, "title"))

    def _record_image(self, tag: Tag) -> ImageRef:
        src = _attr(tag, "src") or ""
        url = urljoin(self.context.url, src)
        site_path = self._site_path(url)
        ref = ImageRef(
            section_id=self._current_section_id,
            src=src,
            url=url,
            alt=_attr(tag, "alt") or "",
            site_path=site_path,
            source_path=self.context.asset_source(site_path) if site_path else None,
        )
        self.images.append(ref)
        return ref

    def _record_link(self, text: str, href: str) -> None:
        url = urljoin(self.context.url, href)
        site_path = self._site_path(url)
        target, anchor = (None, None)
        if site_path is not None:
            target = site_path.split("?", 1)[0]
            anchor = urldefrag(url).fragment or None
        self.links.append(
            LinkRef(
                section_id=self._current_section_id,
                text=text,
                href=href,
                url=url,
                internal=site_path is not None,
                target_page_path=target,
                target_anchor=anchor,
            )
        )

    def _site_path(self, url: str) -> str | None:
        base = self.context.base_url
        if not url.startswith(base):
            return None
        return urldefrag(url).url[len(base) :]


# -- helpers -----------------------------------------------------------------


def _blocks_text(block: Block) -> str:
    """Compact text rendering of a block, used for table cells."""
    if isinstance(block, ParagraphBlock):
        return block.text
    if isinstance(block, HeadingBlock):
        return block.text
    if isinstance(block, CodeBlock):
        return f"`{block.code}`" if "\n" not in block.code else f"```\n{block.code}\n```"
    if isinstance(block, ListBlock):
        lines = []
        for n, item in enumerate(block.items, start=block.start or 1):
            marker = f"{n}." if block.ordered else "-"
            lines.append(f"{marker} " + " ".join(_blocks_text(b) for b in item.blocks))
        return "\n".join(lines)
    if isinstance(block, ImageBlock):
        return f"![{block.alt}]({block.src})"
    if isinstance(block, HtmlBlock):
        return block.text
    if isinstance(block, (AdmonitionBlock, FigureBlock, QuoteBlock)):
        return "\n".join(_blocks_text(b) for b in block.blocks)
    if isinstance(block, TabsBlock):
        return "\n".join(
            f"{tab.label}: " + " ".join(_blocks_text(b) for b in tab.blocks) for tab in block.tabs
        )
    if isinstance(block, TableBlock):
        return "\n".join(" | ".join(c.text for c in row.cells) for row in block.rows)
    return ""


def _code_text(tag: Tag) -> str:
    parts: list[str] = []
    for node in tag.descendants:
        if isinstance(node, NavigableString) and not isinstance(node, PreformattedString):
            if any(isinstance(p, Tag) and _is_theme_ui(p) for p in node.parents):
                continue
            parts.append(str(node))
    return "".join(parts)


def _plain_text(tag: Tag) -> str:
    """Visible text of a tag, excluding permalinks and mkdocstrings labels."""
    parts: list[str] = []
    for node in tag.descendants:
        if not isinstance(node, NavigableString) or isinstance(node, PreformattedString):
            continue
        if any(
            isinstance(p, Tag) and (_is_theme_ui(p) or "doc-labels" in _classes(p))
            for p in node.parents
        ):
            continue
        parts.append(str(node))
    return _WS_RE.sub(" ", "".join(parts)).strip()


def _wrap(inner: str, marker: str) -> str:
    stripped = inner.strip()
    if not stripped:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{marker}{stripped}{marker}{trail}"


def _is_theme_ui(tag: Tag) -> bool:
    return bool(_THEME_CLASSES.intersection(_classes(tag)))


def _classes(tag: Tag) -> list[str]:
    value = tag.get("class")
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    return [str(v) for v in value]


def _attr(tag: Tag, name: str) -> str | None:
    value = tag.get(name)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return " ".join(str(v) for v in value)


def _int_attr(tag: Tag, name: str) -> int:
    value = _attr(tag, name)
    return int(value) if value and value.isdigit() else 1


def _language(classes: list[str]) -> str | None:
    for cls in classes:
        if cls.startswith("language-"):
            return cls.removeprefix("language-") or None
    return None


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"name": name})
    return _attr(tag, "content") if isinstance(tag, Tag) else None


def _page_title(soup: BeautifulSoup, site_name: str | None) -> str | None:
    tag = soup.find("title")
    if not isinstance(tag, Tag):
        return None
    title = _WS_RE.sub(" ", tag.get_text()).strip()
    if site_name and title.endswith(f" - {site_name}"):
        title = title.removesuffix(f" - {site_name}")
    return title or None


def _nav_path(soup: BeautifulSoup) -> list[str]:
    nav = soup.select_one("nav.md-nav--primary")
    if nav is None:
        return []
    path: list[str] = []
    for item in nav.select("li.md-nav__item--active"):
        link = item.find(class_="md-nav__link")
        if isinstance(link, Tag):
            text = _WS_RE.sub(" ", link.get_text()).strip()
            if text:
                path.append(text)
    return path
