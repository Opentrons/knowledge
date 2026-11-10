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
from opentrons_knowledge.artifacts.raw_sources import copy_raw_sources
from opentrons_knowledge.compatibility.validate import validate_compatibility
from opentrons_knowledge.docs.canonical import (
    CANONICAL_DIR,
    build_canonical_corpus,
    load_canonical_documents,
)
from opentrons_knowledge.docs.markdown import ingest_docs_tree
from opentrons_knowledge.docs.mkdocs_build import RenderedSite, build_site, prebuilt_site
from opentrons_knowledge.errors import SourceResolutionError
from opentrons_knowledge.models.canonical import CanonicalManifest
from opentrons_knowledge.models.enums import AuthorityLevel, CompatibilityStatus
from opentrons_knowledge.models.manifest import (
    BuilderInfo,
    CorpusManifest,
    EnvironmentInfo,
    RenderedDocsConfig,
    ResolvedSource,
    RetrievalSettings,
    SourceEntry,
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
from opentrons_knowledge.normalization.ids import source_file_id
from opentrons_knowledge.normalization.serialize import (
    file_sha256,
    load_yaml,
    write_jsonl_zst,
)
from opentrons_knowledge.python_api.ast_symbols import ingest_protocol_api
from opentrons_knowledge.relationships.build import build_knowledge_graph
from opentrons_knowledge.retrieval.build import RetrievalBuild, build_retrieval
from opentrons_knowledge.retrieval.bundle import RETRIEVAL_DIR
from opentrons_knowledge.retrieval.documents import RetrievalInputs
from opentrons_knowledge.shared_data.entities import ingest_shared_data
from opentrons_knowledge.sources.resolve import MaterializedSources, locate_repo, resolve_sources

log = structlog.get_logger(__name__)


AUTHORITY_BY_SOURCE = {
    "protocol_api": AuthorityLevel.NORMATIVE,
    "shared_data": AuthorityLevel.NORMATIVE,
    "opentrons_docs": AuthorityLevel.OFFICIAL_GUIDANCE,
    "opentrons_ai_v1": AuthorityLevel.CURATED_GUIDANCE,
    "curated": AuthorityLevel.CURATED_GUIDANCE,
}


def raw_only_source_files(key: str, source: ResolvedSource) -> list[SourceFileRecord]:
    """Record configured paths as included source files without reading them.

    ``protocol_designer`` is copied into ``raw/`` by ``copy_raw_sources``.
    The TypeScript allowlist is not parsed into entities, relationships,
    retrieval documents, or search chunks.
    """
    return [
        SourceFileRecord(
            source_file_id=source_file_id(key, path),
            source_key=key,
            repository=source.repository,
            commit=source.commit,
            path=path,
            status="included",
        )
        for path in source.paths
    ]


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
        elif key == "protocol_designer":
            source_files.extend(raw_only_source_files(key, source))

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
    canonical_metadata: dict[str, object] = {}
    if manifest.rendered_docs is not None:
        site = _render_pinned_docs(
            manifest,
            materialized,
            work_root=work_root or output_dir / ".work",
            search_roots=search_roots,
        )
        canonical = build_canonical_corpus(
            site, corpus_root / CANONICAL_DIR, corpus_version=version
        )
        counts["canonical_documents"] = canonical.document_count
        canonical_metadata = _canonical_metadata(canonical)
    retrieval_report: dict[str, object] | None = None
    if manifest.retrieval is not None:
        retrieval, retrieval_metadata = _build_retrieval(
            manifest.retrieval,
            corpus_root,
            version=version,
            documents=documents,
            sections=sections,
            symbols=symbols,
            entities=entities,
        )
        counts["retrieval_documents"] = retrieval.manifest.document_count
        counts["retrieval_chunks"] = retrieval.manifest.chunk_count
        canonical_metadata.update(retrieval_metadata)
        retrieval_report = retrieval.report

    repo_root = Path(__file__).resolve().parents[3]
    if schemas_dir is None:
        schemas_dir = repo_root / "schemas"
    copy_schemas(schemas_dir, corpus_root / "schemas")
    copy_agent_guides(repo_root, corpus_root)
    raw_counts = copy_raw_sources(corpus_root, materialized.sources)
    counts["raw_files"] = sum(raw_counts.values())

    duration = time.perf_counter() - started
    excluded = [s for s in source_files if s.status == "excluded"]
    included = [s for s in source_files if s.status == "included"]

    reports = {
        "build-report": {
            "version": version,
            "duration_seconds": round(duration, 3),
            "record_counts": counts,
            "raw_file_counts": raw_counts,
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
    }
    if retrieval_report is not None:
        reports["retrieval-eval"] = retrieval_report
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
        publication=manifest.publication,
        sources=sorted(materialized.sources.values(), key=lambda s: s.key),
        authority_precedence=manifest.authority_precedence,
        environment=env,
        record_counts=counts,
        metadata={
            "compatibility_overall": compat_report.overall_status.value,
            "raw_file_counts": raw_counts,
            **canonical_metadata,
        },
    )
    write_manifest(corpus_root, corpus_manifest)
    checksums = finalize_checksums(corpus_root)
    corpus_manifest.checksums = checksums
    corpus_manifest.artifact_digest = f"sha256:{corpus_artifact_digest(corpus_root)}"
    write_manifest(corpus_root, corpus_manifest)
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
        raw_counts=raw_counts,
        duration=round(duration, 3),
    )
    return BuildResult(corpus_root=corpus_root, manifest=corpus_manifest, duration_seconds=duration)


def build_fixture_corpus(
    output_dir: Path,
    fixtures_root: Path,
    *,
    extra_sources: dict[str, SourceEntry] | None = None,
) -> BuildResult:
    """Build a tiny deterministic corpus from in-repo fixtures (CI default)."""
    from opentrons_knowledge.models.manifest import (
        CompatibilityBlock,
        CorpusIdentity,
        ProcessingInfo,
        PublicationInfo,
    )

    sources = {
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
    }
    if extra_sources:
        sources.update(extra_sources)
    fixture_manifest = SourceManifest(
        corpus=CorpusIdentity(
            name=PRODUCT_NAME,
            version="0.0.0-k1",
            target_opentrons_release="v0.0.0",
            corpus_schema_version=CORPUS_SCHEMA_VERSION,
        ),
        sources=sources,
        builder=BuilderInfo(name=BUILDER_NAME, version=__version__, commit="fixture"),
        processing=ProcessingInfo(),
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
        src_root = Path(entry.local_path) if entry.local_path else fixtures_root
        for rel in entry.paths:
            src = src_root / rel
            target = dest / rel
            if src.is_dir():
                shutil.copytree(src, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
        materialized_sources[key] = ResolvedSource(
            key=key,
            repository=entry.repository,
            tag=entry.tag,
            commit=entry.commit or "0" * 40,
            paths=list(entry.paths),
            exclude_paths=list(entry.exclude_paths),
            compatibility=entry.compatibility,
            materialize_root=str(dest),
        )

    rendered_fixture = fixtures_root.parent / "rendered_site"
    rendered_site = (
        prebuilt_site(
            site_dir=rendered_fixture / "site",
            checkout=rendered_fixture / "checkout",
            repository="https://github.com/Opentrons/opentrons",
            settings=RenderedDocsConfig(),
            commit="0" * 40,
        )
        if (rendered_fixture / "site").is_dir()
        else None
    )

    # Temporarily monkey-patch resolve by writing a one-off build using materialized map
    return _build_from_materialized(
        fixture_manifest,
        MaterializedSources(sources=materialized_sources, work_root=work),
        output_dir=output_dir,
        schemas_dir=Path(__file__).resolve().parents[3] / "schemas",
        compatibility_dir=None,
        rendered_site=rendered_site,
        retrieval=RetrievalSettings(queries=None, run_experiments=False),
    )


def _build_from_materialized(
    manifest: SourceManifest,
    materialized: MaterializedSources,
    *,
    output_dir: Path,
    schemas_dir: Path,
    compatibility_dir: Path | None,
    rendered_site: RenderedSite | None = None,
    retrieval: RetrievalSettings | None = None,
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
        elif key == "protocol_designer":
            source_files.extend(raw_only_source_files(key, source))

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
    for sub in ("corpus", "reports", "schemas"):
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
    canonical_metadata: dict[str, object] = {}
    if rendered_site is not None:
        canonical = build_canonical_corpus(
            rendered_site, corpus_root / CANONICAL_DIR, corpus_version=version
        )
        counts["canonical_documents"] = canonical.document_count
        canonical_metadata = _canonical_metadata(canonical)
        if retrieval is not None:
            built, retrieval_metadata = _build_retrieval(
                retrieval,
                corpus_root,
                version=version,
                documents=documents,
                sections=sections,
                symbols=symbols,
                entities=entities,
            )
            counts["retrieval_documents"] = built.manifest.document_count
            counts["retrieval_chunks"] = built.manifest.chunk_count
            canonical_metadata.update(retrieval_metadata)
    repo_root = Path(__file__).resolve().parents[3]
    copy_schemas(schemas_dir, corpus_root / "schemas")
    copy_agent_guides(repo_root, corpus_root)
    raw_counts = copy_raw_sources(corpus_root, materialized.sources)
    counts["raw_files"] = sum(raw_counts.values())
    duration = time.perf_counter() - started
    write_build_reports(
        corpus_root / "reports",
        {
            "build-report": {
                "version": version,
                "duration_seconds": round(duration, 3),
                "record_counts": counts,
                "raw_file_counts": raw_counts,
                "fixture": True,
            },
            "source-report": {
                "resolved_sources": [s.model_dump() for s in materialized.sources.values()]
            },
            "compatibility-report": compat_report.model_dump(mode="json"),
            "duplication-report": {"duplicates": graph.duplicates, "conflicts": graph.conflicts},
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
        metadata={"raw_file_counts": raw_counts, **canonical_metadata},
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


def _render_pinned_docs(
    manifest: SourceManifest,
    materialized: MaterializedSources,
    *,
    work_root: Path,
    search_roots: list[Path],
) -> RenderedSite:
    """Render the MkDocs site at the commit already resolved for ``rendered_docs.source``."""
    settings = manifest.rendered_docs
    assert settings is not None
    entry = manifest.sources[settings.source]
    resolved = materialized.sources[settings.source]
    site = build_site(
        repository=entry.repository,
        ref=entry.tag or resolved.commit,
        settings=settings,
        work_root=work_root,
        local_repo=locate_repo(entry, search_roots),
    )
    if site.commit != resolved.commit:
        msg = (
            f"Rendered docs commit {site.commit} differs from resolved "
            f"{settings.source} commit {resolved.commit}"
        )
        raise SourceResolutionError(msg)
    return site


def _build_retrieval(
    settings: RetrievalSettings,
    corpus_root: Path,
    *,
    version: str,
    documents: Sequence[Document],
    sections: Sequence[Section],
    symbols: Sequence[CodeSymbol],
    entities: Sequence[Entity],
) -> tuple[RetrievalBuild, dict[str, object]]:
    guides = [d for d in documents if d.source_type == "ai_guidance"]
    guide_ids = {d.document_id for d in guides}
    inputs = RetrievalInputs(
        canonical_documents=load_canonical_documents(corpus_root / CANONICAL_DIR),
        symbols=symbols,
        entities=entities,
        guide_documents=guides,
        guide_sections=[s for s in sections if s.document_id in guide_ids],
    )
    repo_root = Path(__file__).resolve().parents[3]
    result = build_retrieval(
        inputs,
        corpus_root / RETRIEVAL_DIR,
        settings.config(),
        corpus_version=version,
        queries_path=repo_root / settings.queries if settings.queries else None,
        run_grid=settings.run_experiments,
    )
    manifest = result.manifest
    metadata: dict[str, object] = {
        "retrieval": {
            "path": f"{RETRIEVAL_DIR}/",
            "schema_id": manifest.schema_id,
            "schema_version": manifest.schema_version,
            "config": manifest.config.name,
            "document_count": manifest.document_count,
            "chunk_count": manifest.chunk_count,
        }
    }
    return result, metadata


def _canonical_metadata(canonical: CanonicalManifest) -> dict[str, object]:
    return {
        "canonical_docs": {
            "path": f"{CANONICAL_DIR}/",
            "schema_id": canonical.schema_id,
            "schema_version": canonical.schema_version,
            "commit": canonical.source.commit,
            "document_count": canonical.document_count,
            "section_count": canonical.section_count,
        }
    }


def _write_records(path: Path, records: Sequence[BaseModel]) -> int:
    count, _digest = write_jsonl_zst(path, records)
    return count


def _lockfile_digest() -> str | None:
    lock = Path(__file__).resolve().parents[3] / "uv.lock"
    if lock.exists():
        return file_sha256(lock)
    return None
