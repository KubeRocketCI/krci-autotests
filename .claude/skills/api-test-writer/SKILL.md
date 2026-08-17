---
name: api-test-writer
description: This skill should be used when the user asks to "write an API test", "add a platform E2E test", "cover a CRD or PipelineRun flow", or changes files under tests/api, tests/utils, or tests/test_data in krci-autotests.
---

# API test writer

CLAUDE.md holds the hard rules (layering, markers, naming, timeouts, assertion
validity, output discipline) and always loads — do not restate it; on conflict,
CLAUDE.md wins. This skill adds the build order and repo facts CLAUDE.md omits.

## Recipe

1. Discover before writing: `references/fixtures.md` is the map of where
   existing fixtures, flows, and spec builders live and how to list them —
   the code and its docstrings are the source of truth.
2. Build bottom-up:
   a. test data in `tests/test_data/<feature>_data.py` — dataclass + factory,
      own `unique_name` prefix, declare `*_timeout_factor` if the workload is
      heavier than the default;
   b. flow methods in `tests/utils/<feature>_utils.py`;
   c. the test in `tests/api/<area>/test_<feature>.py`; scenario fixtures go in
      that suite's own conftest.
3. Mark `@pytest.mark.api` plus the suite marker (`smoke`/`regression`/`journey`).
4. Run `make lint` and the new test with `--reruns 0`; both must pass.

## Repo facts beyond CLAUDE.md

- Waits narrate themselves via `wait_for(describe=...)` — flow methods log other
  step boundaries once per action, never around a wait.
- Deletion: yield-fixture teardown is the safety net; add asserted deletion steps
  only where deletion IS the behavior under test.
- Assertion triage: if a field on a self-triggered run matters as INPUT to
  downstream behavior, put it in the created spec and assert the downstream
  effect; if it matters as platform OUTPUT, the test needs the real trigger path
  (webhook → EventListener → TriggerTemplate), not a bigger self-built spec.
- New CRD Kind: add it to `codegen/sources.yaml` + the `GVK` registry, then run
  `make generate` — never hand-write models.
