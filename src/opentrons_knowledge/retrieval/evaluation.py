"""Retrieval evaluation: label resolution, metrics, structural queries, and the experiment grid.

Labels in the query set name what a correct answer is, independent of how the
corpus is chunked:

- ``doc:<page_path>``: any section of that page.
- ``doc:<page_path>#<anchor>``: that section or one nested under it.
- ``api:<public name>``: the reference section or the symbol record for it.
- ``labware:<load_name>``, ``pipette:<key>``, ``module:<model>``: that entity.
- ``guide:<file>`` or ``guide:<file>#<anchor>``: an AI guide file or section.

Each label resolves to a set of acceptable retrieval ids. A query scores a hit
at rank *k* when any acceptable id is among the first *k* distinct retrieval
ids the index returns (chunks are expanded to the documents they cover).
"""

from __future__ import annotations

import hashlib
import random
import statistics
import tempfile
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentrons_knowledge.normalization.serialize import load_yaml
from opentrons_knowledge.retrieval.bm25 import build_index, search
from opentrons_knowledge.retrieval.chunking import chunk_documents
from opentrons_knowledge.retrieval.models import (
    ChunkingStrategy,
    Enrichment,
    EvalQuery,
    RetrievalConfig,
    RetrievalDocument,
    RetrievalKind,
)

CUTOFFS = (1, 3, 5, 10)
CHUNK_DEPTH = 50
TIE_MARGIN = 0.01
STRUCTURAL_GUARD = 0.02
_ENTITY_PREFIXES = ("labware:", "pipette:", "module:")

DECISION_RULE = (
    "Among configurations whose returned text is the passage a reader sees "
    "(default tokenizer, not 80-word fragments), pick the highest curated MRR@10. "
    "Configurations within "
    f"{TIE_MARGIN} of the best are tied; break ties by curated Hit@5, then by "
    "simplicity (fewer chunking and enrichment steps, fewer record kinds). The "
    f"winner's structural Hit@10 may not fall more than {STRUCTURAL_GUARD} below "
    "the baseline's. Stemming is measured and not shipped: it did not win, and it "
    "changes which word forms a query must use."
)

BASELINE = RetrievalConfig(
    kinds=[RetrievalKind.DOC_SECTION, RetrievalKind.GUIDE_SECTION],
    chunking=ChunkingStrategy.SECTION,
    enrichment=Enrichment.PLAIN,
)
"""One chunk per section and no added context: the simple index the grid starts from."""

COMPOSITIONS: tuple[tuple[RetrievalKind, ...], ...] = (
    (RetrievalKind.DOC_SECTION,),
    (RetrievalKind.DOC_SECTION, RetrievalKind.ENTITY),
    (RetrievalKind.DOC_SECTION, RetrievalKind.ENTITY, RetrievalKind.API_SYMBOL),
    tuple(RetrievalKind),
)


def load_queries(path: Path) -> list[EvalQuery]:
    """Read curated queries from YAML (``queries:`` list).

    Args:
        path: YAML file.

    Returns:
        Queries with ``source="curated"``.
    """
    data = load_yaml(path) or {}
    return [EvalQuery(source="curated", **item) for item in data.get("queries", [])]


def resolve_labels(
    queries: Sequence[EvalQuery], documents: Sequence[RetrievalDocument]
) -> dict[str, frozenset[str]]:
    """Resolve each query's labels to acceptable retrieval ids.

    Args:
        queries: Labeled queries.
        documents: The full retrieval document set (every kind).

    Returns:
        Acceptable ids per ``query_id``.

    Raises:
        ValueError: If a label matches nothing, so stale labels fail loudly.
    """
    by_id = {d.retrieval_id: d for d in documents}
    by_page: dict[str, list[RetrievalDocument]] = defaultdict(list)
    by_api: dict[str, set[str]] = defaultdict(set)
    by_guide: dict[str, list[RetrievalDocument]] = defaultdict(list)
    for doc in documents:
        if doc.kind == RetrievalKind.DOC_SECTION and doc.page_path:
            by_page[doc.page_path].append(doc)
        if doc.api_name:
            by_api[doc.api_name].add(doc.retrieval_id)
        if doc.kind == RetrievalKind.GUIDE_SECTION:
            by_guide[doc.source_path.rsplit("/", 1)[-1]].append(doc)
    resolved: dict[str, frozenset[str]] = {}
    unresolved: list[str] = []
    for query in queries:
        ids: set[str] = set()
        for label in query.relevant:
            matched = _resolve(label, by_id, by_page, by_api, by_guide)
            if not matched:
                unresolved.append(f"{query.query_id}: {label}")
            ids |= matched
        resolved[query.query_id] = frozenset(ids)
    if unresolved:
        msg = "Unresolved evaluation labels:\n  " + "\n  ".join(unresolved)
        raise ValueError(msg)
    return resolved


def _resolve(
    label: str,
    by_id: dict[str, RetrievalDocument],
    by_page: dict[str, list[RetrievalDocument]],
    by_api: dict[str, set[str]],
    by_guide: dict[str, list[RetrievalDocument]],
) -> set[str]:
    kind, _, value = label.partition(":")
    if kind == "api":
        return set(by_api.get(value, ()))
    if label.startswith(_ENTITY_PREFIXES):
        return {label} if label in by_id else set()
    target, _, anchor = value.partition("#")
    if kind == "doc":
        page = by_page.get(target, [])
        if not anchor:
            return {d.retrieval_id for d in page}
        root = by_id.get(f"doc:{target}#{anchor}")
        if root is None:
            return set()
        depth = len(root.heading_path)
        return {d.retrieval_id for d in page if d.heading_path[:depth] == root.heading_path}
    if kind == "guide":
        guide = by_guide.get(target, [])
        return {d.retrieval_id for d in guide if not anchor or d.anchor == anchor}
    return set()


def structural_queries(documents: Sequence[RetrievalDocument]) -> list[EvalQuery]:
    """Generate queries mechanically from the documents themselves.

    Three families, sampled by a stable hash so the set only changes when the
    documents do: section titles (unique ones only) labeled with their section,
    API member names labeled with the API object, and labware display names
    labeled with the labware entity.

    Args:
        documents: The full retrieval document set.

    Returns:
        Up to 100 heading, 80 API, and 60 labware queries.
    """
    title_counts: dict[str, int] = defaultdict(int)
    for doc in documents:
        title_counts[doc.title.lower()] += 1
    headings = [
        d
        for d in documents
        if d.kind == RetrievalKind.DOC_SECTION
        and d.anchor
        and not d.api_name
        and len(d.title.split()) >= 3
        and title_counts[d.title.lower()] == 1
    ]
    apis = [d for d in documents if d.kind == RetrievalKind.DOC_SECTION and d.api_name]
    labware = [d for d in documents if d.retrieval_id.startswith("labware:")]
    queries: list[EvalQuery] = []
    for doc in _sample(headings, 100):
        queries.append(
            EvalQuery(
                query_id=f"s-heading-{_stable(doc.retrieval_id)[:10]}",
                query=doc.title,
                category="heading",
                source="structural",
                relevant=[doc.retrieval_id],
            )
        )
    for doc in _sample(apis, 80):
        assert doc.api_name is not None
        owner, _, member = doc.api_name.removeprefix("opentrons.protocol_api.").rpartition(".")
        queries.append(
            EvalQuery(
                query_id=f"s-api-{_stable(doc.retrieval_id)[:10]}",
                query=f"{owner} {member}".strip(),
                category="api_name",
                source="structural",
                relevant=[f"api:{doc.api_name}"],
            )
        )
    for doc in _sample(labware, 60):
        queries.append(
            EvalQuery(
                query_id=f"s-labware-{_stable(doc.retrieval_id)[:10]}",
                query=doc.title,
                category="labware_name",
                source="structural",
                relevant=[doc.retrieval_id],
            )
        )
    return queries


def _sample(docs: Sequence[RetrievalDocument], count: int) -> list[RetrievalDocument]:
    return sorted(docs, key=lambda d: _stable(d.retrieval_id))[:count]


def _stable(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Running configurations
# ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    query_id: str
    rank: int | None
    top: list[str]


@dataclass
class ConfigResult:
    """Metrics for one configuration."""

    config: RetrievalConfig
    documents: int
    chunks: int
    mean_chunk_words: float
    build_seconds: float
    index_bytes: int
    p50_latency_ms: float
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    per_query: list[QueryResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.config.name,
            "config": self.config.model_dump(mode="json"),
            "selectable": self.config.selectable,
            "documents": self.documents,
            "chunks": self.chunks,
            "mean_chunk_words": round(self.mean_chunk_words, 1),
            "build_seconds": round(self.build_seconds, 3),
            "index_bytes": self.index_bytes,
            "p50_latency_ms": round(self.p50_latency_ms, 3),
            "metrics": self.metrics,
        }


def run_config(
    config: RetrievalConfig,
    documents: Sequence[RetrievalDocument],
    queries: Sequence[EvalQuery],
    relevant: dict[str, frozenset[str]],
) -> ConfigResult:
    """Build one configuration's index on disk and score every query.

    Args:
        config: The configuration.
        documents: The full retrieval document set; filtered to ``config.kinds``.
        queries: Queries to run.
        relevant: Acceptable ids per query, from ``resolve_labels``.

    Returns:
        Metrics overall, per source, and per category.
    """
    kinds = set(config.kinds)
    subset = [d for d in documents if d.kind in kinds]
    by_id = {d.retrieval_id: d for d in subset}
    started = time.perf_counter()
    chunks = chunk_documents(subset, config.chunking, config.enrichment)
    covers = {c.chunk_id: c.covers for c in chunks}
    with tempfile.TemporaryDirectory() as tmp:
        index = build_index(chunks, by_id, Path(tmp), tokenizer=config.tokenizer)
        build_seconds = time.perf_counter() - started
        index_bytes = sum(p.stat().st_size for p in Path(tmp).rglob("*") if p.is_file())
        latencies: list[float] = []
        per_query: list[QueryResult] = []
        for query in queries:
            t0 = time.perf_counter()
            hits = search(index, query.query, CHUNK_DEPTH)
            latencies.append((time.perf_counter() - t0) * 1000)
            ranked = list(dict.fromkeys(rid for chunk_id, _ in hits for rid in covers[chunk_id]))[
                :10
            ]
            wanted = relevant[query.query_id]
            rank = next((i + 1 for i, rid in enumerate(ranked) if rid in wanted), None)
            per_query.append(QueryResult(query.query_id, rank, ranked))
    result = ConfigResult(
        config=config,
        documents=len(subset),
        chunks=len(chunks),
        mean_chunk_words=statistics.fmean(len(c.text.split()) for c in chunks) if chunks else 0.0,
        build_seconds=build_seconds,
        index_bytes=index_bytes,
        p50_latency_ms=statistics.median(latencies) if latencies else 0.0,
        per_query=per_query,
    )
    result.metrics = _metrics(queries, per_query)
    return result


def _metrics(
    queries: Sequence[EvalQuery], results: Sequence[QueryResult]
) -> dict[str, dict[str, float]]:
    groups: dict[str, list[int | None]] = defaultdict(list)
    for query, result in zip(queries, results, strict=True):
        for key in ("all", query.source, f"{query.source}/{query.category}"):
            groups[key].append(result.rank)
    summary: dict[str, dict[str, float]] = {}
    for key, ranks in sorted(groups.items()):
        n = len(ranks)
        row = {f"hit@{k}": round(sum(1 for r in ranks if r and r <= k) / n, 4) for k in CUTOFFS}
        row["mrr@10"] = round(sum(1 / r for r in ranks if r) / n, 4)
        row["n"] = n
        summary[key] = row
    return summary


def experiment_grid() -> list[RetrievalConfig]:
    """Return the baseline plus every composition, chunking, and enrichment combination.

    Stemming is run only on the full composition. It is measured so the comparison
    exists, and it is not selected: it did not win.

    Returns:
        Configurations in a stable order.
    """
    grid = [BASELINE]
    for kinds in COMPOSITIONS:
        for chunking in ChunkingStrategy:
            for enrichment in Enrichment:
                grid.append(
                    RetrievalConfig(kinds=list(kinds), chunking=chunking, enrichment=enrichment)
                )
    for chunking in (ChunkingStrategy.SECTION, ChunkingStrategy.STRUCTURED):
        grid.append(
            RetrievalConfig(
                kinds=list(COMPOSITIONS[-1]),
                chunking=chunking,
                enrichment=Enrichment.CONTEXT_TERMS,
                tokenizer="en_stem",
            )
        )
    return grid


def select_winner(results: Sequence[ConfigResult]) -> tuple[ConfigResult, list[str]]:
    """Apply ``DECISION_RULE``.

    Args:
        results: Every configuration's result; must include ``BASELINE``.

    Returns:
        The winner and a step-by-step explanation.
    """
    baseline = next(r for r in results if r.config == BASELINE)
    floor = baseline.metrics["structural"]["hit@10"] - STRUCTURAL_GUARD
    eligible = [
        r for r in results if r.config.selectable and r.metrics["structural"]["hit@10"] >= floor
    ]
    best = max(r.metrics["curated"]["mrr@10"] for r in eligible)
    tied = [r for r in eligible if r.metrics["curated"]["mrr@10"] >= best - TIE_MARGIN]
    tied.sort(key=lambda r: (-r.metrics["curated"]["hit@5"], _complexity(r.config)))
    winner = tied[0]
    baseline_hit = baseline.metrics["structural"]["hit@10"]
    notes = [
        f"{len(results)} configurations ran; {len(eligible)} return a readable passage and keep "
        f"structural Hit@10 >= {floor:.3f} (baseline {baseline_hit:.3f}).",
        f"Best curated MRR@10 among them is {best:.4f}; {len(tied)} configurations are within "
        f"{TIE_MARGIN}: " + ", ".join(r.config.name for r in tied) + ".",
        f"Winner by curated Hit@5, then simplicity: {winner.config.name}.",
    ]
    return winner, notes


def ablations(winner: ConfigResult, results: Sequence[ConfigResult]) -> list[ConfigResult]:
    """Return configurations that differ from the winner in exactly one factor.

    Args:
        winner: The selected configuration.
        results: Every configuration's result.

    Returns:
        One-factor variants, plus the baseline.
    """
    w = winner.config
    found: list[ConfigResult] = []
    for result in results:
        c = result.config
        diffs = [
            c.kinds != w.kinds,
            c.chunking != w.chunking,
            c.enrichment != w.enrichment,
            c.tokenizer != w.tokenizer,
        ]
        if sum(diffs) == 1 or c == BASELINE:
            found.append(result)
    stemmed = [
        r for r in results if r.config.tokenizer == "en_stem" and r.config.chunking == w.chunking
    ]
    for result in stemmed:
        unstemmed = result.config.model_copy(update={"tokenizer": "default"})
        if result not in found and any(r.config == unstemmed for r in results):
            found.append(result)
    return found


def paired_delta(
    a: ConfigResult,
    b: ConfigResult,
    queries: Sequence[EvalQuery],
    *,
    source: str = "curated",
    resamples: int = 2000,
) -> dict[str, float]:
    """Paired bootstrap of the MRR@10 difference ``a - b`` over the same queries.

    Args:
        a: First configuration.
        b: Second configuration.
        queries: The queries both were scored on, in result order.
        source: Which query source to compare.
        resamples: Bootstrap resamples (seeded, so the report is reproducible).

    Returns:
        Mean delta and its 95% interval.
    """

    def rr(result: QueryResult) -> float:
        return 1 / result.rank if result.rank else 0.0

    deltas = [
        rr(x) - rr(y)
        for q, x, y in zip(queries, a.per_query, b.per_query, strict=True)
        if q.source == source
    ]
    rng = random.Random(0)
    n = len(deltas)
    means = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return {
        "delta_mrr@10": round(sum(deltas) / n, 4),
        "ci95_low": round(means[int(0.025 * resamples)], 4),
        "ci95_high": round(means[int(0.975 * resamples) - 1], 4),
        "n": n,
    }


def run_experiments(
    documents: Sequence[RetrievalDocument], curated: Sequence[EvalQuery]
) -> tuple[dict[str, Any], RetrievalConfig]:
    """Run the grid, select a winner, and explain it.

    Args:
        documents: The full retrieval document set (every kind).
        curated: Curated queries.

    Returns:
        The evaluation report and the selected configuration.
    """
    queries = [*curated, *structural_queries(documents)]
    relevant = resolve_labels(queries, documents)
    results = [run_config(c, documents, queries, relevant) for c in experiment_grid()]
    winner, notes = select_winner(results)
    by_query = {q.query_id: q for q in queries}
    misses = [
        {
            "query_id": r.query_id,
            "query": by_query[r.query_id].query,
            "rank": r.rank,
            "relevant": by_query[r.query_id].relevant,
            "top3": r.top[:3],
        }
        for r in winner.per_query
        if by_query[r.query_id].source == "curated" and (r.rank is None or r.rank > 5)
    ]
    report = {
        "decision_rule": DECISION_RULE,
        "baseline": BASELINE.name,
        "queries": {
            "curated": sum(1 for q in queries if q.source == "curated"),
            "structural": sum(1 for q in queries if q.source == "structural"),
        },
        "winner": winner.config.name,
        "selection": notes,
        "ablations": [
            {"name": r.config.name, **paired_delta(winner, r, queries)}
            for r in ablations(winner, results)
            if r is not winner
        ],
        "winner_misses": misses,
        "results": [r.to_json() for r in results],
    }
    return report, winner.config


def report_markdown(report: dict[str, Any]) -> str:
    """Render an experiment report as Markdown tables.

    Args:
        report: Output of ``run_experiments``.

    Returns:
        Markdown with the full grid, the ablations, and the winner's categories.
    """
    lines = [
        f"Queries: {report['queries']['curated']} curated, "
        f"{report['queries']['structural']} structural. Winner: `{report['winner']}`.",
        "",
        "| Configuration | Selectable | Chunks | Curated MRR@10 | Hit@1 | Hit@5 | Hit@10 "
        "| Structural Hit@10 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in report["results"]:
        c, s = r["metrics"]["curated"], r["metrics"]["structural"]
        lines.append(
            f"| `{r['name']}` | {'yes' if r['selectable'] else 'no'} | {r['chunks']} "
            f"| {c['mrr@10']:.3f} | {c['hit@1']:.3f} | {c['hit@5']:.3f} | {c['hit@10']:.3f} "
            f"| {s['hit@10']:.3f} |"
        )
    lines += [
        "",
        "| Winner minus | Curated MRR@10 delta | 95% CI |",
        "| --- | ---: | --- |",
    ]
    for a in report["ablations"]:
        lines.append(
            f"| `{a['name']}` | {a['delta_mrr@10']:+.3f} "
            f"| [{a['ci95_low']:+.3f}, {a['ci95_high']:+.3f}] |"
        )
    winner = next(r for r in report["results"] if r["name"] == report["winner"])
    baseline = next(r for r in report["results"] if r["name"] == report["baseline"])
    lines += [
        "",
        "| Category | n | Baseline MRR@10 | Winner MRR@10 | Winner Hit@5 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key, row in winner["metrics"].items():
        if "/" not in key:
            continue
        base = baseline["metrics"][key]
        lines.append(
            f"| {key} | {row['n']:.0f} | {base['mrr@10']:.3f} | {row['mrr@10']:.3f} "
            f"| {row['hit@5']:.3f} |"
        )
    return "\n".join(lines) + "\n"


def _complexity(config: RetrievalConfig) -> tuple[int, int, int]:
    chunking = list(ChunkingStrategy).index(config.chunking)
    enrichment = list(Enrichment).index(config.enrichment)
    return (chunking + enrichment, len(config.kinds), chunking)
