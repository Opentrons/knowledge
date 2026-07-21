"""Deterministic stable identifier helpers."""

from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._/-]+")


def short_commit(commit: str, length: int = 12) -> str:
    """Return a stable short commit prefix."""
    return commit[:length]


def repo_slug(repository: str) -> str:
    """Normalize a repository URL or path into a slug."""
    value = repository.rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if "github.com/" in value:
        value = value.split("github.com/", 1)[1]
    return value.replace("/", "_")


def slugify(value: str, *, max_length: int = 120) -> str:
    """Create a filesystem/URL-safe slug."""
    cleaned = _SLUG_RE.sub("-", value.strip()).strip("-").lower()
    if len(cleaned) > max_length:
        digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:10]
        cleaned = f"{cleaned[: max_length - 11]}-{digest}"
    return cleaned or "empty"


def content_hash(payload: str | bytes) -> str:
    """SHA-256 hex digest of payload bytes."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def document_id(repository: str, commit: str, path: str) -> str:
    return f"doc:{repo_slug(repository)}:{short_commit(commit)}:{path}"


def section_id(document_id_value: str, heading_path: list[str]) -> str:
    path_slug = slugify("/".join(heading_path) or "root")
    return f"section:{document_id_value}:{path_slug}"


def symbol_id(qualified_name: str, release: str) -> str:
    release_key = release.lstrip("v")
    return f"symbol:{qualified_name}:{release_key}"


def entity_id(entity_type: str, canonical_name: str, scope: str) -> str:
    return f"entity:{entity_type}:{canonical_name}:{scope}"


def example_id(repository: str, commit: str, path: str, anchor: str) -> str:
    return f"example:{repo_slug(repository)}:{short_commit(commit)}:{path}:{slugify(anchor)}"


def relationship_id(relationship_type: str, source_id: str, target_id: str) -> str:
    return f"rel:{relationship_type}:{source_id}:{target_id}"


def constraint_id(constraint_type: str, subject_ids: list[str]) -> str:
    subjects = ",".join(sorted(subject_ids))
    digest = content_hash(subjects)[:16]
    return f"constraint:{constraint_type}:{digest}"


def source_file_id(source_key: str, path: str) -> str:
    return f"src:{source_key}:{path}"


def github_blob_url(
    repository: str,
    commit: str,
    path: str,
    *,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Build a commit-pinned GitHub blob URL with optional line range."""
    base = repository.rstrip("/")
    if base.endswith(".git"):
        base = base[:-4]
    if not base.startswith("http"):
        base = f"https://github.com/{base}"
    url = f"{base}/blob/{commit}/{path}"
    if line_start is not None:
        url += f"#L{line_start}"
        if line_end is not None and line_end != line_start:
            url += f"-L{line_end}"
    return url


def rendered_docs_url(source_path: str, *, anchor: str | None = None) -> str | None:
    """Map a docs source path to docs.opentrons.com when possible."""
    marker = "docs/python-api/docs/"
    if marker not in source_path:
        # Other mkdocs projects: docs/<site>/docs/<path>
        parts = source_path.split("/")
        if len(parts) >= 3 and parts[0] == "docs" and parts[2] == "docs":
            site = parts[1]
            rel = "/".join(parts[3:])
        else:
            return None
    else:
        site = "python-api"
        rel = source_path.split(marker, 1)[1]

    if rel.endswith(".md"):
        rel = rel[:-3]
    if rel.endswith("/index") or rel == "index":
        rel = rel[: -len("index")].rstrip("/")
    url = f"https://docs.opentrons.com/{site}/"
    if rel:
        url += f"{rel}/"
    if anchor:
        url += f"#{anchor}"
    return url
