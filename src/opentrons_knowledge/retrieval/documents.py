"""Build retrieval documents from canonical docs, API symbols, entities, and AI guides.

Every builder derives ``retrieval_id`` from a source path (page path and anchor,
module path, definition path, guide file and anchor), never from a title or
display name, and ``build_retrieval_documents`` fails on any duplicate.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from opentrons_knowledge.docs.canonical import CANONICAL_DIR
from opentrons_knowledge.models.canonical import CanonicalDocument, CanonicalSection
from opentrons_knowledge.models.records import CodeSymbol, Document, Entity, Section
from opentrons_knowledge.normalization.ids import content_hash, slugify
from opentrons_knowledge.normalization.serialize import dumps_canonical_json, read_jsonl_zst
from opentrons_knowledge.retrieval.models import RetrievalDocument, RetrievalKind, Segment
from opentrons_knowledge.retrieval.render import render_blocks, section_segments
from opentrons_knowledge.shared_data.entities import (
    labware_robot_scope,
    module_robot_scope,
    pipette_robot_scope,
)

PROTOCOL_API_PREFIX = "opentrons.protocol_api."

_DOC_TYPE_RULES: list[tuple[str, str]] = [
    ("docs/python-api/docs/reference/*", "api_reference"),
    ("docs/python-api/docs/examples.md", "example"),
    ("docs/python-api/docs/tutorial.md", "example"),
    ("docs/python-api/docs/deck-slots.md", "deck_layout"),
    ("docs/*/docs/modules/*", "module_guide"),
    ("docs/*/docs/labware/*", "labware_spec"),
    ("docs/python-api/docs/labware.md", "labware_spec"),
    ("docs/python-api/*", "api_reference"),
    ("docs/flex/*", "user_manual"),
    ("docs/ot-2/*", "user_manual"),
    ("docs/protocol-designer/*", "pd_reference"),
]
"""Path rules for ``doc_type``, in order, plus Protocol Designer."""

_MODULE_PROJECTS = frozenset(
    {
        "absorbance-plate-reader",
        "heater-shaker",
        "hepa-uv",
        "stacker",
        "temperature-module",
        "thermocycler",
    }
)
_ROBOT_PROJECTS = {"flex": ["flex"], "ot-2": ["ot-2"]}


@dataclass(frozen=True)
class RetrievalInputs:
    """Corpus records a retrieval build reads.

    Attributes:
        canonical_documents: Rendered documentation pages.
        symbols: Protocol API symbols from the normalized corpus.
        entities: Shared-data entities from the normalized corpus.
        guide_documents: AI guide documents (``source_type == "ai_guidance"``).
        guide_sections: Sections belonging to ``guide_documents``.
    """

    canonical_documents: Sequence[CanonicalDocument]
    symbols: Sequence[CodeSymbol] = ()
    entities: Sequence[Entity] = ()
    guide_documents: Sequence[Document] = ()
    guide_sections: Sequence[Section] = ()


def load_retrieval_inputs(corpus_dir: Path, canonical_dir: Path | None = None) -> RetrievalInputs:
    """Read retrieval inputs from an unpacked corpus.

    Args:
        corpus_dir: Corpus root containing ``corpus/*.jsonl.zst``.
        canonical_dir: Canonical docs directory; defaults to ``<corpus_dir>/canonical``.

    Returns:
        The records a retrieval build reads.
    """
    records = corpus_dir / "corpus"
    canonical = canonical_dir or corpus_dir / CANONICAL_DIR
    documents = [
        Document.model_validate(d) for d in read_jsonl_zst(records / "documents.jsonl.zst")
    ]
    guides = [d for d in documents if d.source_type == "ai_guidance"]
    guide_ids = {d.document_id for d in guides}
    return RetrievalInputs(
        canonical_documents=[
            CanonicalDocument.model_validate(d)
            for d in read_jsonl_zst(canonical / "documents.jsonl.zst")
        ],
        symbols=[
            CodeSymbol.model_validate(s) for s in read_jsonl_zst(records / "code-symbols.jsonl.zst")
        ],
        entities=[Entity.model_validate(e) for e in read_jsonl_zst(records / "entities.jsonl.zst")],
        guide_documents=guides,
        guide_sections=[
            Section.model_validate(s)
            for s in read_jsonl_zst(records / "sections.jsonl.zst")
            if s["document_id"] in guide_ids
        ],
    )


def build_retrieval_documents(
    inputs: RetrievalInputs, kinds: Iterable[RetrievalKind] = tuple(RetrievalKind)
) -> list[RetrievalDocument]:
    """Build retrieval documents of the requested kinds.

    Args:
        inputs: Corpus records to read.
        kinds: Which document kinds to include.

    Returns:
        Documents in source order (pages, then symbols, entities, guides).

    Raises:
        ValueError: If two documents share a ``retrieval_id``.
    """
    wanted = set(kinds)
    docs: list[RetrievalDocument] = []
    if RetrievalKind.DOC_SECTION in wanted:
        docs.extend(doc_section_documents(inputs.canonical_documents))
    if RetrievalKind.API_SYMBOL in wanted:
        docs.extend(api_symbol_documents(inputs.symbols, inputs.canonical_documents))
    if RetrievalKind.ENTITY in wanted:
        docs.extend(entity_documents(inputs.entities))
    if RetrievalKind.GUIDE_SECTION in wanted:
        docs.extend(guide_section_documents(inputs.guide_documents, inputs.guide_sections))
    duplicates = _duplicates(d.retrieval_id for d in docs)
    if duplicates:
        msg = f"Duplicate retrieval ids: {duplicates[:5]}"
        raise ValueError(msg)
    return docs


# ---------------------------------------------------------------------------
# Documentation sections
# ---------------------------------------------------------------------------


def doc_section_documents(pages: Sequence[CanonicalDocument]) -> list[RetrievalDocument]:
    """One retrieval document per canonical section that has content.

    Pages excluded from MkDocs search and heading-only sections are skipped.

    Args:
        pages: Canonical documents.

    Returns:
        Retrieval documents keyed ``doc:<page_path>#<anchor>``.
    """
    docs: list[RetrievalDocument] = []
    for page in pages:
        if page.search_exclude:
            continue
        source_path = page.source.markdown_path or page.rendered.html_path
        doc_type = doc_type_for_path(source_path, page.project)
        for section in page.sections:
            segments = section_segments(section.blocks)
            if not segments:
                continue
            retrieval_id = doc_retrieval_id(page.page_path, section)
            text = render_blocks(section.blocks)
            api = section.api
            docs.append(
                RetrievalDocument(
                    retrieval_id=retrieval_id,
                    kind=RetrievalKind.DOC_SECTION,
                    group_id=f"doc:{page.page_path}",
                    title=section.title,
                    heading_path=section.heading_path,
                    text=text,
                    segments=segments,
                    url=section.url,
                    source_url=page.source.markdown_url,
                    source_path=source_path,
                    source_record_ids=[section.section_id],
                    authority_level="official_guidance",
                    doc_type=doc_type,
                    project=page.project,
                    page_path=page.page_path,
                    anchor=section.anchor,
                    robot_types=_ROBOT_PROJECTS.get(page.project or "", []),
                    api_name=api.qualified_name if api else None,
                    aliases=[api.qualified_name.rsplit(".", 1)[-1]] if api else [],
                    content_hash=_hash(retrieval_id, section.title, text),
                )
            )
    return docs


def doc_retrieval_id(page_path: str, section: CanonicalSection) -> str:
    """Return ``doc:<page_path>`` for a page root, else ``doc:<page_path>#<anchor>``.

    Args:
        page_path: Site-relative page path, for example ``python-api/pipettes/``.
        section: The canonical section.

    Returns:
        The retrieval id.
    """
    if section.parent_section_id is None or not section.anchor:
        return f"doc:{page_path}"
    return f"doc:{page_path}#{section.anchor}"


def doc_type_for_path(source_path: str, project: str | None) -> str:
    """Classify a documentation page from its path, falling back on the project.

    Args:
        source_path: Repository-relative Markdown path.
        project: MkDocs project the page belongs to.

    Returns:
        A ``doc_type`` value such as ``api_reference`` or ``user_manual``.
    """
    for pattern, doc_type in _DOC_TYPE_RULES:
        if fnmatch(source_path, pattern):
            return doc_type
    if project in _MODULE_PROJECTS:
        return "module_guide"
    return "user_manual"


# ---------------------------------------------------------------------------
# API symbols
# ---------------------------------------------------------------------------


def public_api_name(qualified_name: str) -> str:
    """Map a module path to the name users import.

    ``opentrons.protocol_api.instrument_context.InstrumentContext.aspirate``
    becomes ``opentrons.protocol_api.InstrumentContext.aspirate``: module
    segments between the package and the first class are dropped, matching how
    the API reference names symbols.

    Args:
        qualified_name: Fully qualified name from the source tree.

    Returns:
        The public name.
    """
    if not qualified_name.startswith(PROTOCOL_API_PREFIX):
        return qualified_name
    parts = qualified_name.removeprefix(PROTOCOL_API_PREFIX).split(".")
    for index, part in enumerate(parts):
        if part[:1].isupper():
            return PROTOCOL_API_PREFIX + ".".join(parts[index:])
    return qualified_name


def is_user_facing(symbol: CodeSymbol) -> bool:
    """Return True for documented symbols outside private and core modules.

    Args:
        symbol: A normalized code symbol.

    Returns:
        Whether the symbol belongs in user-facing retrieval.
    """
    parts = symbol.qualified_name.split(".")
    return (
        bool(symbol.docstring and symbol.docstring.strip())
        and ".core." not in f".{symbol.qualified_name}."
        and not any(part.startswith("_") for part in parts)
    )


def api_symbol_documents(
    symbols: Sequence[CodeSymbol], pages: Sequence[CanonicalDocument]
) -> list[RetrievalDocument]:
    """One retrieval document per user-facing symbol.

    Property getters and setters share a qualified name; they merge into one
    document whose text carries both docstrings.

    Args:
        symbols: Normalized code symbols.
        pages: Canonical documents, used to link each symbol to its reference page.

    Returns:
        Retrieval documents keyed ``symbol:<qualified_name>``.
    """
    reference_urls = {
        s.api.qualified_name: s.url for page in pages for s in page.sections if s.api is not None
    }
    by_name: dict[str, list[CodeSymbol]] = defaultdict(list)
    for symbol in symbols:
        if is_user_facing(symbol):
            by_name[symbol.qualified_name].append(symbol)
    docs: list[RetrievalDocument] = []
    for qualified_name, group in sorted(by_name.items()):
        group.sort(key=lambda s: (s.line_start or 0, s.symbol_id))
        first = group[0]
        name = public_api_name(qualified_name)
        retrieval_id = f"symbol:{qualified_name}"
        segments = [Segment(text=f"```python\n{first.signature}\n```")]
        seen: set[str] = set()
        for symbol in group:
            doc = (symbol.docstring or "").strip()
            if doc and doc not in seen:
                seen.add(doc)
                segments.append(Segment(text=doc))
        if first.minimum_api_version:
            segments.append(Segment(text=f"New in API version {first.minimum_api_version}."))
        text = f"`{name}`\n\n" + "\n\n".join(s.text for s in segments)
        docs.append(
            RetrievalDocument(
                retrieval_id=retrieval_id,
                kind=RetrievalKind.API_SYMBOL,
                group_id=retrieval_id,
                title=name.rsplit(".", 1)[-1],
                heading_path=name.removeprefix(PROTOCOL_API_PREFIX).split("."),
                text=text,
                segments=segments,
                url=reference_urls.get(name),
                source_url=first.source_url,
                source_path=first.source_path,
                source_record_ids=sorted({s.symbol_id for s in group}),
                authority_level="normative",
                doc_type="api_reference",
                project="python-api",
                robot_types=[r.lower() for r in first.robot_types],
                api_name=name,
                api_version_min=first.minimum_api_version,
                aliases=sorted({name.rsplit(".", 1)[-1], qualified_name}),
                content_hash=_hash(retrieval_id, name, text),
            )
        )
    return docs


# ---------------------------------------------------------------------------
# Shared-data entities
# ---------------------------------------------------------------------------


def entity_documents(entities: Sequence[Entity]) -> list[RetrievalDocument]:
    """One retrieval document per loadable labware, pipette model, and module.

    Labware keeps the newest definition per load name; pipettes keep the newest
    model revision per channel count, volume, and major version; modules keep the
    newest definition schema per model. Schema files, decks, robots, and schema-1 legacy
    labware are skipped because they are not things a protocol loads by name.

    Args:
        entities: Normalized shared-data entities.

    Returns:
        Retrieval documents keyed ``labware:<load_name>``,
        ``pipette:<channels>/<volume>/v<major>``, or ``module:<model>``.
    """
    labware: dict[str, list[tuple[tuple[int, int], Entity, str]]] = defaultdict(list)
    pipettes: dict[str, list[tuple[tuple[int, int], Entity, str]]] = defaultdict(list)
    modules: dict[str, list[tuple[tuple[int, int], Entity, str]]] = defaultdict(list)
    for entity in entities:
        path = _shared_data_path(entity)
        if path is None:
            continue
        match entity.entity_type.value:
            case "labware" | "tip_rack":
                parts = path.split("/")
                if (
                    len(parts) != 5
                    or parts[2] == "1"
                    or entity.properties.get("namespace") != "opentrons"
                ):
                    continue
                if entity.canonical_name.startswith("schema"):
                    continue
                version = (int(parts[2]), int(parts[4].removesuffix(".json")))
                labware[entity.canonical_name].append((version, entity, path))
            case "pipette":
                parts = path.split("/")
                if len(parts) != 7 or parts[3] != "general":
                    continue
                major, minor = (int(p) for p in parts[6].removesuffix(".json").split("_"))
                key = f"{parts[4]}/{parts[5]}/v{major}"
                pipettes[key].append(((major, minor), entity, path))
            case "module":
                parts = path.split("/")
                if len(parts) != 4 or entity.canonical_name.isdigit():
                    continue
                modules[entity.canonical_name].append(((int(parts[2]), 0), entity, path))
    docs = [
        *(_labware_document(name, max(group, key=_first)) for name, group in labware.items()),
        *(_pipette_document(key, group) for key, group in pipettes.items()),
        *(_module_document(name, max(group, key=_first)) for name, group in modules.items()),
    ]
    return docs


def _labware_document(
    load_name: str, latest: tuple[tuple[int, int], Entity, str]
) -> RetrievalDocument:
    (schema, version), entity, path = latest
    raw = entity.raw_source or {}
    meta = raw.get("metadata", {})
    params = raw.get("parameters", {})
    dims = raw.get("dimensions", {})
    wells: dict[str, Any] = raw.get("wells", {})
    first_well: dict[str, Any] = next(iter(wells.values()), {})
    display = meta.get("displayName") or entity.display_name
    lines = [
        f"**{display}**",
        f"- Load name: `{load_name}`",
        f"- Category: {meta.get('displayCategory', 'unknown')}",
        f"- Brand: {raw.get('brand', {}).get('brand', 'unknown')}",
        f"- Wells: {len(wells)}",
    ]
    if volume := first_well.get("totalLiquidVolume"):
        lines.append(f"- Well volume: {volume} µL")
    if params.get("isTiprack") and params.get("tipLength"):
        lines.append(f"- Tip length: {params['tipLength']} mm")
    if dims:
        lines.append(
            f"- Dimensions: {dims.get('xDimension')} x {dims.get('yDimension')} x "
            f"{dims.get('zDimension')} mm"
        )
    if roles := raw.get("allowedRoles"):
        lines.append(f"- Allowed roles: {', '.join(roles)}")
    lines.append(f"- Definition: schema {schema}, version {version}")
    text = "\n".join(lines)
    retrieval_id = f"labware:{load_name}"
    brand_ids = raw.get("brand", {}).get("brandId", [])
    return RetrievalDocument(
        retrieval_id=retrieval_id,
        kind=RetrievalKind.ENTITY,
        group_id=retrieval_id,
        title=display,
        heading_path=["Labware", display],
        text=text,
        segments=[Segment(text=text)],
        source_path=f"shared-data/{path}",
        source_record_ids=[entity.entity_id],
        authority_level="normative",
        doc_type="labware_spec",
        load_name=load_name,
        robot_types=labware_robot_scope(load_name),
        aliases=sorted({load_name, display, *brand_ids}),
        content_hash=_hash(retrieval_id, display, text),
    )


def _pipette_document(
    key: str, group: list[tuple[tuple[int, int], Entity, str]]
) -> RetrievalDocument:
    _version, entity, path = max(group, key=_first)
    channels, volume, _major = key.split("/")
    revisions = ", ".join(
        f"{major}.{minor}" for (major, minor), _e, _p in sorted(group, key=_first)
    )
    display = entity.display_name
    raw = entity.raw_source or {}
    robot_types = pipette_robot_scope(raw, source_path=path)
    robot_labels = {"flex": "Opentrons Flex", "ot-2": "OT-2"}
    lines = [
        f"**{display}**",
        f"- Channels: {entity.properties.get('channels')}",
        f"- Volume class: {volume}",
        f"- Model revisions: {revisions}",
    ]
    if len(robot_types) == 1:
        lines.append(f"- Robot: {robot_labels[robot_types[0]]}")
    text = "\n".join(lines)
    retrieval_id = f"pipette:{key}"
    return RetrievalDocument(
        retrieval_id=retrieval_id,
        kind=RetrievalKind.ENTITY,
        group_id=retrieval_id,
        title=display,
        heading_path=["Pipettes", display],
        text=text,
        segments=[Segment(text=text)],
        source_path=f"shared-data/{path}",
        source_record_ids=sorted(e.entity_id for _v, e, _p in group),
        authority_level="normative",
        doc_type="user_manual",
        robot_types=robot_types,
        aliases=sorted({display, f"{volume}_{channels}"}),
        content_hash=_hash(retrieval_id, display, text),
    )


def _module_document(model: str, latest: tuple[tuple[int, int], Entity, str]) -> RetrievalDocument:
    _version, entity, path = latest
    raw = entity.raw_source or {}
    display = entity.display_name
    lines = [
        f"**{display}**",
        f"- Model: `{model}`",
        f"- Module type: `{entity.properties.get('module_type') or raw.get('moduleType')}`",
    ]
    if compatible := raw.get("compatibleWith"):
        lines.append(f"- Compatible with: {', '.join(compatible)}")
    if dims := raw.get("dimensions"):
        lines.append(
            "- Dimensions: "
            + ", ".join(f"{k} {v}" for k, v in sorted(dims.items()) if isinstance(v, int | float))
        )
    text = "\n".join(lines)
    retrieval_id = f"module:{model}"
    return RetrievalDocument(
        retrieval_id=retrieval_id,
        kind=RetrievalKind.ENTITY,
        group_id=retrieval_id,
        title=display,
        heading_path=["Modules", display],
        text=text,
        segments=[Segment(text=text)],
        source_path=f"shared-data/{path}",
        source_record_ids=[entity.entity_id],
        authority_level="normative",
        doc_type="module_guide",
        robot_types=module_robot_scope(raw),
        aliases=sorted({model, display}),
        content_hash=_hash(retrieval_id, display, text),
    )


def _shared_data_path(entity: Entity) -> str | None:
    for source_id in entity.source_ids:
        _key, _, path = source_id.partition(":")
        if path.startswith("shared-data/"):
            rest = path.removeprefix("shared-data/")
            if "/definitions/" in f"/{rest}":
                return rest
    return None


def _first(item: tuple[tuple[int, int], Entity, str]) -> tuple[int, int]:
    return item[0]


# ---------------------------------------------------------------------------
# AI guides
# ---------------------------------------------------------------------------


def guide_section_documents(
    documents: Sequence[Document], sections: Sequence[Section]
) -> list[RetrievalDocument]:
    """One retrieval document per non-empty AI guide section.

    Guides repeat headings, so ids use the anchor and a ``-2``, ``-3`` suffix
    in document order for repeats.

    Args:
        documents: AI guide documents.
        sections: Sections of those documents.

    Returns:
        Retrieval documents keyed ``guide:<source_path>#<anchor>``.
    """
    by_doc: dict[str, list[Section]] = defaultdict(list)
    for section in sections:
        by_doc[section.document_id].append(section)
    docs: list[RetrievalDocument] = []
    for document in documents:
        seen: dict[str, int] = defaultdict(int)
        group_id = f"guide:{document.source_path}"
        for section in by_doc.get(document.document_id, []):
            anchor = section.anchor or slugify(section.title) or "section"
            seen[anchor] += 1
            if seen[anchor] > 1:
                anchor = f"{anchor}-{seen[anchor]}"
            text = _strip_leading_heading(section.content_markdown)
            if not text:
                continue
            retrieval_id = f"{group_id}#{anchor}"
            docs.append(
                RetrievalDocument(
                    retrieval_id=retrieval_id,
                    kind=RetrievalKind.GUIDE_SECTION,
                    group_id=group_id,
                    title=section.title,
                    heading_path=section.heading_path,
                    text=text,
                    segments=[Segment(text=p) for p in re.split(r"\n{2,}", text) if p.strip()],
                    source_url=section.source_url or document.source_url,
                    source_path=document.source_path,
                    source_record_ids=[section.section_id],
                    authority_level=document.authority_level.value,
                    doc_type="internal_guide",
                    anchor=anchor,
                    robot_types=[r.lower() for r in document.robot_types],
                    content_hash=_hash(retrieval_id, section.title, text),
                )
            )
    return docs


def _strip_leading_heading(markdown: str) -> str:
    return re.sub(r"\A\s*#{1,6} [^\n]*\n?", "", markdown).strip()


# ---------------------------------------------------------------------------


def _hash(retrieval_id: str, title: str, text: str) -> str:
    return content_hash(dumps_canonical_json({"id": retrieval_id, "title": title, "text": text}))


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        (dupes if value in seen else seen).add(value)
    return sorted(dupes)
