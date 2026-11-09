"""Build the real Opentrons MkDocs site at a pinned tag and check fidelity against its HTML.

Slow (first run clones, syncs the docs uv project, and renders ~280 pages).
Enable with ``OPENTRONS_KNOWLEDGE_INTEGRATION=1``; set ``OPENTRONS_REPO`` to a
local clone (default ``../opentrons``). Builds are cached under ``dist/.work``.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from bs4.element import Tag

from opentrons_knowledge.builder.pipeline import load_source_manifest
from opentrons_knowledge.docs.canonical import (
    build_canonical_corpus,
    find_document,
    iter_blocks,
    load_canonical_documents,
    validate_canonical_corpus,
)
from opentrons_knowledge.docs.mkdocs_build import RenderedSite, build_site
from opentrons_knowledge.models.canonical import (
    AdmonitionBlock,
    CanonicalDocument,
    CodeBlock,
    TabsBlock,
)
from opentrons_knowledge.models.manifest import RenderedDocsConfig

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "corpora" / "10.0.0-k2" / "source-manifest.yaml"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("OPENTRONS_KNOWLEDGE_INTEGRATION") != "1",
        reason="set OPENTRONS_KNOWLEDGE_INTEGRATION=1 to build the real Opentrons docs",
    ),
]


@pytest.fixture(scope="module")
def rendered() -> RenderedSite:
    repo = Path(os.environ.get("OPENTRONS_REPO", ROOT.parent / "opentrons"))
    if not (repo / ".git").exists():
        pytest.skip(f"No Opentrons clone at {repo}")
    manifest = load_source_manifest(MANIFEST)
    entry = manifest.sources["opentrons_docs"]
    return build_site(
        repository=entry.repository,
        ref=entry.tag,
        settings=RenderedDocsConfig(),
        work_root=ROOT / "dist" / ".work",
        local_repo=repo,
    )


@pytest.fixture(scope="module")
def corpus_dir(rendered: RenderedSite, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("canonical")
    build_canonical_corpus(rendered, out)
    return out


@pytest.fixture(scope="module")
def documents(corpus_dir: Path) -> list[CanonicalDocument]:
    return load_canonical_documents(corpus_dir)


def test_pinned_revision_and_source_mapping(
    rendered: RenderedSite, corpus_dir: Path, documents: list[CanonicalDocument]
) -> None:
    manifest = validate_canonical_corpus(corpus_dir)
    assert rendered.commit == "00f1431babdf36a11ec68143c009d5fc889b2478"
    assert manifest.source.ref == "mkdocs-2026-09-30"
    assert set(manifest.build.modified_files) <= {"docs/uv.lock"}
    excluded = {d.page_path for d in documents if d.search_exclude}
    assert excluded == {
        "python-api/modules/vacuum/",
        "python-api/reference/vacuum/",
    }
    assert {e.page_path for e in manifest.documents if e.search_exclude} == excluded
    assert manifest.document_count > 250
    unmapped = [d.page_path for d in documents if d.source.markdown_path is None]
    assert unmapped == []
    assert {p.html_path for p in manifest.excluded_pages} >= {"404.html", "info/index.html"}


def test_deterministic_rewrite(rendered: RenderedSite, corpus_dir: Path, tmp_path: Path) -> None:
    build_canonical_corpus(rendered, tmp_path)
    for name in ("documents.jsonl.zst", "manifest.json"):
        assert (tmp_path / name).read_bytes() == (corpus_dir / name).read_bytes()


def test_representative_pages(documents: list[CanonicalDocument]) -> None:
    app = find_document(documents, "flex/opentrons-app/")
    assert app is not None
    assert app.source.front_matter["title"] == "Opentrons Flex: Opentrons App"
    assert app.search_exclude is False

    loading = find_document(documents, "python-api/pipettes/loading/")
    assert loading is not None
    tabs = [b for s in loading.sections for b in iter_blocks(s.blocks) if isinstance(b, TabsBlock)]
    assert [t.label for t in tabs[0].tabs] == ["Flex Pipettes", "OT-2 Pipettes"]
    examples = [
        b for s in loading.sections for b in iter_blocks(s.blocks) if isinstance(b, CodeBlock)
    ]
    assert any("def run(protocol" in b.code and b.language == "python" for b in examples)

    instruments = find_document(documents, "python-api/reference/instruments/")
    assert instruments is not None
    aspirate = next(
        s
        for s in instruments.sections
        if s.api and s.api.qualified_name == "opentrons.protocol_api.InstrumentContext.aspirate"
    )
    signature = aspirate.blocks[0]
    assert isinstance(signature, CodeBlock) and signature.role == "signature"
    assert signature.code.startswith("aspirate(")

    definitions = find_document(documents, "python-api/liquid-classes/definitions/")
    assert definitions is not None
    tables = [b for s in definitions.sections for b in iter_blocks(s.blocks) if b.type == "table"]
    assert len(tables) > 10, "macro-included liquid class tables should be expanded"

    kinds = Counter(
        b.kind
        for d in documents
        for s in d.sections
        for b in iter_blocks(s.blocks)
        if isinstance(b, AdmonitionBlock)
    )
    assert {"note", "warning", "tip"} <= set(kinds)


def test_fidelity_against_rendered_html(
    rendered: RenderedSite, documents: list[CanonicalDocument]
) -> None:
    """Every code block, tab set, admonition, table, heading, and word survives extraction."""
    problems: list[str] = []
    for doc in documents:
        soup = BeautifulSoup(
            (rendered.site_dir / doc.rendered.html_path).read_text(encoding="utf-8"), "lxml"
        )
        article = soup.select_one("article.md-content__inner")
        assert isinstance(article, Tag)
        blocks = [b for s in doc.sections for b in iter_blocks(s.blocks)]

        html_code = [_code_text(el) for el in article.select("div.highlight")]
        record_code = Counter(b.code for b in blocks if isinstance(b, CodeBlock))
        missing_code = Counter(html_code) - record_code
        if missing_code:
            problems.append(f"{doc.page_path}: {sum(missing_code.values())} code blocks differ")

        checks = {
            "tabs": (len(article.select("div.tabbed-set")), "tabs"),
            "admonitions": (len(article.select("div.admonition, details")), "admonition"),
            "tables": (len(article.select("table:not(.highlighttable)")), "table"),
        }
        for label, (expected, block_type) in checks.items():
            actual = sum(1 for b in blocks if b.type == block_type)
            if actual != expected:
                problems.append(f"{doc.page_path}: {label} {actual} != {expected}")

        headings = len(article.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))
        nested = sum(1 for b in blocks if b.type == "heading")
        preamble = sum(1 for s in doc.sections if s.level == 0)
        if len(doc.sections) - preamble + nested != headings:
            problems.append(f"{doc.page_path}: sections {len(doc.sections)} != headings {headings}")

        record_text = doc.model_dump_json()
        words = _words(article)
        missing = [w for w in words if w not in record_text]
        if words and len(missing) / len(words) > 0.005:
            problems.append(f"{doc.page_path}: {len(missing)}/{len(words)} words missing")
    assert problems == []


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")


def _words(article: Tag) -> list[str]:
    for junk in article.select("a.headerlink, script, style, .md-content__button"):
        junk.decompose()
    return _WORD_RE.findall(article.get_text(" "))


def _code_text(block: Tag) -> str:
    code = block.find("code") or block.find("pre")
    assert isinstance(code, Tag)
    return code.get_text().rstrip("\n")
