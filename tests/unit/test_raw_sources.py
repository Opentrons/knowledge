"""Raw source mirroring tests."""

from __future__ import annotations

from pathlib import Path

from opentrons_knowledge.artifacts.raw_sources import copy_raw_sources
from opentrons_knowledge.models.enums import CompatibilityStatus
from opentrons_knowledge.models.manifest import CompatibilityBlock, ResolvedSource


def test_copy_raw_sources_honors_exclude_paths(tmp_path: Path) -> None:
    materialize = tmp_path / "work" / "opentrons_ai_v1"
    included = materialize / "opentrons-ai-server/api/storage/docs/deck_layout.md"
    excluded = materialize / "opentrons-ai-server/api/storage/docs/pd/secret.md"
    included.parent.mkdir(parents=True)
    excluded.parent.mkdir(parents=True)
    included.write_text("# deck\n", encoding="utf-8")
    excluded.write_text("# pd\n", encoding="utf-8")

    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    sources = {
        "opentrons_ai_v1": ResolvedSource(
            key="opentrons_ai_v1",
            repository="https://github.com/Opentrons/opentrons",
            tag="ai-server@0.0.22",
            commit="a" * 40,
            paths=["opentrons-ai-server/api/storage/docs"],
            exclude_paths=["opentrons-ai-server/api/storage/docs/pd"],
            compatibility=CompatibilityBlock(status=CompatibilityStatus.VALIDATED),
            materialize_root=str(materialize),
        )
    }
    counts = copy_raw_sources(corpus_root, sources)
    assert counts["opentrons_ai_v1"] == 1
    deck = corpus_root / "raw/opentrons_ai_v1/opentrons-ai-server/api/storage/docs/deck_layout.md"
    assert deck.is_file()
    pd_secret = (
        corpus_root / "raw/opentrons_ai_v1/opentrons-ai-server/api/storage/docs/pd/secret.md"
    )
    assert not pd_secret.exists()
