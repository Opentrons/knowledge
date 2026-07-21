#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OPENTRONS_REPO="${OPENTRONS_REPO:-$ROOT/../opentrons}"

cd "$ROOT"
uv sync --all-extras
uv run opentrons-knowledge build \
  --manifest corpora/9.1.1-k1/source-manifest.yaml \
  --opentrons-repo "$OPENTRONS_REPO" \
  --output dist
uv run opentrons-knowledge validate --corpus dist/opentrons-knowledge-9.1.1-k1
uv run opentrons-knowledge inspect --corpus dist/opentrons-knowledge-9.1.1-k1
