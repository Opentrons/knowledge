"""Explicit error types for the Opentrons Knowledge toolchain."""

from __future__ import annotations


class KnowledgeError(Exception):
    """Base error for the Opentrons Knowledge product."""


class ManifestError(KnowledgeError):
    """Source or corpus manifest is invalid."""


class SourceResolutionError(KnowledgeError):
    """A required source commit/tag could not be resolved."""


class CompatibilityError(KnowledgeError):
    """A required source is incompatible with the target release."""


class CorpusValidationError(KnowledgeError):
    """Built corpus failed validation or checksum verification."""


class ArtifactError(KnowledgeError):
    """Corpus archive packaging or unpacking failed."""


class RegistryError(KnowledgeError):
    """OCI registry interaction failed (auth, network, immutability)."""
