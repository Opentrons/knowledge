"""Source and corpus manifest models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opentrons_knowledge.models.enums import (
    DEFAULT_AUTHORITY_PRECEDENCE,
    AuthorityLevel,
    CompatibilityStatus,
)
from opentrons_knowledge.retrieval.models import (
    ChunkingStrategy,
    Enrichment,
    RetrievalConfig,
    RetrievalKind,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompatibilityBlock(StrictModel):
    status: CompatibilityStatus
    target_release: str | None = None
    relationship: str | None = None
    validation_record: str | None = None
    notes: str | None = None


class SourceEntry(StrictModel):
    repository: str
    commit: str | None = None
    tag: str | None = None
    paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    build_target: str | None = None
    local_path: str | None = None
    compatibility: CompatibilityBlock

    @model_validator(mode="after")
    def require_commit_or_tag(self) -> SourceEntry:
        if not self.commit and not self.tag:
            msg = "Each source must declare commit and/or tag"
            raise ValueError(msg)
        return self


class CorpusIdentity(StrictModel):
    name: str = "opentrons-knowledge"
    version: str
    target_opentrons_release: str
    corpus_schema_version: int = 1

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        # <release>-k<n>
        parts = value.rsplit("-k", 1)
        if len(parts) != 2 or not parts[0] or not parts[1].isdigit():
            msg = f"Invalid corpus version '{value}'; expected <release>-k<n>"
            raise ValueError(msg)
        return value


class BuilderInfo(StrictModel):
    name: str = "opentrons-knowledge-builder"
    version: str
    commit: str | None = None


class ProcessingInfo(StrictModel):
    parser_version: int = 1
    normalization_version: int = 1
    relationship_model_version: int = 1
    chunking_strategy: str = "semantic-sections-v1"


class PublicationInfo(StrictModel):
    """How the corpus is packaged for distribution."""

    formats: list[str] = Field(default_factory=lambda: ["tar.zst", "oci"])
    artifact_name_template: str = "opentrons-knowledge-{version}.tar.zst"
    registry: str = "ghcr.io"
    repository: str = "opentrons/opentrons-knowledge"


class RenderedDocsConfig(StrictModel):
    """How to render the Opentrons MkDocs site for canonical document extraction.

    Defaults mirror the Opentrons ``docs-build-deploy`` workflow: ``uv sync``
    followed by ``make build`` in ``docs/`` with ``CI=true`` (strict build)
    under the Python version that workflow installs. The Playwright browser
    install from ``make setup`` is skipped because it is only used for PDFs.
    """

    source: str = "opentrons_docs"
    mkdocs_config: str = "docs/mkdocs.yml"
    working_directory: str = "docs"
    setup_command: list[str] = Field(default_factory=lambda: ["uv", "sync", "--frozen"])
    build_command: list[str] = Field(default_factory=lambda: ["make", "build"])
    site_dir: str = "docs/site"
    python: str = "3.12"
    strict: bool = True
    sparse_paths: list[str] = Field(default_factory=lambda: ["docs", "api", "shared-data"])
    base_url: str = "https://docs.opentrons.com/"
    allowed_modifications: list[str] = Field(
        default_factory=lambda: ["docs/uv.lock"],
        description=(
            "Tracked files the build itself may rewrite. `make build` runs `uv run`, which "
            "re-locks docs/uv.lock when it is stale, exactly as in the production workflow."
        ),
    )

    @field_validator("base_url")
    @classmethod
    def require_trailing_slash(cls, value: str) -> str:
        return value if value.endswith("/") else f"{value}/"

    def environment(self) -> dict[str, str]:
        """Environment overrides applied to the setup and build commands."""
        env = {"UV_PYTHON": self.python}
        if self.strict:
            env["CI"] = "true"
        return env


class RetrievalSettings(StrictModel):
    """Retrieval bundle to build into the corpus. Needs ``rendered_docs``.

    Defaults are the configuration selected in ``docs/retrieval-experiments.md``.
    """

    kinds: list[RetrievalKind] = Field(
        default_factory=lambda: [RetrievalKind.DOC_SECTION, RetrievalKind.ENTITY]
    )
    chunking: ChunkingStrategy = ChunkingStrategy.STRUCTURED
    enrichment: Enrichment = Enrichment.CONTEXT_TERMS
    tokenizer: Literal["default", "en_stem"] = "default"
    queries: str | None = Field(
        default="eval/retrieval/curated.yaml",
        description="Curated evaluation set, relative to the builder repository root.",
    )
    run_experiments: bool = Field(
        default=True,
        description="Re-run the full experiment grid and write reports/retrieval-eval.json.",
    )

    def config(self) -> RetrievalConfig:
        return RetrievalConfig(
            kinds=self.kinds,
            chunking=self.chunking,
            enrichment=self.enrichment,
            tokenizer=self.tokenizer,
        )


class SourceManifest(StrictModel):
    corpus: CorpusIdentity
    sources: dict[str, SourceEntry]
    builder: BuilderInfo
    processing: ProcessingInfo = Field(default_factory=ProcessingInfo)
    publication: PublicationInfo = Field(default_factory=PublicationInfo)
    authority_precedence: list[AuthorityLevel] = Field(
        default_factory=lambda: list(DEFAULT_AUTHORITY_PRECEDENCE)
    )
    rendered_docs: RenderedDocsConfig | None = None
    retrieval: RetrievalSettings | None = None

    @model_validator(mode="after")
    def require_core_sources(self) -> SourceManifest:
        required = {"opentrons_docs", "protocol_api", "shared_data"}
        missing = required - set(self.sources)
        if missing:
            msg = f"Source manifest missing required sources: {sorted(missing)}"
            raise ValueError(msg)
        if self.rendered_docs and self.rendered_docs.source not in self.sources:
            msg = f"rendered_docs.source '{self.rendered_docs.source}' is not a declared source"
            raise ValueError(msg)
        if self.retrieval and not self.rendered_docs:
            msg = "retrieval requires rendered_docs (it is built from canonical documents)"
            raise ValueError(msg)
        return self


class ResolvedSource(StrictModel):
    key: str
    repository: str
    tag: str | None = None
    commit: str
    paths: list[str]
    exclude_paths: list[str] = Field(default_factory=list)
    compatibility: CompatibilityBlock
    materialize_root: str | None = None


class EnvironmentInfo(StrictModel):
    os: str
    python_version: str
    lockfile_digest: str | None = None
    build_timestamp: str


class CorpusManifest(StrictModel):
    name: str
    version: str
    human_identity: str
    target_opentrons_release: str
    corpus_schema_version: int
    builder: BuilderInfo
    processing: ProcessingInfo
    publication: PublicationInfo
    sources: list[ResolvedSource]
    authority_precedence: list[AuthorityLevel]
    environment: EnvironmentInfo
    checksums: dict[str, str] = Field(default_factory=dict)
    artifact_digest: str | None = None
    variants: list[str] = Field(default_factory=lambda: ["full"])
    record_counts: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompatibilityRecord(StrictModel):
    """Maintainable per-source compatibility annotation file."""

    source_key: str
    target_release: str
    status: CompatibilityStatus
    relationship: str
    validated_on: str | None = None
    notes: str | None = None
    known_gaps: list[str] = Field(default_factory=list)


class CompatibilityReport(StrictModel):
    overall_status: CompatibilityStatus
    target_release: str
    sources: dict[str, CompatibilityBlock]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


CorpusBuildMode = Literal["full", "fixture"]
