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

.PHONY: ci
ci:
	just ci

.PHONY: zizmor
zizmor:
	just zizmor
