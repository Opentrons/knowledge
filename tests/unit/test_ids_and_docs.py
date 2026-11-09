"""Stable ID and markdown parsing tests."""

from __future__ import annotations

from pathlib import Path

from opentrons_knowledge.docs.markdown import parse_markdown_document, split_front_matter
from opentrons_knowledge.models.enums import AuthorityLevel
from opentrons_knowledge.normalization.ids import (
    document_id,
    github_blob_url,
    rendered_docs_url,
    section_id,
    symbol_id,
)


def test_stable_ids_are_deterministic() -> None:
    doc = document_id("https://github.com/Opentrons/opentrons", "abc123def456", "docs/a.md")
    assert doc == document_id("https://github.com/Opentrons/opentrons", "abc123def456", "docs/a.md")
    assert section_id(doc, ["Aspirate"]) == section_id(doc, ["Aspirate"])
    assert symbol_id("opentrons.protocol_api.InstrumentContext.transfer", "v9.1.1").endswith(
        ":9.1.1"
    )


def test_github_and_rendered_urls() -> None:
    url = github_blob_url(
        "https://github.com/Opentrons/opentrons",
        "ad074b80e267084f08065b6d559b791140dfa671",
        "api/src/opentrons/protocol_api/labware.py",
        line_start=100,
        line_end=145,
    )
    assert url.endswith("#L100-L145")
    rendered = rendered_docs_url(
        "docs/python-api/docs/building-block-commands/liquids.md",
        anchor="aspirate",
    )
    assert rendered == (
        "https://docs.opentrons.com/python-api/building-block-commands/liquids/#aspirate"
    )


def test_tight_quoted_front_matter_keeps_colons_in_the_value() -> None:
    meta, body = split_front_matter(
        '---\ntitle:"Opentrons Flex: Opentrons App"\ndescription: "Use the app."\n---\n\nBody\n'
    )
    assert meta == {
        "title": "Opentrons Flex: Opentrons App",
        "description": "Use the app.",
    }
    assert body == "Body\n"


def test_markdown_sections_and_examples(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text(
        "---\ntitle: Sample\n---\n\n# Hello\n\n## Aspirate { #aspirate-building-block }\n\n"
        "Use aspirate.\n\n```python\npipette.aspirate(10)\n```\n",
        encoding="utf-8",
    )
    bundle = parse_markdown_document(
        path,
        repository="https://github.com/Opentrons/opentrons",
        commit="a" * 40,
        source_path="docs/python-api/docs/sample.md",
        source_key="opentrons_docs",
        authority_level=AuthorityLevel.OFFICIAL_GUIDANCE,
        source_type="mkdocs_markdown",
    )
    assert len(bundle.documents) == 1
    assert any(s.anchor == "aspirate-building-block" for s in bundle.sections)
    assert len(bundle.examples) == 1
    assert bundle.documents[0].content_hash
    assert bundle.sections[0].document_id == bundle.documents[0].document_id
