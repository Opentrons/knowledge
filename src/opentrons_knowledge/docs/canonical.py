"""Assemble, write, read, and validate the canonical document corpus.

Layout of a canonical corpus directory::

    manifest.json          # CanonicalManifest (pretty, sorted keys)
    documents.jsonl.zst    # one CanonicalDocument per line, sorted by document_id
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import structlog
import zstandard as zstd

from opentrons_knowledge.__version__ import __version__
from opentrons_knowledge.docs.html_extract import (
    HTML_PARSER,
    PageContext,
    extract_page,
    section_content_hash,
)
from opentrons_knowledge.docs.icons import load_icon_index
from opentrons_knowledge.docs.markdown import split_front_matter
from opentrons_knowledge.docs.mkdocs_build import RenderedSite
from opentrons_knowledge.docs.site_pages import discover_pages, load_site_layout
from opentrons_knowledge.errors import CorpusValidationError
from opentrons_knowledge.models.canonical import (
    AdmonitionBlock,
    Block,
    CanonicalArtifact,
    CanonicalBuildInfo,
    CanonicalDocument,
    CanonicalDocumentEntry,
    CanonicalExtractorInfo,
    CanonicalManifest,
    CanonicalSourceInfo,
    ExcludedPage,
    FigureBlock,
    ListBlock,
    QuoteBlock,
    RenderedRef,
    SourceRef,
    TabsBlock,
)
from opentrons_knowledge.normalization.ids import content_hash, document_id, github_blob_url
from opentrons_knowledge.normalization.serialize import (
    dumps_canonical_json,
    file_sha256,
    read_jsonl_zst,
    write_json,
    write_jsonl_zst,
)

log = structlog.get_logger(__name__)

CANONICAL_DIR = "canonical"
EXTRACTOR_NAME = "opentrons-knowledge.mkdocs-html"
EXTRACTOR_VERSION = 1
DOCUMENTS_FILE = "documents.jsonl.zst"
MANIFEST_FILE = "manifest.json"
_ERROR_PAGES = {"404.html"}


@dataclass
class CanonicalExtraction:
    """Documents extracted from one rendered site."""

    documents: list[CanonicalDocument] = field(default_factory=list)
    excluded_pages: list[ExcludedPage] = field(default_factory=list)
    mkdocs_extra: dict[str, Any] = field(default_factory=dict)
    icon_shortcodes: int = 0


def extract_site(site: RenderedSite) -> CanonicalExtraction:
    """Convert every content page of a rendered site into canonical documents.

    Args:
        site: Rendered site and its checkout/provenance.

    Returns:
        Documents sorted by ``document_id`` plus pages that were skipped and why.

    Raises:
        CorpusValidationError: If two pages resolve to the same document ID.
    """
    settings = site.settings
    layout = load_site_layout(site.checkout, settings.mkdocs_config)
    icons = load_icon_index(site.checkout, settings.mkdocs_config)
    result = CanonicalExtraction(mkdocs_extra=_json_safe(layout.extra), icon_shortcodes=len(icons))
    seen: dict[str, str] = {}

    for page in discover_pages(site.site_dir):
        if page.html_path in _ERROR_PAGES:
            result.excluded_pages.append(
                ExcludedPage(html_path=page.html_path, reason="error-page")
            )
            continue
        raw = (site.site_dir / page.html_path).read_bytes()
        markdown_path = layout.source_markdown(page.page_path, site.checkout)
        doc_id = document_id(
            site.repository, site.commit, markdown_path or f"site/{page.html_path}"
        )
        extracted = extract_page(
            raw.decode("utf-8"),
            PageContext(
                document_id=doc_id,
                page_path=page.page_path,
                base_url=settings.base_url,
                site_name=layout.site_name,
                icons=icons,
                asset_source=lambda path: layout.source_asset(path, site.checkout),
            ),
        )
        if extracted is None:
            result.excluded_pages.append(
                ExcludedPage(html_path=page.html_path, reason="no-article-content")
            )
            continue
        if doc_id in seen:
            raise CorpusValidationError(
                f"Pages {seen[doc_id]} and {page.html_path} both map to {doc_id}"
            )
        seen[doc_id] = page.html_path
        project = layout.project_for(page.page_path)
        source = _source_ref(site, markdown_path)
        document = CanonicalDocument(
            document_id=doc_id,
            page_path=page.page_path,
            url=f"{settings.base_url}{page.page_path}",
            title=extracted.title,
            page_title=extracted.page_title,
            description=extracted.description,
            project=project.name if project else None,
            nav_path=extracted.nav_path,
            source=source,
            search_exclude=_search_excluded(source.front_matter),
            rendered=RenderedRef(
                html_path=page.html_path,
                html_sha256=content_hash(raw),
                generator=extracted.generator,
            ),
            sections=extracted.sections,
            links=extracted.links,
            images=extracted.images,
            content_hash="",
        )
        document.content_hash = document_content_hash(document)
        result.documents.append(document)

    result.documents.sort(key=lambda d: d.document_id)
    return result


def write_canonical_corpus(
    output_dir: Path,
    extraction: CanonicalExtraction,
    site: RenderedSite,
    *,
    corpus_version: str | None = None,
) -> CanonicalManifest:
    """Write ``documents.jsonl.zst`` and ``manifest.json`` into ``output_dir``.

    Args:
        output_dir: Destination directory (created; existing corpus files replaced).
        extraction: Result of :func:`extract_site`.
        site: The rendered site (provenance and build settings).
        corpus_version: Knowledge corpus version when written inside a corpus artifact.

    Returns:
        The manifest that was written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    documents_path = output_dir / DOCUMENTS_FILE
    count, _ = write_jsonl_zst(documents_path, extraction.documents)
    settings = site.settings
    generator = next((d.rendered.generator for d in extraction.documents), None)
    manifest = CanonicalManifest(
        corpus_version=corpus_version,
        source=CanonicalSourceInfo(
            repository=site.repository,
            ref=site.ref,
            commit=site.commit,
            dirty=site.dirty,
            mkdocs_extra=extraction.mkdocs_extra,
        ),
        build=CanonicalBuildInfo(
            mkdocs_config=settings.mkdocs_config,
            working_directory=settings.working_directory,
            setup_command=list(settings.setup_command),
            build_command=list(settings.build_command),
            environment=settings.environment(),
            site_dir=settings.site_dir,
            base_url=settings.base_url,
            generator=generator,
            prebuilt_site=site.prebuilt,
            modified_files=list(site.modified_files),
        ),
        extractor=CanonicalExtractorInfo(
            name=EXTRACTOR_NAME,
            version=EXTRACTOR_VERSION,
            builder_version=__version__,
            html_parser=HTML_PARSER,
            dependencies=_dependency_versions(),
            icon_shortcodes=extraction.icon_shortcodes,
        ),
        artifacts=[
            CanonicalArtifact(
                path=DOCUMENTS_FILE,
                record_count=count,
                sha256=file_sha256(documents_path),
                uncompressed_sha256=content_hash(_decompress(documents_path)),
            )
        ],
        document_count=count,
        section_count=sum(len(d.sections) for d in extraction.documents),
        block_counts=dict(sorted(_block_counts(extraction.documents).items())),
        documents=[_inventory_entry(d) for d in extraction.documents],
        excluded_pages=sorted(extraction.excluded_pages, key=lambda p: p.html_path),
    )
    write_json(output_dir / MANIFEST_FILE, manifest.model_dump(mode="json"))
    log.info("canonical_corpus_written", path=str(output_dir), documents=count)
    return manifest


def build_canonical_corpus(
    site: RenderedSite, output_dir: Path, *, corpus_version: str | None = None
) -> CanonicalManifest:
    """Extract a rendered site and write the canonical corpus in one step."""
    return write_canonical_corpus(
        output_dir, extract_site(site), site, corpus_version=corpus_version
    )


def load_canonical_manifest(corpus_dir: Path) -> CanonicalManifest:
    """Read ``manifest.json`` from a canonical corpus directory."""
    path = corpus_dir / MANIFEST_FILE
    if not path.is_file():
        raise CorpusValidationError(f"Missing {MANIFEST_FILE} in {corpus_dir}")
    return CanonicalManifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_canonical_documents(corpus_dir: Path) -> list[CanonicalDocument]:
    """Read and validate every record in ``documents.jsonl.zst``."""
    return [
        CanonicalDocument.model_validate(row) for row in read_jsonl_zst(corpus_dir / DOCUMENTS_FILE)
    ]


def validate_canonical_corpus(corpus_dir: Path) -> CanonicalManifest:
    """Check checksums, record schema, inventory, IDs, links, and content hashes.

    Args:
        corpus_dir: Directory holding ``manifest.json`` and ``documents.jsonl.zst``.

    Returns:
        The validated manifest.

    Raises:
        CorpusValidationError: Listing every problem found.
    """
    manifest = load_canonical_manifest(corpus_dir)
    problems: list[str] = []
    for artifact in manifest.artifacts:
        path = corpus_dir / artifact.path
        if not path.is_file():
            problems.append(f"missing artifact {artifact.path}")
            continue
        if file_sha256(path) != artifact.sha256:
            problems.append(f"sha256 mismatch for {artifact.path}")
        if content_hash(_decompress(path)) != artifact.uncompressed_sha256:
            problems.append(f"uncompressed sha256 mismatch for {artifact.path}")
    if problems:
        raise CorpusValidationError("; ".join(problems))

    documents = load_canonical_documents(corpus_dir)
    ids = [d.document_id for d in documents]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        problems.append("documents are not uniquely sorted by document_id")
    if len(documents) != manifest.document_count:
        problems.append(f"document_count {manifest.document_count} != {len(documents)} records")
    if [_inventory_entry(d) for d in documents] != manifest.documents:
        problems.append("manifest document inventory does not match records")
    if sum(len(d.sections) for d in documents) != manifest.section_count:
        problems.append("section_count does not match records")

    all_sections: set[str] = set()
    for doc in documents:
        problems.extend(_document_problems(doc, all_sections))
    section_hashes = [s.content_hash for doc in documents for s in doc.sections]
    if len(section_hashes) != len(set(section_hashes)):
        problems.append("section content_hash values are not unique")
    document_hashes = [doc.content_hash for doc in documents]
    if len(document_hashes) != len(set(document_hashes)):
        problems.append("document content_hash values are not unique")
    if problems:
        shown = problems[:25]
        more = f" (+{len(problems) - len(shown)} more)" if len(problems) > len(shown) else ""
        raise CorpusValidationError("; ".join(shown) + more)
    return manifest


def document_content_hash(document: CanonicalDocument) -> str:
    """SHA-256 over a document's path, title, and ordered section hashes."""
    payload = {
        "document_id": document.document_id,
        "page_path": document.page_path,
        "title": document.title,
        "sections": [section_content_hash(s) for s in document.sections],
    }
    return content_hash(dumps_canonical_json(payload))


def find_document(documents: list[CanonicalDocument], key: str) -> CanonicalDocument | None:
    """Look up a document by ID, page path, URL, or source Markdown path."""
    normalized = key.strip()
    for doc in documents:
        if normalized in {
            doc.document_id,
            doc.page_path,
            doc.page_path.rstrip("/"),
            doc.url,
            doc.source.markdown_path,
        }:
            return doc
    return None


def iter_blocks(blocks: list[Block]) -> list[Block]:
    """Flatten nested blocks depth-first (container before its children)."""
    flat: list[Block] = []
    for block in blocks:
        flat.append(block)
        if isinstance(block, ListBlock):
            for item in block.items:
                flat.extend(iter_blocks(item.blocks))
        elif isinstance(block, TabsBlock):
            for tab in block.tabs:
                flat.extend(iter_blocks(tab.blocks))
        elif isinstance(block, (AdmonitionBlock, FigureBlock, QuoteBlock)):
            flat.extend(iter_blocks(block.blocks))
    return flat


def _document_problems(doc: CanonicalDocument, all_sections: set[str]) -> list[str]:
    problems: list[str] = []
    local = {s.section_id for s in doc.sections}
    if len(local) != len(doc.sections):
        problems.append(f"{doc.document_id}: duplicate section IDs")
    if local & all_sections:
        problems.append(f"{doc.document_id}: section IDs collide with another document")
    all_sections.update(local)
    for ordinal, section in enumerate(doc.sections):
        if section.document_id != doc.document_id or section.ordinal != ordinal:
            problems.append(f"{section.section_id}: wrong document_id or ordinal")
        refs = [section.parent_section_id, section.previous_section_id, section.next_section_id]
        refs += section.child_section_ids
        if any(ref is not None and ref not in local for ref in refs):
            problems.append(f"{section.section_id}: dangling section reference")
        if section.content_hash != section_content_hash(section):
            problems.append(f"{section.section_id}: content_hash mismatch")
    if doc.content_hash != document_content_hash(doc):
        problems.append(f"{doc.document_id}: content_hash mismatch")
    for ref_section in [*(r.section_id for r in doc.links), *(r.section_id for r in doc.images)]:
        if ref_section not in local:
            problems.append(f"{doc.document_id}: link/image points at unknown section")
            break
    return problems


def _search_excluded(front_matter: dict[str, Any]) -> bool:
    search = front_matter.get("search")
    return isinstance(search, dict) and bool(search.get("exclude"))


def _source_ref(site: RenderedSite, markdown_path: str | None) -> SourceRef:
    if markdown_path is None:
        return SourceRef(repository=site.repository, commit=site.commit, ref=site.ref)
    raw = (site.checkout / markdown_path).read_bytes()
    front_matter, _body = split_front_matter(raw.decode("utf-8"))
    return SourceRef(
        repository=site.repository,
        commit=site.commit,
        ref=site.ref,
        markdown_path=markdown_path,
        markdown_url=github_blob_url(site.repository, site.commit, markdown_path),
        markdown_sha256=content_hash(raw),
        front_matter=_json_safe(front_matter),
    )


def _inventory_entry(doc: CanonicalDocument) -> CanonicalDocumentEntry:
    return CanonicalDocumentEntry(
        document_id=doc.document_id,
        page_path=doc.page_path,
        title=doc.title,
        markdown_path=doc.source.markdown_path,
        section_count=len(doc.sections),
        search_exclude=doc.search_exclude,
        content_hash=doc.content_hash,
    )


def _block_counts(documents: list[CanonicalDocument]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for doc in documents:
        for section in doc.sections:
            counts.update(block.type for block in iter_blocks(section.blocks))
    return counts


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in ("beautifulsoup4", "lxml"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    return versions


def _decompress(path: Path) -> bytes:
    with path.open("rb") as handle:
        return zstd.ZstdDecompressor().stream_reader(handle).read()


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(json.dumps(value, default=str, sort_keys=True))
    return result
