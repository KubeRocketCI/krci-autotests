"""Unit tests for GitLabClient verb -> endpoint translation (mock transport, no network)."""

import json

import pytest

from krci_testkit import clients
from krci_testkit.clients import UnsupportedProvider, vcs_client
from krci_testkit.clients.gitlab import GitLabClient
from krci_testkit.clients.protocol import Change, CommitStatus, MergeStrategy, VCSProvider
from krci_testkit.models import GitProvider, GitServer
from krci_testkit.platform import CIStatus
from krci_testkit.waits import WaitTimeout
from tests.unit.vcs_mock import Recorder


def _gitserver(provider: str = "gitlab") -> GitServer:
    return GitServer.model_validate(
        {
            "apiVersion": "v2.edp.epam.com/v1",
            "kind": "GitServer",
            "metadata": {"name": provider},
            "spec": {
                "gitHost": "git.example.test",
                "gitProvider": provider,
                "gitUser": "git",
                "httpsPort": 443,
                "nameSshKeySecret": "ci-creds",
                "sshPort": 22,
            },
        }
    )


def _client(recorder: Recorder) -> GitLabClient:
    return GitLabClient(
        "https://git.example.test",
        "tok",
        transport=recorder.transport,
        merge_timeout=1,
        poll_interval=0,
    )


def test_submit_change_creates_branch_commit_and_change():
    proj = "/api/v4/projects/grp/app"
    rec = Recorder(
        {
            ("POST", f"{proj}/repository/branches"): [(201, {"name": "chg-1"})],
            ("POST", f"{proj}/repository/commits"): [(201, {"id": "sha"})],
            ("POST", f"{proj}/merge_requests"): [
                (201, {"iid": 7, "web_url": "https://git.example.test/grp/app/-/merge_requests/7"})
            ],
        }
    )
    change = _client(rec).submit_change(
        "/grp/app",
        source_branch="chg-1",
        target_branch="main",
        title="test: smoke",
        files={"chg-1.txt": "content\n"},
    )
    assert change.id == "7"
    assert change.source_branch == "chg-1"
    commit_body = json.loads(rec.requests[1].content)
    assert commit_body["actions"] == [
        {"action": "create", "file_path": "chg-1.txt", "content": "content\n"}
    ]
    assert rec.requests[0].headers["PRIVATE-TOKEN"] == "tok"
    assert b"/projects/grp%2Fapp/" in rec.requests[0].url.raw_path  # project id stays URL-encoded


def test_merge_change_polls_until_mergeable_then_merges():
    proj = "/api/v4/projects/grp/app"
    rec = Recorder(
        {
            ("GET", f"{proj}/merge_requests/7"): [
                (200, {"detailed_merge_status": "checking"}),
                (200, {"detailed_merge_status": "mergeable"}),
            ],
            ("PUT", f"{proj}/merge_requests/7/merge"): [(200, {"state": "merged"})],
        }
    )
    _client(rec).merge_change("/grp/app", Change(id="7", source_branch="chg-1", url="u"))
    assert [r.method for r in rec.requests] == ["GET", "GET", "PUT"]


def test_delete_repo_tolerates_missing_project():
    rec = Recorder({("DELETE", "/api/v4/projects/grp/app"): [(404, {})]})
    _client(rec).delete_repo("/grp/app")  # must not raise


def test_vcs_client_dispatches_to_the_providers_client():
    assert isinstance(vcs_client(_gitserver(), {"token": "tok"}), GitLabClient)


def test_vcs_client_rejects_a_provider_that_has_no_client(monkeypatch: pytest.MonkeyPatch):
    """Every provider the CRD declares now has a client, so this guard is only
    reachable when the CRD gains one before this package does — which is exactly
    the state a regenerated model can arrive in. The message has to say which
    providers ARE available, or the reader cannot tell a typo from a gap."""
    monkeypatch.delitem(clients._BUILDERS, GitProvider.gitlab)
    with pytest.raises(UnsupportedProvider) as err:
        vcs_client(_gitserver(), {"token": "tok"})
    message = str(err.value)
    assert "gitlab" in message  # the provider that was asked for
    assert "github" in message  # and the ones that would have worked


def test_vcs_client_names_the_secret_when_the_token_key_is_missing():
    """A bare KeyError('token') says nothing about which secret is misconfigured;
    the message must name it and the keys it does hold — never their values."""
    with pytest.raises(ValueError, match="ci-creds") as err:
        vcs_client(_gitserver(), {"id_rsa": "-----BEGIN KEY-----", "username": "git"})
    message = str(err.value)
    assert "id_rsa" in message  # keys are listed
    assert "username" in message
    assert "BEGIN KEY" not in message  # values are not


def test_gitlab_client_satisfies_protocol():
    assert isinstance(_client(Recorder({})), VCSProvider)


def test_create_repo_resolves_namespace_and_commits_files():
    rec = Recorder(
        {
            ("GET", "/api/v4/namespaces"): [
                (200, [{"id": 7, "full_path": "grp"}, {"id": 8, "full_path": "grp-other"}])
            ],
            ("POST", "/api/v4/projects"): [(201, {"id": 42})],
            ("POST", "/api/v4/projects/grp/app/repository/commits"): [(201, {"id": "sha"})],
        }
    )
    _client(rec).create_repo("/grp/app", default_branch="main", files={"go.mod": "module app\n"})
    create_body = json.loads(rec.requests[1].content)
    assert create_body["path"] == "app"
    assert create_body["namespace_id"] == 7  # the exact full_path match, not the substring one
    commit_body = json.loads(rec.requests[2].content)
    assert commit_body["branch"] == "main"
    assert commit_body["actions"] == [
        {"action": "create", "file_path": "go.mod", "content": "module app\n"}
    ]


def test_create_repo_rejects_unknown_namespace_by_name():
    rec = Recorder({("GET", "/api/v4/namespaces"): [(200, [{"id": 8, "full_path": "grp-other"}])]})
    with pytest.raises(ValueError, match="'grp'"):
        _client(rec).create_repo("/grp/app", default_branch="main", files={"f": "x"})


def test_comment_change_posts_note():
    proj = "/api/v4/projects/grp/app"  # httpx decodes %2F in url.path
    rec = Recorder({("POST", f"{proj}/merge_requests/7/notes"): [(201, {"id": 1})]})
    _client(rec).comment_change("/grp/app", Change(id="7", source_branch="b", url="u"), "/recheck")
    assert json.loads(rec.requests[0].content) == {"body": "/recheck"}


def test_merge_change_squash_passes_squash_param():
    proj = "/api/v4/projects/grp/app"  # httpx decodes %2F in url.path
    rec = Recorder(
        {
            ("GET", f"{proj}/merge_requests/7"): [(200, {"detailed_merge_status": "mergeable"})],
            ("PUT", f"{proj}/merge_requests/7/merge"): [
                (200, {"state": "merged", "squash_commit_sha": "sq-sha"})
            ],
        }
    )
    _client(rec).merge_change(
        "/grp/app", Change(id="7", source_branch="b", url="u"), strategy=MergeStrategy.SQUASH
    )
    assert json.loads(rec.requests[-1].content) == {"squash": True}


def test_merge_change_fast_forward_sets_project_merge_method_first():
    proj = "/api/v4/projects/grp/app"  # httpx decodes %2F in url.path
    rec = Recorder(
        {
            ("PUT", proj): [(200, {"merge_method": "ff"})],
            ("GET", f"{proj}/merge_requests/7"): [(200, {"detailed_merge_status": "mergeable"})],
            ("PUT", f"{proj}/merge_requests/7/merge"): [(200, {"state": "merged"})],
        }
    )
    _client(rec).merge_change(
        "/grp/app", Change(id="7", source_branch="b", url="u"), strategy=MergeStrategy.FAST_FORWARD
    )
    assert json.loads(rec.requests[0].content) == {"merge_method": "ff"}


def test_merge_change_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="rebase-please"):
        _client(Recorder({})).merge_change(
            "/grp/app",
            Change(id="7", source_branch="b", url="u"),
            # Deliberately invalid: exercises the runtime MergeStrategy(strategy)
            # boundary check, not the typed call path.
            strategy="rebase-please",  # pyright: ignore[reportArgumentType]
        )


def test_change_statuses_walks_all_pages_via_x_next_page():
    """Old bug: change_statuses only read the first page, silently truncating the
    result once a commit accumulated more than one page of statuses."""
    proj = "/api/v4/projects/grp/app"
    rec = Recorder(
        {
            ("GET", f"{proj}/merge_requests/7"): [(200, {"sha": "head-sha"})],
            ("GET", f"{proj}/repository/commits/head-sha/statuses"): [
                (200, [{"name": "page1", "status": "success"}], {"X-Next-Page": "2"}),
                (200, [{"name": "page2", "status": "success"}]),
            ],
        }
    )
    statuses = _client(rec).change_statuses("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert {s.name for s in statuses} == {"page1", "page2"}


def test_merge_change_fast_forward_fails_loud_when_project_setting_did_not_take():
    """Same silent-degradation guard as the squash assertion: a plan or permission
    restriction can make GitLab accept the PUT (200) and keep the old merge_method,
    which would quietly turn a fast-forward test into a plain-merge test."""
    proj = "/api/v4/projects/grp/app"
    rec = Recorder({("PUT", proj): [(200, {"merge_method": "merge"})]})
    with pytest.raises(AssertionError, match="merge_method"):
        _client(rec).merge_change(
            "/grp/app",
            Change(id="7", source_branch="b", url="u"),
            strategy=MergeStrategy.FAST_FORWARD,
        )
    assert len(rec.requests) == 1  # failed before probing mergeability


def test_merge_change_squash_requires_squash_commit_sha():
    proj = "/api/v4/projects/grp/app"
    rec = Recorder(
        {
            ("GET", f"{proj}/merge_requests/7"): [(200, {"detailed_merge_status": "mergeable"})],
            # state merged but NO squash_commit_sha -> GitLab silently ignored squash
            ("PUT", f"{proj}/merge_requests/7/merge"): [(200, {"state": "merged"})],
        }
    )
    with pytest.raises(AssertionError, match="squash"):
        _client(rec).merge_change(
            "/grp/app", Change(id="7", source_branch="b", url="u"), strategy=MergeStrategy.SQUASH
        )


def test_merge_probe_fails_fast_on_terminal_status_but_retries_5xx():
    """A revoked token must not read as 'not mergeable yet' — that burns the whole
    merge timeout and reports it as a generic wait failure. 5xx stays retryable."""
    proj = "/api/v4/projects/grp/app"
    rec = Recorder({("GET", f"{proj}/merge_requests/7"): [(401, {"message": "401 Unauthorized"})]})
    # httpx.HTTPStatusError, asserted structurally: tests may not import httpx
    # (import-linter layering contract), and the point is that it is NOT a timeout.
    with pytest.raises(Exception, match="401") as err:
        _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert not isinstance(err.value, WaitTimeout)
    assert len(rec.requests) == 1  # no polling on a terminal status

    rec = Recorder(
        {
            ("GET", f"{proj}/merge_requests/7"): [
                (502, {}),
                (200, {"detailed_merge_status": "mergeable"}),
            ],
            ("PUT", f"{proj}/merge_requests/7/merge"): [(200, {"state": "merged"})],
        }
    )
    _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))


def test_merge_put_fails_fast_when_merging_is_forbidden():
    """The change is mergeable but the token may not merge it (protected branch):
    terminal, and previously indistinguishable from 'not mergeable yet'."""
    proj = "/api/v4/projects/grp/app"
    rec = Recorder(
        {
            ("GET", f"{proj}/merge_requests/7"): [(200, {"detailed_merge_status": "mergeable"})],
            ("PUT", f"{proj}/merge_requests/7/merge"): [(403, {"message": "403 Forbidden"})],
        }
    )
    with pytest.raises(Exception, match="403") as err:
        _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert not isinstance(err.value, WaitTimeout)


def test_merge_put_retries_while_not_mergeable_yet():
    """405 is GitLab's 'not mergeable yet' — it must stay a poll, not a failure."""
    proj = "/api/v4/projects/grp/app"
    rec = Recorder(
        {
            ("GET", f"{proj}/merge_requests/7"): [(200, {"detailed_merge_status": "mergeable"})]
            * 2,
            ("PUT", f"{proj}/merge_requests/7/merge"): [
                (405, {"message": "Method Not Allowed"}),
                (200, {"state": "merged"}),
            ],
        }
    )
    _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert [r.method for r in rec.requests] == ["GET", "PUT", "GET", "PUT"]


def test_change_statuses_resolves_head_sha_and_normalizes():
    proj = "/api/v4/projects/grp/app"
    rec = Recorder(
        {
            ("GET", f"{proj}/merge_requests/7"): [(200, {"sha": "head-sha"})],
            ("GET", f"{proj}/repository/commits/head-sha/statuses"): [
                (
                    200,
                    [
                        {"name": "review-pipeline", "status": "success"},
                        {"name": "review-pipeline", "status": "running"},
                    ],
                )
            ],
        }
    )
    statuses = _client(rec).change_statuses("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert CommitStatus(name="review-pipeline", state=CIStatus.SUCCESS) in statuses
