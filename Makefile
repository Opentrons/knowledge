# Thin wrappers around the justfile. Prefer `just <recipe>`.

.PHONY: sync
sync:
	just sync

.PHONY: lint
lint:
	just lint

.PHONY: format
format:
	just format

.PHONY: typecheck
typecheck:
	just typecheck

.PHONY: test
test:
	just test

.PHONY: fixture-corpus
fixture-corpus:
	just fixture-corpus

.PHONY: build-9.1.1-k1
build-9.1.1-k1:
	just build-9-1-1-k1

.PHONY: validate
validate:
	just validate-9-1-1-k1

.PHONY: docs-build
docs-build:
	just docs-build

.PHONY: docs-validate
docs-validate:
	just docs-validate

.PHONY: build-10.0.0-k3
build-10.0.0-k3:
	just build-10-0-0-k3

.PHONY: retrieval-experiment
retrieval-experiment:
	just retrieval-experiment

.PHONY: retrieval-validate
retrieval-validate:
	just retrieval-validate

.PHONY: retrieval-audit
retrieval-audit:
	just retrieval-audit

.PHONY: retrieval-explore
retrieval-explore:
	just retrieval-explore

.PHONY: test-integration
test-integration:
	just test-integration

.PHONY: ci
ci:
	just ci

.PHONY: zizmor
zizmor:
	just zizmor
