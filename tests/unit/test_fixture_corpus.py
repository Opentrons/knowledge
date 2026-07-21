"""Fixture corpus build, validation, pack, diff, and determinism."""

from __future__ import annotations

from pathlib import Path

from opentrons_knowledge.artifacts.archive import pack_corpus, unpack_corpus
from opentrons_knowledge.artifacts.package import validate_corpus_dir
from opentrons_knowledge.builder.pipeline import build_fixture_corpus
from opentrons_knowledge.consumer.corpus import Corpus, diff_corpora
from opentrons_knowledge.normalization.serialize import file_sha256, read_jsonl_zst

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mini_sources"


def test_fixture_corpus_build_and_validate(tmp_path: Path) -> None:
    result = build_fixture_corpus(tmp_path, FIXTURES)
    manifest = validate_corpus_dir(result.corpus_root)
    assert manifest.version == "0.0.0-k1"
    assert manifest.record_counts["symbols"] >= 1
    assert manifest.record_counts["entities"] >= 1
    assert manifest.record_counts["documents"] >= 1
    assert (result.corpus_root / "indexes" / "lexical" / "symbols.json").exists()
    assert (result.corpus_root / "indexes" / "vector" / "embeddings.jsonl.zst").exists()
    assert (result.corpus_root / "AGENTS.md").exists()
    assert (result.corpus_root / "llms.txt").exists()
    assert (result.corpus_root / "docs" / "agent-usage.md").exists()
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


def test_diff_identical_corpora(tmp_path: Path) -> None:
    left = build_fixture_corpus(tmp_path / "left", FIXTURES).corpus_root
    right = build_fixture_corpus(tmp_path / "right", FIXTURES).corpus_root
    result = diff_corpora(left, right)
    assert result["documents"]["added"] == []
    assert result["documents"]["removed"] == []
    assert result["symbols"]["changed"] == []


def test_source_exclusions_recorded(tmp_path: Path) -> None:
    result = build_fixture_corpus(tmp_path, FIXTURES)
    rows = read_jsonl_zst(result.corpus_root / "corpus" / "source-files.jsonl.zst")
    excluded = [r for r in rows if r["status"] == "excluded"]
    assert isinstance(excluded, list)
