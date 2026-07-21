"""Compatibility validation tests."""

from __future__ import annotations

import pytest

from opentrons_knowledge.compatibility.validate import validate_compatibility
from opentrons_knowledge.errors import CompatibilityError
from opentrons_knowledge.models.enums import CompatibilityStatus
from opentrons_knowledge.models.manifest import (
    BuilderInfo,
    CompatibilityBlock,
    CorpusIdentity,
    ResolvedSource,
    SourceEntry,
    SourceManifest,
)


def _manifest() -> SourceManifest:
    return SourceManifest(
        corpus=CorpusIdentity(
            name="opentrons-knowledge",
            version="9.1.1-k1",
            target_opentrons_release="v9.1.1",
        ),
        sources={
            "opentrons_docs": SourceEntry(
                repository="https://github.com/Opentrons/opentrons",
                commit="a" * 40,
                paths=["docs"],
                compatibility=CompatibilityBlock(status=CompatibilityStatus.EXACT_RELEASE),
            ),
            "protocol_api": SourceEntry(
                repository="https://github.com/Opentrons/opentrons",
                commit="a" * 40,
                paths=["api"],
                compatibility=CompatibilityBlock(status=CompatibilityStatus.EXACT_RELEASE),
            ),
            "shared_data": SourceEntry(
                repository="https://github.com/Opentrons/opentrons",
                commit="a" * 40,
                paths=["shared-data"],
                compatibility=CompatibilityBlock(status=CompatibilityStatus.INCOMPATIBLE),
            ),
        },
        builder=BuilderInfo(name="opentrons-knowledge-builder", version="0.1.0"),
    )


def test_incompatible_source_fails_build_gate() -> None:
    manifest = _manifest()
    resolved = {
        key: ResolvedSource(
            key=key,
            repository=entry.repository,
            commit=entry.commit or "a" * 40,
            paths=entry.paths,
            compatibility=entry.compatibility,
        )
        for key, entry in manifest.sources.items()
    }
    with pytest.raises(CompatibilityError):
        validate_compatibility(manifest, resolved)
