"""ORAS publish helpers (mocked CLI)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opentrons_knowledge.builder.pipeline import build_fixture_corpus
from opentrons_knowledge.errors import RegistryError
from opentrons_knowledge.registry.oras import publish_corpus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mini_sources"


def test_publish_refuses_overwrite_when_remote_exists(tmp_path: Path) -> None:
    corpus = build_fixture_corpus(tmp_path, FIXTURES).corpus_root

    with (
        patch("opentrons_knowledge.registry.oras.ensure_oras", return_value="oras"),
        patch("opentrons_knowledge.registry.oras._remote_exists", return_value=True),
        pytest.raises(RegistryError, match="Refusing to overwrite"),
    ):
        publish_corpus(corpus, registry_repo="ghcr.io/example/knowledge")


def test_publish_pushes_when_remote_missing(tmp_path: Path) -> None:
    corpus = build_fixture_corpus(tmp_path, FIXTURES).corpus_root
    push = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))

    with (
        patch("opentrons_knowledge.registry.oras.ensure_oras", return_value="oras"),
        patch("opentrons_knowledge.registry.oras._remote_exists", return_value=False),
        patch("opentrons_knowledge.registry.oras._resolve_digest", return_value="sha256:abc"),
        patch("opentrons_knowledge.registry.oras.subprocess.run", push),
    ):
        result = publish_corpus(corpus, registry_repo="ghcr.io/example/knowledge")

    assert result["reference"] == "ghcr.io/example/knowledge:0.0.0-k1"
    assert result["digest"] == "sha256:abc"
    assert push.call_args.args[0][0:2] == ["oras", "push"]
