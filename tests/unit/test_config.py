import os
from pathlib import Path

import pytest

from krci_testkit.config import load_config


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch):
    """These tests assert config-source precedence, so the developer's real
    KRCI_* environment (including values auto-loaded from the repo .env) must
    not leak in."""
    for key in list(os.environ):
        if key.startswith("KRCI_"):
            monkeypatch.delenv(key)


def test_env_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KRCI_NAMESPACE", "plat")
    monkeypatch.setenv("KRCI_PORTAL_URL", "https://portal.example.com")
    monkeypatch.setenv("KRCI_GIT_GROUP", "grp")
    monkeypatch.setenv("KRCI_GIT_SERVER", "gitlab")
    monkeypatch.setenv("KRCI_VERIFY_SSL", "false")
    cfg = load_config()
    assert cfg.namespace == "plat"
    assert cfg.verify_ssl is False
    assert cfg.kube_context is None  # in-cluster / current-context default


def test_portal_is_optional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """An API-only run must load without portal facts: requiring them would force
    every such run to invent a URL that nothing reads."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KRCI_NAMESPACE", "plat")
    monkeypatch.setenv("KRCI_GIT_GROUP", "grp")
    monkeypatch.setenv("KRCI_GIT_SERVER", "gitlab")
    cfg = load_config()
    assert cfg.portal_url is None
    assert cfg.portal_token is None


def test_dotenv_fills_values_and_process_env_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Documented precedence: process env > .env file."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "KRCI_NAMESPACE=from-dotenv\n"
        "KRCI_PORTAL_URL=https://p.example.com\n"
        "KRCI_GIT_GROUP=from-dotenv-grp\n"
        "KRCI_GIT_SERVER=gitlab\n"
    )
    monkeypatch.setenv("KRCI_NAMESPACE", "from-env")
    cfg = load_config()
    assert cfg.namespace == "from-env"  # process env wins
    assert cfg.git_group == "from-dotenv-grp"  # absent from env -> .env still fills it


def test_git_server_is_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Explicit provider selection: a run must declare which GitServer it tests."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KRCI_NAMESPACE", "plat")
    monkeypatch.setenv("KRCI_PORTAL_URL", "https://portal.example.com")
    monkeypatch.setenv("KRCI_GIT_GROUP", "grp")
    with pytest.raises(Exception, match="git_server"):
        load_config()
