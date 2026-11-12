"""Corpus packaging, checksums, and validation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from opentrons_knowledge.artifacts.raw_sources import validate_raw_layout
from opentrons_knowledge.docs.canonical import CANONICAL_DIR, validate_canonical_corpus
from opentrons_knowledge.errors import CorpusValidationError
from opentrons_knowledge.models.manifest import CorpusManifest
from opentrons_knowledge.normalization.serialize import (
    file_sha256,
    load_yaml,
    read_checksums,
    read_jsonl_zst,
    write_checksums,
    write_json,
    write_yaml,
)
from opentrons_knowledge.protocol_designer.tables import TABLES_DIR, validate_tables
from opentrons_knowledge.retrieval.bundle import RETRIEVAL_DIR, validate_bundle

CORPUS_FILES = (
    "documents.jsonl.zst",
    "sections.jsonl.zst",
    "code-symbols.jsonl.zst",
    "entities.jsonl.zst",
    "relationships.jsonl.zst",
    "examples.jsonl.zst",
    "constraints.jsonl.zst",
    "source-files.jsonl.zst",
)


def write_build_reports(reports_dir: Path, reports: dict[str, Any]) -> dict[str, str]:
    """Write report JSON files; return relative path -> hash."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, payload in sorted(reports.items()):
        path = reports_dir / f"{name}.json"
        write_json(path, payload)
        rel = f"reports/{name}.json"
        hashes[rel] = file_sha256(path)
    return hashes


def compute_checksums(corpus_root: Path) -> dict[str, str]:
    """Hash all files under corpus_root except checksums.txt and runtime lock files."""
    checksums: dict[str, str] = {}
    for path in artifact_files(corpus_root):
        rel = path.relative_to(corpus_root).as_posix()
        if rel == "checksums.txt":
            continue
        checksums[rel] = file_sha256(path)
    return checksums


def artifact_files(corpus_root: Path) -> list[Path]:
    """List the files that make up a corpus, sorted.

    Tantivy creates empty ``.tantivy-*.lock`` files whenever an index is
    opened; they are runtime state, so they are neither checksummed nor packed.

    Args:
        corpus_root: Corpus directory.

    Returns:
        Files under the corpus, excluding Tantivy lock files.
    """
    return [
        path
        for path in sorted(corpus_root.rglob("*"))
        if path.is_file() and not (path.name.startswith(".tantivy-") and path.suffix == ".lock")
    ]


def finalize_checksums(corpus_root: Path) -> dict[str, str]:
    checksums = compute_checksums(corpus_root)
    write_checksums(corpus_root / "checksums.txt", checksums)
    return checksums


def validate_corpus_dir(corpus_root: Path) -> CorpusManifest:
    """Validate layout, schemas presence, and checksums."""
    manifest_path = corpus_root / "manifest.yaml"
    if not manifest_path.exists():
        raise CorpusValidationError(f"Missing manifest.yaml in {corpus_root}")
    checksums_path = corpus_root / "checksums.txt"
    if not checksums_path.exists():
        raise CorpusValidationError("Missing checksums.txt")

    for name in CORPUS_FILES:
        if not (corpus_root / "corpus" / name).exists():
            raise CorpusValidationError(f"Missing corpus/{name}")

    data = load_yaml(manifest_path)
    manifest = CorpusManifest.model_validate(data)
    validate_raw_layout(corpus_root, [s.key for s in manifest.sources])
    if (corpus_root / CANONICAL_DIR).exists():
        validate_canonical_corpus(corpus_root / CANONICAL_DIR)
    if (corpus_root / RETRIEVAL_DIR).exists():
        problems = validate_bundle(corpus_root / RETRIEVAL_DIR)
        if problems:
            raise CorpusValidationError(f"Invalid {RETRIEVAL_DIR}/: {'; '.join(problems)}")
    if (corpus_root / TABLES_DIR).exists():
        problems = validate_tables(corpus_root / TABLES_DIR)
        if problems:
            raise CorpusValidationError(f"Invalid {TABLES_DIR}/: {'; '.join(problems)}")

    expected = read_checksums(checksums_path)
    actual = compute_checksums(corpus_root)
    # checksums.txt is excluded from both
    if expected != actual:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(
            path for path in set(expected) & set(actual) if expected[path] != actual[path]
        )
        raise CorpusValidationError(
            f"Checksum mismatch: missing={missing} extra={extra} changed={changed[:20]}"
        )

    return manifest


def inspect_corpus(corpus_root: Path) -> dict[str, Any]:
    manifest = validate_corpus_dir(corpus_root)
    counts = dict(manifest.record_counts)
    if not counts:
        for name, key in [
            ("documents.jsonl.zst", "documents"),
            ("sections.jsonl.zst", "sections"),
            ("code-symbols.jsonl.zst", "symbols"),
            ("entities.jsonl.zst", "entities"),
            ("relationships.jsonl.zst", "relationships"),
            ("examples.jsonl.zst", "examples"),
            ("constraints.jsonl.zst", "constraints"),
            ("source-files.jsonl.zst", "source_files"),
        ]:
            counts[key] = len(read_jsonl_zst(corpus_root / "corpus" / name))
    return {
        "version": manifest.version,
        "human_identity": manifest.human_identity,
        "target_opentrons_release": manifest.target_opentrons_release,
        "corpus_schema_version": manifest.corpus_schema_version,
        "builder": manifest.builder.model_dump(),
        "sources": [s.model_dump() for s in manifest.sources],
        "record_counts": counts,
        "artifact_digest": manifest.artifact_digest,
    }


def copy_schemas(schemas_src: Path, schemas_dst: Path) -> None:
    schemas_dst.mkdir(parents=True, exist_ok=True)
    if not schemas_src.exists():
        return
    for path in schemas_src.glob("*.schema.json"):
        shutil.copy2(path, schemas_dst / path.name)


def copy_agent_guides(repo_root: Path, corpus_root: Path) -> None:
    """Copy agent discovery docs into the published corpus artifact.

    Agents commonly look for AGENTS.md / llms.txt at the artifact root and a
    fuller guide under docs/.
    """
    for relative in ("AGENTS.md", "docs/agent-usage.md", "docs/retrieval-tool.md"):
        source = repo_root / relative
        if not source.exists():
            continue
        destination = corpus_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    # Artifact-local discovery file (only paths that exist inside the corpus).
    llms = corpus_root / "llms.txt"
    llms.write_text(
        "\n".join(
            [
                "# Opentrons Knowledge Corpus",
                "",
                "> Agent entrypoints for this published corpus artifact.",
                "",
                "## Start here",
                "",
                "- [AGENTS.md](AGENTS.md): short agent entrypoint",
                "- [docs/agent-usage.md](docs/agent-usage.md): full agent guide",
                "- [docs/retrieval-tool.md](docs/retrieval-tool.md): "
                "the two agent tools, search_api and search_docs",
                "- [manifest.yaml](manifest.yaml): version, sources, schema, digest",
                "",
                "## Data",
                "",
                "- raw/: verbatim pinned source files (monorepo layout per source key)",
                "- corpus/*.jsonl.zst: normalized records",
                "- retrieval/ when present: api/bm25 for the Python API, docs/bm25 for the rest",
                "- canonical/ (when present): structured pages from rendered MkDocs HTML",
                "- schemas/: JSON schemas",
                "- reports/: build and compatibility reports",
                "",
            ]
        ),
        encoding="utf-8",
    )


def corpus_artifact_digest(corpus_root: Path) -> str:
    """Digest over checksums.txt contents (stable artifact identity helper)."""
    return file_sha256(corpus_root / "checksums.txt")


def write_manifest(corpus_root: Path, manifest: CorpusManifest) -> None:
    write_yaml(corpus_root / "manifest.yaml", json.loads(manifest.model_dump_json()))
