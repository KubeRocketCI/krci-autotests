# krci-autotests — architecture rules

Platform-level E2E suite for KubeRocketCI. Tests cross-component journeys ONLY
(onboard → build → deploy); single-operator checks belong in the operator's own repo.

## Layering (enforced by import-linter — `make lint`)

tests/* → tests/utils + tests/ui/pageobjects → krci_testkit → external libs

- Raw `kr8s`/`kubernetes`/`httpx`/`requests`: ONLY inside `krci_testkit` (and `scripts/`).
- Playwright imports: ONLY under `tests/ui/`.
- `krci_testkit` never imports `tests/`. Generated `krci_testkit/models/*`: never hand-edit; re-run `make generate`.

## Hard authoring rules

- Testkit-first: no raw HTTP or raw-dict CRD manipulation in tests. CR specs are built
  from the GENERATED models via the pure `*_spec()` builders in `tests/utils`, serialized
  with `models.spec_dict` (exclude_unset + exclude_none: only declared fields go on the wire).
- Every test owns uniquely-named resources via `krci_testkit.naming.unique_name`; cleanup via
  yield fixtures only. Shared state is read-only; mutable shared state is banned.
- WHAT a codebase is built from is a `Stack` in `tests/test_data/stacks.py` (the platform's
  pipeline selector); HOW it is onboarded is one of the three strategy builders in
  `codebase_data`. Adding a language is one `CATALOG` entry, never a new factory.
- Codebases come from the `owned_codebase` / `owned_imported_codebase` FACTORY fixtures in
  the root conftest; a scenario declares its own test data in the conftest of the suite that
  owns it. Never add a scenario-specific fixture to the root conftest. Every scenario needs
  its own `unique_name` prefix — the factory raises on a repeat.
- Platform value vocabulary (pipeline types, ArgoCD sync/health) lives in
  `krci_testkit.platform` as StrEnums; label KEYS live in `krci_testkit.labels`. Never write
  either as a bare string.
- No `if provider ==` / `if flavor ==` in test bodies or utils — provider facts come from the
  `GitServer` fixture; use neutral vocabulary (submit_change/merge, not create_pull_request).
- No conditionals or loops in test bodies; parametrize instead.
- ANNOTATE every fixture parameter of a test function (`vcs: VCSProvider`,
  `pipeline_runs: PipelineRuns`, ...). Without annotations the parameter is `Any` and
  pyright checks nothing in the body — that is what let a bare `"review"` string past the
  PipelineType enum. The annotation is what makes the vocabulary rules enforceable.
- No environment values (hosts, namespaces, context names, secret names) in code — everything
  through `KrciConfig`.
- Waits only via `krci_testkit.waits.wait_for` (transient-error allowlist; no blanket except).
- Output discipline: test bodies are silent (assertions only — no print, no logging); support
  layers (`krci_testkit`, `tests/utils`) narrate step boundaries via
  `logging.getLogger(__name__).info(...)` — one line per meaningful action, not per poll;
  noisy third-party loggers get demoted to WARNING in `tests/conftest.py`; rendering is
  config (`log_cli`), never code. One log call feeds terminal, failure report and
  ReportPortal alike.
- Timeout layering: run knobs are declared ONCE as fields on `krci_testkit.waits.Timeouts`
  (the ini option and the `timeouts` fixture both derive from `timeout_knobs()`); override with
  `-o` / `PYTEST_ADDOPTS`; workload cost lives in test data as `*_timeout_factor` multipliers
  (effective wait = knob × factor); `KrciConfig` holds target facts only (URLs/tokens/namespace)
  — never add tuning knobs to it. Never hardcode a timeout in a test body or flow, including
  `@pytest.mark.timeout(...)`: the per-test kill switch is derived from the knobs in
  `tests/conftest.py` so raising a knob cannot get the test killed before its own WaitTimeout.
- Every test docstring is a full Given/When/Then scenario incl. what is deliberately NOT
  asserted — it is the human-readable spec (`make scenarios` prints the catalog; ReportPortal
  shows it per run).
- Comments/docstrings state platform facts and current behavior ONLY — never how the fact
  was learned or when it appeared: no Jira/ticket IDs, no "verified against <repo>", no
  source-file paths of other repos, no "on platforms that predate X", no plan/option/review
  narration. A comment exists only for a genuinely unobvious WHY the code cannot express;
  match the file's existing comment density (for plain dataclass fields that is usually
  none). Provenance lives in the commit message, not the code.
- Markers describe a TEST's own properties, never its suite membership: SURFACE is
  `api`/`ui` (a mixed test carries the marker of its dominant assertion surface), plus
  `serial` for genuinely serial tests. Every marker is registered in `pyproject.toml` —
  an unregistered one silently selects nothing.
- SUITES are data, not markers: `suites.yaml` maps a name to a list of pytest targets
  (directory, file, or one parametrized case). A test declares nothing, so it can belong
  to any number of suites and a new suite costs no test edits. Run one with
  `make test SUITE=<name>`. The trade is that a test no suite names would silently never
  run — `scripts/suite.py check` (part of `make lint`) fails on an orphan test and on an
  entry left behind by a rename.
- Test naming: CRUD chains are `test_<subject>_[<variant>_]lifecycle`
  (`test_codebase_create_lifecycle`, `test_feature_branch_lifecycle`); single-behavior
  tests read as trigger→effect (`test_recheck_comment_reruns_review`); deploy flows are
  `test_<mode>_<flow>` (`test_manual_deploy`, `test_platform_journey`). Names are STABLE
  IDs — ReportPortal keys history on them; renaming resets that history.
- Manual deploys replicate the portal: render the Stage's TriggerTemplate via
  `tests/utils/deploy_utils.render_deploy_run` — never hand-build a PipelineRun
  manifest. Auto deploys are never triggered by tests at all.
- One-time/shared setup goes in a script under `scripts/` (run via make), NEVER in pytest
  fixtures — no exceptions: `scripts/preflight.py` (`make preflight`) verifies the
  environment, `scripts/bootstrap.py` (`make bootstrap`) onboards environment
  prerequisites (the gitops codebase). Tests NEVER provision a platform prerequisite,
  check that one is present, or repair one that is broken. A deploy run against a
  namespace with no gitops repo is expected to fail, and that failure is the finding —
  a suite that arranges the state it then grades is measuring itself.
- Expensive prerequisites: seed via API/CR shortcuts, never depend on another test's output.
- Assert only platform-computed state, never values the test itself injected (a green
  tautology covers nothing). Self-created resources (e.g. a directly-created PipelineRun)
  validly test behavior *downstream* of their creation; testing how the platform *produces*
  such resources (webhook → interceptor → template rendering) requires the real event path.

## Workflow

`make install` → `make preflight` → `make bootstrap` → `make test SUITE=smoke`. Lint gate:
`make lint` (ruff + import-linter + pyright + suite check) must pass before commit. Writing tests: use the `api-test-writer` /
`ui-test-writer` skills.
