"""Canonical corpus assembly: source mapping, determinism, manifest, validation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import zstandard as zstd

from opentrons_knowledge.artifacts.package import validate_corpus_dir
from opentrons_knowledge.builder.pipeline import build_fixture_corpus
from opentrons_knowledge.docs.canonical import (
    DOCUMENTS_FILE,
    MANIFEST_FILE,
    build_canonical_corpus,
    extract_site,
    find_document,
    load_canonical_documents,
    validate_canonical_corpus,
)
from opentrons_knowledge.docs.markdown import parse_markdown_document
from opentrons_knowledge.docs.mkdocs_build import RenderedSite, prebuilt_site
from opentrons_knowledge.docs.site_pages import discover_pages, load_site_layout, page_path_for
from opentrons_knowledge.errors import CorpusValidationError
from opentrons_knowledge.models.canonical import CanonicalDocument, CanonicalManifest
from opentrons_knowledge.models.enums import AuthorityLevel
from opentrons_knowledge.models.manifest import RenderedDocsConfig
from opentrons_knowledge.normalization.ids import content_hash
from opentrons_knowledge.normalization.serialize import file_sha256, write_jsonl_zst

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RENDERED = FIXTURES / "rendered_site"
REPO = "https://github.com/Opentrons/opentrons"
COMMIT = "0" * 40


@pytest.fixture
def site() -> RenderedSite:
    return prebuilt_site(
        site_dir=RENDERED / "site",
        checkout=RENDERED / "checkout",
        repository=REPO,
        settings=RenderedDocsConfig(),
        ref="mkdocs-fixture",
        commit=COMMIT,
    )


def test_site_layout_reads_monorepo_configs() -> None:
    layout = load_site_layout(RENDERED / "checkout", "docs/mkdocs.yml")
    assert [(p.name, p.url_prefix, p.docs_dir) for p in layout.projects] == [
        (None, "", "docs/shared"),
        ("python-api", "python-api/", "docs/python-api/docs"),
    ]
    assert layout.extra == {"apiLevel": "2.30", "robot_stack_version": "10.0.0"}
    checkout = RENDERED / "checkout"
    assert layout.source_markdown("", checkout) == "docs/shared/index.md"
    assert (
        layout.source_markdown("python-api/pipettes/loading/", checkout)
        == "docs/python-api/docs/pipettes/loading.md"
    )
    assert layout.source_markdown("python-api/missing/", checkout) is None
    assert (
        layout.source_asset("python-api/images/pipette.png", checkout)
        == "docs/python-api/docs/images/pipette.png"
    )


def test_page_discovery_is_sorted_and_normalized() -> None:
    pages = discover_pages(RENDERED / "site")
    assert [p.html_path for p in pages] == sorted(p.html_path for p in pages)
    assert page_path_for("index.html") == ""
    assert page_path_for("python-api/labware/index.html") == "python-api/labware/"
    assert page_path_for("print.html") == "print.html"


def test_extract_site_documents_and_provenance(site: RenderedSite) -> None:
    extraction = extract_site(site)
    assert [p.html_path for p in extraction.excluded_pages] == ["404.html", "info/index.html"]
    assert [d.page_path for d in extraction.documents] == [
        "python-api/pipettes/loading/",
        "python-api/reference/instruments/",
        "",
    ]
    assert [d.document_id for d in extraction.documents] == sorted(
        d.document_id for d in extraction.documents
    )
    loading = find_document(extraction.documents, "python-api/pipettes/loading")
    assert loading is not None
    assert loading.project == "python-api"
    source = loading.source
    assert source.markdown_path == "docs/python-api/docs/pipettes/loading.md"
    assert source.markdown_url == (f"{REPO}/blob/{COMMIT}/docs/python-api/docs/pipettes/loading.md")
    assert source.front_matter["title"] == "Python API: Loading Pipettes"
    assert source.ref == "mkdocs-fixture"
    assert source.markdown_sha256 == file_sha256(RENDERED / "checkout" / source.markdown_path)
    assert loading.rendered.html_path == "python-api/pipettes/loading/index.html"
    assert loading.images[0].source_path == "docs/python-api/docs/images/pipette.png"
    assert extraction.icon_shortcodes == 1


def test_document_id_matches_legacy_markdown_record(site: RenderedSite) -> None:
    rel = "docs/python-api/docs/pipettes/loading.md"
    legacy = parse_markdown_document(
        RENDERED / "checkout" / rel,
        repository=REPO,
        commit=COMMIT,
        source_path=rel,
        source_key="opentrons_docs",
        authority_level=AuthorityLevel.OFFICIAL_GUIDANCE,
        source_type="mkdocs_markdown",
    )
    canonical = find_document(extract_site(site).documents, rel)
    assert canonical is not None
    assert canonical.document_id == legacy.documents[0].document_id


def test_corpus_is_deterministic(site: RenderedSite, tmp_path: Path) -> None:
    build_canonical_corpus(site, tmp_path / "a")
    build_canonical_corpus(site, tmp_path / "b")
    for name in (DOCUMENTS_FILE, MANIFEST_FILE):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_zstd_roundtrip_and_manifest_accuracy(site: RenderedSite, tmp_path: Path) -> None:
    manifest = build_canonical_corpus(site, tmp_path, corpus_version="0.0.0-k1")
    raw = zstd.ZstdDecompressor().decompress((tmp_path / DOCUMENTS_FILE).read_bytes())
    lines = raw.decode("utf-8").splitlines()
    docs = [CanonicalDocument.model_validate_json(line) for line in lines]
    assert len(docs) == manifest.document_count == 3
    assert manifest.section_count == sum(len(d.sections) for d in docs)
    (artifact,) = manifest.artifacts
    assert artifact.path == DOCUMENTS_FILE and artifact.compression == "zstd"
    assert artifact.sha256 == file_sha256(tmp_path / DOCUMENTS_FILE)
    assert artifact.record_count == 3
    assert [d.document_id for d in manifest.documents] == [d.document_id for d in docs]
    assert manifest.source.commit == COMMIT and manifest.source.ref == "mkdocs-fixture"
    assert manifest.corpus_version == "0.0.0-k1"
    assert manifest.build.build_command == ["make", "build"]
    assert manifest.build.environment == {"UV_PYTHON": "3.12", "CI": "true"}
    assert manifest.build.prebuilt_site
    assert manifest.block_counts["tabs"] == 1
    assert manifest.extractor.dependencies.keys() == {"beautifulsoup4", "lxml"}
    on_disk = json.loads((tmp_path / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert CanonicalManifest.model_validate(on_disk) == manifest
    assert str(tmp_path) not in (tmp_path / MANIFEST_FILE).read_text(encoding="utf-8")


def test_validate_accepts_and_detects_tampering(site: RenderedSite, tmp_path: Path) -> None:
    build_canonical_corpus(site, tmp_path)
    assert validate_canonical_corpus(tmp_path).document_count == 3

    docs = load_canonical_documents(tmp_path)
    docs[0].sections[1].title = "Tampered"
    payload = "".join(d.model_dump_json() + "\n" for d in docs).encode("utf-8")
    (tmp_path / DOCUMENTS_FILE).write_bytes(zstd.ZstdCompressor().compress(payload))
    with pytest.raises(CorpusValidationError, match="sha256 mismatch"):
        validate_canonical_corpus(tmp_path)


def test_validate_detects_inconsistent_records(site: RenderedSite, tmp_path: Path) -> None:
    manifest = build_canonical_corpus(site, tmp_path)
    docs = load_canonical_documents(tmp_path)
    docs[0].sections[1].parent_section_id = "section:missing"
    write_jsonl_zst(tmp_path / DOCUMENTS_FILE, docs)
    manifest.artifacts[0].sha256 = file_sha256(tmp_path / DOCUMENTS_FILE)
    raw = zstd.ZstdDecompressor().decompress((tmp_path / DOCUMENTS_FILE).read_bytes())
    manifest.artifacts[0].uncompressed_sha256 = content_hash(raw)
    (tmp_path / MANIFEST_FILE).write_text(manifest.model_dump_json(), encoding="utf-8")
    with pytest.raises(CorpusValidationError, match="dangling section reference"):
        validate_canonical_corpus(tmp_path)


def test_duplicate_document_ids_fail(site: RenderedSite, tmp_path: Path) -> None:
    site_copy = tmp_path / "site"
    shutil.copytree(site.site_dir, site_copy)
    dup = site_copy / "python-api" / "pipettes" / "loading.html"
    shutil.copy(site_copy / "python-api" / "pipettes" / "loading" / "index.html", dup)
    other = prebuilt_site(
        site_dir=site_copy,
        checkout=site.checkout,
        repository=REPO,
        settings=RenderedDocsConfig(),
        commit=COMMIT,
    )
    with pytest.raises(CorpusValidationError, match="both map to"):
        extract_site(other)


def test_fixture_corpus_ships_canonical_docs(tmp_path: Path) -> None:
    result = build_fixture_corpus(tmp_path, FIXTURES / "mini_sources")
    canonical = result.corpus_root / "canonical"
    assert (canonical / MANIFEST_FILE).is_file()
    assert result.manifest.record_counts["canonical_documents"] == 3
    assert result.manifest.metadata["canonical_docs"]["path"] == "canonical/"
    validate_corpus_dir(result.corpus_root)
    assert (result.corpus_root / "corpus" / "documents.jsonl.zst").is_file()
    assert "canonical/documents.jsonl.zst" in result.manifest.checksums
