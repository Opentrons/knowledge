"""Discover rendered MkDocs pages and map them back to source Markdown.

The Opentrons site is a ``mkdocs-monorepo-plugin`` build: ``docs/mkdocs.yml``
includes one ``mkdocs.yml`` per publication, and each publication's pages are
served under its ``site_name``. Mapping reads those configs from the checkout
that was rendered; Knowledge does not keep its own copy.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

_INCLUDE_PREFIX = "!include "


class _TolerantLoader(yaml.SafeLoader):
    """SafeLoader for ``mkdocs.yml`` metadata.

    MkDocs-specific tags (``!!python/name``, ``!ENV``) load as None, and floats
    keep their literal text so version-like values such as ``apiLevel: 2.30``
    are not recorded as ``2.3``.
    """


def _ignore_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> None:
    return None


def _literal_float(loader: yaml.SafeLoader, node: yaml.Node) -> str:
    return str(node.value)


_TolerantLoader.add_multi_constructor("tag:yaml.org,2002:python/", _ignore_tag)  # type: ignore[no-untyped-call]
_TolerantLoader.add_multi_constructor("!", _ignore_tag)  # type: ignore[no-untyped-call]
_TolerantLoader.add_constructor("tag:yaml.org,2002:float", _literal_float)


def load_mkdocs_config(path: Path) -> dict[str, Any]:
    """Load an ``mkdocs.yml`` without executing or resolving custom tags."""
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_TolerantLoader)
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class MkDocsProject:
    """One publication in the monorepo build.

    Attributes:
        name: Publication ``site_name`` (``None`` for the root project).
        url_prefix: Site-relative prefix of its pages (``""`` for the root).
        docs_dir: Repository-relative directory holding its Markdown sources.
    """

    name: str | None
    url_prefix: str
    docs_dir: str


@dataclass(frozen=True)
class SitePage:
    html_path: str
    page_path: str


@dataclass(frozen=True)
class SiteLayout:
    """Projects and config metadata used to map rendered pages to sources."""

    projects: tuple[MkDocsProject, ...]
    site_url: str | None
    site_name: str | None
    extra: dict[str, Any]

    def project_for(self, site_path: str) -> MkDocsProject | None:
        """Return the most specific project whose URL prefix matches ``site_path``."""
        best: MkDocsProject | None = None
        for project in self.projects:
            if site_path.startswith(project.url_prefix) and (
                best is None or len(project.url_prefix) > len(best.url_prefix)
            ):
                best = project
        return best

    def source_markdown(self, page_path: str, checkout: Path) -> str | None:
        """Repository-relative Markdown path that rendered ``page_path``, if found."""
        project = self.project_for(page_path)
        if project is None:
            return None
        rel = page_path[len(project.url_prefix) :]
        if rel.endswith(".html"):
            candidates = [rel.removesuffix(".html") + ".md"]
        else:
            stem = rel.rstrip("/")
            candidates = (
                [f"{stem}.md", f"{stem}/index.md", f"{stem}/README.md"]
                if stem
                else ["index.md", "README.md"]
            )
        for candidate in candidates:
            repo_path = f"{project.docs_dir}/{candidate}"
            if (checkout / repo_path).is_file():
                return repo_path
        return None

    def source_asset(self, site_path: str, checkout: Path) -> str | None:
        """Repository-relative path of a static asset (image) served at ``site_path``."""
        project = self.project_for(site_path)
        if project is None:
            return None
        repo_path = f"{project.docs_dir}/{site_path[len(project.url_prefix) :]}"
        return repo_path if (checkout / repo_path).is_file() else None


def load_site_layout(checkout: Path, mkdocs_config: str) -> SiteLayout:
    """Read the root MkDocs config and every ``!include``-d publication config.

    Args:
        checkout: Repository root that was rendered.
        mkdocs_config: Repository-relative path of the root ``mkdocs.yml``.

    Returns:
        The project layout. Missing configs yield an empty layout (no source mapping).
    """
    root_path = checkout / mkdocs_config
    if not root_path.is_file():
        return SiteLayout(projects=(), site_url=None, site_name=None, extra={})
    root_cfg = load_mkdocs_config(root_path)
    config_dir = PurePosixPath(mkdocs_config).parent
    projects = [
        MkDocsProject(
            name=None,
            url_prefix="",
            docs_dir=_join(config_dir, str(root_cfg.get("docs_dir") or "docs")),
        )
    ]
    for include in sorted(set(_iter_includes(root_cfg.get("nav")))):
        include_path = config_dir / include
        cfg_file = checkout / include_path
        if not cfg_file.is_file():
            continue
        cfg = load_mkdocs_config(cfg_file)
        name = str(cfg.get("site_name") or include_path.parent.name)
        projects.append(
            MkDocsProject(
                name=name,
                url_prefix=f"{name}/",
                docs_dir=_join(include_path.parent, str(cfg.get("docs_dir") or "docs")),
            )
        )
    extra = root_cfg.get("extra")
    return SiteLayout(
        projects=tuple(projects),
        site_url=root_cfg.get("site_url"),
        site_name=root_cfg.get("site_name"),
        extra=dict(extra) if isinstance(extra, dict) else {},
    )


def discover_pages(site_dir: Path) -> list[SitePage]:
    """List rendered HTML pages in deterministic order (theme assets excluded)."""
    pages: list[SitePage] = []
    for path in sorted(site_dir.rglob("*.html")):
        rel = path.relative_to(site_dir).as_posix()
        if rel.startswith(("assets/", "search/")):
            continue
        pages.append(SitePage(html_path=rel, page_path=page_path_for(rel)))
    return pages


def page_path_for(html_path: str) -> str:
    """Site-relative page URL path for an HTML file (directory URLs keep a trailing slash)."""
    if html_path == "index.html":
        return ""
    if html_path.endswith("/index.html"):
        return html_path.removesuffix("index.html")
    return html_path


def _iter_includes(nav: Any) -> list[str]:
    found: list[str] = []
    if isinstance(nav, str):
        if nav.startswith(_INCLUDE_PREFIX):
            found.append(nav[len(_INCLUDE_PREFIX) :].strip())
    elif isinstance(nav, list):
        for item in nav:
            found.extend(_iter_includes(item))
    elif isinstance(nav, dict):
        for value in nav.values():
            found.extend(_iter_includes(value))
    return found


def _join(base: PurePosixPath, rel: str) -> str:
    return posixpath.normpath((base / rel).as_posix())
