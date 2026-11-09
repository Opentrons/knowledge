"""Regenerate schemas/canonical-*.schema.json and schemas/retrieval-*.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

from opentrons_knowledge.models.canonical import CANONICAL_JSON_SCHEMAS, canonical_json_schema
from opentrons_knowledge.retrieval.bundle import RETRIEVAL_JSON_SCHEMAS

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"

for filename, model in {**CANONICAL_JSON_SCHEMAS, **RETRIEVAL_JSON_SCHEMAS}.items():
    schema = canonical_json_schema(model, filename)
    (SCHEMAS / filename).write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote schemas/{filename}")
