# Discovery map (API tests)

Do not trust a catalog — catalogs drift. The code is the source of truth, and
fixture/flow docstrings state the ownership and sharing contract. This map says
what to discover, when, and where.

## When and where to look

| Before... | Discover in | How |
|---|---|---|
| adding a fixture | root `tests/conftest.py` (env + factories ONLY) and the owning suite's `conftest.py` | `uv run pytest --fixtures tests/api -q` prints every fixture with its docstring and source line |
| building a CR spec | pure `*_spec()` builders in `tests/utils/*_utils.py` | wire shape is unit-tested in `tests/unit/test_spec_builders.py` — read those tests for the exact output |
| writing a flow method | `tests/utils/<feature>_utils.py` | grep the verb first: `grep -rn "def .*branch" tests/utils/` |
| waiting for anything | `krci_testkit/waits.py` | read `wait_for` and `Timeouts` docstrings; raise `FailFast` inside a predicate for terminal failures; `not_found="fail"` when the resource must already exist |
| writing a name, label, or status value | `krci_testkit/naming.py`, `platform.py`, `labels.py` | StrEnums and label keys — never bare strings |
| touching models | `krci_testkit/models/__init__.py` | `GVK` registry, `spec_dict`, helpers; models are generated — `make generate`, never hand-edit |
| deploying | `tests/utils/deploy_utils.py`, `gitops_utils.py` | read the module docstrings; `render_deploy_run` renders the Stage's TriggerTemplate |
| reusing test data | `tests/test_data/` | one `<feature>_data.py` per feature: frozen dataclass + factory functions |

## Facts no single file states (keep pinned)

- `PipelineRuns` (tests/utils/pipelinerun_utils.py) only OBSERVES platform-rendered
  runs (`baseline` → act → `wait_success`); check it for a one-call composite
  (`submit_and_verify_change`: submit → review green → merge → build green)
  before composing lower-level calls.
- `built_codebase` (tests/api/deploy) is session-scoped: ONE real build shared
  read-only across deploy tests — never mutate it.
