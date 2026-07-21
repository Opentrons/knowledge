"""Deterministic serialization helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml
import zstandard as zstd
from pydantic import BaseModel

from opentrons_knowledge.normalization.ids import content_hash


def to_canonical_dict(model: BaseModel) -> dict[str, Any]:
    """Serialize a Pydantic model with sorted keys."""
    return model.model_dump(mode="json")


def dumps_canonical_json(value: Any) -> str:
    """Compact, key-sorted JSON string."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_json(path: Path, value: Any) -> str:
    """Write pretty JSON for reports; return content hash of canonical bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return content_hash(dumps_canonical_json(value))


def write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            value,
            handle,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def write_jsonl_zst(
    path: Path, records: Sequence[BaseModel] | Iterable[BaseModel]
) -> tuple[int, str]:
    """Write sorted JSONL compressed with zstd. Returns (count, sha256 of compressed file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [to_canonical_dict(record) for record in records]
    items.sort(key=lambda item: str(item.get(_primary_key(item), "")))
    lines = [dumps_canonical_json(item) for item in items]
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    compressed = zstd.ZstdCompressor(level=3).compress(payload)
    path.write_bytes(compressed)
    return len(items), content_hash(compressed)


def read_jsonl_zst(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    text = zstd.ZstdDecompressor().decompress(raw).decode("utf-8")
    if not text.strip():
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def write_checksums(path: Path, checksums: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{digest}  {rel}" for rel, digest in sorted(checksums.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_checksums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        result[rel] = digest
    return result


def file_sha256(path: Path) -> str:
    return content_hash(path.read_bytes())


def _primary_key(item: dict[str, Any]) -> str:
    for key in (
        "document_id",
        "section_id",
        "symbol_id",
        "entity_id",
        "relationship_id",
        "constraint_id",
        "example_id",
        "source_file_id",
        "id",
    ):
        if key in item:
            return key
    return next(iter(item), "")
