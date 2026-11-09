"""``opentrons-knowledge docs``: render MkDocs and build the canonical document corpus."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import typer
from rich import print as rprint
from rich.pretty import Pretty

from opentrons_knowledge.builder.pipeline import load_source_manifest
from opentrons_knowledge.docs.canonical import (
    build_canonical_corpus,
    find_document,
    iter_blocks,
    load_canonical_documents,
    validate_canonical_corpus,
)
from opentrons_knowledge.docs.mkdocs_build import RenderedSite, build_site, prebuilt_site
from opentrons_knowledge.errors import KnowledgeError
from opentrons_knowledge.models.manifest import RenderedDocsConfig, SourceEntry, SourceManifest

DEFAULT_REPOSITORY = "https://github.com/Opentrons/opentrons"

docs_app = typer.Typer(
    help="Render the Opentrons MkDocs site and build the canonical document corpus.",
    no_args_is_help=True,
)

_MANIFEST = typer.Option(
    None,
    "--manifest",
    exists=True,
    dir_okay=False,
    help="Source manifest; the rendered_docs source (default opentrons_docs) pins the revision.",
)
_REF = typer.Option(None, "--ref", help="Tag, branch, or commit to render (overrides --manifest).")
_REPOSITORY = typer.Option(None, "--repository", help="Repository URL to clone or record.")
_LOCAL = typer.Option(
    None, "--opentrons-repo", help="Existing local Opentrons clone to read objects from."
)
_IN_PLACE = typer.Option(
    False, "--in-place", help="Build in --opentrons-repo's working tree at its HEAD."
)
_WORK = typer.Option(Path("dist/.work"), "--work", help="Scratch directory for checkouts.")
_REBUILD = typer.Option(False, "--rebuild", help="Ignore a cached build for the same commit.")


@docs_app.command("build-site")
def build_site_cmd(
    manifest: Path | None = _MANIFEST,
    ref: str | None = _REF,
    repository: str | None = _REPOSITORY,
    opentrons_repo: Path | None = _LOCAL,
    in_place: bool = _IN_PLACE,
    work: Path = _WORK,
    rebuild: bool = _REBUILD,
) -> None:
    """Render the MkDocs site for a pinned revision and print where it is."""
    site = _render(manifest, ref, repository, opentrons_repo, in_place, work, rebuild)
    rprint(f"[green]Rendered[/green] {site.commit} -> {site.site_dir}")


@docs_app.command("build")
def build_cmd(
    output: Path = typer.Option(Path("dist/canonical-docs"), "--output"),
    site_dir: Path | None = typer.Option(
        None,
        "--site",
        file_okay=False,
        help="Extract an already-rendered site instead of building (needs --opentrons-repo).",
    ),
    manifest: Path | None = _MANIFEST,
    ref: str | None = _REF,
    repository: str | None = _REPOSITORY,
    opentrons_repo: Path | None = _LOCAL,
    in_place: bool = _IN_PLACE,
    work: Path = _WORK,
    rebuild: bool = _REBUILD,
) -> None:
    """Render (or reuse) the site and write the canonical corpus to --output."""
    if site_dir is not None:
        if opentrons_repo is None:
            raise typer.BadParameter("--site requires --opentrons-repo for source mapping")
        settings, repo_url, _ = _settings(manifest, repository)
        site = _guard(
            lambda: prebuilt_site(
                site_dir=site_dir,
                checkout=opentrons_repo,
                repository=repo_url,
                settings=settings,
                ref=ref,
            )
        )
    else:
        site = _render(manifest, ref, repository, opentrons_repo, in_place, work, rebuild)
    result = _guard(lambda: build_canonical_corpus(site, output))
    rprint(f"[green]Built[/green] canonical corpus {output}")
    rprint(
        Pretty(
            {
                "commit": result.source.commit,
                "documents": result.document_count,
                "sections": result.section_count,
                "blocks": result.block_counts,
                "excluded_pages": [p.html_path for p in result.excluded_pages],
            }
        )
    )


@docs_app.command("validate")
def validate_cmd(
    corpus: Path = typer.Option(..., "--corpus", exists=True, file_okay=False),
) -> None:
    """Validate checksums, schema, IDs, and content hashes of a canonical corpus."""
    result = _guard(lambda: validate_canonical_corpus(corpus))
    rprint(
        f"[green]Valid[/green] {result.document_count} documents, "
        f"{result.section_count} sections @ {result.source.commit[:12]}"
    )


@docs_app.command("inspect")
def inspect_cmd(
    corpus: Path = typer.Option(..., "--corpus", exists=True, file_okay=False),
    document: str | None = typer.Option(
        None, "--document", help="Document ID, page path, URL, or Markdown path to print."
    ),
    json_out: bool = typer.Option(False, "--json", help="Print the full JSON record."),
) -> None:
    """Summarize a canonical corpus, or print one document."""
    manifest = _guard(lambda: validate_canonical_corpus(corpus))
    if document is None:
        rprint(
            Pretty(
                {
                    "source": manifest.source.model_dump(),
                    "documents": manifest.document_count,
                    "sections": manifest.section_count,
                    "blocks": manifest.block_counts,
                    "excluded_pages": [p.model_dump() for p in manifest.excluded_pages],
                }
            )
        )
        return
    found = find_document(load_canonical_documents(corpus), document)
    if found is None:
        raise typer.BadParameter(f"No document matches {document!r}")
    if json_out:
        typer.echo(json.dumps(found.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return
    rprint(f"[bold]{found.title}[/bold]  {found.url}")
    rprint(f"source: {found.source.markdown_path}  id: {found.document_id}")
    for section in found.sections:
        counts = Counter(b.type for b in iter_blocks(section.blocks))
        indent = "  " * max(section.level - 1, 0)
        rprint(f"{indent}- {section.title}  [dim]{dict(sorted(counts.items()))}[/dim]")


def _render(
    manifest: Path | None,
    ref: str | None,
    repository: str | None,
    opentrons_repo: Path | None,
    in_place: bool,
    work: Path,
    rebuild: bool,
) -> RenderedSite:
    settings, repo_url, pin = _settings(manifest, repository)
    revision = ref or (pin.tag or pin.commit if pin else None)
    if not revision and not in_place:
        raise typer.BadParameter("Pass --ref or --manifest to choose the docs revision")
    site = _guard(
        lambda: build_site(
            repository=repo_url,
            ref=revision,
            settings=settings,
            work_root=work,
            local_repo=opentrons_repo,
            in_place=in_place,
            rebuild=rebuild,
        )
    )
    if ref is None and pin and pin.commit and not site.commit.startswith(pin.commit):
        rprint(
            f"[red]Error:[/red] {revision} resolved to {site.commit}, manifest pins {pin.commit}"
        )
        raise typer.Exit(1)
    return site


def _settings(
    manifest: Path | None, repository: str | None
) -> tuple[RenderedDocsConfig, str, SourceEntry | None]:
    if manifest is None:
        return RenderedDocsConfig(), repository or DEFAULT_REPOSITORY, None
    loaded: SourceManifest = load_source_manifest(manifest)
    settings = loaded.rendered_docs or RenderedDocsConfig()
    entry = loaded.sources[settings.source]
    return settings, repository or entry.repository, entry


def _guard[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except KnowledgeError as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
