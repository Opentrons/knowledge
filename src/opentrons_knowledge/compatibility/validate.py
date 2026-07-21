"""Compatibility validation for source pins."""

from __future__ import annotations

from pathlib import Path

from opentrons_knowledge.errors import CompatibilityError
from opentrons_knowledge.models.enums import CompatibilityStatus
from opentrons_knowledge.models.manifest import (
    CompatibilityBlock,
    CompatibilityRecord,
    CompatibilityReport,
    ResolvedSource,
    SourceManifest,
)
from opentrons_knowledge.normalization.serialize import load_yaml

STATUS_RANK = {
    CompatibilityStatus.EXACT_RELEASE: 0,
    CompatibilityStatus.VALIDATED: 1,
    CompatibilityStatus.PARTIALLY_VALIDATED: 2,
    CompatibilityStatus.UNVERIFIED: 3,
    CompatibilityStatus.INCOMPATIBLE: 4,
}


def load_compatibility_record(path: Path) -> CompatibilityRecord:
    data = load_yaml(path)
    return CompatibilityRecord.model_validate(data)


def validate_compatibility(
    manifest: SourceManifest,
    resolved: dict[str, ResolvedSource],
    *,
    compatibility_dir: Path | None = None,
    allow_unverified: bool = True,
) -> CompatibilityReport:
    """Validate source compatibility; fail on incompatible required sources."""
    warnings: list[str] = []
    errors: list[str] = []
    blocks: dict[str, CompatibilityBlock] = {}

    for key, source in sorted(resolved.items()):
        block = source.compatibility
        if block.validation_record and compatibility_dir:
            record_path = compatibility_dir / block.validation_record
            if not record_path.exists():
                # Also allow path relative to corpora dir as written in manifest
                alt = Path(block.validation_record)
                record_path = (
                    alt if alt.exists() else compatibility_dir / Path(block.validation_record).name
                )
            if record_path.exists():
                record = load_compatibility_record(record_path)
                if record.status != block.status:
                    warnings.append(
                        f"{key}: manifest status {block.status} differs from record {record.status}"
                    )
            else:
                warnings.append(f"{key}: validation record missing: {block.validation_record}")

        if block.status == CompatibilityStatus.INCOMPATIBLE:
            errors.append(f"{key}: marked incompatible with target release")
        elif block.status == CompatibilityStatus.UNVERIFIED and not allow_unverified:
            errors.append(f"{key}: unverified sources are not allowed")
        elif block.status in {
            CompatibilityStatus.UNVERIFIED,
            CompatibilityStatus.PARTIALLY_VALIDATED,
        }:
            warnings.append(f"{key}: compatibility is {block.status.value}")

        target = block.target_release or manifest.corpus.target_opentrons_release
        if target and target.lstrip("v") != manifest.corpus.target_opentrons_release.lstrip("v"):
            warnings.append(
                f"{key}: compatibility target_release {target} != "
                f"{manifest.corpus.target_opentrons_release}"
            )
        blocks[key] = block

    if errors:
        raise CompatibilityError("; ".join(errors))

    overall = _overall_status(blocks)
    return CompatibilityReport(
        overall_status=overall,
        target_release=manifest.corpus.target_opentrons_release,
        sources=blocks,
        warnings=warnings,
        errors=errors,
    )


def _overall_status(blocks: dict[str, CompatibilityBlock]) -> CompatibilityStatus:
    if not blocks:
        return CompatibilityStatus.UNVERIFIED
    worst = max(blocks.values(), key=lambda b: STATUS_RANK[b.status])
    return worst.status
