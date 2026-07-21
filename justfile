# Opentrons Knowledge task runner
# Install: https://github.com/casey/just  (brew install just)
#
#   just              # list recipes
#   just sync         # install deps
#   just ci           # lint + typecheck + test + fixture corpus
#   just zizmor       # audit GitHub Actions workflows

set shell := ["bash", "-euo", "pipefail", "-c"]

python := "uv run"
opentrons_repo := env_var_or_default("OPENTRONS_REPO", "../opentrons")

# Keep in sync with .github/workflows/zizmor.yml `version:` input.
zizmor_version := "1.27.0"
zizmor_persona := "pedantic"
zizmor_min_severity := "low"

# List available recipes
default:
    @just --list

# Install package and dev dependencies
sync:
    uv sync --all-extras

# Lint with Ruff
lint:
    {{ python }} ruff check src tests
    {{ python }} ruff format --check src tests

# Auto-format and apply safe Ruff fixes
format:
    {{ python }} ruff format src tests
    {{ python }} ruff check --fix src tests

# Strict typecheck
typecheck:
    {{ python }} mypy

# Unit tests
test:
    {{ python }} pytest -q

# Build the deterministic fixture corpus (CI default)
fixture-corpus:
    {{ python }} opentrons-knowledge build --fixture --output dist

# Build the 9.1.1-k1 corpus from a local Opentrons checkout
build-9-1-1-k1:
    {{ python }} opentrons-knowledge build \
        --manifest corpora/9.1.1-k1/source-manifest.yaml \
        --opentrons-repo {{ opentrons_repo }} \
        --output dist

# Validate the built 9.1.1-k1 corpus
validate-9-1-1-k1:
    {{ python }} opentrons-knowledge validate --corpus dist/opentrons-knowledge-9.1.1-k1

# Pack 9.1.1-k1 into tar.zst
pack-9-1-1-k1:
    {{ python }} opentrons-knowledge pack \
        --corpus dist/opentrons-knowledge-9.1.1-k1 \
        --overwrite

# Full local CI gate
ci: lint typecheck test fixture-corpus

# -----------------------------------------------------------------------------
# GitHub Actions (zizmor)
# -----------------------------------------------------------------------------

# Audit workflows (offline; same persona/severity as CI)
zizmor:
    uvx zizmor@{{ zizmor_version }} \
        --persona={{ zizmor_persona }} \
        --min-severity={{ zizmor_min_severity }} \
        --min-confidence=high \
        --format=plain \
        .

# Audit with GitHub API (pin verification and online rules)
zizmor-online:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -z "${GH_TOKEN:-}" ]]; then
        if command -v gh >/dev/null 2>&1; then
            export GH_TOKEN="$(gh auth token)"
        else
            echo "!! Set GH_TOKEN or install and authenticate gh." >&2
            exit 1
        fi
    fi
    uvx zizmor@{{ zizmor_version }} \
        --persona={{ zizmor_persona }} \
        --min-severity={{ zizmor_min_severity }} \
        --min-confidence=high \
        --format=plain \
        .

# Apply safe autofixes (e.g. persist-credentials)
zizmor-fix:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -z "${GH_TOKEN:-}" ]]; then
        if command -v gh >/dev/null 2>&1; then
            export GH_TOKEN="$(gh auth token)"
        else
            echo "!! Set GH_TOKEN or install and authenticate gh." >&2
            exit 1
        fi
    fi
    uvx zizmor@{{ zizmor_version }} --persona={{ zizmor_persona }} --fix=safe .

# Refresh action SHA pins to match tag comments (requires GitHub API)
zizmor-fix-pins:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -z "${GH_TOKEN:-}" ]]; then
        if command -v gh >/dev/null 2>&1; then
            export GH_TOKEN="$(gh auth token)"
        else
            echo "!! Set GH_TOKEN or install and authenticate gh." >&2
            exit 1
        fi
    fi
    uvx zizmor@{{ zizmor_version }} --persona={{ zizmor_persona }} --fix=all .
