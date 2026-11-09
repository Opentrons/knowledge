"""Recover icon shortcodes (``:material-check:``) from inline SVGs.

``pymdownx.emoji`` with Material's ``to_svg`` generator inlines icon SVGs and
drops the shortcode name, yet icons such as check marks carry meaning in
compatibility tables. The SVG path data is identical to the icon file it came
from, so a reverse index over the icon sets used by the build recovers the name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentrons_knowledge.docs.site_pages import load_mkdocs_config

_PATH_D_RE = re.compile(r"<path\b[^>]*?\sd=\"([^\"]*)\"", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

IconKey = tuple[str, ...]


def icon_key(path_data: Iterable[str]) -> IconKey:
    """Normalized identity of an SVG: its ordered path ``d`` attributes."""
    return tuple(_WS_RE.sub(" ", d).strip() for d in path_data if d.strip())


@dataclass
class IconIndex:
    """Map from SVG path data to the shortcode that produced it."""

    shortcodes: dict[IconKey, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.shortcodes)

    def lookup(self, key: IconKey) -> str | None:
        return self.shortcodes.get(key) if key else None

    def add_icon_set(self, root: Path) -> None:
        """Index ``root/<set>/.../<name>.svg`` as ``:<set>-...-<name>:``.

        When several icons share path data, the lexicographically smallest
        shortcode wins so results do not depend on filesystem order.
        """
        if not root.is_dir():
            return
        for svg in sorted(root.rglob("*.svg")):
            rel = svg.relative_to(root).with_suffix("")
            if len(rel.parts) < 2:
                continue
            key = icon_key(_PATH_D_RE.findall(svg.read_text(encoding="utf-8", errors="replace")))
            if not key:
                continue
            shortcode = f":{'-'.join(rel.parts)}:"
            current = self.shortcodes.get(key)
            if current is None or shortcode < current:
                self.shortcodes[key] = shortcode


def load_icon_index(checkout: Path, mkdocs_config: str) -> IconIndex:
    """Build the icon index from the docs build environment and custom icon dirs.

    Args:
        checkout: Rendered repository root.
        mkdocs_config: Repository-relative root ``mkdocs.yml``.

    Returns:
        An index (possibly empty when the docs virtualenv is not present).
    """
    index = IconIndex()
    config_path = checkout / mkdocs_config
    project_dir = config_path.parent
    for site_packages in sorted(project_dir.glob(".venv/lib/python*/site-packages")):
        index.add_icon_set(site_packages / "material" / "templates" / ".icons")
    if config_path.is_file():
        for custom in _custom_icon_dirs(load_mkdocs_config(config_path)):
            index.add_icon_set(project_dir / custom)
    return index


def _custom_icon_dirs(config: dict[str, Any]) -> list[str]:
    dirs: list[str] = []
    for ext in config.get("markdown_extensions") or []:
        if not isinstance(ext, dict):
            continue
        emoji = ext.get("pymdownx.emoji")
        if not isinstance(emoji, dict):
            continue
        options = emoji.get("options")
        if isinstance(options, dict):
            dirs.extend(str(d) for d in options.get("custom_icons") or [])
    return dirs
