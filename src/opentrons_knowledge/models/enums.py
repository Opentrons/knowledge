"""Shared enumerations for corpus records."""

from __future__ import annotations

from enum import StrEnum


class AuthorityLevel(StrEnum):
    NORMATIVE = "normative"
    OFFICIAL_GUIDANCE = "official_guidance"
    REFERENCE = "reference"
    CURATED_GUIDANCE = "curated_guidance"
    EXAMPLE = "example"
    HISTORICAL = "historical"
    DEPRECATED = "deprecated"
    GENERATED = "generated"


class CompatibilityStatus(StrEnum):
    EXACT_RELEASE = "exact-release"
    VALIDATED = "validated"
    PARTIALLY_VALIDATED = "partially-validated"
    UNVERIFIED = "unverified"
    INCOMPATIBLE = "incompatible"


class SymbolType(StrEnum):
    CLASS = "class"
    METHOD = "method"
    FUNCTION = "function"
    ENUM = "enum"
    CONSTANT = "constant"
    DATA_MODEL = "data_model"
    PROPERTY = "property"
    MODULE = "module"


class EntityType(StrEnum):
    ROBOT = "robot"
    PIPETTE = "pipette"
    TIP_RACK = "tip_rack"
    LABWARE = "labware"
    MODULE = "module"
    DECK = "deck"
    PROTOCOL_OPERATION = "protocol_operation"
    API_VERSION = "api_version"
    FEATURE = "feature"


class ConstraintSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DerivationMethod(StrEnum):
    DIRECT = "direct"
    INFERRED = "inferred"
    CURATED = "curated"


DEFAULT_AUTHORITY_PRECEDENCE: tuple[AuthorityLevel, ...] = (
    AuthorityLevel.NORMATIVE,
    AuthorityLevel.OFFICIAL_GUIDANCE,
    AuthorityLevel.GENERATED,
    AuthorityLevel.CURATED_GUIDANCE,
    AuthorityLevel.EXAMPLE,
    AuthorityLevel.HISTORICAL,
    AuthorityLevel.DEPRECATED,
)
