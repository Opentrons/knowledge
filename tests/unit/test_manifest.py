"""Source manifest validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from opentrons_knowledge.builder.pipeline import load_source_manifest
from opentrons_knowledge.models.enums import CompatibilityStatus
from opentrons_knowledge.models.manifest import CompatibilityBlock, SourceEntry, SourceManifest


def test_corpus_version_pattern() -> None:
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(
            {
                "corpus": {
                    "name": "opentrons-knowledge",
                    "version": "9.1.1",
                    "target_opentrons_release": "v9.1.1",
                },
                "sources": {
                    "opentrons_docs": {
                        "repository": "https://github.com/Opentrons/opentrons",
                        "commit": "a" * 40,
                        "paths": ["docs"],
                        "compatibility": {"status": "exact-release"},
                    },
                    "protocol_api": {
                        "repository": "https://github.com/Opentrons/opentrons",
                        "commit": "a" * 40,
                        "paths": ["api"],
                        "compatibility": {"status": "exact-release"},
                    },
                    "shared_data": {
                        "repository": "https://github.com/Opentrons/opentrons",
                        "commit": "a" * 40,
                        "paths": ["shared-data"],
                        "compatibility": {"status": "exact-release"},
                    },
                },
                "builder": {"name": "opentrons-knowledge-builder", "version": "0.1.0"},
            }
        )


def test_requires_core_sources() -> None:
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(
            {
                "corpus": {
                    "name": "opentrons-knowledge",
                    "version": "9.1.1-k1",
                    "target_opentrons_release": "v9.1.1",
                },
                "sources": {},
                "builder": {"name": "opentrons-knowledge-builder", "version": "0.1.0"},
            }
        )


def test_load_real_911_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "9.1.1-k1" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "9.1.1-k1"
    assert manifest.sources["protocol_api"].tag == "v9.1.1"
    assert manifest.sources["protocol_api"].commit.startswith("ad074b80")
    assert manifest.sources["opentrons_ai_v1"].tag == "ai-server@0.0.20"
    assert manifest.sources["opentrons_ai_v1"].commit.startswith("aa7bb9ef")
    assert "pd" in "".join(manifest.sources["opentrons_ai_v1"].exclude_paths)
    assert manifest.sources["opentrons_docs"].compatibility.status == CompatibilityStatus.VALIDATED
    assert manifest.publication.formats == ["tar.zst", "oci"]
    assert manifest.publication.repository == "opentrons/opentrons-knowledge"


def test_source_requires_commit_or_tag() -> None:
    with pytest.raises(ValidationError):
        SourceEntry(
            repository="https://github.com/Opentrons/opentrons",
            paths=["docs"],
            compatibility=CompatibilityBlock(status=CompatibilityStatus.UNVERIFIED),
        )
