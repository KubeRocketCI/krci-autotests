"""Unit tests for BitbucketClient verb -> endpoint translation (mock transport, no network)."""

import json

import pytest

from krci_testkit.clients import bitbucket
from krci_testkit.clients.bitbucket import BitbucketClient
from krci_testkit.clients.protocol import (
    Change,
    MergeStrategy,
    UnsupportedMergeStrategy,
    VCSProvider,
)
from krci_testkit.platform import CIStatus
from krci_testkit.waits import WaitTimeout
from tests.unit.vcs_mock import Recorder


def _client(recorder: Recorder) -> BitbucketClient:
    return BitbucketClient(
        "https://api.bitbucket.test/2.0",
        "tok",
        transport=recorder.transport,
        merge_timeout=1,
        poll_interval=0,
    )


def test_submit_change_creates_branch_commit_and_pr():
    repo = "/2.0/repositories/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/refs/branches/main"): [(200, {"target": {"hash": "base-sha"}})],
            ("POST", f"{repo}/refs/branches"): [(201, {"name": "chg-1"})],
            ("POST", f"{repo}/src"): [(201, {})],
            ("POST", f"{repo}/pullrequests"): [
                (
                    201,
                    {
                        "id": 7,
                        "links": {
                            "html": {"href": "https://bitbucket.test/grp/app/pull-requests/7"}
                        },
                    },
                )
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
    assert change.url == "https://bitbucket.test/grp/app/pull-requests/7"
    branch_body = json.loads(rec.requests[1].content)
    assert branch_body == {"name": "chg-1", "target": {"hash": "base-sha"}}
    pr_body = json.loads(rec.requests[3].content)
    assert pr_body["source"]["branch"]["name"] == "chg-1"
    assert pr_body["destination"]["branch"]["name"] == "main"
    # Platform convention (codebase-operator BasicTokenAuthProvider): the secret's
    # token is a pre-encoded user:app_password, sent verbatim after "Basic ".
    assert rec.requests[0].headers["Authorization"] == "Basic tok"


def test_submit_change_rejects_file_colliding_with_reserved_src_field():
    """Old bug: `files` was unpacked into the SAME /src form body as the reserved
    branch/message fields, so a file literally named 'message' silently overwrote
    the commit message instead of being sent as file content."""
    rec = Recorder({})
    with pytest.raises(ValueError, match="message"):
        _client(rec).submit_change(
            "/grp/app",
            source_branch="chg-1",
            target_branch="main",
            title="test: smoke",
            files={"message": "this is file content, not the commit message"},
        )
    assert rec.requests == []  # rejected before any HTTP call


def test_submit_change_percent_encodes_target_branch_with_slash():
    """Old bug: target_branch was spliced raw into the URL path, so a branch like
    'release/1.0' addressed the wrong route (an extra path segment) instead of the
    branch endpoint."""
    repo = "/2.0/repositories/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/refs/branches/release/1.0"): [(200, {"target": {"hash": "base-sha"}})],
            ("POST", f"{repo}/refs/branches"): [(201, {"name": "chg-1"})],
            ("POST", f"{repo}/src"): [(201, {})],
            ("POST", f"{repo}/pullrequests"): [(201, {"id": 7, "links": {"html": {"href": "u"}}})],
        }
    )
    _client(rec).submit_change(
        "/grp/app",
        source_branch="chg-1",
        target_branch="release/1.0",
        title="test: smoke",
        files={"chg-1.txt": "content\n"},
    )
    assert b"refs/branches/release%2F1.0" in rec.requests[0].url.raw_path


def test_change_statuses_walks_all_pages_via_next_url():
    """Old bug: change_statuses only read the first page, silently truncating the
    result once a change accumulated more than one page of statuses."""
    repo = "/2.0/repositories/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/pullrequests/7"): [
                (200, {"source": {"commit": {"hash": "head-sha"}}})
            ],
            ("GET", f"{repo}/commit/head-sha/statuses"): [
                (
                    200,
                    {
                        "values": [{"name": "page1", "state": "SUCCESSFUL"}],
                        "next": f"https://api.bitbucket.test{repo}/commit/head-sha/statuses?page=2",
                    },
                ),
                (200, {"values": [{"name": "page2", "state": "SUCCESSFUL"}]}),
            ],
        }
    )
    statuses = _client(rec).change_statuses("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert {s.name for s in statuses} == {"page1", "page2"}


def test_merge_change_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="bogus"):
        _client(Recorder({})).merge_change(
            "/grp/app",
            Change(id="1", source_branch="b", url="u"),
            # Deliberately invalid: exercises the runtime MergeStrategy(strategy)
            # boundary check, not the typed call path.
            strategy="bogus",  # pyright: ignore[reportArgumentType]
        )


def test_merge_change_reports_an_unmapped_strategy_as_unsupported(
    monkeypatch: pytest.MonkeyPatch,
):
    """A strategy the client has no native type for must raise the neutral
    UnsupportedMergeStrategy, like the GitHub client — never a bare KeyError.

    The translation table is emptied for this test on purpose: every current
    MergeStrategy member is mapped, so the guard is only reachable the way a
    FUTURE fourth member would reach it, and asserting it any other way would
    pass without ever entering the branch."""
    monkeypatch.setattr(bitbucket, "_STRATEGY_TO_TYPE", {})
    with pytest.raises(UnsupportedMergeStrategy, match="squash"):
        _client(Recorder({})).merge_change(
            "/grp/app",
            Change(id="1", source_branch="b", url="u"),
            strategy=MergeStrategy.SQUASH,
        )


def test_merge_change_retries_until_merged():
    repo = "/2.0/repositories/grp/app"
    rec = Recorder(
        {
            ("POST", f"{repo}/pullrequests/7/merge"): [
                (555, {}),
                (200, {"state": "MERGED"}),
            ],
        }
    )
    _client(rec).merge_change("/grp/app", Change(id="7", source_branch="chg-1", url="u"))
    assert [r.method for r in rec.requests] == ["POST", "POST"]


def test_merge_fails_fast_on_terminal_status():
    """This client retries the merge itself, so it used to retry EVERY status —
    an unauthorized token polled until the merge timeout. 409 (still settling) and
    Bitbucket's own 555 remain retryable."""
    repo = "/2.0/repositories/grp/app"
    rec = Recorder({("POST", f"{repo}/pullrequests/7/merge"): [(401, {"error": "Unauthorized"})]})
    with pytest.raises(Exception, match="401") as err:
        _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert not isinstance(err.value, WaitTimeout)
    assert len(rec.requests) == 1

    rec = Recorder(
        {
            ("POST", f"{repo}/pullrequests/7/merge"): [
                (409, {}),
                (555, {}),
                (200, {"state": "MERGED"}),
            ]
        }
    )
    _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert len(rec.requests) == 3


def test_delete_repo_tolerates_missing_project():
    rec = Recorder({("DELETE", "/2.0/repositories/grp/app"): [(404, {})]})
    _client(rec).delete_repo("/grp/app")  # must not raise


def test_bitbucket_client_satisfies_protocol():
    assert isinstance(_client(Recorder({})), VCSProvider)


def test_vcs_client_builds_bitbucket_from_gitserver():
    from krci_testkit.clients import vcs_client
    from krci_testkit.models import GitServer

    gs = GitServer.model_validate(
        {
            "apiVersion": "v2.edp.epam.com/v1",
            "kind": "GitServer",
            "metadata": {"name": "bitbucket"},
            "spec": {
                "gitHost": "bitbucket.org",
                "gitProvider": "bitbucket",
                "gitUser": "git",
                "httpsPort": 443,
                "nameSshKeySecret": "ci-bitbucket",
                "sshPort": 22,
            },
        }
    )
    assert isinstance(vcs_client(gs, {"token": "tok"}), BitbucketClient)


def test_comment_change_posts_pr_comment():
    rec = Recorder(
        {("POST", "/2.0/repositories/grp/app/pullrequests/7/comments"): [(201, {"id": 1})]}
    )
    _client(rec).comment_change("/grp/app", Change(id="7", source_branch="b", url="u"), "/recheck")
    assert json.loads(rec.requests[0].content) == {"content": {"raw": "/recheck"}}


def test_merge_change_maps_strategies_to_bitbucket_types():
    repo = "/2.0/repositories/grp/app"
    rec = Recorder({("POST", f"{repo}/pullrequests/7/merge"): [(200, {"state": "MERGED"})] * 3})
    client = _client(rec)
    change = Change(id="7", source_branch="b", url="u")
    client.merge_change("/grp/app", change, strategy=MergeStrategy.MERGE)
    client.merge_change("/grp/app", change, strategy=MergeStrategy.SQUASH)
    client.merge_change("/grp/app", change, strategy=MergeStrategy.FAST_FORWARD)
    types = [json.loads(r.content)["type"] for r in rec.requests]
    assert types == ["merge_commit", "squash", "fast_forward"]


def test_change_statuses_resolves_head_sha_and_normalizes():
    repo = "/2.0/repositories/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/pullrequests/7"): [
                (200, {"source": {"commit": {"hash": "head-sha"}}})
            ],
            ("GET", f"{repo}/commit/head-sha/statuses"): [
                (
                    200,
                    {
                        "values": [
                            {"name": "review-pipeline", "state": "SUCCESSFUL"},
                            {"name": "review-pipeline", "state": "INPROGRESS"},
                        ]
                    },
                )
            ],
        }
    )
    from krci_testkit.clients.protocol import CommitStatus

    statuses = _client(rec).change_statuses("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert CommitStatus(name="review-pipeline", state=CIStatus.SUCCESS) in statuses
    assert CommitStatus(name="review-pipeline", state=CIStatus.RUNNING) in statuses
