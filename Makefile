.DEFAULT_GOAL := help

.PHONY: help install generate lint format preflight bootstrap scenarios unit-tests test-smoke list-smoke test-smoke-api test-smoke-ui test-regression list-regression

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

test-smoke: ## Run the full smoke suite (API + UI), fully parallel
	uv run pytest -m smoke -n 3 --dist load --reruns 0

list-smoke: ## Show which tests `make test-smoke` would run (no execution)
	uv run pytest -m smoke --collect-only -q

test-smoke-api: ## Run the API smoke only (3 parallel workers by design)
	uv run pytest -m "smoke and api" -n 3 --dist load --reruns 0

test-smoke-ui: ## Run the UI smoke only (headless)
	uv run pytest -m "smoke and ui" -n 0 --reruns 0

test-regression: ## Run the core regression suite (branch CRUD + deploy flows), single worker
	uv run pytest -m regression -n 0 --reruns 0

test-journey: ## Run the full-chain journey (provider certification), single worker
	uv run pytest -m journey -n 0 --reruns 0

list-regression: ## Show which tests `make test-regression` would run (no execution)
	uv run pytest -m regression --collect-only -q

scenarios: ## Print the human-readable Given/When/Then scenario catalog
	uv run python scripts/scenarios.py
