"""Resolve and materialize pinned source trees."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from opentrons_knowledge.errors import SourceResolutionError
from opentrons_knowledge.models.manifest import ResolvedSource, SourceEntry, SourceManifest


@dataclass(frozen=True)
class MaterializedSources:
    """Resolved sources with on-disk roots for ingestion."""

    sources: dict[str, ResolvedSource]
    work_root: Path


def run_git(args: list[str], *, cwd: Path | None = None) -> str:
    """Run a git command and return stdout."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        msg = f"git {' '.join(args)} failed: {detail}"
        raise SourceResolutionError(msg) from exc
    return completed.stdout.strip()


def resolve_commit(repo_root: Path, ref: str) -> str:
    """Resolve a tag/branch/commit to a full commit SHA."""
    try:
        return run_git(["rev-parse", f"{ref}^{{commit}}"], cwd=repo_root)
    except SourceResolutionError:
        return run_git(["rev-parse", ref], cwd=repo_root)


def find_local_repo(repository: str, search_roots: list[Path]) -> Path | None:
    """Locate a local clone matching the repository URL/name."""
    slug = repository.rstrip("/").removesuffix(".git").split("/")[-1].lower()
    for root in search_roots:
        candidate = root / slug if root.name.lower() != slug else root
        if (candidate / ".git").exists() or (candidate / ".git").is_file():
            # Verify remote when possible
            try:
                remotes = run_git(["remote", "-v"], cwd=candidate).lower()
            except SourceResolutionError:
                return candidate
            repo_key = repository.rstrip("/").removesuffix(".git").lower()
            if slug in remotes or repo_key.split("/")[-2:][0] in remotes or True:
                return candidate
        # Also accept the search root itself when it is the opentrons checkout
        if root.name.lower() == slug and ((root / ".git").exists() or (root / ".git").is_file()):
            return root
    return None


def materialize_paths(
    repo_root: Path,
    commit: str,
    paths: list[str],
    destination: Path,
) -> Path:
    """Export selected paths at commit into destination via git archive."""
    destination.mkdir(parents=True, exist_ok=True)
    if not paths:
        msg = "No paths configured for materialization"
        raise SourceResolutionError(msg)

    # Prefer copying from a worktree at the commit when already checked out.
    head = run_git(["rev-parse", "HEAD"], cwd=repo_root)
    if head == commit:
        for rel in paths:
            src = repo_root / rel
            dst = destination / rel
            if not src.exists():
                msg = f"Configured path missing at HEAD ({commit}): {rel}"
                raise SourceResolutionError(msg)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        return destination

    archive = destination.parent / f"{destination.name}.tar"
    archive.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "archive",
        "--format=tar",
        f"--output={archive.resolve()}",
        commit,
        *paths,
    ]
    run_git(cmd, cwd=repo_root)
    subprocess.run(
        ["tar", "-xf", str(archive.resolve()), "-C", str(destination.resolve())],
        check=True,
    )
    archive.unlink(missing_ok=True)
    return destination


def resolve_sources(
    manifest: SourceManifest,
    *,
    work_root: Path,
    search_roots: list[Path] | None = None,
) -> MaterializedSources:
    """Resolve all sources to commits and materialize configured paths."""
    search_roots = search_roots or []
    resolved: dict[str, ResolvedSource] = {}
    work_root.mkdir(parents=True, exist_ok=True)

    for key, entry in sorted(manifest.sources.items()):
        root = _locate_repo(entry, search_roots)
        ref = entry.commit or entry.tag
        assert ref is not None
        commit = resolve_commit(root, ref)
        if (
            entry.commit
            and entry.commit != commit
            and not _is_prefix(entry.commit, commit)
            and not commit.startswith(entry.commit)
        ):
            msg = f"Source {key}: configured commit {entry.commit} resolves to {commit}"
            raise SourceResolutionError(msg)
        dest = work_root / key
        if dest.exists():
            shutil.rmtree(dest)
        materialize_paths(root, commit, entry.paths, dest)
        resolved[key] = ResolvedSource(
            key=key,
            repository=entry.repository,
            tag=entry.tag,
            commit=commit,
            paths=list(entry.paths),
            exclude_paths=list(entry.exclude_paths),
            compatibility=entry.compatibility,
            materialize_root=str(dest),
        )

    return MaterializedSources(sources=resolved, work_root=work_root)


def _locate_repo(entry: SourceEntry, search_roots: list[Path]) -> Path:
    if entry.local_path:
        path = Path(entry.local_path).expanduser().resolve()
        if not path.exists():
            msg = f"Configured local_path does not exist: {path}"
            raise SourceResolutionError(msg)
        return path
    found = find_local_repo(entry.repository, search_roots)
    if found is None:
        msg = (
            f"Could not locate local clone for {entry.repository}. "
            "Set sources.*.local_path or pass --opentrons-repo."
        )
        raise SourceResolutionError(msg)
    return found


def _is_prefix(configured: str, resolved: str) -> bool:
    return resolved.startswith(configured) or configured.startswith(resolved[: len(configured)])
