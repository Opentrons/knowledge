"""Source manifest validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from opentrons_knowledge.builder.pipeline import load_source_manifest
from opentrons_knowledge.corpora import highest_corpus_version, version_sort_key
from opentrons_knowledge.errors import ManifestError
from opentrons_knowledge.models.enums import CompatibilityStatus
from opentrons_knowledge.models.manifest import CompatibilityBlock, SourceEntry, SourceManifest


def test_highest_corpus_version_orders_release_then_revision(tmp_path: Path) -> None:
    for name in ("9.1.2-k3", "10.0.0-k1", "10.0.0-k10", "9.0.0-k1", "10.0.0-k5"):
        version_dir = tmp_path / name
        version_dir.mkdir()
        (version_dir / "source-manifest.yaml").write_text("corpus: {}\n", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    assert highest_corpus_version(tmp_path) == "10.0.0-k10"
    assert version_sort_key("9.1.2-k3") < version_sort_key("10.0.0-k1")
    assert version_sort_key("10.0.0-k5") < version_sort_key("10.0.0-k10")


def test_highest_corpus_version_rejects_a_bad_name(tmp_path: Path) -> None:
    version_dir = tmp_path / "not-a-version"
    version_dir.mkdir()
    (version_dir / "source-manifest.yaml").write_text("corpus: {}\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="Invalid corpus version"):
        highest_corpus_version(tmp_path)


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


def test_load_real_900_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "9.0.0-k1" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "9.0.0-k1"
    assert manifest.corpus.target_opentrons_release == "v9.0.0"
    assert manifest.sources["protocol_api"].tag == "v9.0.0"
    assert manifest.sources["protocol_api"].commit.startswith("44b37a2f")
    assert manifest.sources["shared_data"].commit == manifest.sources["protocol_api"].commit
    assert manifest.sources["opentrons_docs"].tag == "mkdocs-2026-06-02"
    assert manifest.sources["opentrons_docs"].commit.startswith("345c2408")
    assert manifest.sources["opentrons_docs"].compatibility.status == CompatibilityStatus.VALIDATED
    assert manifest.sources["opentrons_ai_v1"].tag == "ai-server@0.0.20"
    assert manifest.sources["opentrons_ai_v1"].commit.startswith("aa7bb9ef")
    assert "pd" in "".join(manifest.sources["opentrons_ai_v1"].exclude_paths)


def test_load_real_912_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "9.1.2-k1" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "9.1.2-k1"
    assert manifest.corpus.target_opentrons_release == "v9.1.2"
    assert manifest.sources["protocol_api"].tag == "v9.1.2"
    assert manifest.sources["protocol_api"].commit.startswith("1fb64381")
    assert manifest.sources["shared_data"].commit == manifest.sources["protocol_api"].commit
    assert manifest.sources["opentrons_docs"].tag == "mkdocs-2026-08-12"
    assert manifest.sources["opentrons_docs"].commit.startswith("f76e83ca")
    assert manifest.sources["opentrons_docs"].compatibility.status == CompatibilityStatus.VALIDATED
    assert manifest.sources["opentrons_ai_v1"].tag == "ai-server@0.0.20"
    assert manifest.sources["opentrons_ai_v1"].commit.startswith("aa7bb9ef")
    assert "pd" in "".join(manifest.sources["opentrons_ai_v1"].exclude_paths)


def test_load_real_912_k2_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "9.1.2-k2" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "9.1.2-k2"
    assert manifest.corpus.target_opentrons_release == "v9.1.2"
    assert manifest.sources["protocol_api"].tag == "v9.1.2"
    assert manifest.sources["protocol_api"].commit.startswith("1fb64381")
    assert manifest.sources["shared_data"].commit == manifest.sources["protocol_api"].commit
    assert manifest.sources["opentrons_docs"].tag == "mkdocs-2026-09-01"
    assert manifest.sources["opentrons_docs"].commit.startswith("b38ab22d")
    assert manifest.sources["opentrons_docs"].compatibility.status == CompatibilityStatus.VALIDATED
    assert manifest.sources["opentrons_ai_v1"].tag == "ai-server@0.0.22"
    assert manifest.sources["opentrons_ai_v1"].commit.startswith("0b6a6ecd")
    assert "pd" in "".join(manifest.sources["opentrons_ai_v1"].exclude_paths)


def test_load_real_912_k3_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "9.1.2-k3" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "9.1.2-k3"
    assert manifest.corpus.target_opentrons_release == "v9.1.2"
    assert manifest.sources["protocol_api"].commit.startswith("1fb64381")
    assert manifest.sources["opentrons_docs"].commit.startswith("b38ab22d")
    assert manifest.sources["opentrons_ai_v1"].commit.startswith("0b6a6ecd")


def test_load_real_1000_k2_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "10.0.0-k2" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "10.0.0-k2"
    assert manifest.sources["protocol_api"].commit.startswith("e8c6d0a4")


_K3_SOURCES = {"opentrons_ai_v1", "opentrons_docs", "protocol_api", "shared_data"}


def test_load_real_1000_k3_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "10.0.0-k3" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "10.0.0-k3"
    assert set(manifest.sources) == _K3_SOURCES
    assert "protocol_designer" not in manifest.sources


def test_load_real_1000_k4_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "10.0.0-k4" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "10.0.0-k4"
    assert set(manifest.sources) == _K3_SOURCES | {"protocol_designer"}
    source = manifest.sources["protocol_designer"]
    assert source.repository == "https://github.com/Opentrons/opentrons"
    assert source.tag == "protocol-designer@9.0.1"
    assert source.commit == "677274a40c5d22044c4efe7365d4904a56eeefd4"
    assert source.paths == ["protocol-designer/src/utils/labwareModuleCompatibility.ts"]
    assert source.compatibility.status == CompatibilityStatus.VALIDATED
    assert source.compatibility.target_release == "v10.0.0"
    assert source.compatibility.relationship == "latest-protocol-designer-tag"
    assert source.compatibility.validation_record == "compatibility/protocol-designer-v10.0.0.yaml"
    record = path.parent / "compatibility" / "protocol-designer-v10.0.0.yaml"
    assert record.is_file()
    assert manifest.protocol_designer_tables is None


def test_load_real_1000_k5_manifest() -> None:
    corpora = Path(__file__).resolve().parents[2] / "corpora"
    manifest = load_source_manifest(corpora / "10.0.0-k5" / "source-manifest.yaml")
    k4 = load_source_manifest(corpora / "10.0.0-k4" / "source-manifest.yaml")
    assert manifest.corpus.version == "10.0.0-k5"
    assert manifest.sources.keys() == k4.sources.keys()
    for key, entry in manifest.sources.items():
        assert (entry.tag, entry.commit) == (k4.sources[key].tag, k4.sources[key].commit)
        if key != "protocol_designer":
            assert entry.paths == k4.sources[key].paths
    tables = manifest.protocol_designer_tables
    assert tables is not None
    assert (tables.source, tables.labware_source) == ("protocol_designer", "shared_data")
    assert manifest.sources["protocol_designer"].paths == [
        "protocol-designer/src/constants.ts",
        "protocol-designer/src/modules/moduleData.ts",
        "protocol-designer/src/pages/Designer/DeckSetup/constants.ts",
        "protocol-designer/src/pages/Designer/DeckSetup/utils.ts",
        "protocol-designer/src/pages/Onboarding/constants.ts",
        "protocol-designer/src/utils/labwareModuleCompatibility.ts",
    ]
    assert manifest.sources["protocol_designer"].paths != k4.sources["protocol_designer"].paths
    assert manifest.rendered_docs == k4.rendered_docs
    assert manifest.retrieval == k4.retrieval


def test_protocol_designer_tables_require_declared_sources() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "10.0.0-k5" / "source-manifest.yaml"
    data = load_source_manifest(path).model_dump(mode="json")
    del data["sources"]["protocol_designer"]
    with pytest.raises(ValidationError, match=r"protocol_designer_tables\.source"):
        SourceManifest.model_validate(data)


def test_load_real_1000_k1_manifest() -> None:
    path = Path(__file__).resolve().parents[2] / "corpora" / "10.0.0-k1" / "source-manifest.yaml"
    manifest = load_source_manifest(path)
    assert manifest.corpus.version == "10.0.0-k1"
    assert manifest.corpus.target_opentrons_release == "v10.0.0"
    assert manifest.sources["protocol_api"].tag == "v10.0.0"
    assert manifest.sources["protocol_api"].commit.startswith("e8c6d0a4")
    assert manifest.sources["shared_data"].commit == manifest.sources["protocol_api"].commit
    assert manifest.sources["opentrons_docs"].tag == "mkdocs-2026-09-30"
    assert manifest.sources["opentrons_docs"].commit.startswith("00f1431b")
    assert manifest.sources["opentrons_docs"].compatibility.status == CompatibilityStatus.VALIDATED
    assert manifest.sources["opentrons_ai_v1"].tag == "ai-server@0.0.22"
    assert manifest.sources["opentrons_ai_v1"].commit.startswith("0b6a6ecd")
    assert "pd" in "".join(manifest.sources["opentrons_ai_v1"].exclude_paths)


def test_source_requires_commit_or_tag() -> None:
    with pytest.raises(ValidationError):
        SourceEntry(
            repository="https://github.com/Opentrons/opentrons",
            paths=["docs"],
            compatibility=CompatibilityBlock(status=CompatibilityStatus.UNVERIFIED),
        )
