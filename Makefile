.DEFAULT_GOAL := help

.PHONY: help install generate lint format preflight bootstrap scenarios unit-tests test list suites

help: ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Setup

install: ## Install dependencies into .venv (uv) and the Playwright chromium browser
	uv sync --all-groups
	uv run playwright install chromium

generate: ## Regenerate Pydantic CRD models from pinned schemas (codegen/sources.yaml)
	uv run python codegen/generate.py

##@ Quality

lint: ## Run ruff checks, format check, the import-linter layering gate and pyright
	uv run ruff check .
	uv run ruff format --check .
	uv run lint-imports
	uv run pyright
	uv run python scripts/suite.py check

format: ## Auto-fix ruff findings and reformat the codebase
	uv run ruff check --fix .
	uv run ruff format .

unit-tests: ## Verify the testkit itself (offline, no cluster required)
	uv run pytest tests/unit -n auto

##@ Environment

preflight: ## Verify the target environment (cluster, GitServer, portal) before any test
	uv run python scripts/preflight.py

bootstrap: ## Onboard the environment prerequisites deploy runs need (gitops codebase)
	uv run python scripts/bootstrap.py

##@ Tests

test: ## Run a suite from suites.yaml, e.g. make test SUITE=smoke
	@test -n "$(SUITE)" || (echo "usage: make test SUITE=<name>  (see 'make suites')"; exit 1)
	uv run python scripts/suite.py run $(SUITE)

list: ## Show which tests a suite would run, e.g. make list SUITE=regression
	@test -n "$(SUITE)" || (echo "usage: make list SUITE=<name>  (see 'make suites')"; exit 1)
	uv run python scripts/suite.py run $(SUITE) --collect-only -q

suites: ## List the defined suites with their case counts
	uv run python scripts/suite.py list

scenarios: ## Print the human-readable Given/When/Then scenario catalog
	uv run python scripts/scenarios.py
