"""Deterministic corpus build pipeline."""

from __future__ import annotations

import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog
from pydantic import BaseModel

from opentrons_knowledge import __version__
from opentrons_knowledge.__version__ import BUILDER_NAME, CORPUS_SCHEMA_VERSION, PRODUCT_NAME
from opentrons_knowledge.artifacts.package import (
    copy_agent_guides,
    copy_schemas,
    corpus_artifact_digest,
    finalize_checksums,
    write_build_reports,
    write_manifest,
)
from opentrons_knowledge.compatibility.validate import validate_compatibility
from opentrons_knowledge.docs.markdown import ingest_docs_tree
from opentrons_knowledge.indexing.embeddings import FakeEmbeddingProvider, build_vector_index
from opentrons_knowledge.indexing.lexical import build_lexical_index
from opentrons_knowledge.models.enums import AuthorityLevel, CompatibilityStatus
from opentrons_knowledge.models.manifest import (
    BuilderInfo,
    CorpusManifest,
    EnvironmentInfo,
    ResolvedSource,
    SourceManifest,
)
from opentrons_knowledge.models.records import (
    CodeSymbol,
    Constraint,
    Document,
    Entity,
    Example,
    Relationship,
    Section,
    SourceFileRecord,
)
from opentrons_knowledge.normalization.serialize import (
    file_sha256,
    load_yaml,
    write_jsonl_zst,
)
from opentrons_knowledge.python_api.ast_symbols import ingest_protocol_api
from opentrons_knowledge.relationships.build import build_knowledge_graph
from opentrons_knowledge.shared_data.entities import ingest_shared_data
from opentrons_knowledge.sources.resolve import MaterializedSources, resolve_sources

log = structlog.get_logger(__name__)


AUTHORITY_BY_SOURCE = {
    "protocol_api": AuthorityLevel.NORMATIVE,
    "shared_data": AuthorityLevel.NORMATIVE,
    "opentrons_docs": AuthorityLevel.OFFICIAL_GUIDANCE,
    "opentrons_ai_v1": AuthorityLevel.CURATED_GUIDANCE,
    "curated": AuthorityLevel.CURATED_GUIDANCE,
}


@dataclass
class BuildResult:
    corpus_root: Path
    manifest: CorpusManifest
    duration_seconds: float


def load_source_manifest(path: Path) -> SourceManifest:
    data = load_yaml(path)
    return SourceManifest.model_validate(data)


def build_corpus(
    manifest_path: Path,
    *,
    output_dir: Path,
    opentrons_repo: Path | None = None,
    work_root: Path | None = None,
    schemas_dir: Path | None = None,
    builder_commit: str | None = None,
) -> BuildResult:
    """Build a corpus artifact from a source manifest."""
    started = time.perf_counter()
    manifest = load_source_manifest(manifest_path)
    compatibility_dir = manifest_path.parent / "compatibility"

    search_roots: list[Path] = []
    if opentrons_repo:
        search_roots.append(opentrons_repo.resolve())
    # Common local layout: ../opentrons next to knowledge/
    sibling = manifest_path.resolve().parents[2] / "opentrons"
    if sibling.exists():
        search_roots.append(sibling)
    default_local = Path("/Users/joshmcvey/github/opentrons/opentrons")
    if default_local.exists():
        search_roots.append(default_local)

    work = work_root or (output_dir / ".work" / manifest.corpus.version)
    log.info("resolving_sources", version=manifest.corpus.version)
    materialized = resolve_sources(manifest, work_root=work, search_roots=search_roots)

    compat_report = validate_compatibility(
        manifest,
        materialized.sources,
        compatibility_dir=compatibility_dir if compatibility_dir.exists() else None,
    )

    documents: list[Document] = []
    sections: list[Section] = []
    examples: list[Example] = []
    symbols: list[CodeSymbol] = []
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    constraints: list[Constraint] = []
    source_files: list[SourceFileRecord] = []

    release = manifest.corpus.target_opentrons_release

    for key, source in materialized.sources.items():
        root = Path(source.materialize_root or "")
        if key in {"opentrons_docs", "opentrons_ai_v1", "curated"}:
            authority = AUTHORITY_BY_SOURCE.get(key, AuthorityLevel.REFERENCE)
            source_type = "ai_guidance" if key == "opentrons_ai_v1" else "mkdocs_markdown"
            bundle = ingest_docs_tree(
                root,
                repository=source.repository,
                commit=source.commit,
                configured_paths=source.paths,
                exclude_paths=source.exclude_paths,
                source_key=key,
                authority_level=authority,
                source_type=source_type,
            )
            documents.extend(bundle.documents)
            sections.extend(bundle.sections)
            examples.extend(bundle.examples)
            source_files.extend(bundle.source_files)
        elif key == "protocol_api":
            api_bundle = ingest_protocol_api(
                root,
                repository=source.repository,
                commit=source.commit,
                configured_paths=source.paths,
                release=release,
                source_key=key,
            )
            symbols.extend(api_bundle.symbols)
            relationships.extend(api_bundle.relationships)
            source_files.extend(api_bundle.source_files)
        elif key == "shared_data":
            data_bundle = ingest_shared_data(
                root,
                repository=source.repository,
                commit=source.commit,
                configured_paths=source.paths,
                release=release,
                source_key=key,
            )
            entities.extend(data_bundle.entities)
            relationships.extend(data_bundle.relationships)
            source_files.extend(data_bundle.source_files)

    graph = build_knowledge_graph(
        documents=documents,
        sections=sections,
        symbols=symbols,
        entities=entities,
        examples=examples,
        existing_relationships=relationships,
    )
    relationships = graph.relationships
    constraints = graph.constraints

    version = manifest.corpus.version
    corpus_root = output_dir / f"{PRODUCT_NAME}-{version}"
    if corpus_root.exists():
        import shutil

        shutil.rmtree(corpus_root)
    (corpus_root / "corpus").mkdir(parents=True)
    (corpus_root / "indexes" / "lexical").mkdir(parents=True)
    (corpus_root / "indexes" / "vector").mkdir(parents=True)
    (corpus_root / "reports").mkdir(parents=True)
    (corpus_root / "schemas").mkdir(parents=True)

    counts = {
        "documents": _write_records(corpus_root / "corpus" / "documents.jsonl.zst", documents),
        "sections": _write_records(corpus_root / "corpus" / "sections.jsonl.zst", sections),
        "symbols": _write_records(corpus_root / "corpus" / "code-symbols.jsonl.zst", symbols),
        "entities": _write_records(corpus_root / "corpus" / "entities.jsonl.zst", entities),
        "relationships": _write_records(
            corpus_root / "corpus" / "relationships.jsonl.zst", relationships
        ),
        "examples": _write_records(corpus_root / "corpus" / "examples.jsonl.zst", examples),
        "constraints": _write_records(
            corpus_root / "corpus" / "constraints.jsonl.zst", constraints
        ),
        "source_files": _write_records(
            corpus_root / "corpus" / "source-files.jsonl.zst", source_files
        ),
    }

    lexical_stats = build_lexical_index(
        corpus_root / "indexes" / "lexical",
        symbols=symbols,
        entities=entities,
        sections=sections,
    )
    provider = None
    if manifest.embedding.enabled and (manifest.embedding.provider or "fake") == "fake":
        provider = FakeEmbeddingProvider(
            dimensions=manifest.embedding.dimensions or 32,
            model=manifest.embedding.model or "fake-hash-v1",
        )
    vector_stats = build_vector_index(
        corpus_root / "indexes" / "vector",
        sections=sections,
        symbols=symbols,
        entities=entities,
        constraints=constraints,
        examples=examples,
        embedding=manifest.embedding,
        provider=provider,
    )

    repo_root = Path(__file__).resolve().parents[3]
    if schemas_dir is None:
        schemas_dir = repo_root / "schemas"
    copy_schemas(schemas_dir, corpus_root / "schemas")
    copy_agent_guides(repo_root, corpus_root)

    duration = time.perf_counter() - started
    excluded = [s for s in source_files if s.status == "excluded"]
    included = [s for s in source_files if s.status == "included"]

    reports = {
        "build-report": {
            "version": version,
            "duration_seconds": round(duration, 3),
            "record_counts": counts,
            "source_files_included": len(included),
            "source_files_excluded": len(excluded),
            "duplicates_detected": len(graph.duplicates),
            "conflicts_detected": len(graph.conflicts),
            "warnings": list(compat_report.warnings),
            "errors": list(compat_report.errors),
        },
        "source-report": {
            "included": [s.model_dump() for s in included],
            "excluded": [s.model_dump() for s in excluded],
            "resolved_sources": [s.model_dump() for s in materialized.sources.values()],
        },
        "compatibility-report": compat_report.model_dump(mode="json"),
        "duplication-report": {
            "duplicates": graph.duplicates,
            "conflicts": graph.conflicts,
        },
        "indexing-report": {
            "lexical": lexical_stats,
            "vector": vector_stats,
        },
    }
    write_build_reports(corpus_root / "reports", reports)

    env = EnvironmentInfo(
        os=f"{platform.system()} {platform.release()}",
        python_version=platform.python_version(),
        lockfile_digest=_lockfile_digest(),
        build_timestamp=datetime.now(UTC).isoformat(),
    )
    corpus_manifest = CorpusManifest(
        name=manifest.corpus.name,
        version=version,
        human_identity=f"{PRODUCT_NAME}:{version}",
        target_opentrons_release=manifest.corpus.target_opentrons_release,
        corpus_schema_version=manifest.corpus.corpus_schema_version or CORPUS_SCHEMA_VERSION,
        builder=BuilderInfo(
            name=manifest.builder.name or BUILDER_NAME,
            version=manifest.builder.version or __version__,
            commit=builder_commit or manifest.builder.commit,
        ),
        processing=manifest.processing,
        embedding=manifest.embedding,
        publication=manifest.publication,
        sources=sorted(materialized.sources.values(), key=lambda s: s.key),
        authority_precedence=manifest.authority_precedence,
        environment=env,
        record_counts=counts,
        metadata={
            "compatibility_overall": compat_report.overall_status.value,
        },
    )
    write_manifest(corpus_root, corpus_manifest)
    checksums = finalize_checksums(corpus_root)
    corpus_manifest.checksums = checksums
    corpus_manifest.artifact_digest = f"sha256:{corpus_artifact_digest(corpus_root)}"
    write_manifest(corpus_root, corpus_manifest)
    # Re-finalize checksums after embedding digest into manifest
    checksums = finalize_checksums(corpus_root)
    corpus_manifest.checksums = checksums
    corpus_manifest.artifact_digest = f"sha256:{corpus_artifact_digest(corpus_root)}"
    write_manifest(corpus_root, corpus_manifest)
    finalize_checksums(corpus_root)

    log.info(
        "corpus_built",
        version=version,
        path=str(corpus_root),
        counts=counts,
        duration=round(duration, 3),
    )
    return BuildResult(corpus_root=corpus_root, manifest=corpus_manifest, duration_seconds=duration)


def build_fixture_corpus(output_dir: Path, fixtures_root: Path) -> BuildResult:
    """Build a tiny deterministic corpus from in-repo fixtures (CI default)."""
    from opentrons_knowledge.models.manifest import (
        CompatibilityBlock,
        CorpusIdentity,
        EmbeddingInfo,
        ProcessingInfo,
        PublicationInfo,
        SourceEntry,
    )

    fixture_manifest = SourceManifest(
        corpus=CorpusIdentity(
            name=PRODUCT_NAME,
            version="0.0.0-k1",
            target_opentrons_release="v0.0.0",
            corpus_schema_version=CORPUS_SCHEMA_VERSION,
        ),
        sources={
            "opentrons_docs": SourceEntry(
                repository="https://github.com/Opentrons/opentrons",
                commit="0" * 40,
                paths=["docs/python-api/docs"],
                local_path=str(fixtures_root),
                compatibility=CompatibilityBlock(
                    status=CompatibilityStatus.EXACT_RELEASE,
                    target_release="v0.0.0",
                    relationship="fixture",
                ),
            ),
            "protocol_api": SourceEntry(
                repository="https://github.com/Opentrons/opentrons",
                commit="0" * 40,
                paths=["api/src/opentrons/protocol_api"],
                local_path=str(fixtures_root),
                compatibility=CompatibilityBlock(
                    status=CompatibilityStatus.EXACT_RELEASE,
                    target_release="v0.0.0",
                    relationship="fixture",
                ),
            ),
            "shared_data": SourceEntry(
                repository="https://github.com/Opentrons/opentrons",
                commit="0" * 40,
                paths=["shared-data/labware/definitions"],
                local_path=str(fixtures_root),
                compatibility=CompatibilityBlock(
                    status=CompatibilityStatus.EXACT_RELEASE,
                    target_release="v0.0.0",
                    relationship="fixture",
                ),
            ),
            "opentrons_ai_v1": SourceEntry(
                repository="https://github.com/Opentrons/opentrons",
                commit="0" * 40,
                paths=["opentrons-ai-server/api/storage/docs"],
                exclude_paths=["opentrons-ai-server/api/storage/docs/pd"],
                local_path=str(fixtures_root),
                compatibility=CompatibilityBlock(
                    status=CompatibilityStatus.VALIDATED,
                    target_release="v0.0.0",
                    relationship="fixture",
                ),
            ),
        },
        builder=BuilderInfo(name=BUILDER_NAME, version=__version__, commit="fixture"),
        processing=ProcessingInfo(),
        embedding=EmbeddingInfo(enabled=True, provider="fake", model="fake-hash-v1", dimensions=16),
        publication=PublicationInfo(),
    )

    # For fixtures, bypass git by materializing via direct copy layout.
    work = output_dir / ".work" / "fixture"
    work.mkdir(parents=True, exist_ok=True)
    materialized_sources: dict[str, ResolvedSource] = {}
    for key, entry in fixture_manifest.sources.items():
        dest = work / key
        import shutil

        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for rel in entry.paths:
            src = fixtures_root / rel
            target = dest / rel
            if src.is_dir():
                shutil.copytree(src, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
        materialized_sources[key] = ResolvedSource(
            key=key,
            repository=entry.repository,
            commit=entry.commit or "0" * 40,
            paths=list(entry.paths),
            exclude_paths=list(entry.exclude_paths),
            compatibility=entry.compatibility,
            materialize_root=str(dest),
        )

    # Temporarily monkey-patch resolve by writing a one-off build using materialized map
    return _build_from_materialized(
        fixture_manifest,
        MaterializedSources(sources=materialized_sources, work_root=work),
        output_dir=output_dir,
        schemas_dir=Path(__file__).resolve().parents[3] / "schemas",
        compatibility_dir=None,
    )


def _build_from_materialized(
    manifest: SourceManifest,
    materialized: MaterializedSources,
    *,
    output_dir: Path,
    schemas_dir: Path,
    compatibility_dir: Path | None,
) -> BuildResult:
    started = time.perf_counter()
    compat_report = validate_compatibility(
        manifest,
        materialized.sources,
        compatibility_dir=compatibility_dir,
    )

    documents: list[Document] = []
    sections: list[Section] = []
    examples: list[Example] = []
    symbols: list[CodeSymbol] = []
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    source_files: list[SourceFileRecord] = []
    release = manifest.corpus.target_opentrons_release

    for key, source in materialized.sources.items():
        root = Path(source.materialize_root or "")
        if key in {"opentrons_docs", "opentrons_ai_v1", "curated"}:
            bundle = ingest_docs_tree(
                root,
                repository=source.repository,
                commit=source.commit,
                configured_paths=source.paths,
                exclude_paths=source.exclude_paths,
                source_key=key,
                authority_level=AUTHORITY_BY_SOURCE.get(key, AuthorityLevel.REFERENCE),
                source_type="fixture_markdown",
            )
            documents.extend(bundle.documents)
            sections.extend(bundle.sections)
            examples.extend(bundle.examples)
            source_files.extend(bundle.source_files)
        elif key == "protocol_api":
            api_bundle = ingest_protocol_api(
                root,
                repository=source.repository,
                commit=source.commit,
                configured_paths=source.paths,
                release=release,
            )
            symbols.extend(api_bundle.symbols)
            relationships.extend(api_bundle.relationships)
            source_files.extend(api_bundle.source_files)
        elif key == "shared_data":
            data_bundle = ingest_shared_data(
                root,
                repository=source.repository,
                commit=source.commit,
                configured_paths=source.paths,
                release=release,
            )
            entities.extend(data_bundle.entities)
            relationships.extend(data_bundle.relationships)
            source_files.extend(data_bundle.source_files)

    graph = build_knowledge_graph(
        documents=documents,
        sections=sections,
        symbols=symbols,
        entities=entities,
        examples=examples,
        existing_relationships=relationships,
    )

    version = manifest.corpus.version
    corpus_root = output_dir / f"{PRODUCT_NAME}-{version}"
    if corpus_root.exists():
        import shutil

        shutil.rmtree(corpus_root)
    for sub in ("corpus", "indexes/lexical", "indexes/vector", "reports", "schemas"):
        (corpus_root / sub).mkdir(parents=True)

    counts = {
        "documents": _write_records(corpus_root / "corpus" / "documents.jsonl.zst", documents),
        "sections": _write_records(corpus_root / "corpus" / "sections.jsonl.zst", sections),
        "symbols": _write_records(corpus_root / "corpus" / "code-symbols.jsonl.zst", symbols),
        "entities": _write_records(corpus_root / "corpus" / "entities.jsonl.zst", entities),
        "relationships": _write_records(
            corpus_root / "corpus" / "relationships.jsonl.zst", graph.relationships
        ),
        "examples": _write_records(corpus_root / "corpus" / "examples.jsonl.zst", examples),
        "constraints": _write_records(
            corpus_root / "corpus" / "constraints.jsonl.zst", graph.constraints
        ),
        "source_files": _write_records(
            corpus_root / "corpus" / "source-files.jsonl.zst", source_files
        ),
    }
    lexical_stats = build_lexical_index(
        corpus_root / "indexes" / "lexical",
        symbols=symbols,
        entities=entities,
        sections=sections,
    )
    vector_stats = build_vector_index(
        corpus_root / "indexes" / "vector",
        sections=sections,
        symbols=symbols,
        entities=entities,
        constraints=graph.constraints,
        examples=examples,
        embedding=manifest.embedding,
        provider=FakeEmbeddingProvider(
            dimensions=manifest.embedding.dimensions or 16,
            model=manifest.embedding.model or "fake-hash-v1",
        ),
    )
    repo_root = Path(__file__).resolve().parents[3]
    copy_schemas(schemas_dir, corpus_root / "schemas")
    copy_agent_guides(repo_root, corpus_root)
    duration = time.perf_counter() - started
    write_build_reports(
        corpus_root / "reports",
        {
            "build-report": {
                "version": version,
                "duration_seconds": round(duration, 3),
                "record_counts": counts,
                "fixture": True,
            },
            "source-report": {
                "resolved_sources": [s.model_dump() for s in materialized.sources.values()]
            },
            "compatibility-report": compat_report.model_dump(mode="json"),
            "duplication-report": {"duplicates": graph.duplicates, "conflicts": graph.conflicts},
            "indexing-report": {"lexical": lexical_stats, "vector": vector_stats},
        },
    )
    corpus_manifest = CorpusManifest(
        name=manifest.corpus.name,
        version=version,
        human_identity=f"{PRODUCT_NAME}:{version}",
        target_opentrons_release=manifest.corpus.target_opentrons_release,
        corpus_schema_version=CORPUS_SCHEMA_VERSION,
        builder=manifest.builder,
        processing=manifest.processing,
        embedding=manifest.embedding,
        publication=manifest.publication,
        sources=sorted(materialized.sources.values(), key=lambda s: s.key),
        authority_precedence=manifest.authority_precedence,
        environment=EnvironmentInfo(
            os=f"{platform.system()} {platform.release()}",
            python_version=sys.version.split()[0],
            lockfile_digest=_lockfile_digest(),
            build_timestamp="1970-01-01T00:00:00+00:00",
        ),
        record_counts=counts,
    )
    write_manifest(corpus_root, corpus_manifest)
    finalize_checksums(corpus_root)
    corpus_manifest.checksums = {
        p.relative_to(corpus_root).as_posix(): file_sha256(p)
        for p in corpus_root.rglob("*")
        if p.is_file() and p.name != "checksums.txt"
    }
    corpus_manifest.artifact_digest = f"sha256:{corpus_artifact_digest(corpus_root)}"
    write_manifest(corpus_root, corpus_manifest)
    finalize_checksums(corpus_root)
    return BuildResult(corpus_root=corpus_root, manifest=corpus_manifest, duration_seconds=duration)


def _write_records(path: Path, records: Sequence[BaseModel]) -> int:
    count, _digest = write_jsonl_zst(path, records)
    return count


def _lockfile_digest() -> str | None:
    lock = Path(__file__).resolve().parents[3] / "uv.lock"
    if lock.exists():
        return file_sha256(lock)
    return None
