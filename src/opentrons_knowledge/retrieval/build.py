"""Build the retrieval bundle and, optionally, re-run the experiment grid."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from opentrons_knowledge.normalization.serialize import file_sha256
from opentrons_knowledge.retrieval.bundle import RetrievalManifest, write_bundle
from opentrons_knowledge.retrieval.documents import RetrievalInputs, build_retrieval_documents
from opentrons_knowledge.retrieval.evaluation import (
    DECISION_RULE,
    load_queries,
    resolve_labels,
    run_config,
    run_experiments,
    structural_queries,
)
from opentrons_knowledge.retrieval.models import EvalQuery, RetrievalConfig

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RetrievalBuild:
    """A written bundle and, when the grid ran, its experiment report."""

    manifest: RetrievalManifest
    report: dict[str, Any] | None


def build_retrieval(
    inputs: RetrievalInputs,
    bundle_dir: Path,
    config: RetrievalConfig,
    *,
    corpus_version: str,
    queries_path: Path | None = None,
    run_grid: bool = False,
) -> RetrievalBuild:
    """Build retrieval documents, evaluate, and write the bundle.

    The configured ``config`` is what ships. When ``run_grid`` is set the full
    grid runs as well; if it selects a different configuration, the build logs
    a warning and records both, so a new release that shifts the result is
    visible rather than silently adopted.

    Args:
        inputs: Corpus records to build from.
        bundle_dir: Output directory, normally ``<corpus>/retrieval``.
        config: Configuration to ship.
        corpus_version: Corpus version the bundle belongs to.
        queries_path: Curated query YAML; skips evaluation when omitted.
        run_grid: Also run every configuration in the experiment grid.

    Returns:
        The manifest and the experiment report (when ``run_grid``).
    """
    documents = build_retrieval_documents(inputs)
    queries: list[EvalQuery] = []
    relevant: dict[str, frozenset[str]] = {}
    evaluation: dict[str, Any] | None = None
    report: dict[str, Any] | None = None
    if queries_path is not None:
        curated = load_queries(queries_path)
        queries = [*curated, *structural_queries(documents)]
        relevant = resolve_labels(queries, documents)
        shipped = run_config(config, documents, queries, relevant)
        evaluation = {
            "decision_rule": DECISION_RULE,
            "queries_sha256": file_sha256(queries_path),
            "measured_on": (
                "One index containing every selected document. That measurement "
                "chooses how the docs index is cut. The shipped bundle then moves "
                "symbol sections into the api index."
            ),
            "metrics": {k: shipped.metrics[k] for k in ("curated", "structural")},
        }
        if run_grid:
            report, winner = run_experiments(documents, curated)
            evaluation["grid_winner"] = winner.name
            if winner != config:
                log.warning("retrieval_grid_disagrees", shipped=config.name, winner=winner.name)
    manifest = write_bundle(
        bundle_dir,
        documents,
        config,
        corpus_version=corpus_version,
        queries=queries,
        relevant=relevant,
        evaluation=evaluation,
    )
    log.info(
        "retrieval_built",
        path=str(bundle_dir),
        documents=manifest.document_count,
        chunks=manifest.chunk_count,
        config=config.name,
    )
    return RetrievalBuild(manifest=manifest, report=report)
