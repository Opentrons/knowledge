"""``opentrons-knowledge retrieval``: build, evaluate, validate, and search retrieval bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from opentrons_knowledge.models.manifest import RetrievalSettings
from opentrons_knowledge.normalization.serialize import read_jsonl_zst, write_json
from opentrons_knowledge.retrieval.audit import audit_api
from opentrons_knowledge.retrieval.bm25 import search, search_api
from opentrons_knowledge.retrieval.build import build_retrieval
from opentrons_knowledge.retrieval.bundle import API_INDEX, DOCS_INDEX, open_index, validate_bundle
from opentrons_knowledge.retrieval.documents import build_retrieval_documents, load_retrieval_inputs
from opentrons_knowledge.retrieval.evaluation import load_queries, report_markdown, run_experiments
from opentrons_knowledge.retrieval.fusion import fused_search
from opentrons_knowledge.retrieval.models import (
    Chunk,
    ChunkingStrategy,
    Enrichment,
    RetrievalDocument,
    RetrievalKind,
)
from opentrons_knowledge.retrieval.passages import Passage, passages_for_hits

# Longest section in the 10.0.0-k3 docs index is 6 chunks. Fetching this many
# chunks per requested hit keeps `limit` as a count of sections after siblings
# of one section collapse into a single passage.
_CHUNKS_PER_SECTION = 8

_console = Console()

retrieval_app = typer.Typer(
    help="Build, evaluate, validate, and search the retrieval bundle.", no_args_is_help=True
)

_CORPUS = typer.Option(
    ..., "--corpus", exists=True, file_okay=False, help="Unpacked corpus directory."
)
_CANONICAL = typer.Option(
    None,
    "--canonical",
    exists=True,
    file_okay=False,
    help="Canonical docs directory (default <corpus>/canonical).",
)
_QUERIES = typer.Option(
    Path("eval/retrieval/curated.yaml"), "--queries", exists=True, dir_okay=False
)
_BUNDLE = typer.Option(..., "--bundle", exists=True, file_okay=False, help="Retrieval bundle.")


@retrieval_app.command("experiment")
def experiment_cmd(
    corpus: Path = _CORPUS,
    canonical: Path | None = _CANONICAL,
    queries: Path = _QUERIES,
    report: Path = typer.Option(Path("dist/retrieval-eval.json"), "--report"),
    markdown: Path | None = typer.Option(None, "--markdown", help="Also write Markdown tables."),
) -> None:
    """Run the full experiment grid and write the report."""
    documents = build_retrieval_documents(load_retrieval_inputs(corpus, canonical))
    result, winner = run_experiments(documents, load_queries(queries))
    write_json(report, result)
    if markdown is not None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(report_markdown(result), encoding="utf-8")
    rprint(f"[green]Winner[/green] {winner.name}")
    for note in result["selection"]:
        rprint(f"  {note}")


@retrieval_app.command("build")
def build_cmd(
    corpus: Path = _CORPUS,
    canonical: Path | None = _CANONICAL,
    output: Path = typer.Option(..., "--output", help="Bundle directory to write."),
    queries: Path | None = typer.Option(None, "--queries", exists=True, dir_okay=False),
    kinds: list[RetrievalKind] | None = typer.Option(None, "--kind"),
    chunking: ChunkingStrategy | None = typer.Option(None, "--chunking"),
    enrichment: Enrichment | None = typer.Option(None, "--enrichment"),
) -> None:
    """Build a retrieval bundle from an existing corpus (defaults to the shipped config)."""
    defaults = RetrievalSettings()
    settings = defaults.model_copy(
        update={
            "kinds": kinds or defaults.kinds,
            "chunking": chunking or defaults.chunking,
            "enrichment": enrichment or defaults.enrichment,
        }
    )
    manifest_path = corpus / "manifest.yaml"
    version = _corpus_version(manifest_path) if manifest_path.exists() else corpus.name
    result = build_retrieval(
        load_retrieval_inputs(corpus, canonical),
        output,
        settings.config(),
        corpus_version=version,
        queries_path=queries,
    )
    manifest = result.manifest
    rprint(f"[green]Built[/green] {output}")
    rprint(
        Pretty(
            {
                "config": manifest.config.name,
                "documents": manifest.document_count,
                "chunks": manifest.chunk_count,
                "kinds": manifest.kind_counts,
                "evaluation": manifest.evaluation and manifest.evaluation["metrics"],
            }
        )
    )


@retrieval_app.command("validate")
def validate_cmd(bundle: Path = _BUNDLE) -> None:
    """Check digests, unique ids, and that the BM25 index opens and answers."""
    problems = validate_bundle(bundle)
    if problems:
        for problem in problems:
            rprint(f"[red]Error:[/red] {problem}")
        raise typer.Exit(1)
    rprint(f"[green]Valid[/green] {bundle}")


@retrieval_app.command("search")
def search_cmd(
    query: str = typer.Argument(...),
    bundle: Path = _BUNDLE,
    index: str = typer.Option(
        "all", "--index", help="api, docs, or all (one ranked list from both)."
    ),
    limit: int = typer.Option(5, "--limit", "-k"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Search a bundle and show the passages that would be returned."""
    which = _index_choice(index)
    loaded = _load(bundle)
    hits = _search(loaded, query, which, limit)
    if json_out:
        typer.echo(json.dumps([hit.as_json() for hit in hits], indent=2, ensure_ascii=False))
        return
    _render(query, hits, which)


@retrieval_app.command("explore")
def explore_cmd(
    bundle: Path = _BUNDLE,
    index: str = typer.Option(
        "all", "--index", help="api, docs, or all (one ranked list from both)."
    ),
    limit: int = typer.Option(5, "--limit", "-k"),
) -> None:
    """Interactive search. Type a query, or /api, /docs, /all, /k N, /open N, /quit."""
    which = _index_choice(index)
    loaded = _load(bundle)
    counts = json.loads((bundle / "manifest.json").read_text(encoding="utf-8")).get(
        "index_counts", {}
    )
    last: list[_Hit] = []
    while True:
        _print_instructions(counts, which, limit)
        try:
            line = Prompt.ask(f"[cyan]{which}[/cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            _console.print()
            return
        if not line:
            continue
        if line in {"/quit", "/q", "quit", "exit"}:
            return
        if line == "/api":
            which = "api"
        elif line == "/docs":
            which = "docs"
        elif line == "/all":
            which = "all"
        elif line.startswith("/k"):
            parsed = _parse_limit(line)
            if parsed is not None:
                limit = parsed
        elif line.startswith("/open"):
            _open_hit(last, line)
        else:
            last = _search(loaded, line, which, limit)
            _render(line, last, which)


@retrieval_app.command("audit")
def audit_cmd(
    bundle: Path = _BUNDLE,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Look up every documented symbol and report whether its section comes back first."""
    documents = [
        RetrievalDocument.model_validate(row)
        for row in read_jsonl_zst(bundle / "documents.jsonl.zst")
    ]
    chunks = [Chunk.model_validate(row) for row in read_jsonl_zst(bundle / "chunks.jsonl.zst")]
    api_chunks = [chunk for chunk in chunks if _doc_name(documents, chunk.retrieval_id)]
    report = audit_api(open_index(bundle, API_INDEX), documents, api_chunks)
    summary: dict[str, Any] = {
        "symbols": report.total,
        "hit_at_1": round(report.hit_rate(1), 4),
        "hit_at_5": round(report.hit_rate(5), 4),
        "misses": [
            {"api_name": miss.api_name, "query": miss.query, "rank": miss.rank}
            for miss in report.misses
        ],
    }
    if json_out:
        typer.echo(json.dumps(summary, indent=2))
    else:
        _console.print(
            f"[bold]{summary['symbols']}[/bold] symbols. "
            f"Rank 1: [bold]{summary['hit_at_1']:.1%}[/bold]. "
            f"In the top 5: [bold]{summary['hit_at_5']:.1%}[/bold]."
        )
        for miss in summary["misses"]:
            rank = "miss" if miss["rank"] is None else f"rank {miss['rank']}"
            _console.print(f"  [red]{rank}[/red]  {miss['query']}  [dim]{miss['api_name']}[/dim]")
    if summary["misses"]:
        raise typer.Exit(1)


def _corpus_version(manifest_path: Path) -> str:
    from opentrons_knowledge.normalization.serialize import load_yaml

    return str(load_yaml(manifest_path)["version"])


@dataclass
class _Hit:
    index: str
    score: float
    chunk_id: str
    retrieval_id: str
    title: str
    heading: str
    url: str | None
    api_name: str | None
    doc_type: str
    text: str

    def as_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "score": round(self.score, 3),
            "chunk_id": self.chunk_id,
            "retrieval_id": self.retrieval_id,
            "title": self.title,
            "heading": self.heading,
            "url": self.url,
            "api_name": self.api_name,
            "doc_type": self.doc_type,
            "text": self.text,
        }


@dataclass
class _Bundle:
    chunks: dict[str, dict[str, Any]]
    documents: dict[str, dict[str, Any]]
    api: Any
    docs: Any


def _load(bundle: Path) -> _Bundle:
    return _Bundle(
        chunks={row["chunk_id"]: row for row in read_jsonl_zst(bundle / "chunks.jsonl.zst")},
        documents={
            row["retrieval_id"]: row for row in read_jsonl_zst(bundle / "documents.jsonl.zst")
        },
        api=open_index(bundle, API_INDEX),
        docs=open_index(bundle, DOCS_INDEX),
    )


def _search(
    loaded: _Bundle, query: str, which: Literal["api", "docs", "all"], limit: int
) -> list[_Hit]:
    fetch = limit * _CHUNKS_PER_SECTION
    if which == "all":
        fused = fused_search(
            query, loaded.api, loaded.docs, loaded.chunks, limit=limit, fetch=fetch
        )
        return [_to_hit(loaded, item.index, item.passage) for item in fused]
    if which == "api":
        found = search_api(loaded.api, query, fetch)
    else:
        found = search(loaded.docs, query, fetch)
    passages = passages_for_hits(found, loaded.chunks, limit=limit)
    return [_to_hit(loaded, which, passage) for passage in passages]


def _to_hit(loaded: _Bundle, index: str, passage: Passage) -> _Hit:
    doc = loaded.documents[passage.retrieval_id]
    return _Hit(
        index=index,
        score=passage.score,
        chunk_id=passage.chunk_id,
        retrieval_id=doc["retrieval_id"],
        title=doc["title"],
        heading=" > ".join(doc.get("heading_path") or []),
        url=doc.get("url") or doc.get("source_url"),
        api_name=doc.get("api_name"),
        doc_type=doc.get("doc_type") or "",
        text=passage.text,
    )


def _render(query: str, hits: list[_Hit], which: str) -> None:
    if not hits:
        _console.print(f"[yellow]No hits[/yellow] for [bold]{query}[/bold] in {which}.")
        return
    table = Table(title=f"{query}  ({which})", show_lines=False, expand=True)
    table.add_column("#", justify="right", style="bold", width=3)
    table.add_column("index", width=5)
    table.add_column("score", justify="right", width=7)
    table.add_column("result")
    for number, hit in enumerate(hits, start=1):
        label = hit.api_name or hit.heading or hit.title
        table.add_row(str(number), hit.index, f"{hit.score:.2f}", label)
    _console.print(table)
    for number, hit in enumerate(hits, start=1):
        _console.print(_panel(number, hit, preview=True))


def _panel(number: int, hit: _Hit, *, preview: bool) -> Panel:
    body = Text()
    if hit.heading:
        body.append(hit.heading + "\n", style="dim")
    body.append(hit.retrieval_id + "\n", style="cyan")
    if hit.url:
        body.append(hit.url + "\n", style="dim underline")
    snippet = hit.text if not preview else _snippet(hit.text)
    body.append("\n" + snippet)
    title = f"{number}  {hit.index}  {hit.score:.2f}  {hit.title}"
    return Panel(body, title=title, border_style="green" if hit.index == "api" else "blue")


def _snippet(text: str, lines: int = 12) -> str:
    kept = text.splitlines()[:lines]
    clipped = "\n".join(kept)
    if len(kept) < len(text.splitlines()):
        clipped += "\n..."
    return clipped


def _open_hit(hits: list[_Hit], line: str) -> None:
    parts = line.split()
    if len(parts) != 2 or not parts[1].isdigit() or not (1 <= int(parts[1]) <= len(hits)):
        _console.print("[yellow]Usage: /open N[/yellow], where N is a result from the last query.")
        return
    _console.print(_panel(int(parts[1]), hits[int(parts[1]) - 1], preview=False))


def _print_instructions(counts: dict[str, Any], which: str, limit: int) -> None:
    """Reprint the command list so it stays on screen after each result."""
    _console.print(
        Panel(
            "\n".join(
                [
                    f"[bold]api[/bold]  {counts.get('api', 0)} symbol sections. "
                    "Query with [bold]Class.method[/bold], for example InstrumentContext.blow_out.",
                    f"[bold]docs[/bold]  {counts.get('docs', 0)} passages, including labware, "
                    "pipettes, and modules. Query with the words a heading would use.",
                    "Commands: [bold]/api[/bold]  [bold]/docs[/bold]  [bold]/all[/bold]  "
                    "[bold]/k N[/bold]  [bold]/open N[/bold]  [bold]/quit[/bold]",
                    f"Now: [bold]{which}[/bold], showing [bold]{limit}[/bold] hits.",
                ]
            ),
            title="Retrieval search",
            border_style="cyan",
        )
    )


def _index_choice(value: str) -> Literal["api", "docs", "all"]:
    choices: dict[str, Literal["api", "docs", "all"]] = {
        "api": "api",
        "docs": "docs",
        "all": "all",
    }
    try:
        return choices[value]
    except KeyError:
        raise typer.BadParameter("--index must be api, docs, or all") from None


def _parse_limit(line: str) -> int | None:
    parts = line.split()
    if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
        return int(parts[1])
    _console.print("[yellow]Usage: /k N[/yellow]")
    return None


def _doc_name(documents: list[RetrievalDocument], retrieval_id: str) -> str | None:
    for doc in documents:
        if doc.retrieval_id == retrieval_id:
            return doc.api_name
    return None
