"""Evaluate Protocol Designer compatibility tables and publish them as JSON.

``tools/protocol-designer-export`` imports the Protocol Designer modules through
Vite (the bundler Protocol Designer ships with) and writes the runtime values of
the exports below. This module checks out the pinned sources, runs that
exporter, and shapes its output into ``corpus/protocol-designer/*.json``. The
TypeScript source text is never read here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opentrons_knowledge.errors import ProtocolDesignerExportError
from opentrons_knowledge.models.manifest import ProtocolDesignerTablesConfig, ResolvedSource
from opentrons_knowledge.normalization.serialize import write_json
from opentrons_knowledge.sources.resolve import materialize_paths

TABLES_DIR = "corpus/protocol-designer"
TABLES_SCHEMA_VERSION = 1
EXPORTER_DIR = Path(__file__).resolve().parents[3] / "tools" / "protocol-designer-export"

LABWARE_COMPATIBILITY = "protocol-designer/src/utils/labwareModuleCompatibility.ts"
DECK_SETUP = "protocol-designer/src/pages/Designer/DeckSetup/constants.ts"
DECK_SETUP_UTILS = "protocol-designer/src/pages/Designer/DeckSetup/utils.ts"
PD_CONSTANTS = "protocol-designer/src/constants.ts"
MODULE_DATA = "protocol-designer/src/modules/moduleData.ts"
ONBOARDING = "protocol-designer/src/pages/Onboarding/constants.ts"

# Opentrons edge (.nvmrc and package.json engines) on 2026-11-10.
MIN_NODE = (24, 22, 1)

LIMIT_EXPORTS: tuple[tuple[str, str], ...] = (
    (PD_CONSTANTS, "MIN_ENGAGE_HEIGHT_V1"),
    (PD_CONSTANTS, "MAX_ENGAGE_HEIGHT_V1"),
    (PD_CONSTANTS, "MIN_ENGAGE_HEIGHT_V2"),
    (PD_CONSTANTS, "MAX_ENGAGE_HEIGHT_V2"),
    (PD_CONSTANTS, "MIN_TEMP_MODULE_TEMP"),
    (PD_CONSTANTS, "MAX_TEMP_MODULE_TEMP"),
    (PD_CONSTANTS, "MIN_HEATER_SHAKER_MODULE_TEMP"),
    (PD_CONSTANTS, "MAX_HEATER_SHAKER_MODULE_TEMP"),
    (PD_CONSTANTS, "MIN_HEATER_SHAKER_MODULE_RPM"),
    (PD_CONSTANTS, "MAX_HEATER_SHAKER_MODULE_RPM"),
    (PD_CONSTANTS, "MIN_HEATER_SHAKER_DURATION_SECONDS"),
    (PD_CONSTANTS, "MAX_HEATER_SHAKER_DURATION_SECONDS"),
    (PD_CONSTANTS, "MIN_TC_BLOCK_TEMP"),
    (PD_CONSTANTS, "MAX_TC_BLOCK_TEMP"),
    (PD_CONSTANTS, "MIN_TC_LID_TEMP"),
    (PD_CONSTANTS, "MAX_TC_LID_TEMP"),
    (PD_CONSTANTS, "MIN_TC_DURATION_SECONDS"),
    (PD_CONSTANTS, "MAX_TC_DURATION_SECONDS"),
    (PD_CONSTANTS, "MIN_TC_PROFILE_VOLUME"),
    (PD_CONSTANTS, "MAX_TC_PROFILE_VOLUME"),
    (DECK_SETUP, "MAX_MOAM_MODULES"),
    (DECK_SETUP, "MAX_MAGNETIC_BLOCKS"),
)

LABWARE_SELECTION = (
    "namespace 'opentrons'; per load name the newest schemaVersion, then the newest "
    "version; schema3test_* definitions skipped"
)


def evaluate_tables(
    *,
    repo: Path,
    commit: str,
    settings: ProtocolDesignerTablesConfig,
    labware_definitions: Path,
    work_root: Path,
    exporter_dir: Path = EXPORTER_DIR,
) -> dict[str, Any]:
    """Run the TypeScript exporter against ``repo`` at ``commit``.

    Args:
        repo: Local Opentrons clone that contains ``commit``.
        commit: Protocol Designer commit to evaluate.
        settings: Which paths to check out and where the package lives.
        labware_definitions: ``shared-data/labware/definitions`` from the pinned
            shared-data source; the compatibility predicate runs against these.
        work_root: Scratch directory for the checkout and exporter output.
        exporter_dir: The ``tools/protocol-designer-export`` package.

    Returns:
        The exporter output: ``exports`` (module path to export name to value)
        and ``getLabwareCompatibleWithModule`` (predicate results).
    """
    _require_node()
    if work_root.exists():
        shutil.rmtree(work_root)
    checkout = work_root / "checkout"
    materialize_paths(repo, commit, settings.sparse_paths, checkout)
    node_modules = install_exporter(exporter_dir)
    (checkout / "node_modules").symlink_to(node_modules, target_is_directory=True)

    output = work_root / "tables.json"
    _run(
        [
            "node",
            "run.mjs",
            "--package",
            str((checkout / settings.package).resolve()),
            "--labware",
            str(labware_definitions.resolve()),
            "--out",
            str(output.resolve()),
        ],
        cwd=exporter_dir,
    )
    result: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
    return result


def install_exporter(exporter_dir: Path = EXPORTER_DIR) -> Path:
    """Install the exporter's locked npm dependencies when they are missing."""
    node_modules = exporter_dir / "node_modules"
    if not (node_modules / "vite").is_dir():
        _run(["npm", "ci", "--no-audit", "--no-fund"], cwd=exporter_dir)
    return node_modules.resolve()


def write_tables(
    raw: Mapping[str, Any],
    output_dir: Path,
    *,
    protocol_designer: ResolvedSource,
    labware: ResolvedSource,
    labware_definitions: str,
) -> list[str]:
    """Write the evaluated tables as sorted JSON files.

    Args:
        raw: ``evaluate_tables`` output.
        output_dir: ``corpus/protocol-designer`` inside the corpus being built.
        protocol_designer: The resolved Protocol Designer source (the pin).
        labware: The resolved shared-data source the predicate ran against.
        labware_definitions: Labware definitions path within ``labware``.

    Returns:
        Written file names, sorted.
    """
    exports = raw["exports"]
    compatible = raw["getLabwareCompatibleWithModule"]
    recommended = raw["getLabwareIsRecommended"]
    adapters = raw["getLabwareCompatibleWithAdapter"]
    models_by_slot = raw["getModuleModelsBySlot"]
    slots_by_type = raw["getAllModuleSlotsByTypeOt2"]

    def value(module: str, name: str) -> Any:
        try:
            return exports[module][name]
        except KeyError as exc:
            msg = f"Exporter output is missing {name} from {module}"
            raise ProtocolDesignerExportError(msg) from exc

    def source(*names: tuple[str, str]) -> dict[str, Any]:
        return {
            **_pin(protocol_designer),
            "exports": [{"module": module, "name": name} for module, name in names],
        }

    labware_pin = {**_pin(labware), "path": labware_definitions}
    files: dict[str, dict[str, Any]] = {
        "labware-allowlist.json": {
            "source": source(
                (LABWARE_COMPATIBILITY, "COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE")
            ),
            "by_module_type": _load_names_by_key(
                value(LABWARE_COMPATIBILITY, "COMPATIBLE_LABWARE_ALLOWLIST_BY_MODULE_TYPE")
            ),
        },
        "labware-compatible.json": {
            "source": source(
                (compatible["module"], "getLabwareCompatibleWithModule"),
                (adapters["module"], "getLabwareCompatibleWithAdapter"),
                (LABWARE_COMPATIBILITY, "ADAPTER_96_CHANNEL"),
            ),
            "labware_definitions": {
                **labware_pin,
                "selection": LABWARE_SELECTION,
                "count": compatible["definition_count"],
            },
            "by_module_type": _load_names_by_key(compatible["by_module_type"]),
            "by_adapter": _load_names_by_key(adapters["by_adapter"]),
            "adapter_96_channel": _text(value(LABWARE_COMPATIBILITY, "ADAPTER_96_CHANNEL")),
        },
        "recommended-labware.json": {
            "source": source(
                (DECK_SETUP, "RECOMMENDED_LABWARE_BY_MODULE"),
                (recommended["module"], "getLabwareIsRecommended"),
            ),
            "by_module_type": _load_names_by_key(
                value(DECK_SETUP, "RECOMMENDED_LABWARE_BY_MODULE")
            ),
            "by_module_model": _load_names_by_key(recommended["by_module_model"]),
            "vacuum_module_with_labware": _strings(recommended["vacuum_module_with_labware"]),
            "vacuum_dock_without_collar": _strings(recommended["vacuum_dock_without_collar"]),
            "vacuum_dock_with_collar": _strings(recommended["vacuum_dock_with_collar"]),
        },
        "module-models.json": {
            "source": source(
                (DECK_SETUP, "FLEX_MODULE_MODELS"),
                (DECK_SETUP, "OT2_MODULE_MODELS"),
                (DECK_SETUP, "FIXTURES"),
                (DECK_SETUP, "MOAM_MODELS"),
                (DECK_SETUP, "MOAM_MODELS_WITH_FF"),
                (ONBOARDING, "FLEX_SUPPORTED_MODULE_MODELS"),
                (ONBOARDING, "OT2_SUPPORTED_MODULE_MODELS"),
                (MODULE_DATA, "SUPPORTED_MODULE_TYPES"),
            ),
            "flex": _strings(value(DECK_SETUP, "FLEX_MODULE_MODELS")),
            "flex_supported_models": _strings(value(ONBOARDING, "FLEX_SUPPORTED_MODULE_MODELS")),
            "ot2": _strings(value(DECK_SETUP, "OT2_MODULE_MODELS")),
            "ot2_supported_models": _strings(value(ONBOARDING, "OT2_SUPPORTED_MODULE_MODELS")),
            "supported_module_types": _strings(value(MODULE_DATA, "SUPPORTED_MODULE_TYPES")),
            "moam_models": _strings(value(DECK_SETUP, "MOAM_MODELS")),
            "moam_models_with_feature_flag": _strings(value(DECK_SETUP, "MOAM_MODELS_WITH_FF")),
            "fixtures": _strings(value(DECK_SETUP, "FIXTURES")),
        },
        "module-slots.json": {
            "source": source(
                (MODULE_DATA, "SUPPORTED_MODULE_SLOTS_OT2"),
                (MODULE_DATA, "ALL_MODULE_SLOTS_OT2"),
                (slots_by_type["module"], "getAllModuleSlotsByTypeOt2"),
                (models_by_slot["module"], "getModuleModelsBySlot"),
                (ONBOARDING, "DEFAULT_SLOT_MAP_FLEX"),
                (ONBOARDING, "DEFAULT_SLOT_MAP_OT2"),
            ),
            "supported_slots_ot2": _slot_map(value(MODULE_DATA, "SUPPORTED_MODULE_SLOTS_OT2")),
            "all_slots_ot2": [
                _slot_option(option) for option in value(MODULE_DATA, "ALL_MODULE_SLOTS_OT2")
            ],
            "slots_by_module_type_ot2": _slot_map(slots_by_type["by_module_type"]),
            "models_by_slot": {
                robot: {slot: _strings(models, sort=False) for slot, models in by_slot.items()}
                for robot, by_slot in models_by_slot["by_robot"].items()
            },
            "default_slots_flex": dict(value(ONBOARDING, "DEFAULT_SLOT_MAP_FLEX")),
            "default_slots_ot2": dict(value(ONBOARDING, "DEFAULT_SLOT_MAP_OT2")),
        },
        "pipette-options.json": {
            "source": source(
                (ONBOARDING, "PIPETTE_GENS"),
                (ONBOARDING, "PIPETTE_TYPES"),
                (ONBOARDING, "PIPETTE_VOLUMES"),
            ),
            "gens": _strings(value(ONBOARDING, "PIPETTE_GENS"), sort=False),
            "by_robot": value(ONBOARDING, "PIPETTE_TYPES"),
            "volumes": value(ONBOARDING, "PIPETTE_VOLUMES"),
        },
        "module-limits.json": {
            "source": source(*LIMIT_EXPORTS),
            "limits": {name: _number(name, value(module, name)) for module, name in LIMIT_EXPORTS},
        },
    }

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    for name, payload in files.items():
        write_json(output_dir / name, payload)
    names = sorted([*files, "manifest.json"])
    write_json(
        output_dir / "manifest.json",
        {
            "schema_version": TABLES_SCHEMA_VERSION,
            "files": names,
            "protocol_designer": _pin(protocol_designer),
            "labware_definitions": labware_pin,
        },
    )
    return names


def validate_tables(tables_dir: Path) -> list[str]:
    """Return problems with a ``corpus/protocol-designer`` directory, if any."""
    manifest_path = tables_dir / "manifest.json"
    if not manifest_path.is_file():
        return [f"{TABLES_DIR}/manifest.json is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed = set(manifest.get("files", []))
    present = {p.name for p in tables_dir.iterdir() if p.is_file()}
    problems = [f"{TABLES_DIR}/{name} is listed but missing" for name in sorted(listed - present)]
    problems += [f"{TABLES_DIR}/{name} is not listed" for name in sorted(present - listed)]
    return problems


def _pin(source: ResolvedSource) -> dict[str, Any]:
    return {"repository": source.repository, "tag": source.tag, "commit": source.commit}


def _strings(values: Any, *, sort: bool = True) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        msg = f"Expected a list of strings, got {values!r}"
        raise ProtocolDesignerExportError(msg)
    return sorted(values) if sort else list(values)


def _text(value: Any) -> str:
    if not isinstance(value, str):
        msg = f"Expected a string, got {value!r}"
        raise ProtocolDesignerExportError(msg)
    return value


def _load_names_by_key(mapping: Mapping[str, Any]) -> dict[str, list[str]]:
    return {key: _strings(names) for key, names in mapping.items()}


def _slot_map(mapping: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    return {key: [_slot_option(option) for option in options] for key, options in mapping.items()}


def _slot_option(option: Mapping[str, Any]) -> dict[str, str]:
    slot = {"value": str(option["value"])}
    if option.get("name") != option["value"]:
        slot["name"] = str(option["name"])
    return slot


def _number(name: str, value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"Expected {name} to be a number, got {value!r}"
        raise ProtocolDesignerExportError(msg)
    return value


def _require_node() -> None:
    """The exporter runs on the Node.js version Opentrons edge pins."""
    try:
        completed = subprocess.run(
            ["node", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        msg = "node is not installed; Protocol Designer export needs Node.js >= 24.22.1"
        raise ProtocolDesignerExportError(msg) from exc
    raw = completed.stdout.strip().lstrip("v")
    try:
        found = tuple(int(part) for part in raw.split(".")[:3])
    except ValueError:
        found = ()
    if completed.returncode != 0 or found < MIN_NODE:
        required = ".".join(str(part) for part in MIN_NODE)
        msg = (
            f"Protocol Designer export needs Node.js >= {required} "
            f"(Opentrons edge); found {raw or 'none'}"
        )
        raise ProtocolDesignerExportError(msg)


def _run(cmd: list[str], *, cwd: Path) -> None:
    try:
        subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        msg = f"{cmd[0]} is not installed; the Protocol Designer exporter needs Node.js and npm"
        raise ProtocolDesignerExportError(msg) from exc
    except subprocess.CalledProcessError as exc:
        msg = f"{' '.join(cmd)} failed in {cwd}:\n{exc.stderr or exc.stdout}"
        raise ProtocolDesignerExportError(msg) from exc
