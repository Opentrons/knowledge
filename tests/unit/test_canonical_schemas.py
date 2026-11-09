from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentrons_knowledge.models.canonical import CANONICAL_JSON_SCHEMAS, canonical_json_schema
from opentrons_knowledge.retrieval.bundle import RETRIEVAL_JSON_SCHEMAS

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
PUBLISHED = {**CANONICAL_JSON_SCHEMAS, **RETRIEVAL_JSON_SCHEMAS}


@pytest.mark.parametrize("filename", sorted(PUBLISHED))
def test_published_schema_matches_models(filename: str) -> None:
    expected = canonical_json_schema(PUBLISHED[filename], filename)
    published = json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
    assert published == expected, f"Run `just schemas` to regenerate schemas/{filename}"
