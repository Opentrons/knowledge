"""Canonical corpus record models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opentrons_knowledge.models.enums import (
    AuthorityLevel,
    ConstraintSeverity,
    DerivationMethod,
    EntityType,
    SymbolType,
)


class StrictModel(BaseModel):
    """Base model with stable serialization defaults."""

    model_config = ConfigDict(extra="forbid", frozen=False)


class Document(StrictModel):
    document_id: str
    title: str
    source_repository: str
    source_commit: str
    source_path: str
    source_url: str
    rendered_url: str | None = None
    source_type: str
    authority_level: AuthorityLevel
    robot_types: list[str] = Field(default_factory=list)
    api_versions: list[str] = Field(default_factory=list)
    content_hash: str
    document_format: str = "markdown"
    headings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Section(StrictModel):
    section_id: str
    document_id: str
    title: str
    heading_path: list[str]
    content: str
    content_markdown: str
    content_plaintext: str
    parent_section_id: str | None = None
    child_section_ids: list[str] = Field(default_factory=list)
    previous_section_id: str | None = None
    next_section_id: str | None = None
    anchor: str | None = None
    source_url: str | None = None
    token_count: int = 0
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SymbolParameter(StrictModel):
    name: str
    annotation: str | None = None
    default: str | None = None
    kind: str = "positional_or_keyword"


class CodeSymbol(StrictModel):
    symbol_id: str
    qualified_name: str
    symbol_type: SymbolType
    module_path: str
    source_path: str
    source_url: str
    signature: str
    parameters: list[SymbolParameter] = Field(default_factory=list)
    return_type: str | None = None
    docstring: str | None = None
    minimum_api_version: str | None = None
    maximum_api_version: str | None = None
    deprecated: bool = False
    deprecation_message: str | None = None
    robot_types: list[str] = Field(default_factory=list)
    related_symbols: list[str] = Field(default_factory=list)
    related_document_sections: list[str] = Field(default_factory=list)
    line_start: int | None = None
    line_end: int | None = None
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Entity(StrictModel):
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    version_scope: str | None = None
    robot_scope: list[str] = Field(default_factory=list)
    deprecated: bool = False
    content_hash: str
    raw_source: dict[str, Any] | None = None


class Relationship(StrictModel):
    relationship_id: str
    source_id: str
    target_id: str
    relationship_type: str
    properties: dict[str, Any] = Field(default_factory=dict)
    source_reference: str | None = None
    confidence: float = 1.0
    derivation_method: DerivationMethod = DerivationMethod.DIRECT


class Constraint(StrictModel):
    constraint_id: str
    constraint_type: str
    description: str
    severity: ConstraintSeverity = ConstraintSeverity.WARNING
    subject_ids: list[str] = Field(default_factory=list)
    condition: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    version_scope: str | None = None
    robot_scope: list[str] = Field(default_factory=list)
    derivation_method: DerivationMethod = DerivationMethod.DIRECT


class Example(StrictModel):
    example_id: str
    title: str
    description: str = ""
    code: str
    language: str = "python"
    source_path: str
    source_url: str
    robot_types: list[str] = Field(default_factory=list)
    api_versions: list[str] = Field(default_factory=list)
    symbols_used: list[str] = Field(default_factory=list)
    entities_used: list[str] = Field(default_factory=list)
    verified: bool = False
    verification_method: str | None = None
    authority_level: AuthorityLevel = AuthorityLevel.EXAMPLE
    content_hash: str


class SourceFileRecord(StrictModel):
    source_file_id: str
    source_key: str
    repository: str
    commit: str
    path: str
    status: str  # included | excluded
    reason: str | None = None
    content_hash: str | None = None
    byte_size: int | None = None
