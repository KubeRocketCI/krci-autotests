# krci-autotests

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Platform-level E2E test suite for KubeRocketCI: pytest + Playwright over `krci_testkit`,
a thin typed client for the platform's CRDs.

Tests exercise cross-component journeys — onboard a codebase, let the platform's own
webhook → EventListener → TriggerTemplate chain render review and build PipelineRuns,
deploy through CD stages, assert the resulting cluster state. Single-operator behavior
belongs in that operator's own repo, not here.

Coverage:

- **Codebase lifecycle** — create, import and clone onboarding strategies; branch CRUD
  (feature and release branches with their per-branch review/build runs); review recheck
  via a `/recheck` comment; squash-merge build triggering.
- **CD flows** — manual Deploy (portal-parity TriggerTemplate render), AutoDeploy, and
  stage-to-stage Promote via verified image streams, asserted through deploy PipelineRuns,
  ArgoCD Application health and CodebaseImageStream tags.
- **Portal UI** — token login, Overview widgets, Projects list.

VCS access goes through the `VCSProvider` protocol; clients exist for GitLab, GitHub and
Bitbucket Cloud. Gerrit raises `UnsupportedProvider`. Where a provider has no native
equivalent of a neutral merge strategy (GitHub has no fast-forward merge), the client raises
`UnsupportedMergeStrategy` rather than substituting a near-equivalent.

The suite is environment-neutral: no cluster names, hosts or namespaces are hardcoded.
Everything comes from configuration you provision per environment. Self-signed certificates
are supported via `KRCI_VERIFY_SSL` / `KRCI_CA_BUNDLE`.

## Quick start

Needs [uv](https://docs.astral.sh/uv/) (it installs Python 3.14 per `.python-version`), a
running KubeRocketCI cluster, and a kubeconfig context that reaches it.

```bash
make install                      # dependencies + playwright chromium
make unit-tests                   # offline check of the testkit — no cluster needed

cp .env.example .env              # then fill the four values below
make preflight                    # verify the cluster, GitServer, VCS auth and RBAC
make bootstrap                    # onboard the gitops codebase — once per environment
make test SUITE=smoke-api         # ~10 min against the cluster
```

The four values `.env` must carry for an API run:

```bash
KRCI_NAMESPACE=      # platform namespace holding the KRCI CRs
KRCI_GIT_SERVER=     # GitServer CR name to test, e.g. gitlab
KRCI_GIT_GROUP=      # VCS group/org the suite creates repos in, e.g. mygroup
KRCI_KUBE_CONTEXT=   # only if the cluster is not your current kubeconfig context
```

Add `KRCI_PORTAL_URL` and `KRCI_PORTAL_TOKEN` for the UI suite (`make test SUITE=smoke-ui`); an
API-only run needs neither. Every other variable has a working default — see
[Configuration](#configuration).

The API suite creates **real resources on the target cluster and Git server**: uniquely named
codebases, their repositories, and changes that get merged. Point `KRCI_GIT_GROUP` at a group
you are happy to have written to.

## Configuration

Define `KEY=VALUE` in `.env`; it is auto-loaded at pytest startup, and real environment
variables win over file values. Copy `.env.example` to `.env` to start.

| Variable            | Meaning                                                                  | Default         |
|---------------------|--------------------------------------------------------------------------|-----------------|
| `KRCI_KUBE_CONTEXT` | kubeconfig context; empty = current context / in-cluster                 | empty           |
| `KRCI_NAMESPACE`    | platform namespace holding KRCI CRs                                      | required        |
| `KRCI_PORTAL_URL`   | portal base URL                                                          | required for UI |
| `KRCI_PORTAL_TOKEN` | ServiceAccount bearer token for portal login                             | required for UI |
| `KRCI_GIT_GROUP`    | VCS group/org path prefix for created repos (see below)                  | required        |
| `KRCI_GIT_SERVER`   | GitServer CR name to test — always explicit; change `KRCI_GIT_GROUP` together with it (org paths differ per provider) | required |
| `KRCI_GITHUB_TOKEN` | token for template-tarball fetches from api.github.com (import seeds); anonymous is ~60/hour — required in practice for `import-matrix` | empty |
| `KRCI_VERIFY_SSL`   | TLS verification (false for self-signed environments)                    | `true`          |
| `KRCI_CA_BUNDLE`    | optional CA bundle path                                                  | empty           |
| `KRCI_RUN_ID`       | run identity suffix for resource names                                   | auto-generated  |

### Git group

`KRCI_GIT_GROUP` is a group/org path and nothing else: no scheme, no host (the `GitServer` CR
carries `gitHost`), no surrounding slashes, no repo name. Each test appends its own uniquely
named repo, so `mygroup` produces `gitUrlPath: /mygroup/at-helm-a1b2c3`.

Nested groups (`mygroup/subgroup`) work on GitLab, whose API addresses a project by its full
URL-encoded path. GitHub and Bitbucket address repos as `<owner>/<repo>` and take one segment.

### Portal token

Any ServiceAccount token the portal accepts, e.g.

```bash
kubectl -n <platform-ns> create token <admin-sa> --duration=24h
```

The SA needs enough RBAC to read what the portal shows. Tokens are typically short-lived —
refresh before a run.

An API-only run needs no portal at all: leave both `KRCI_PORTAL_*` empty and `make preflight`
reports them as skipped instead of failed.

### Timeouts

Run-behavior knobs are **pytest ini options**, not env config. They are declared once as
fields on `krci_testkit.waits.Timeouts`; the ini registration and the `timeouts` fixture
both derive from that, so adding a knob is a single edit.

| Option                         | Default |
|--------------------------------|---------|
| `krci_timeout_codebase_ready`  | 600     |
| `krci_timeout_build_success`   | 900     |
| `krci_timeout_codebase_delete` | 180     |
| `krci_timeout_run_trigger`     | 300     |
| `krci_timeout_change_merge`    | 180     |
| `krci_timeout_deploy_success`  | 900     |
| `krci_timeout_ui_expect`       | 15      |
| `krci_poll_interval`           | 5       |

Override per run with `pytest -o krci_timeout_build_success=1800`, or
`PYTEST_ADDOPTS="-o krci_timeout_build_success=1800"` in CI. Per-workload cost lives in test
data as `build_timeout_factor` multipliers (effective wait = knob × factor).

## Running

```bash
make install          # uv sync (installs Python 3.14 automatically) + playwright chromium
make preflight        # verify the target environment before any test
make bootstrap        # onboard environment prerequisites (gitops codebase), once per env
make unit-tests       # offline tests of the testkit itself (no cluster)
make suites                    # the defined suites and their case counts
make test SUITE=smoke          # full smoke (API + UI)
make test SUITE=smoke-api      # API smoke only
make test SUITE=smoke-ui       # UI smoke only (headless)
make test SUITE=regression     # core regression (onboarding, branch CRUD, deploy flows)
make test SUITE=stack-matrix   # onboarding for every stack in the catalog (long)
make test SUITE=journey     # full-chain provider-certification journey
make scenarios        # print the human-readable Given/When/Then catalog
make lint             # ruff + import-linter layering gate
```

### Environment prerequisites

`make bootstrap` onboards what deploy scenarios need from the platform but never create
themselves — today the gitops system codebase. It adopts an existing repo with the import
strategy and provisions a new one otherwise, so re-running it after a partial cleanup is
safe. Run it once per environment.

Tests do not check for it. A deploy run against a namespace without a gitops repo fails on
the ArgoCD assertion, which is the platform's own answer rather than a guard the suite
supplies.

Multi-GitServer clusters — one process per provider; run-ID naming keeps parallel runs
collision-free:

```bash
KRCI_GIT_SERVER=gitlab KRCI_GIT_GROUP=krci  make test SUITE=regression &
KRCI_GIT_SERVER=github KRCI_GIT_GROUP=myorg make test SUITE=regression &
```

Smoke defaults to the platform's lightest build (helm library: lint + template) for fast
feedback; heavier factories (go application: compile + sonar + container build) live in
`tests/test_data/`. Teardown removes VCS repos best-effort, so the account behind the
`GitServer` secret needs permission to delete them.

UI debugging:

```bash
uv run pytest tests/ui -m smoke -n 0 --headed --slowmo 300
```

ReportPortal is optional: define `RP_ENDPOINT`, `RP_PROJECT`, `RP_API_KEY` in `.env` and any
`make test SUITE=...` run publishes a launch. Without them the suite runs identically with console
output only.

## Layout

```
krci_testkit/     typed CRD clients, config, waits, VCS provider clients
  models/         Pydantic CRD models — generated, never hand-edited (make generate)
  clients/        GitLab / GitHub / Bitbucket behind the VCSProvider protocol
tests/
  api/            CRD-level journeys (codebase, branch, deploy, review, journey)
  ui/             Playwright tests + page objects
  utils/          flow-level wrappers + pure CR-spec builders
  test_data/      factories — no literals in test bodies
  */conftest.py   each suite owns its scenarios' fixtures; the root holds only
                  environment fixtures and the owned_codebase factory
  unit/           offline tests of the testkit itself
scripts/          environment preflight and bootstrap, scenario catalog
codegen/          CRD model generation from pinned schemas
```

Layering is enforced by import-linter (`make lint`):
`tests/* → tests/utils + tests/ui/pageobjects → krci_testkit → external libs`. Raw
`kr8s`/`httpx`/`requests` live only inside `krci_testkit`; Playwright only under `tests/ui/`.
See `CLAUDE.md` for the full authoring rules.

## Known limitations

- Portal auth is ServiceAccount-token only; no Keycloak flow.
- VCS repo cleanup is best-effort teardown via the provider client (the codebase-operator
  deliberately never deletes remote repos). A leftover repo survives only if teardown itself
  dies, and unique run-ID names keep leftovers collision-free.
- One provider is exercised per environment — whatever the cluster's `GitServer` is. Only
  GitLab is live-validated; the GitHub and Bitbucket Cloud clients are unit-verified and
  need a matching environment to certify.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
