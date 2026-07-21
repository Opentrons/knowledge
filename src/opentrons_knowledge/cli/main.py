"""CLI entrypoint: opentrons-knowledge."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print as rprint
from rich.pretty import Pretty

from opentrons_knowledge.artifacts.archive import pack_corpus, unpack_corpus
from opentrons_knowledge.artifacts.package import inspect_corpus, validate_corpus_dir
from opentrons_knowledge.builder.pipeline import (
    build_corpus,
    build_fixture_corpus,
    load_source_manifest,
)
from opentrons_knowledge.consumer.corpus import Corpus, diff_corpora
from opentrons_knowledge.registry.oras import publish_corpus, pull_corpus

app = typer.Typer(
    name="opentrons-knowledge",
    help="Build, validate, and publish Opentrons Knowledge corpora.",
    no_args_is_help=True,
)


@app.command()
def build(
    manifest: Path | None = typer.Option(None, "--manifest", exists=True, dir_okay=False),
    output: Path = typer.Option(Path("dist"), "--output"),
    opentrons_repo: Path | None = typer.Option(None, "--opentrons-repo"),
    fixture: bool = typer.Option(False, "--fixture", help="Build CI fixture corpus"),
) -> None:
    """Build a corpus from a source manifest (or the CI fixture with --fixture)."""
    if fixture:
        fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "mini_sources"
        result = build_fixture_corpus(output, fixtures)
    else:
        if manifest is None:
            raise typer.BadParameter("--manifest is required unless --fixture is set")
        result = build_corpus(
            manifest,
            output_dir=output,
            opentrons_repo=opentrons_repo,
        )
    rprint(f"[green]Built[/green] {result.corpus_root}")
    rprint(Pretty(result.manifest.record_counts))


@app.command()
def validate(
    corpus: Path = typer.Option(..., "--corpus", exists=True, file_okay=False),
) -> None:
    """Validate corpus layout and checksums."""
    manifest = validate_corpus_dir(corpus)
    rprint(f"[green]Valid[/green] {manifest.human_identity}")


@app.command("inspect")
def inspect_cmd(
    corpus: Path = typer.Option(..., "--corpus", exists=True, file_okay=False),
) -> None:
    """Inspect corpus metadata and counts."""
    rprint(Pretty(inspect_corpus(corpus)))


@app.command()
def pack(
    corpus: Path = typer.Option(..., "--corpus", exists=True, file_okay=False),
    output: Path | None = typer.Option(None, "--output", help="Path for .tar.zst"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Pack a built corpus directory into a tar.zst artifact."""
    result = pack_corpus(corpus, output=output, overwrite=overwrite)
    rprint(f"[green]Packed[/green] {result['archive']}")
    rprint(Pretty(result))


@app.command()
def unpack(
    archive: Path = typer.Argument(..., exists=True, dir_okay=False),
    output: Path = typer.Option(Path("dist"), "--output"),
) -> None:
    """Unpack a tar.zst corpus archive into a directory."""
    # Default to dist/opentrons-knowledge-<stem without .tar.zst>
    name = archive.name.removesuffix(".tar.zst").removesuffix(".zst")
    destination = output / name if output.name != name else output
    root = unpack_corpus(archive, destination)
    rprint(f"[green]Unpacked[/green] {root}")


@app.command()
def publish(
    corpus: Path = typer.Option(..., "--corpus", exists=True, file_okay=False),
    registry: str = typer.Option(
        "ghcr.io/opentrons/opentrons-knowledge",
        "--registry",
    ),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Publish a corpus directory to an OCI registry via ORAS."""
    result = publish_corpus(corpus, registry_repo=registry, overwrite=overwrite)
    rprint(f"[green]Published[/green] {result['reference']}")
    rprint(Pretty(result))


@app.command()
def pull(
    version: str = typer.Argument(...),
    registry: str = typer.Option(
        "ghcr.io/opentrons/opentrons-knowledge",
        "--registry",
    ),
    output: Path = typer.Option(Path("dist"), "--output"),
) -> None:
    """Pull a corpus version from an OCI registry via ORAS."""
    root = pull_corpus(version, registry_repo=registry, destination=output)
    rprint(f"[green]Pulled[/green] {root}")


@app.command()
def verify(
    corpus: Path = typer.Option(..., "--corpus", exists=True, file_okay=False),
) -> None:
    """Verify a local corpus directory checksums."""
    manifest = Corpus.open(corpus).verify()
    rprint(f"[green]Verified[/green] {manifest.human_identity} digest={manifest.artifact_digest}")


@app.command()
def diff(
    left: str = typer.Argument(...),
    right: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Diff two corpus directories (paths or dist versions)."""
    left_path = _resolve_corpus_arg(left)
    right_path = _resolve_corpus_arg(right)
    result = diff_corpora(left_path, right_path)
    if json_out:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        rprint(Pretty(result))


@app.command()
def sources(
    corpus: Path = typer.Option(..., "--corpus", exists=True, file_okay=False),
) -> None:
    """Show resolved sources for a corpus directory."""
    opened = Corpus.open(corpus)
    rprint(Pretty(opened.sources()))


@app.command("validate-manifest")
def validate_manifest(
    manifest: Path = typer.Option(..., "--manifest", exists=True),
) -> None:
    """Validate a source manifest only."""
    loaded = load_source_manifest(manifest)
    rprint(f"[green]Manifest OK[/green] {loaded.corpus.version}")


def _resolve_corpus_arg(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    dist = Path("dist") / f"opentrons-knowledge-{value}"
    if dist.exists():
        return dist
    raise typer.BadParameter(f"Corpus not found: {value}")


if __name__ == "__main__":
    app()
