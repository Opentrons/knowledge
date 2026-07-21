"""OCI artifact publish/pull via ORAS CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from opentrons_knowledge.errors import RegistryError
from opentrons_knowledge.models.manifest import CorpusManifest
from opentrons_knowledge.normalization.serialize import load_yaml


def ensure_oras() -> str:
    path = shutil.which("oras")
    if not path:
        raise RegistryError(
            "oras CLI not found on PATH. Install ORAS: https://oras.land/docs/installation"
        )
    return path


def publish_corpus(
    corpus_root: Path,
    *,
    registry_repo: str = "ghcr.io/opentrons/opentrons-knowledge",
    overwrite: bool = False,
) -> dict[str, str]:
    """Publish a corpus directory as an OCI artifact. Refuses overwrite by default."""
    oras = ensure_oras()
    manifest = CorpusManifest.model_validate(load_yaml(corpus_root / "manifest.yaml"))
    reference = f"{registry_repo}:{manifest.version}"

    if not overwrite and _remote_exists(oras, reference):
        raise RegistryError(
            f"Refusing to overwrite immutable corpus tag {reference}. Bump the knowledge revision."
        )

    annotations = {
        "org.opencontainers.image.title": "Opentrons Knowledge Corpus",
        "org.opencontainers.image.description": (
            f"Opentrons Knowledge corpus {manifest.version} for {manifest.target_opentrons_release}"
        ),
        "org.opencontainers.image.version": manifest.version,
        "org.opencontainers.image.revision": manifest.builder.commit or "",
        "org.opencontainers.image.source": "https://github.com/Opentrons/knowledge",
        "org.opencontainers.image.created": manifest.environment.build_timestamp,
        "org.opentrons.knowledge.target-release": manifest.target_opentrons_release,
        "org.opentrons.knowledge.schema-version": str(manifest.corpus_schema_version),
        "org.opentrons.knowledge.builder-version": manifest.builder.version,
        "org.opentrons.knowledge.formats": "oci,tar.zst",
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive_name = f"opentrons-knowledge-{manifest.version}.tar.gz"
        archive = tmp_path / archive_name
        _tar_directory(corpus_root, archive)
        # ORAS rejects absolute artifact paths unless path validation is disabled.
        # Push from the temp dir with a relative filename instead.
        cmd = [
            oras,
            "push",
            reference,
            f"{archive_name}:application/vnd.opentrons.knowledge.corpus.v1+tar+gzip",
        ]
        for key, value in annotations.items():
            if value:
                cmd.extend(["--annotation", f"{key}={value}"])
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=tmp_path,
            )
        except subprocess.CalledProcessError as exc:
            raise RegistryError(exc.stderr or str(exc)) from exc

    digest = _resolve_digest(oras, reference)
    return {"reference": reference, "digest": digest}


def pull_corpus(
    version: str,
    *,
    registry_repo: str = "ghcr.io/opentrons/opentrons-knowledge",
    destination: Path,
) -> Path:
    """Pull a corpus OCI artifact into destination/<version>."""
    oras = ensure_oras()
    reference = f"{registry_repo}:{version}"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cmd = [oras, "pull", reference, "--output", str(tmp_path)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise RegistryError(exc.stderr or str(exc)) from exc
        archives = list(tmp_path.glob("*.tar.gz")) + list(tmp_path.glob("*.tgz"))
        target = destination / version
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        if not archives:
            shutil.copytree(tmp_path, target, dirs_exist_ok=True)
            return target
        with tarfile.open(archives[0], "r:gz") as handle:
            handle.extractall(target, filter="data")
    return target


def _tar_directory(source: Path, archive: Path) -> None:
    with tarfile.open(archive, "w:gz") as handle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                handle.add(path, arcname=path.relative_to(source).as_posix())


def _remote_exists(oras: str, reference: str) -> bool:
    completed = subprocess.run(
        [oras, "manifest", "fetch", reference],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def _resolve_digest(oras: str, reference: str) -> str:
    completed = subprocess.run(
        [oras, "manifest", "fetch", "--descriptor", reference],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    try:
        descriptor = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ""
    return str(descriptor.get("digest", ""))
