"""Render the Opentrons MkDocs site from a pinned revision.

The build reuses the Opentrons repository's own ``docs/`` uv project, Makefile,
and ``mkdocs.yml``. Pinned builds run in an isolated ``git clone --shared``
sparse checkout under the Knowledge work directory, so the developer's clone is
never modified. ``in_place`` builds use an existing checkout as-is for local
iteration on documentation changes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import structlog

from opentrons_knowledge.errors import DocsBuildError, SourceResolutionError
from opentrons_knowledge.models.manifest import RenderedDocsConfig
from opentrons_knowledge.normalization.ids import repo_slug, short_commit, slugify
from opentrons_knowledge.sources.resolve import resolve_commit, run_git

log = structlog.get_logger(__name__)

# Variables that would leak the caller's (Knowledge) environment into the
# Opentrons docs uv project.
_SCRUBBED_ENV = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_PROJECT", "PYTHONPATH", "PYTHONHOME")
_STAMP_NAME = "build-stamp.json"
_LOG_TAIL_LINES = 40


@dataclass(frozen=True)
class RenderedSite:
    """A rendered MkDocs site plus the checkout and revision it came from.

    Attributes:
        site_dir: Directory containing the static HTML site.
        checkout: Repository working tree used for the build (source Markdown lives here).
        repository: Repository URL recorded in provenance.
        ref: Tag or branch requested, when known.
        commit: Full commit SHA that was rendered.
        dirty: True when the checkout had uncommitted changes to tracked files.
        settings: Build settings used.
        log_path: Combined setup/build log, when a build ran.
        reused: True when a previous build for the same commit and settings was reused.
        prebuilt: True when the site was supplied rather than built by Knowledge.
        modified_files: Tracked files the build rewrote (limited to
            ``settings.allowed_modifications``).
    """

    site_dir: Path
    checkout: Path
    repository: str
    ref: str | None
    commit: str
    dirty: bool
    settings: RenderedDocsConfig
    log_path: Path | None = None
    reused: bool = False
    prebuilt: bool = False
    modified_files: tuple[str, ...] = ()


def build_site(
    *,
    repository: str,
    ref: str | None,
    settings: RenderedDocsConfig,
    work_root: Path,
    local_repo: Path | None = None,
    in_place: bool = False,
    rebuild: bool = False,
) -> RenderedSite:
    """Check out the docs revision and run the Opentrons MkDocs build.

    Args:
        repository: Repository URL (used for cloning and provenance).
        ref: Tag, branch, or commit to render. Required unless ``in_place``.
        settings: Build commands, environment, and paths.
        work_root: Knowledge scratch directory for checkouts, mirrors, and logs.
        local_repo: Existing local clone to read objects from (or build in, with
            ``in_place``). When omitted, ``repository`` is cloned blob-less.
        in_place: Build directly in ``local_repo``'s working tree at its HEAD.
        rebuild: Ignore a previous successful build for the same commit.

    Returns:
        The rendered site and its provenance.

    Raises:
        DocsBuildError: If the revision cannot be checked out or the build fails.
    """
    if in_place:
        if local_repo is None:
            raise DocsBuildError("--in-place requires a local Opentrons checkout")
        return _build_in_place(
            repository=repository,
            ref=ref,
            settings=settings,
            checkout=local_repo.resolve(),
            work_root=work_root,
        )
    if not ref:
        raise DocsBuildError("A docs revision (tag, branch, or commit) is required")

    repo_root = (
        _require_git_repo(local_repo.resolve())
        if local_repo is not None
        else _ensure_mirror(repository, work_root)
    )
    commit = _resolve_revision(repo_root, ref, fetchable=local_repo is None)
    build_root = work_root / "mkdocs" / short_commit(commit)
    checkout = build_root / "checkout"
    stamp_path = build_root / _STAMP_NAME
    stamp = _stamp(commit, settings)
    site_dir = checkout / settings.site_dir

    log_path = build_root / "mkdocs-build.log"
    previous = _read_stamp(stamp_path, stamp)
    if not rebuild and previous is not None and (site_dir / "index.html").is_file():
        log.info("mkdocs_build_reused", commit=commit, site=str(site_dir))
        return RenderedSite(
            site_dir=site_dir,
            checkout=checkout,
            repository=repository,
            ref=ref,
            commit=commit,
            dirty=False,
            settings=settings,
            log_path=log_path,
            reused=True,
            modified_files=tuple(previous),
        )

    stamp_path.unlink(missing_ok=True)
    prepare_checkout(repo_root, commit, checkout, settings.sparse_paths)
    _run_build(checkout, settings, log_path)
    modified = _check_modifications(checkout, settings, before=set())
    _require_site(site_dir, log_path)
    stamp_path.write_text(
        json.dumps({**stamp, "modified_files": modified}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    log.info("mkdocs_build_complete", commit=commit, site=str(site_dir), modified=modified)
    return RenderedSite(
        site_dir=site_dir,
        checkout=checkout,
        repository=repository,
        ref=ref,
        commit=commit,
        dirty=False,
        settings=settings,
        log_path=log_path,
        modified_files=tuple(modified),
    )


def prebuilt_site(
    *,
    site_dir: Path,
    checkout: Path,
    repository: str,
    settings: RenderedDocsConfig,
    ref: str | None = None,
    commit: str | None = None,
) -> RenderedSite:
    """Describe an already-rendered site so it can be extracted without rebuilding.

    Args:
        site_dir: Rendered site directory (for example ``docs/site`` after ``make build``).
        checkout: Repository root holding ``docs/`` sources, for source mapping.
        repository: Repository URL recorded in provenance.
        settings: Build settings (paths and base URL are used for mapping).
        ref: Optional tag or branch name to record.
        commit: Commit to record. Defaults to the checkout's HEAD.

    Returns:
        A ``RenderedSite`` flagged as prebuilt.

    Raises:
        DocsBuildError: If the site or commit cannot be determined.
    """
    if not (site_dir / "index.html").is_file():
        raise DocsBuildError(f"No rendered site at {site_dir} (missing index.html)")
    dirty = False
    if commit is None:
        try:
            commit = run_git(["rev-parse", "HEAD"], cwd=checkout)
        except SourceResolutionError as exc:
            raise DocsBuildError(
                f"Cannot determine commit for {checkout}; pass an explicit commit"
            ) from exc
        dirty = bool(_tracked_changes(checkout))
    return RenderedSite(
        site_dir=site_dir.resolve(),
        checkout=checkout.resolve(),
        repository=repository,
        ref=ref,
        commit=commit,
        dirty=dirty,
        settings=settings,
        prebuilt=True,
    )


def prepare_checkout(repo_root: Path, commit: str, dest: Path, sparse_paths: list[str]) -> Path:
    """Create (or reuse) an isolated sparse checkout of ``commit``.

    ``git clone --shared`` borrows objects from ``repo_root`` without writing to
    it, and keeps tags so ``hatch-vcs`` versions resolve as they do in CI.

    Args:
        repo_root: Local clone that contains ``commit``.
        commit: Full commit SHA.
        dest: Checkout directory to create.
        sparse_paths: Top-level paths needed by the docs build (cone mode).

    Returns:
        ``dest``.
    """
    if (dest / ".git").exists():
        try:
            if run_git(["rev-parse", "HEAD"], cwd=dest) == commit and not _tracked_changes(dest):
                return dest
        except SourceResolutionError:
            pass
        shutil.rmtree(dest)
    elif dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_git(["clone", "--quiet", "--shared", "--no-checkout", str(repo_root), str(dest)])
        if sparse_paths:
            run_git(["sparse-checkout", "set", "--cone", *sparse_paths], cwd=dest)
        run_git(["checkout", "--quiet", "--detach", commit], cwd=dest)
    except SourceResolutionError as exc:
        raise DocsBuildError(f"Could not check out {commit} into {dest}: {exc}") from exc
    return dest


def build_environment(
    settings: RenderedDocsConfig, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Environment for setup/build commands: caller env, scrubbed, plus settings overrides."""
    env = dict(os.environ if base is None else base)
    for key in _SCRUBBED_ENV:
        env.pop(key, None)
    env.update(settings.environment())
    return env


def _build_in_place(
    *,
    repository: str,
    ref: str | None,
    settings: RenderedDocsConfig,
    checkout: Path,
    work_root: Path,
) -> RenderedSite:
    _require_git_repo(checkout)
    commit = run_git(["rev-parse", "HEAD"], cwd=checkout)
    if ref and resolve_commit(checkout, ref) != commit:
        raise DocsBuildError(
            f"--in-place builds the checkout's HEAD ({short_commit(commit)}), "
            f"but ref {ref!r} points elsewhere; check it out first or drop --in-place"
        )
    before = _tracked_changes(checkout)
    log_path = work_root / "mkdocs" / "in-place" / "mkdocs-build.log"
    _run_build(checkout, settings, log_path)
    modified = _check_modifications(checkout, settings, before=before)
    site_dir = checkout / settings.site_dir
    _require_site(site_dir, log_path)
    return RenderedSite(
        site_dir=site_dir,
        checkout=checkout,
        repository=repository,
        ref=ref,
        commit=commit,
        dirty=bool(before),
        settings=settings,
        log_path=log_path,
        modified_files=tuple(modified),
    )


def _run_build(checkout: Path, settings: RenderedDocsConfig, log_path: Path) -> None:
    cwd = checkout / settings.working_directory
    if not (checkout / settings.mkdocs_config).is_file():
        raise DocsBuildError(f"MkDocs config not found: {checkout / settings.mkdocs_config}")
    env = build_environment(settings)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        for command in (settings.setup_command, settings.build_command):
            if not command:
                continue
            if shutil.which(command[0], path=env.get("PATH")) is None:
                raise DocsBuildError(f"Required build tool not found on PATH: {command[0]}")
            handle.write(f"$ (cd {settings.working_directory} && {' '.join(command)})\n")
            handle.flush()
            log.info("mkdocs_command", command=command, cwd=str(cwd))
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
            handle.flush()
            if completed.returncode != 0:
                raise DocsBuildError(
                    f"Docs build command failed (exit {completed.returncode}): "
                    f"{' '.join(command)}\n"
                    f"--- last {_LOG_TAIL_LINES} lines of {log_path} ---\n"
                    f"{_tail(log_path)}"
                )


def _require_site(site_dir: Path, log_path: Path) -> None:
    if not (site_dir / "index.html").is_file():
        raise DocsBuildError(
            f"Build finished but {site_dir}/index.html is missing. See {log_path}.\n"
            f"{_tail(log_path)}"
        )


def _check_modifications(
    checkout: Path, settings: RenderedDocsConfig, *, before: set[str]
) -> list[str]:
    """Return tracked files the build changed; fail if any are not explicitly allowed."""
    changed = sorted(_tracked_changes(checkout) - before)
    unexpected = [path for path in changed if path not in settings.allowed_modifications]
    if unexpected:
        raise DocsBuildError(
            "Docs build modified tracked files in the checkout: " + ", ".join(unexpected[:20])
        )
    return changed


def _tracked_changes(checkout: Path) -> set[str]:
    diff = run_git(["diff", "--name-only", "HEAD"], cwd=checkout)
    return {line for line in diff.splitlines() if line.strip()}


def _require_git_repo(path: Path) -> Path:
    if not (path / ".git").exists():
        raise DocsBuildError(f"Not a git checkout: {path}")
    return path


def _ensure_mirror(repository: str, work_root: Path) -> Path:
    mirror = work_root / "mirrors" / slugify(repo_slug(repository))
    if (mirror / ".git").exists():
        return mirror
    mirror.parent.mkdir(parents=True, exist_ok=True)
    log.info("cloning_repository", repository=repository, dest=str(mirror))
    try:
        run_git(
            ["clone", "--quiet", "--filter=blob:none", "--no-checkout", repository, str(mirror)]
        )
    except SourceResolutionError as exc:
        raise DocsBuildError(f"Could not clone {repository}: {exc}") from exc
    return mirror


def _resolve_revision(repo_root: Path, ref: str, *, fetchable: bool) -> str:
    try:
        return resolve_commit(repo_root, ref)
    except SourceResolutionError:
        if not fetchable:
            raise DocsBuildError(
                f"Revision {ref!r} not found in {repo_root}. Fetch it there "
                "(git fetch --tags) or omit --opentrons-repo to clone the repository."
            ) from None
    try:
        run_git(["fetch", "--quiet", "--tags", "origin"], cwd=repo_root)
        run_git(["fetch", "--quiet", "origin", ref], cwd=repo_root)
    except SourceResolutionError:
        pass
    try:
        return resolve_commit(repo_root, ref)
    except SourceResolutionError as exc:
        raise DocsBuildError(f"Revision {ref!r} not found in {repo_root}") from exc


def _stamp(commit: str, settings: RenderedDocsConfig) -> dict[str, object]:
    return {"commit": commit, "settings": settings.model_dump(mode="json")}


def _read_stamp(path: Path, stamp: dict[str, object]) -> list[str] | None:
    """Modified files recorded by a previous matching build, or None when it does not match."""
    if not path.is_file():
        return None
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(recorded, dict):
        return None
    modified = recorded.pop("modified_files", [])
    if recorded != stamp or not isinstance(modified, list):
        return None
    return [str(m) for m in modified]


def _tail(path: Path, lines: int = _LOG_TAIL_LINES) -> str:
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
