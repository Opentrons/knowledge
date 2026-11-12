"""Choose a corpus version from the ``corpora/`` directory."""

from __future__ import annotations

from pathlib import Path

from opentrons_knowledge.errors import ManifestError


def version_sort_key(version: str) -> tuple[tuple[int, ...], int]:
    """Order ``<release>-k<n>`` by release, then knowledge revision.

    ``10.0.0-k10`` sorts after ``10.0.0-k5``, and any ``10.*`` sorts after ``9.*``.
    """
    release, separator, knowledge = version.rpartition("-k")
    if not separator or not release or not knowledge.isdigit():
        msg = f"Invalid corpus version '{version}'; expected <release>-k<n>"
        raise ManifestError(msg)
    try:
        parts = tuple(int(part) for part in release.split("."))
    except ValueError as exc:
        msg = f"Invalid corpus version '{version}'; expected <release>-k<n>"
        raise ManifestError(msg) from exc
    if any(part < 0 for part in parts):
        msg = f"Invalid corpus version '{version}'; expected <release>-k<n>"
        raise ManifestError(msg)
    return parts, int(knowledge)


def highest_corpus_version(corpora_dir: Path) -> str:
    """Return the newest ``corpora/<version>/source-manifest.yaml`` version."""
    if not corpora_dir.is_dir():
        msg = f"No corpus directory at {corpora_dir}"
        raise ManifestError(msg)
    versions = [
        path.name
        for path in corpora_dir.iterdir()
        if path.is_dir() and (path / "source-manifest.yaml").is_file()
    ]
    if not versions:
        msg = f"No source manifests in {corpora_dir}"
        raise ManifestError(msg)
    return max(versions, key=version_sort_key)


def main() -> None:
    """Print the highest corpus version under ``./corpora``."""
    print(highest_corpus_version(Path("corpora")))


if __name__ == "__main__":
    main()
