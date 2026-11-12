"""Integration tests read the latest built package and fail when it is absent."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentrons_knowledge.corpora import highest_corpus_version

ROOT = Path(__file__).resolve().parents[2]
VERSION = highest_corpus_version(ROOT / "corpora")
CORPUS = ROOT / "dist" / f"opentrons-knowledge-{VERSION}"


@pytest.fixture(scope="session", autouse=True)
def built_corpus() -> Path:
    assert (CORPUS / "manifest.yaml").is_file(), f"Build {CORPUS} before running tests."
    return CORPUS
