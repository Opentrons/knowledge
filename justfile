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
# Canonical docs corpus (rendered MkDocs HTML)
# -----------------------------------------------------------------------------

docs_manifest := "corpora/10.0.0-k2/source-manifest.yaml"

# Render the pinned Opentrons MkDocs site into dist/.work (isolated checkout)
docs-build-site:
    {{ python }} opentrons-knowledge docs build-site \
        --manifest {{ docs_manifest }} \
        --opentrons-repo {{ opentrons_repo }}

# Render the pinned site and write dist/canonical-docs
docs-build:
    {{ python }} opentrons-knowledge docs build \
        --manifest {{ docs_manifest }} \
        --opentrons-repo {{ opentrons_repo }} \
        --output dist/canonical-docs

# Validate dist/canonical-docs (checksums, inventory, section graph)
docs-validate:
    {{ python }} opentrons-knowledge docs validate --corpus dist/canonical-docs

# Summarize dist/canonical-docs, or one page with DOC=python-api/pipettes/loading/
docs-inspect:
    {{ python }} opentrons-knowledge docs inspect --corpus dist/canonical-docs \
        {{ if env_var_or_default("DOC", "") != "" { "--document " + env_var("DOC") } else { "" } }}

# -----------------------------------------------------------------------------
# Retrieval (documents, chunks, HDE-native BM25 index)
# -----------------------------------------------------------------------------

retrieval_corpus := "dist/opentrons-knowledge-10.0.0-k5"

# Build the 10.0.0-k5 corpus (k4 plus evaluated Protocol Designer compatibility JSON)
build-10-0-0-k5:
    {{ python }} opentrons-knowledge build \
        --manifest corpora/10.0.0-k5/source-manifest.yaml \
        --opentrons-repo {{ opentrons_repo }} \
        --output dist

# Build the 10.0.0-k4 corpus (k3 plus the Protocol Designer allowlist as a raw file)
build-10-0-0-k4:
    {{ python }} opentrons-knowledge build \
        --manifest corpora/10.0.0-k4/source-manifest.yaml \
        --opentrons-repo {{ opentrons_repo }} \
        --output dist

# Build the 10.0.0-k3 corpus (canonical docs + retrieval bundle + experiment report)
build-10-0-0-k3:
    {{ python }} opentrons-knowledge build \
        --manifest corpora/10.0.0-k3/source-manifest.yaml \
        --opentrons-repo {{ opentrons_repo }} \
        --output dist

# Re-run the retrieval experiment grid against a built corpus
retrieval-experiment:
    {{ python }} opentrons-knowledge retrieval experiment \
        --corpus {{ retrieval_corpus }} \
        --report dist/retrieval-eval.json \
        --markdown dist/retrieval-eval.md

# Validate the retrieval bundle in the built corpus
retrieval-validate:
    {{ python }} opentrons-knowledge retrieval validate --bundle {{ retrieval_corpus }}/retrieval

# Search the built bundle: just retrieval-search "InstrumentContext.blow_out" api
retrieval-search query index="both":
    {{ python }} opentrons-knowledge retrieval search "{{ query }}" \
        --bundle {{ retrieval_corpus }}/retrieval --index {{ index }}

# Interactive search over both indexes
retrieval-explore:
    {{ python }} opentrons-knowledge retrieval explore \
        --bundle {{ retrieval_corpus }}/retrieval

# Every documented symbol must come back as the first API hit
retrieval-audit:
    {{ python }} opentrons-knowledge retrieval audit \
        --bundle {{ retrieval_corpus }}/retrieval

# Regenerate schemas/canonical-*.schema.json and retrieval-*.schema.json
schemas:
    {{ python }} python scripts/write_canonical_schemas.py

# Check the latest built package. Build it first; this does not render docs again.
test-integration:
    {{ python }} pytest -q tests/integration

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
