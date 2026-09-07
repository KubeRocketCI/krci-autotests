"""Unit tests for bootstrap's provisioning waits.

bootstrap runs seconds after a deploy recreated the platform, so it has to tolerate a
GitServer the codebase-operator has not reconciled yet. The tests keep failing fast on a
disconnected server — that is them reporting the platform as they find it — which is why
the wait lives in bootstrap and not in connected_git_server."""

from typing import cast

import pytest

from krci_testkit.clusters import Cluster
from krci_testkit.config import KrciConfig
from krci_testkit.errors import NotFound
from krci_testkit.waits import Timeouts, WaitTimeout
from scripts import bootstrap

# _repo_exists only hands the cluster to collaborators, both stubbed below, so these
# tests never read it — constructing a real one would need a live API server.
_NO_CLUSTER = cast(Cluster, None)


def _cfg() -> KrciConfig:
    # Passed explicitly so a configured checkout's .env cannot decide what is under test.
    return KrciConfig(git_server="gerrit", git_group="grp", namespace="krci")


class _Vcs:
    def repo_exists(self, path: str) -> bool:
        return True


def _stub_vcs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "git_credentials", lambda cluster, git_server: {})
    monkeypatch.setattr(bootstrap, "vcs_client", lambda *args, **kwargs: _Vcs())


def test_repo_exists_waits_out_a_git_server_that_is_not_connected_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[str] = []

    def connects_on_the_third_read(cluster: object, name: str) -> str:
        reads.append(name)
        if len(reads) < 3:
            raise NotFound(f"GitServer/{name} exists but is not connected")
        return "git-server"

    monkeypatch.setattr(bootstrap, "connected_git_server", connects_on_the_third_read)
    _stub_vcs(monkeypatch)

    exists = bootstrap._repo_exists(
        _cfg(), _NO_CLUSTER, Timeouts(git_server_connected=5, poll_interval=0)
    )

    assert exists is True
    assert len(reads) == 3


def test_repo_exists_still_gives_up_when_the_git_server_never_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wait is bounded: a server that stays disconnected is a finding, not a hang."""

    def never_connects(cluster: object, name: str) -> str:
        raise NotFound(f"GitServer/{name} exists but is not connected")

    monkeypatch.setattr(bootstrap, "connected_git_server", never_connects)
    _stub_vcs(monkeypatch)

    with pytest.raises(WaitTimeout, match="GitServer/gerrit connected"):
        bootstrap._repo_exists(
            _cfg(), _NO_CLUSTER, Timeouts(git_server_connected=0, poll_interval=0)
        )
