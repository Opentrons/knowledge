"""Markdown documentation parsing into documents, sections, and examples."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from opentrons_knowledge.models.enums import AuthorityLevel
from opentrons_knowledge.models.records import Document, Example, Section, SourceFileRecord
from opentrons_knowledge.normalization.ids import (
    content_hash,
    document_id,
    example_id,
    github_blob_url,
    rendered_docs_url,
    section_id,
    source_file_id,
)

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
EXPLICIT_ANCHOR_RE = re.compile(r"\{?\s*#([A-Za-z0-9_.:-]+)\s*\}?\s*$")
CODE_FENCE_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}
SKIP_DIR_NAMES = {".venv", "site", "node_modules", "__pycache__", ".git", "img"}


@dataclass
class ParsedDocBundle:
    documents: list[Document] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)
    source_files: list[SourceFileRecord] = field(default_factory=list)


def discover_markdown_files(
    root: Path,
    *,
    relative_prefix: str,
    exclude_path_prefixes: list[str] | None = None,
) -> tuple[list[Path], list[SourceFileRecord]]:
    """Walk a tree and classify markdown vs excluded files."""
    exclude_path_prefixes = exclude_path_prefixes or []
    included: list[Path] = []
    records: list[SourceFileRecord] = []
    if not root.exists():
        return included, records

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        source_path = f"{relative_prefix.rstrip('/')}/{rel}" if relative_prefix else rel
        if path.is_dir():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            records.append(
                SourceFileRecord(
                    source_file_id=source_file_id("docs", source_path),
                    source_key="docs",
                    repository="",
                    commit="",
                    path=source_path,
                    status="excluded",
                    reason="build-or-cache-directory",
                )
            )
            continue
        if any(
            source_path.startswith(prefix.rstrip("/") + "/") or source_path == prefix.rstrip("/")
            for prefix in exclude_path_prefixes
        ):
            records.append(
                SourceFileRecord(
                    source_file_id=source_file_id("docs", source_path),
                    source_key="docs",
                    repository="",
                    commit="",
                    path=source_path,
                    status="excluded",
                    reason="manifest-exclude-paths",
                )
            )
            continue
        if path.suffix.lower() in IMAGE_EXTS:
            records.append(
                SourceFileRecord(
                    source_file_id=source_file_id("docs", source_path),
                    source_key="docs",
                    repository="",
                    commit="",
                    path=source_path,
                    status="excluded",
                    reason="image-asset",
                    byte_size=path.stat().st_size,
                )
            )
            continue
        if path.suffix.lower() not in {".md", ".markdown", ".rst"}:
            records.append(
                SourceFileRecord(
                    source_file_id=source_file_id("docs", source_path),
                    source_key="docs",
                    repository="",
                    commit="",
                    path=source_path,
                    status="excluded",
                    reason=f"unsupported-extension:{path.suffix or '<none>'}",
                    byte_size=path.stat().st_size,
                )
            )
            continue
        included.append(path)
    return included, records


def parse_markdown_document(
    path: Path,
    *,
    repository: str,
    commit: str,
    source_path: str,
    source_key: str,
    authority_level: AuthorityLevel,
    source_type: str,
) -> ParsedDocBundle:
    """Parse one Markdown file into document/section/example records."""
    text = path.read_text(encoding="utf-8")
    meta, body = _split_front_matter(text)
    title = str(meta.get("title") or _first_heading(body) or path.stem)
    doc_id = document_id(repository, commit, source_path)
    source_url = github_blob_url(repository, commit, source_path)
    rendered = rendered_docs_url(source_path)
    robot_types = _infer_robot_types(source_path, body)
    headings = [h for _, h in _iter_headings(body)]

    document = Document(
        document_id=doc_id,
        title=title,
        source_repository=repository,
        source_commit=commit,
        source_path=source_path,
        source_url=source_url,
        rendered_url=rendered,
        source_type=source_type,
        authority_level=authority_level,
        robot_types=robot_types,
        api_versions=[],
        content_hash=content_hash(body),
        document_format="markdown" if path.suffix.lower() != ".rst" else "rst",
        headings=headings,
        metadata={"front_matter": meta, "source_key": source_key},
    )

    sections = _build_sections(doc_id, body, source_url=source_url, rendered_base=rendered)
    examples = _extract_examples(
        body,
        repository=repository,
        commit=commit,
        source_path=source_path,
        robot_types=robot_types,
    )
    source_file = SourceFileRecord(
        source_file_id=source_file_id(source_key, source_path),
        source_key=source_key,
        repository=repository,
        commit=commit,
        path=source_path,
        status="included",
        content_hash=content_hash(text),
        byte_size=len(text.encode("utf-8")),
    )
    return ParsedDocBundle(
        documents=[document],
        sections=sections,
        examples=examples,
        source_files=[source_file],
    )


def ingest_docs_tree(
    materialize_root: Path,
    *,
    repository: str,
    commit: str,
    configured_paths: list[str],
    exclude_paths: list[str],
    source_key: str,
    authority_level: AuthorityLevel,
    source_type: str,
) -> ParsedDocBundle:
    """Ingest all markdown under materialized configured paths."""
    bundle = ParsedDocBundle()
    for configured in configured_paths:
        root = materialize_root / configured
        files, excluded = discover_markdown_files(
            root,
            relative_prefix=configured,
            exclude_path_prefixes=[
                p for p in exclude_paths if p.startswith(configured) or configured.startswith(p)
            ]
            or exclude_paths,
        )
        for record in excluded:
            record.repository = repository
            record.commit = commit
            record.source_key = source_key
            record.source_file_id = source_file_id(source_key, record.path)
            bundle.source_files.append(record)
        for path in files:
            rel = path.relative_to(materialize_root).as_posix()
            parsed = parse_markdown_document(
                path,
                repository=repository,
                commit=commit,
                source_path=rel,
                source_key=source_key,
                authority_level=authority_level,
                source_type=source_type,
            )
            bundle.documents.extend(parsed.documents)
            bundle.sections.extend(parsed.sections)
            bundle.examples.extend(parsed.examples)
            bundle.source_files.extend(parsed.source_files)
    return bundle


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    meta_raw = match.group(1)
    try:
        meta = yaml.safe_load(meta_raw) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[match.end() :]


def _first_heading(body: str) -> str | None:
    for _, title in _iter_headings(body):
        return title
    return None


def _iter_headings(body: str) -> list[tuple[int, str]]:
    results: list[tuple[int, str]] = []
    for match in HEADING_RE.finditer(body):
        level = len(match.group(1))
        title = EXPLICIT_ANCHOR_RE.sub("", match.group(2)).strip()
        results.append((level, title))
    return results


def _heading_anchor(raw_heading: str) -> str:
    explicit = EXPLICIT_ANCHOR_RE.search(raw_heading)
    if explicit:
        return explicit.group(1)
    cleaned = EXPLICIT_ANCHOR_RE.sub("", raw_heading).strip().lower()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    return re.sub(r"[-\s]+", "-", cleaned).strip("-")


def _build_sections(
    doc_id: str,
    body: str,
    *,
    source_url: str,
    rendered_base: str | None,
) -> list[Section]:
    matches = list(HEADING_RE.finditer(body))
    if not matches:
        sec_id = section_id(doc_id, ["root"])
        text = body.strip()
        return [
            Section(
                section_id=sec_id,
                document_id=doc_id,
                title="root",
                heading_path=["root"],
                content=text,
                content_markdown=text,
                content_plaintext=_to_plaintext(text),
                source_url=source_url,
                token_count=_estimate_tokens(text),
                content_hash=content_hash(text),
                metadata={"kind": "document-body"},
            )
        ]

    # Prefix before first heading
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        raw = match.group(2).strip()
        title = EXPLICIT_ANCHOR_RE.sub("", raw).strip()
        anchor = _heading_anchor(raw)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        heading_path = [item[1] for item in stack]
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        sec_id = section_id(doc_id, heading_path)
        rendered = f"{rendered_base}#{anchor}" if rendered_base else None
        sections.append(
            Section(
                section_id=sec_id,
                document_id=doc_id,
                title=title,
                heading_path=heading_path,
                content=content,
                content_markdown=content,
                content_plaintext=_to_plaintext(content),
                anchor=anchor,
                source_url=f"{source_url}#{anchor}" if anchor else source_url,
                token_count=_estimate_tokens(content),
                content_hash=content_hash(content),
                metadata={"rendered_url": rendered, "level": level},
            )
        )

    # Link neighbors / parents
    by_path = {tuple(sec.heading_path): sec for sec in sections}
    for i, sec in enumerate(sections):
        if i > 0:
            sec.previous_section_id = sections[i - 1].section_id
        if i + 1 < len(sections):
            sec.next_section_id = sections[i + 1].section_id
        if len(sec.heading_path) > 1:
            parent_path = tuple(sec.heading_path[:-1])
            parent = by_path.get(parent_path)
            if parent:
                sec.parent_section_id = parent.section_id
                parent.child_section_ids.append(sec.section_id)
    return sections


def _extract_examples(
    body: str,
    *,
    repository: str,
    commit: str,
    source_path: str,
    robot_types: list[str],
) -> list[Example]:
    examples: list[Example] = []
    for index, match in enumerate(CODE_FENCE_RE.finditer(body)):
        language = (match.group(1) or "text").lower()
        code = match.group(2).rstrip("\n")
        if (
            language not in {"python", "py"}
            and "protocol" not in code.lower()
            and language in {"text", "bash", "shell", "console", "json", "yaml", "yml"}
        ):
            continue
        anchor = f"code-{index + 1}"
        ex_id = example_id(repository, commit, source_path, anchor)
        examples.append(
            Example(
                example_id=ex_id,
                title=f"Example {index + 1} from {Path(source_path).name}",
                description="",
                code=code,
                language=language,
                source_path=source_path,
                source_url=github_blob_url(repository, commit, source_path),
                robot_types=robot_types,
                authority_level=AuthorityLevel.EXAMPLE,
                content_hash=content_hash(code),
            )
        )
    return examples


def _infer_robot_types(source_path: str, body: str) -> list[str]:
    robots: set[str] = set()
    lowered = source_path.lower()
    if "/flex/" in lowered or "flex" in lowered:
        robots.add("flex")
    if "/ot-2/" in lowered or "ot-2" in lowered or "ot2" in lowered:
        robots.add("ot-2")
    if '=== "Flex"' in body:
        robots.add("flex")
    if '=== "OT-2"' in body:
        robots.add("ot-2")
    return sorted(robots)


def _to_plaintext(markdown: str) -> str:
    text = CODE_FENCE_RE.sub(" ", markdown)
    text = re.sub(r"[#>*_`\[\]\(\)!]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _estimate_tokens(text: str) -> int:
    # Rough whitespace tokenizer for reporting only.
    return max(1, len(text.split())) if text.strip() else 0
