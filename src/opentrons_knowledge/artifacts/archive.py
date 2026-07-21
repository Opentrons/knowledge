"""Pack and unpack corpus directories as tar.zst artifacts."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import zstandard as zstd

from opentrons_knowledge.errors import ArtifactError
from opentrons_knowledge.models.manifest import CorpusManifest
from opentrons_knowledge.normalization.serialize import file_sha256, load_yaml


def corpus_archive_name(version: str) -> str:
    """Filename for a published corpus archive."""
    return f"opentrons-knowledge-{version}.tar.zst"


def pack_corpus(
    corpus_root: Path,
    *,
    output: Path | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """Create a tar.zst archive of a built corpus directory."""
    if not (corpus_root / "manifest.yaml").exists():
        raise ArtifactError(f"Not a corpus directory: {corpus_root}")
    manifest = CorpusManifest.model_validate(load_yaml(corpus_root / "manifest.yaml"))
    archive_path = output or (corpus_root.parent / corpus_archive_name(manifest.version))
    if archive_path.exists() and not overwrite:
        raise ArtifactError(
            f"Refusing to overwrite existing archive {archive_path}. "
            "Pass overwrite=True or remove the file."
        )
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    compressor = zstd.ZstdCompressor(level=3)
    with (
        archive_path.open("wb") as raw,
        compressor.stream_writer(raw) as zst_out,
        tarfile.open(fileobj=zst_out, mode="w|") as tar,
    ):
        for path in sorted(corpus_root.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(corpus_root).as_posix())

    digest = file_sha256(archive_path)
    return {
        "version": manifest.version,
        "archive": str(archive_path),
        "sha256": f"sha256:{digest}",
        "bytes": str(archive_path.stat().st_size),
    }


def unpack_corpus(archive_path: Path, destination: Path) -> Path:
    """Extract a tar.zst corpus archive into destination/<version> or destination."""
    if not archive_path.exists():
        raise ArtifactError(f"Archive not found: {archive_path}")

    decompressor = zstd.ZstdDecompressor()
    with archive_path.open("rb") as raw, decompressor.stream_reader(raw) as reader:
        # tarfile needs a seekable or buffered stream; read into BytesIO for reliability
        data = reader.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        # Peek manifest for version if destination should include version dir
        members = tar.getmembers()
        if not any(m.name == "manifest.yaml" for m in members):
            raise ArtifactError("Archive is missing manifest.yaml")
        destination.mkdir(parents=True, exist_ok=True)
        tar.extractall(destination, filter="data")

    if not (destination / "manifest.yaml").exists():
        raise ArtifactError(f"Unpack did not produce manifest.yaml under {destination}")
    return destination
