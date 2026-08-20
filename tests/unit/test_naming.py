import re

import pytest

from krci_testkit import naming
from krci_testkit.naming import (
    argo_app_name,
    branch_cr_name,
    image_stream_name,
    repo_path,
    stage_cr_name,
    stage_namespace,
    verified_stream_name,
)


def test_unique_name_is_dns1123_and_short():
    name = naming.unique_name("go")
    assert re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", name)
    assert len(name) <= 30
    assert name.startswith("at-go-")


def test_unique_name_stable_run_id_within_process():
    a, b = naming.unique_name("x"), naming.unique_name("x")
    assert a == b  # same prefix + same run id → same name (uniqueness comes from run id)


def test_run_id_honors_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KRCI_RUN_ID", "abc123")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    naming._cached_run_id = None
    assert naming.run_id() == "abc123"
    naming._cached_run_id = None


def test_run_id_is_per_worker_under_xdist(monkeypatch: pytest.MonkeyPatch):
    """A CI-provided KRCI_RUN_ID is SHARED by every parallel worker. Without the
    worker suffix two scenarios that happen to share a name prefix would land on
    the same Codebase from different workers and corrupt each other."""
    monkeypatch.setenv("KRCI_RUN_ID", "abc123")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    naming._cached_run_id = None
    first = naming.run_id()
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    naming._cached_run_id = None
    second = naming.run_id()
    assert first != second
    assert naming.unique_name("helm").startswith("at-helm-")
    naming._cached_run_id = None


def test_long_run_id_is_shortened_but_deterministic(monkeypatch: pytest.MonkeyPatch):
    """CI run ids (e.g. Tekton taskrun names) can be 30+ chars; naming must keep
    the unique entropy instead of letting name truncation chop it off."""
    monkeypatch.setenv("KRCI_RUN_ID", "krci-autotests-smoke-n9jsx-run")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    naming._cached_run_id = None
    first = naming.run_id()
    naming._cached_run_id = None
    second = naming.run_id()
    assert first == second  # deterministic for the same external id
    assert len(first) <= 8
    monkeypatch.setenv("KRCI_RUN_ID", "krci-autotests-smoke-zz111-run")
    naming._cached_run_id = None
    assert naming.run_id() != first  # different taskrun -> different short id
    naming._cached_run_id = None


def test_long_prefix_keeps_run_id_unique_across_xdist_workers(monkeypatch: pytest.MonkeyPatch):
    """Old bug: unique_name truncated the ASSEMBLED string to 30 chars, chopping the
    run-id suffix off a long prefix — two xdist workers with the same long prefix
    then computed the IDENTICAL name and fought over one CR."""
    monkeypatch.setenv("KRCI_RUN_ID", "abc123")
    long_prefix = "a-very-long-scenario-name-prefix-that-eats-the-budget"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    naming._cached_run_id = None
    first = naming.unique_name(long_prefix)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    naming._cached_run_id = None
    second = naming.unique_name(long_prefix)
    naming._cached_run_id = None
    assert first != second


def test_long_prefix_name_stays_within_budget_and_dns1123():
    name = naming.unique_name("a-very-long-scenario-name-prefix-that-eats-the-budget")
    assert len(name) <= 30
    assert re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", name)


def test_short_prefix_name_is_unaffected_by_the_truncation_fix(monkeypatch: pytest.MonkeyPatch):
    """Only the PREFIX must be truncated now, not the assembled string — a short
    prefix that never hit the old truncation must produce exactly the same name."""
    monkeypatch.setenv("KRCI_RUN_ID", "fixedid")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    naming._cached_run_id = None
    assert naming.unique_name("go") == "at-go-fixedid"
    naming._cached_run_id = None


def test_platform_name_rules():
    assert branch_cr_name("app", "main") == "app-main"
    assert image_stream_name("app", "main") == "app-main"
    assert stage_cr_name("pipe", "dev") == "pipe-dev"
    assert argo_app_name("pipe", "dev", "app") == "pipe-dev-app"
    assert verified_stream_name("pipe", "dev", "app") == "pipe-dev-app-verified"
    assert stage_namespace("krci", "pipe", "dev") == "krci-pipe-dev"


def test_repo_path_drops_the_separator_when_a_provider_has_no_group():
    """Gerrit projects are flat, so their path is the bare name. The operator reads
    gitUrlPath as the project id, and a doubled slash would become part of the name
    it asks the provider to create."""
    assert repo_path("mygroup", "app") == "/mygroup/app"
    assert repo_path("parent/team", "app") == "/parent/team/app"
    assert repo_path("", "app") == "/app"
    # A group written with separators of its own must not double them either.
    assert repo_path("/mygroup/", "app") == "/mygroup/app"
