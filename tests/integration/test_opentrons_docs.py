"""Check canonical docs in the latest built knowledge package.

The package is ``dist/opentrons-knowledge-<highest version>``. These tests read
``canonical/`` from that build. They do not render MkDocs again and they do not
compare the records to a fixture site. A missing package fails.
"""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path

import pytest

from opentrons_knowledge.builder.pipeline import load_source_manifest
from opentrons_knowledge.corpora import highest_corpus_version
from opentrons_knowledge.docs.canonical import (
    find_document,
    iter_blocks,
    load_canonical_documents,
    validate_canonical_corpus,
)
from opentrons_knowledge.errors import CorpusValidationError
from opentrons_knowledge.models.canonical import AdmonitionBlock, CodeBlock, TabsBlock
from opentrons_knowledge.normalization.serialize import write_jsonl_zst

ROOT = Path(__file__).resolve().parents[2]
VERSION = highest_corpus_version(ROOT / "corpora")
CORPUS = ROOT / "dist" / f"opentrons-knowledge-{VERSION}"
CANONICAL = CORPUS / "canonical"


def test_canonical_docs_match_the_corpus_pin() -> None:
    manifest = validate_canonical_corpus(CANONICAL)
    source = load_source_manifest(ROOT / "corpora" / VERSION / "source-manifest.yaml")
    docs = source.sources["opentrons_docs"]
    documents = load_canonical_documents(CANONICAL)

    assert manifest.corpus_version == VERSION
    assert manifest.source.repository == docs.repository
    assert manifest.source.ref == docs.tag
    assert manifest.source.commit == docs.commit
    assert manifest.source.dirty is False
    assert set(manifest.build.modified_files) <= {"docs/uv.lock"}
    assert manifest.document_count > 250
    assert manifest.section_count > 1000
    assert len(documents) == manifest.document_count
    assert [d.page_path for d in documents if d.source.markdown_path is None] == []

    excluded = {d.page_path for d in documents if d.search_exclude}
    assert excluded == {
        "python-api/modules/vacuum/",
        "python-api/reference/vacuum/",
    }
    assert {entry.page_path for entry in manifest.documents if entry.search_exclude} == excluded
    assert {page.html_path for page in manifest.excluded_pages} >= {
        "404.html",
        "info/index.html",
    }
    for kind in ("code", "tabs", "table", "admonition", "paragraph", "list"):
        assert manifest.block_counts.get(kind, 0) > 0
    assert "html" not in manifest.block_counts


def test_representative_pages_keep_their_structure() -> None:
    documents = load_canonical_documents(CANONICAL)

    app = find_document(documents, "flex/opentrons-app/")
    assert app is not None
    assert app.source.front_matter["title"] == "Opentrons Flex: Opentrons App"
    assert app.search_exclude is False

    loading = find_document(documents, "python-api/pipettes/loading/")
    assert loading is not None
    tabs = [b for s in loading.sections for b in iter_blocks(s.blocks) if isinstance(b, TabsBlock)]
    assert tabs
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
    assert len(tables) > 10

    kinds = Counter(
        b.kind
        for d in documents
        for s in d.sections
        for b in iter_blocks(s.blocks)
        if isinstance(b, AdmonitionBlock)
    )
    assert {"note", "warning", "tip"} <= set(kinds)


def test_validation_rejects_a_changed_copy(tmp_path: Path) -> None:
    copied = tmp_path / "canonical"
    shutil.copytree(CANONICAL, copied)
    documents = load_canonical_documents(copied)
    documents[0].title = f"{documents[0].title} changed"
    write_jsonl_zst(copied / "documents.jsonl.zst", documents)
    with pytest.raises(CorpusValidationError, match="sha256 mismatch"):
        validate_canonical_corpus(copied)
