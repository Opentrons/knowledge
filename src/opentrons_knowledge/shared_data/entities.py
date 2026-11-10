"""Parse Opentrons shared-data definitions into entities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentrons_knowledge.models.enums import DerivationMethod, EntityType
from opentrons_knowledge.models.records import Entity, Relationship, SourceFileRecord
from opentrons_knowledge.normalization.ids import (
    content_hash,
    entity_id,
    relationship_id,
    source_file_id,
)

SKIP_DIR_NAMES = {"__pycache__", "js", "python", "python_tests", "tools", "images", "fixtures"}

# Deck ids shared-data uses on module definitions, and the robot each deck belongs to.
_MODULE_DECKS = {
    "ot2_standard": "ot-2",
    "ot2_short_trash": "ot-2",
    "ot3_standard": "flex",
}
_OT2_SLOTS = frozenset(str(slot) for slot in range(1, 12))
_FLEX_SLOTS = frozenset(f"{row}{column}" for row in "ABCD" for column in range(1, 5))
_ROBOT_ORDER = ("flex", "ot-2")


@dataclass
class SharedDataBundle:
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    source_files: list[SourceFileRecord] = field(default_factory=list)


def ingest_shared_data(
    materialize_root: Path,
    *,
    repository: str,
    commit: str,
    configured_paths: list[str],
    release: str,
    source_key: str = "shared_data",
) -> SharedDataBundle:
    """Ingest labware/pipette/module/deck/robot definitions."""
    bundle = SharedDataBundle()
    release_key = release.lstrip("v")
    for configured in configured_paths:
        root = materialize_root / configured
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            rel_parts = path.relative_to(root).parts
            rel = path.relative_to(materialize_root).as_posix()
            if any(part in SKIP_DIR_NAMES for part in rel_parts):
                bundle.source_files.append(
                    SourceFileRecord(
                        source_file_id=source_file_id(source_key, rel),
                        source_key=source_key,
                        repository=repository,
                        commit=commit,
                        path=rel,
                        status="excluded",
                        reason="non-definition-shared-data-path",
                        byte_size=path.stat().st_size,
                    )
                )
                continue
            text = path.read_text(encoding="utf-8")
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                bundle.source_files.append(
                    SourceFileRecord(
                        source_file_id=source_file_id(source_key, rel),
                        source_key=source_key,
                        repository=repository,
                        commit=commit,
                        path=rel,
                        status="excluded",
                        reason="invalid-json",
                    )
                )
                continue

            entity = _entity_from_definition(
                data,
                source_path=rel,
                release_key=release_key,
                source_key=source_key,
            )
            bundle.source_files.append(
                SourceFileRecord(
                    source_file_id=source_file_id(source_key, rel),
                    source_key=source_key,
                    repository=repository,
                    commit=commit,
                    path=rel,
                    status="included" if entity else "excluded",
                    reason=None if entity else "unrecognized-definition-shape",
                    content_hash=content_hash(text),
                    byte_size=len(text.encode("utf-8")),
                )
            )
            if entity is None:
                continue
            bundle.entities.append(entity)
            for rel_obj in _relationships_from_definition(entity, data):
                bundle.relationships.append(rel_obj)
    return bundle


def labware_robot_scope(load_name: str) -> list[str]:
    """Robots that can load this labware or tip rack.

    ``opentrons_flex_*`` is Flex. Every other load name is both robots: a
    labware definition has no robot field, and ``ProtocolContext.load_labware``
    does not reject a load name for the other robot.
    """
    if load_name.startswith("opentrons_flex_"):
        return ["flex"]
    return list(_ROBOT_ORDER)


def pipette_robot_scope(data: dict[str, Any], *, source_path: str = "") -> list[str]:
    """Robot for a pipette general definition.

    ``displayCategory`` ``FLEX`` is Flex. ``GEN1`` and ``GEN2`` are OT-2.
    A 96-channel pipette is Flex even when ``displayCategory`` is ``GEN1``.
    """
    if data.get("channels") == 96 or "ninety_six_channel" in source_path:
        return ["flex"]
    category = data.get("displayCategory")
    if not isinstance(category, str) or not category:
        return []
    if category.upper() == "FLEX":
        return ["flex"]
    return ["ot-2"]


def module_robot_scope(data: dict[str, Any]) -> list[str]:
    """Robots whose decks can accept this module.

    Start from the shared-data decks absent from ``incompatibleWithDecks``.
    When ``orientation`` names slots, keep a robot only if one of those slots
    is its own (``1`` through ``11`` for OT-2, ``A1`` through ``D4`` for Flex).
    """
    incompatible = data.get("incompatibleWithDecks")
    blocked = set(incompatible) if isinstance(incompatible, list) else set()
    robots = {robot for deck, robot in _MODULE_DECKS.items() if deck not in blocked}
    orientation = data.get("orientation")
    if isinstance(orientation, dict) and orientation:
        slots = {str(slot) for slot in orientation}
        if not slots & _OT2_SLOTS:
            robots.discard("ot-2")
        if not slots & _FLEX_SLOTS:
            robots.discard("flex")
    return [robot for robot in _ROBOT_ORDER if robot in robots]


def _entity_from_definition(
    data: dict[str, Any],
    *,
    source_path: str,
    release_key: str,
    source_key: str,
) -> Entity | None:
    lower = source_path.lower()
    # Schema documents are not loadable hardware. A path stem is always
    # non-empty, so it must not be used as proof that a file is a definition.
    if "/schemas/" in lower:
        return None
    schema_version = str(data.get("schemaVersion") or data.get("schema_version") or "unknown")

    if "/labware/" in lower and ("parameters" in data or "wells" in data):
        load_name = (
            data.get("parameters", {}).get("loadName")
            or data.get("namespace")
            or Path(source_path).stem
        )
        # schema3test_* labware (definition version 999) are shared-data test fixtures.
        if str(load_name).startswith("schema") or data.get("version") == 999:
            return None
        display = data.get("metadata", {}).get("displayName") or load_name
        is_tiprack = bool(data.get("parameters", {}).get("isTiprack"))
        entity_type = EntityType.TIP_RACK if is_tiprack else EntityType.LABWARE
        eid = entity_id(entity_type.value, str(load_name), f"schema-{schema_version}")
        return Entity(
            entity_id=eid,
            entity_type=entity_type,
            canonical_name=str(load_name),
            display_name=str(display),
            aliases=[str(load_name)],
            source_ids=[f"{source_key}:{source_path}"],
            properties={
                "namespace": data.get("namespace"),
                "version": data.get("version"),
                "schema_version": schema_version,
                "is_tiprack": is_tiprack,
                "display_category": data.get("metadata", {}).get("displayCategory"),
            },
            version_scope=release_key,
            robot_scope=labware_robot_scope(str(load_name)),
            content_hash=content_hash(json.dumps(data, sort_keys=True)),
            raw_source=data,
        )

    if "/pipette/" in lower and ("channels" in data or "pipetteName" in data or "model" in lower):
        name = (
            data.get("name")
            or data.get("pipetteName")
            or data.get("metadata", {}).get("displayName")
            or Path(source_path).stem
        )
        eid = entity_id(EntityType.PIPETTE.value, str(name), release_key)
        return Entity(
            entity_id=eid,
            entity_type=EntityType.PIPETTE,
            canonical_name=str(name),
            display_name=str(
                data.get("displayName") or data.get("metadata", {}).get("displayName") or name
            ),
            aliases=[str(name)],
            source_ids=[f"{source_key}:{source_path}"],
            properties={
                "channels": data.get("channels"),
                "schema_version": schema_version,
                "model": Path(source_path).stem,
            },
            version_scope=release_key,
            robot_scope=pipette_robot_scope(data, source_path=source_path),
            content_hash=content_hash(json.dumps(data, sort_keys=True)),
            raw_source=data,
        )

    if "/module/" in lower and isinstance(data.get("model"), str):
        model = data["model"]
        eid = entity_id(EntityType.MODULE.value, model, release_key)
        return Entity(
            entity_id=eid,
            entity_type=EntityType.MODULE,
            canonical_name=model,
            display_name=str(data.get("displayName") or model),
            source_ids=[f"{source_key}:{source_path}"],
            properties={
                "module_type": data.get("moduleType"),
                "schema_version": schema_version,
            },
            version_scope=release_key,
            robot_scope=module_robot_scope(data),
            content_hash=content_hash(json.dumps(data, sort_keys=True)),
            raw_source=data,
        )

    if "/deck/" in lower:
        name = data.get("otId") or Path(source_path).stem
        eid = entity_id(EntityType.DECK.value, str(name), release_key)
        return Entity(
            entity_id=eid,
            entity_type=EntityType.DECK,
            canonical_name=str(name),
            display_name=str(name),
            source_ids=[f"{source_key}:{source_path}"],
            properties={"schema_version": schema_version, "robot": data.get("robot")},
            version_scope=release_key,
            robot_scope=_robot_scope_from_deck(data, name),
            content_hash=content_hash(json.dumps(data, sort_keys=True)),
            raw_source=data,
        )

    if "/robot/" in lower:
        name = data.get("name") or data.get("displayName") or Path(source_path).stem
        eid = entity_id(EntityType.ROBOT.value, str(name), release_key)
        return Entity(
            entity_id=eid,
            entity_type=EntityType.ROBOT,
            canonical_name=str(name),
            display_name=str(data.get("displayName") or name),
            source_ids=[f"{source_key}:{source_path}"],
            properties={"schema_version": schema_version},
            version_scope=release_key,
            robot_scope=[str(name)],
            content_hash=content_hash(json.dumps(data, sort_keys=True)),
            raw_source=data,
        )

    return None


def _robot_scope_from_deck(data: dict[str, Any], name: str) -> list[str]:
    robot = data.get("robot")
    if isinstance(robot, dict) and robot.get("model"):
        return [str(robot["model"])]
    lower = name.lower()
    if "ot2" in lower or "ot-2" in lower:
        return ["ot-2"]
    if "ot3" in lower or "flex" in lower:
        return ["flex"]
    return []


def _relationships_from_definition(entity: Entity, data: dict[str, Any]) -> list[Relationship]:
    rels: list[Relationship] = []
    if entity.entity_type in {EntityType.LABWARE, EntityType.TIP_RACK}:
        load_name = entity.canonical_name
        rels.append(
            Relationship(
                relationship_id=relationship_id(
                    "entity_defined_by_shared_data",
                    entity.entity_id,
                    entity.source_ids[0] if entity.source_ids else entity.entity_id,
                ),
                source_id=entity.entity_id,
                target_id=entity.source_ids[0] if entity.source_ids else entity.entity_id,
                relationship_type="entity_defined_by_shared_data",
                properties={"load_name": load_name},
                derivation_method=DerivationMethod.DIRECT,
            )
        )
        # Tiprack compatibility listed on some labware / pipette defs
    compatible = data.get("compatible") or data.get("compatibleParent") or []
    if isinstance(compatible, list):
        for item in compatible:
            target = str(item)
            rels.append(
                Relationship(
                    relationship_id=relationship_id("compatible_with", entity.entity_id, target),
                    source_id=entity.entity_id,
                    target_id=target,
                    relationship_type="compatible_with",
                    derivation_method=DerivationMethod.DIRECT,
                )
            )
    return rels
