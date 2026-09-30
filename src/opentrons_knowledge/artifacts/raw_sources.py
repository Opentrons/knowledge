"""Copy pinned source trees into the published corpus as verbatim ``raw/`` files."""

from __future__ import annotations

import shutil
from pathlib import Path

from opentrons_knowledge.models.manifest import ResolvedSource
from opentrons_knowledge.normalization.serialize import write_yaml

SKIP_DIR_NAMES = {".venv", "site", "node_modules", "__pycache__", ".git"}


def _is_excluded(relative_path: str, exclude_paths: list[str]) -> bool:
    normalized = relative_path.replace("\\", "/")
    for prefix in exclude_paths:
        p = prefix.rstrip("/")
        if normalized == p or normalized.startswith(f"{p}/"):
            return True
    return False


def copy_raw_sources(
    corpus_root: Path,
    sources: dict[str, ResolvedSource],
) -> dict[str, int]:
    """Mirror materialized source trees under ``raw/<source_key>/``.

    Paths inside each source directory match the Opentrons monorepo layout at
    the pinned commit for that source. Different sources may pin different
    commits, so files are partitioned by ``source_key`` rather than merged into
    one checkout.
    """
    raw_root = corpus_root / "raw"
    if raw_root.exists():
        shutil.rmtree(raw_root)
    raw_root.mkdir(parents=True)

    counts: dict[str, int] = {}
    manifest_sources: list[dict[str, object]] = []

    for key in sorted(sources):
        source = sources[key]
        materialize = Path(source.materialize_root or "")
        if not materialize.is_dir():
            msg = f"Missing materialize_root for source {key}: {materialize}"
            raise FileNotFoundError(msg)

        dest_root = raw_root / key
        dest_root.mkdir(parents=True, exist_ok=True)
        file_count = 0

        for path in sorted(materialize.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(materialize).as_posix()
            if any(part in SKIP_DIR_NAMES for part in path.relative_to(materialize).parts):
                continue
            if _is_excluded(rel, source.exclude_paths):
                continue
            target = dest_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            file_count += 1

        counts[key] = file_count
        manifest_sources.append(
            {
                "key": key,
                "repository": source.repository,
                "tag": source.tag,
                "commit": source.commit,
                "artifact_root": f"raw/{key}",
                "configured_paths": list(source.paths),
                "exclude_paths": list(source.exclude_paths),
                "file_count": file_count,
            }
        )

    readme = raw_root / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Raw pinned sources",
                "",
                "Verbatim files from the Opentrons monorepo at the commits pinned in",
                "`manifest.yaml`. Each top-level folder is one manifest source key;",
                "paths inside match the repository layout for that pin.",
                "",
                "Use this tree when you want to chunk, index, or parse sources yourself.",
                "Normalized records live under `corpus/*.jsonl.zst`.",
                "",
                "See `raw/manifest.yaml` for per-source commits and file counts.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    write_yaml(
        raw_root / "manifest.yaml",
        {
            "description": "Verbatim source files included in this corpus artifact",
            "sources": manifest_sources,
        },
    )
    return counts


def validate_raw_layout(corpus_root: Path, source_keys: list[str]) -> None:
    """Ensure ``raw/`` exists and contains each resolved source key."""
    raw_root = corpus_root / "raw"
    if not raw_root.is_dir():
        msg = "Missing raw/ directory in corpus artifact"
        raise ValueError(msg)
    for key in sorted(source_keys):
        if not (raw_root / key).is_dir():
            msg = f"Missing raw/{key}/ in corpus artifact"
            raise ValueError(msg)
    if not (raw_root / "manifest.yaml").is_file():
        msg = "Missing raw/manifest.yaml in corpus artifact"
        raise ValueError(msg)
