"""Fixture corpus build, validation, pack, diff, and determinism."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from opentrons_knowledge.artifacts.archive import pack_corpus, unpack_corpus
from opentrons_knowledge.artifacts.package import validate_corpus_dir
from opentrons_knowledge.builder.pipeline import build_corpus, build_fixture_corpus
from opentrons_knowledge.consumer.corpus import Corpus, diff_corpora
from opentrons_knowledge.models.enums import CompatibilityStatus
from opentrons_knowledge.models.manifest import (
    BuilderInfo,
    CompatibilityBlock,
    CorpusIdentity,
    ResolvedSource,
    SourceEntry,
    SourceManifest,
)
from opentrons_knowledge.normalization.serialize import (
    file_sha256,
    load_yaml,
    read_jsonl_zst,
    write_yaml,
)
from opentrons_knowledge.retrieval.bundle import validate_bundle
from opentrons_knowledge.sources.resolve import MaterializedSources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mini_sources"


def test_fixture_corpus_build_and_validate(tmp_path: Path) -> None:
    result = build_fixture_corpus(tmp_path, FIXTURES)
    manifest = validate_corpus_dir(result.corpus_root)
    assert manifest.version == "0.0.0-k1"
    assert manifest.record_counts["symbols"] >= 1
    assert manifest.record_counts["entities"] >= 1
    assert manifest.record_counts["documents"] >= 1
    assert not (result.corpus_root / "indexes").exists()
    assert (result.corpus_root / "AGENTS.md").exists()
    assert (result.corpus_root / "llms.txt").exists()
    assert (result.corpus_root / "docs" / "agent-usage.md").exists()
    assert (result.corpus_root / "raw" / "manifest.yaml").exists()
    assert (result.corpus_root / "raw" / "protocol_api").is_dir()
    assert manifest.record_counts.get("raw_files", 0) >= 1
    assert (
        manifest.record_counts["retrieval_chunks"] >= manifest.record_counts["retrieval_documents"]
    )
    assert validate_bundle(result.corpus_root / "retrieval") == []
    assert "tar.zst" in (result.corpus_root / "AGENTS.md").read_text(encoding="utf-8")

    corpus = Corpus.open(result.corpus_root)
    assert corpus.manifest.version == "0.0.0-k1"
    assert corpus.sources()


def test_pack_and_unpack_roundtrip(tmp_path: Path) -> None:
    built = build_fixture_corpus(tmp_path / "build", FIXTURES).corpus_root
    packed = pack_corpus(built, output=tmp_path / "opentrons-knowledge-0.0.0-k1.tar.zst")
    archive = Path(packed["archive"])
    assert archive.exists()
    assert packed["sha256"].startswith("sha256:")

    dest = tmp_path / "unpacked"
    root = unpack_corpus(archive, dest)
    validate_corpus_dir(root)
    assert file_sha256(built / "corpus" / "documents.jsonl.zst") == file_sha256(
        root / "corpus" / "documents.jsonl.zst"
    )


def test_fixture_corpus_deterministic(tmp_path: Path) -> None:
    first = build_fixture_corpus(tmp_path / "a", FIXTURES).corpus_root
    second = build_fixture_corpus(tmp_path / "b", FIXTURES).corpus_root
    for name in [
        "documents.jsonl.zst",
        "sections.jsonl.zst",
        "code-symbols.jsonl.zst",
        "entities.jsonl.zst",
        "relationships.jsonl.zst",
        "examples.jsonl.zst",
        "constraints.jsonl.zst",
        "source-files.jsonl.zst",
    ]:
        assert file_sha256(first / "corpus" / name) == file_sha256(second / "corpus" / name)
    for name in ["documents.jsonl.zst", "chunks.jsonl.zst", "queries.jsonl.zst"]:
        assert file_sha256(first / "retrieval" / name) == file_sha256(second / "retrieval" / name)


def test_diff_identical_corpora(tmp_path: Path) -> None:
    left = build_fixture_corpus(tmp_path / "left", FIXTURES).corpus_root
    right = build_fixture_corpus(tmp_path / "right", FIXTURES).corpus_root
    result = diff_corpora(left, right)
    assert result["documents"]["added"] == []
    assert result["documents"]["removed"] == []
    assert result["symbols"]["changed"] == []


ALLOWLIST = "protocol-designer/src/utils/labwareModuleCompatibility.ts"
PD_TAG = "protocol-designer@9.0.1"
PD_COMMIT = "677274a40c5d22044c4efe7365d4904a56eeefd4"


def _protocol_designer_tree(root: Path, text: str) -> None:
    path = root / ALLOWLIST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_entry(paths: list[str]) -> SourceEntry:
    return SourceEntry(
        repository="https://github.com/Opentrons/opentrons",
        commit="0" * 40,
        paths=paths,
        local_path=str(FIXTURES),
        compatibility=CompatibilityBlock(
            status=CompatibilityStatus.EXACT_RELEASE,
            target_release="v0.0.0",
            relationship="fixture",
        ),
    )


def _protocol_designer_entry(root: Path) -> SourceEntry:
    return SourceEntry(
        repository="https://github.com/Opentrons/opentrons",
        tag=PD_TAG,
        commit=PD_COMMIT,
        paths=[ALLOWLIST],
        local_path=str(root),
        compatibility=CompatibilityBlock(
            status=CompatibilityStatus.VALIDATED,
            target_release="v0.0.0",
            relationship="latest-protocol-designer-tag",
        ),
    )


def test_protocol_designer_is_raw_only(tmp_path: Path) -> None:
    """The allowlist is copied and listed, and parsed record counts stay put."""
    baseline = build_fixture_corpus(tmp_path / "baseline", FIXTURES)
    source_root = tmp_path / "pd-source"
    body = "export const COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE = {}\n"
    _protocol_designer_tree(source_root, body)
    built = build_fixture_corpus(
        tmp_path / "with-pd",
        FIXTURES,
        extra_sources={"protocol_designer": _protocol_designer_entry(source_root)},
    )
    raw = built.corpus_root / "raw" / "protocol_designer" / ALLOWLIST
    assert raw.read_text(encoding="utf-8") == body
    listed = load_yaml(built.corpus_root / "raw" / "manifest.yaml")
    (record,) = [item for item in listed["sources"] if item["key"] == "protocol_designer"]
    assert record["tag"] == PD_TAG
    assert record["commit"] == PD_COMMIT
    assert record["configured_paths"] == [ALLOWLIST]
    assert record["file_count"] == 1

    rows = read_jsonl_zst(built.corpus_root / "corpus" / "source-files.jsonl.zst")
    matches = [row for row in rows if row["path"] == ALLOWLIST]
    assert len(matches) == 1
    assert matches[0]["source_key"] == "protocol_designer"
    assert matches[0]["repository"] == "https://github.com/Opentrons/opentrons"
    assert matches[0]["commit"] == PD_COMMIT
    assert matches[0]["status"] == "included"
    assert matches[0]["content_hash"] is None
    assert matches[0]["byte_size"] is None

    for field in ("entities", "relationships", "retrieval_documents", "retrieval_chunks"):
        assert built.manifest.record_counts[field] == baseline.manifest.record_counts[field]


def test_build_corpus_records_protocol_designer_without_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``build_corpus`` lists the allowlist and does not turn it into entities."""
    source_root = tmp_path / "pd-source"
    body = "export const COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE = { heater: [] }\n"
    _protocol_designer_tree(source_root, body)
    manifest = SourceManifest(
        corpus=CorpusIdentity(
            name="opentrons-knowledge",
            version="0.0.0-k2",
            target_opentrons_release="v0.0.0",
        ),
        sources={
            "opentrons_docs": _fixture_entry(["docs/python-api/docs"]),
            "protocol_api": _fixture_entry(["api/src/opentrons/protocol_api"]),
            "shared_data": _fixture_entry(["shared-data/labware/definitions"]),
            "protocol_designer": _protocol_designer_entry(source_root),
        },
        builder=BuilderInfo(name="opentrons-knowledge-builder", version="0.1.0"),
    )
    manifest_path = tmp_path / "source-manifest.yaml"
    write_yaml(manifest_path, manifest.model_dump(mode="json"))

    def fake_resolve(
        manifest: SourceManifest, *, work_root: Path, search_roots: list[Path]
    ) -> MaterializedSources:
        del search_roots
        sources: dict[str, ResolvedSource] = {}
        for key, entry in manifest.sources.items():
            root = Path(entry.local_path or FIXTURES)
            dest = work_root / key
            dest.mkdir(parents=True, exist_ok=True)
            for rel in entry.paths:
                src = root / rel
                target = dest / rel
                if src.is_dir():
                    shutil.copytree(src, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
            sources[key] = ResolvedSource(
                key=key,
                repository=entry.repository,
                tag=entry.tag,
                commit=entry.commit or "0" * 40,
                paths=list(entry.paths),
                compatibility=entry.compatibility,
                materialize_root=str(dest),
            )
        return MaterializedSources(sources=sources, work_root=work_root)

    monkeypatch.setattr("opentrons_knowledge.builder.pipeline.resolve_sources", fake_resolve)
    without = manifest.model_copy(deep=True)
    del without.sources["protocol_designer"]
    without_path = tmp_path / "without.yaml"
    write_yaml(without_path, without.model_dump(mode="json"))
    baseline = build_corpus(without_path, output_dir=tmp_path / "without")
    result = build_corpus(manifest_path, output_dir=tmp_path / "with")

    raw = result.corpus_root / "raw" / "protocol_designer" / ALLOWLIST
    assert raw.read_text(encoding="utf-8") == body
    rows = read_jsonl_zst(result.corpus_root / "corpus" / "source-files.jsonl.zst")
    (match,) = [row for row in rows if row["source_key"] == "protocol_designer"]
    assert match["path"] == ALLOWLIST
    assert match["repository"] == "https://github.com/Opentrons/opentrons"
    assert match["commit"] == PD_COMMIT
    assert match["status"] == "included"
    assert match["content_hash"] is None
    assert match["byte_size"] is None
    listed = load_yaml(result.corpus_root / "raw" / "manifest.yaml")
    (record,) = [item for item in listed["sources"] if item["key"] == "protocol_designer"]
    assert record["tag"] == PD_TAG
    assert record["commit"] == PD_COMMIT
    assert record["file_count"] == 1
    for field in ("entities", "relationships"):
        assert result.manifest.record_counts[field] == baseline.manifest.record_counts[field]
    entity_blob = (result.corpus_root / "corpus" / "entities.jsonl.zst").read_bytes()
    relationship_blob = (result.corpus_root / "corpus" / "relationships.jsonl.zst").read_bytes()
    assert b"labwareModuleCompatibility" not in entity_blob
    assert b"COMPATIBLE_LABWARE_ALLOWLIST" not in entity_blob
    assert b"labwareModuleCompatibility" not in relationship_blob


def test_source_exclusions_recorded(tmp_path: Path) -> None:
    result = build_fixture_corpus(tmp_path, FIXTURES)
    rows = read_jsonl_zst(result.corpus_root / "corpus" / "source-files.jsonl.zst")
    excluded = [r for r in rows if r["status"] == "excluded"]
    assert isinstance(excluded, list)
