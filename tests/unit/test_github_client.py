"""Unit tests for GitHubClient verb -> endpoint translation (mock transport, no network)."""

import json

import pytest

from krci_testkit.clients.github import GitHubClient
from krci_testkit.clients.protocol import (
    Change,
    MergeStrategy,
    UnsupportedMergeStrategy,
    VCSProvider,
)
from krci_testkit.platform import CIStatus
from krci_testkit.waits import WaitTimeout
from tests.unit.vcs_mock import Recorder


def _client(recorder: Recorder) -> GitHubClient:
    return GitHubClient(
        "https://api.github.test",
        "tok",
        transport=recorder.transport,
        merge_timeout=1,
        poll_interval=0,
    )


def test_submit_change_creates_ref_file_and_pull():
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/branches/main"): [(200, {"commit": {"sha": "base-sha"}})],
            ("POST", f"{repo}/git/refs"): [(201, {"ref": "refs/heads/chg-1"})],
            ("PUT", f"{repo}/contents/chg-1.txt"): [(201, {"commit": {"sha": "c1"}})],
            ("POST", f"{repo}/pulls"): [
                (201, {"number": 7, "html_url": "https://github.test/grp/app/pull/7"})
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
    assert change == Change(id="7", source_branch="chg-1", url="https://github.test/grp/app/pull/7")
    ref_body = json.loads(rec.requests[1].content)
    assert ref_body == {"ref": "refs/heads/chg-1", "sha": "base-sha"}
    put_body = json.loads(rec.requests[2].content)
    assert put_body["branch"] == "chg-1"
    assert put_body["content"]  # base64 payload present
    assert rec.requests[0].headers["Authorization"] == "Bearer tok"


def test_submit_change_percent_encodes_target_branch_with_slash():
    """Old bug: target_branch was spliced raw into the URL path, so a branch like
    'release/1.0' addressed the wrong route instead of the branch endpoint."""
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/branches/release/1.0"): [(200, {"commit": {"sha": "base-sha"}})],
            ("POST", f"{repo}/git/refs"): [(201, {"ref": "refs/heads/chg-1"})],
            ("PUT", f"{repo}/contents/chg-1.txt"): [(201, {"commit": {"sha": "c1"}})],
            ("POST", f"{repo}/pulls"): [(201, {"number": 7, "html_url": "u"})],
        }
    )
    _client(rec).submit_change(
        "/grp/app",
        source_branch="chg-1",
        target_branch="release/1.0",
        title="test: smoke",
        files={"chg-1.txt": "content\n"},
    )
    assert b"branches/release%2F1.0" in rec.requests[0].url.raw_path


def test_change_statuses_walks_all_pages_via_link_header():
    """Old bug: change_statuses only read the first page, silently truncating the
    result once a commit accumulated more than one page of statuses."""
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/pulls/7"): [(200, {"head": {"sha": "head-sha"}})],
            ("GET", f"{repo}/commits/head-sha/status"): [
                (
                    200,
                    {"statuses": [{"context": "page1", "state": "success"}]},
                    {
                        "Link": (
                            f"<https://api.github.test{repo}/commits/head-sha/status?page=2>; "
                            'rel="next"'
                        )
                    },
                ),
                (200, {"statuses": [{"context": "page2", "state": "success"}]}),
            ],
        }
    )
    statuses = _client(rec).change_statuses("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert {s.name for s in statuses} == {"page1", "page2"}


def test_merge_disabled_method_fails_fast_on_405():
    """GitHub returns 405 for BOTH 'not mergeable yet' and 'this merge method is
    disabled on the repo'; only the response message distinguishes them. Old bug:
    both were retried until the whole merge timeout expired, burning it on a
    permanent misconfiguration instead of failing immediately."""
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/pulls/7"): [(200, {"mergeable": True})],
            ("PUT", f"{repo}/pulls/7/merge"): [
                (405, {"message": "Squash merging is not allowed on this repository."})
            ],
        }
    )
    with pytest.raises(UnsupportedMergeStrategy, match="not allowed"):
        _client(rec).merge_change(
            "/grp/app",
            Change(id="7", source_branch="b", url="u"),
            strategy=MergeStrategy.SQUASH,
        )
    assert len(rec.requests) == 2  # failed fast, no retry burning the merge timeout


def test_merge_generic_405_is_still_retried_as_not_mergeable_yet():
    """A 405 without the 'is not allowed' wording is the ordinary 'not mergeable
    yet' signal and must keep polling, not fail fast."""
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/pulls/7"): [(200, {"mergeable": True})] * 2,
            ("PUT", f"{repo}/pulls/7/merge"): [
                (405, {"message": "Pull Request is not mergeable"}),
                (200, {"merged": True}),
            ],
        }
    )
    _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert [r.method for r in rec.requests] == ["GET", "PUT", "GET", "PUT"]


def test_merge_change_polls_mergeable_then_merges():
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/pulls/7"): [
                (200, {"mergeable": None}),
                (200, {"mergeable": True}),
            ],
            ("PUT", f"{repo}/pulls/7/merge"): [(200, {"merged": True})],
        }
    )
    _client(rec).merge_change("/grp/app", Change(id="7", source_branch="chg-1", url="u"))
    assert [r.method for r in rec.requests] == ["GET", "GET", "PUT"]


def test_delete_repo_tolerates_missing_project():
    rec = Recorder({("DELETE", "/repos/grp/app"): [(404, {})]})
    _client(rec).delete_repo("/grp/app")  # must not raise


def test_github_client_satisfies_protocol():
    assert isinstance(_client(Recorder({})), VCSProvider)


def test_create_repo_under_org_seeds_one_commit_via_git_data():
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("POST", "/orgs/grp/repos"): [(201, {"full_name": "grp/app"})],
            ("POST", f"{repo}/git/blobs"): [(201, {"sha": "b1"}), (201, {"sha": "b2"})],
            ("POST", f"{repo}/git/trees"): [(201, {"sha": "t1"})],
            ("POST", f"{repo}/git/commits"): [(201, {"sha": "c1"})],
            ("POST", f"{repo}/git/refs"): [(201, {"ref": "refs/heads/main"})],
        }
    )
    _client(rec).create_repo(
        "/grp/app",
        default_branch="main",
        files={"go.mod": "module app\n", "main.go": "package main\n"},
    )
    create_body = json.loads(rec.requests[0].content)
    assert create_body == {"name": "app", "private": True, "auto_init": False}
    tree_body = json.loads(rec.requests[3].content)
    assert [e["path"] for e in tree_body["tree"]] == ["go.mod", "main.go"]
    assert [e["sha"] for e in tree_body["tree"]] == ["b1", "b2"]
    commit_body = json.loads(rec.requests[4].content)
    assert commit_body == {"message": "Initial commit", "tree": "t1", "parents": []}
    ref_body = json.loads(rec.requests[5].content)
    assert ref_body == {"ref": "refs/heads/main", "sha": "c1"}


def test_create_repo_falls_back_to_user_when_owner_is_no_org():
    """GitHub only creates under /orgs/{owner} for organizations; a user-account
    owner answers 404 there and the repo must land under the authenticated user
    instead of surfacing a misleading not-found."""
    repo = "/repos/edp-robot/app"
    rec = Recorder(
        {
            ("POST", "/orgs/edp-robot/repos"): [(404, {"message": "Not Found"})],
            ("POST", "/user/repos"): [(201, {"full_name": "edp-robot/app"})],
            ("POST", f"{repo}/git/blobs"): [(201, {"sha": "b1"})],
            ("POST", f"{repo}/git/trees"): [(201, {"sha": "t1"})],
            ("POST", f"{repo}/git/commits"): [(201, {"sha": "c1"})],
            ("POST", f"{repo}/git/refs"): [(201, {"ref": "refs/heads/main"})],
        }
    )
    _client(rec).create_repo("/edp-robot/app", default_branch="main", files={"f.txt": "x\n"})
    assert [r.url.path for r in rec.requests[:2]] == ["/orgs/edp-robot/repos", "/user/repos"]


def test_create_repo_accepts_canonical_casing_of_the_requested_owner():
    """GitHub's full_name carries the org's canonical casing; the configured
    group may be cased differently. A casing difference is the SAME owner and
    must not be treated as a wrong-place landing (which deletes the repo)."""
    repo = "/repos/GRP/app"
    rec = Recorder(
        {
            ("POST", "/orgs/GRP/repos"): [(201, {"full_name": "grp/app"})],
            ("POST", f"{repo}/git/blobs"): [(201, {"sha": "b1"})],
            ("POST", f"{repo}/git/trees"): [(201, {"sha": "t1"})],
            ("POST", f"{repo}/git/commits"): [(201, {"sha": "c1"})],
            ("POST", f"{repo}/git/refs"): [(201, {"ref": "refs/heads/main"})],
        }
    )
    _client(rec).create_repo("/GRP/app", default_branch="main", files={"f": "x"})
    assert all(r.method != "DELETE" for r in rec.requests)  # nothing was "cleaned up"


def test_create_repo_rejects_repo_landing_under_wrong_owner():
    """The org 404 also means "org missing" or "token lacks scope" — the user
    fallback then creates the repo under the token's own account, at a path the
    rest of the run never looks at. The stray must be removed and the mismatch
    named, instead of every later call 404ing confusingly."""
    rec = Recorder(
        {
            ("POST", "/orgs/some-org/repos"): [(404, {"message": "Not Found"})],
            ("POST", "/user/repos"): [(201, {"full_name": "token-user/app"})],
            ("DELETE", "/repos/token-user/app"): [(204, {})],
        }
    )
    with pytest.raises(ValueError, match="token-user/app"):
        _client(rec).create_repo("/some-org/app", default_branch="main", files={"f": "x"})
    assert rec.requests[-1].method == "DELETE"  # the stray repo was cleaned up


def test_vcs_client_builds_github_from_gitserver():
    from krci_testkit.clients import vcs_client
    from krci_testkit.models import GitServer

    gs = GitServer.model_validate(
        {
            "apiVersion": "v2.edp.epam.com/v1",
            "kind": "GitServer",
            "metadata": {"name": "github"},
            "spec": {
                "gitHost": "github.com",
                "gitProvider": "github",
                "gitUser": "git",
                "httpsPort": 443,
                "nameSshKeySecret": "ci-github",
                "sshPort": 22,
            },
        }
    )
    assert isinstance(vcs_client(gs, {"token": "tok"}), GitHubClient)


def test_comment_change_posts_issue_comment():
    rec = Recorder({("POST", "/repos/grp/app/issues/7/comments"): [(201, {"id": 1})]})
    _client(rec).comment_change("/grp/app", Change(id="7", source_branch="b", url="u"), "/recheck")
    assert json.loads(rec.requests[0].content) == {"body": "/recheck"}


def test_merge_change_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="bogus"):
        _client(Recorder({})).merge_change(
            "/grp/app",
            Change(id="1", source_branch="b", url="u"),
            # Deliberately invalid: exercises the runtime MergeStrategy(strategy)
            # boundary check, not the typed call path.
            strategy="bogus",  # pyright: ignore[reportArgumentType]
        )


def test_merge_change_maps_strategies_to_github_methods():
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/pulls/7"): [(200, {"mergeable": True})] * 2,
            ("PUT", f"{repo}/pulls/7/merge"): [(200, {"merged": True})] * 2,
        }
    )
    client = _client(rec)
    change = Change(id="7", source_branch="b", url="u")
    client.merge_change("/grp/app", change, strategy=MergeStrategy.MERGE)
    client.merge_change("/grp/app", change, strategy=MergeStrategy.SQUASH)
    methods = [json.loads(r.content)["merge_method"] for r in rec.requests if r.method == "PUT"]
    assert methods == ["merge", "squash"]


def test_merge_change_refuses_fast_forward_instead_of_substituting_rebase():
    """GitHub has no fast-forward merge method. Rebase rewrites commits, so
    substituting it would leave a green test asserting a strategy it never ran —
    the request must fail before any HTTP call."""
    rec = Recorder({})
    with pytest.raises(UnsupportedMergeStrategy, match="fast_forward"):
        _client(rec).merge_change(
            "/grp/app",
            Change(id="7", source_branch="b", url="u"),
            strategy=MergeStrategy.FAST_FORWARD,
        )
    assert rec.requests == []


def test_merge_fails_fast_on_terminal_status_but_retries_the_retryable():
    """A deleted PR (404) or a forbidden merge (403) is terminal; 405 'not mergeable
    yet' and 5xx blips stay polls. Terminal statuses previously burned the whole
    merge timeout and surfaced as a generic wait failure."""
    repo = "/repos/grp/app"
    rec = Recorder({("GET", f"{repo}/pulls/7"): [(404, {"message": "Not Found"})]})
    with pytest.raises(Exception, match="404") as err:
        _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert not isinstance(err.value, WaitTimeout)
    assert len(rec.requests) == 1

    rec = Recorder(
        {
            ("GET", f"{repo}/pulls/7"): [(200, {"mergeable": True})],
            ("PUT", f"{repo}/pulls/7/merge"): [(403, {"message": "Forbidden"})],
        }
    )
    with pytest.raises(Exception, match="403") as err:
        _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert not isinstance(err.value, WaitTimeout)

    rec = Recorder(
        {
            ("GET", f"{repo}/pulls/7"): [(502, {}), (200, {"mergeable": True})] * 2,
            ("PUT", f"{repo}/pulls/7/merge"): [(405, {}), (200, {"merged": True})],
        }
    )
    _client(rec).merge_change("/grp/app", Change(id="7", source_branch="b", url="u"))


def test_change_statuses_resolves_head_sha_and_normalizes():
    repo = "/repos/grp/app"
    rec = Recorder(
        {
            ("GET", f"{repo}/pulls/7"): [(200, {"head": {"sha": "head-sha"}})],
            ("GET", f"{repo}/commits/head-sha/status"): [
                (
                    200,
                    {
                        "statuses": [
                            {"context": "review-pipeline", "state": "success"},
                            {"context": "review-pipeline", "state": "pending"},
                        ]
                    },
                )
            ],
        }
    )
    from krci_testkit.clients.protocol import CommitStatus

    statuses = _client(rec).change_statuses("/grp/app", Change(id="7", source_branch="b", url="u"))
    assert CommitStatus(name="review-pipeline", state=CIStatus.SUCCESS) in statuses
