"""Unit tests for GerritClient verb -> endpoint translation (mock transport, no network)."""

import base64
import json
from typing import Any

import pytest

from krci_testkit.clients import (
    MissingCredential,
    UnsupportedMergeStrategy,
    credential_secrets,
    vcs_client,
)
from krci_testkit.clients.gerrit import BinaryContentUnsupported, GerritClient
from krci_testkit.clients.protocol import Change, MergeStrategy, VCSProvider
from krci_testkit.models import GitServer
from krci_testkit.platform import CIStatus
from krci_testkit.waits import WaitTimeout
from tests.unit.vcs_mock import GerritRecorder

BASE = "https://gerrit.example.test"
CHANGE = Change(id="42", source_branch="unused", url="u")


def _gitserver(provider: str = "gerrit") -> GitServer:
    return GitServer.model_validate(
        {
            "apiVersion": "v2.edp.epam.com/v1",
            "kind": "GitServer",
            "metadata": {"name": provider},
            "spec": {
                "gitHost": "gerrit.krci",
                "gitProvider": provider,
                "gitUser": "edp-ci",
                "httpsPort": 443,
                "nameSshKeySecret": "gerrit-ciuser-sshkey",
                "sshPort": 30022,
            },
        }
    )


def _client(
    recorder: GerritRecorder, *, merge_timeout: float = 1, poll_interval: float = 0
) -> GerritClient:
    return GerritClient(
        BASE,
        "edp-ci",
        "pw",
        transport=recorder.transport,
        merge_timeout=merge_timeout,
        poll_interval=poll_interval,
    )


def _body(request: Any) -> dict:
    """The recorded httpx.Request, typed loosely: importing httpx here would break
    the layering contract that keeps real HTTP out of tests (vcs_mock is the seam)."""
    return json.loads(request.content)


def test_ping_strips_the_xssi_prefix():
    """Gerrit guards every JSON body with `)]}'`, which is not valid JSON. A client
    that forgets to strip it fails on the very first call against a real server."""
    rec = GerritRecorder({("GET", "/a/config/server/version"): [(200, "3.14.2")]})
    assert _client(rec).ping() == "3.14.2"


def test_submit_change_carries_its_content_as_a_patch_on_creation():
    """One request creates the change WITH its files. The alternative — a change
    edit per file — addresses each path in the URL, and a path containing '/' has
    no form that survives there: encoded, the separator is normalised away and
    answered with a redirect; decoded, the path is read as a resource plus a view
    and answered 404. In a patch the paths are body data."""
    rec = GerritRecorder({("POST", "/a/changes/"): [(201, {"_number": 42})]})
    change = _client(rec).submit_change(
        "/app",
        source_branch="ignored",
        target_branch="main",
        title="t",
        files={"conf/nested.yaml": "k: v\n"},
    )
    assert [r.method for r in rec.requests] == ["POST"]
    sent = _body(rec.requests[0])
    # The project is a body field, so it stays a plain name; the branch is the
    # target, because Gerrit reviews a revision against it rather than a branch.
    assert sent["project"] == "app"
    assert sent["branch"] == "main"
    assert sent["subject"] == "t"
    assert sent["patch"]["patch"] == (
        "diff --git a/conf/nested.yaml b/conf/nested.yaml\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/conf/nested.yaml\n"
        "@@ -0,0 +1,1 @@\n"
        "+k: v\n"
    )
    # The NUMBER identifies the change: unambiguous server-wide, needs no escaping,
    # and it is what the platform's trigger binding carries as changeNumber.
    assert change.id == "42"


def test_submit_change_without_files_sends_no_patch():
    """An empty payload is a change with nothing in it, not a patch that adds
    nothing — Gerrit rejects the latter."""
    rec = GerritRecorder({("POST", "/a/changes/"): [(201, {"_number": 7})]})
    _client(rec).submit_change("/app", source_branch="x", target_branch="main", title="t", files={})
    assert "patch" not in _body(rec.requests[0])


def test_patch_marks_content_that_does_not_end_in_a_newline():
    """git records the missing terminator explicitly; a patch that omits the marker
    describes a file one byte different from the one asked for."""
    rec = GerritRecorder({("POST", "/a/changes/"): [(201, {"_number": 1})]})
    _client(rec).submit_change(
        "/app", source_branch="x", target_branch="main", title="t", files={"f.txt": "no newline"}
    )
    assert _body(rec.requests[0])["patch"]["patch"].endswith(
        "@@ -0,0 +1,1 @@\n+no newline\n\\ No newline at end of file\n"
    )


def test_patch_adds_an_empty_file_without_a_hunk():
    """git emits no hunk for an empty new file, and a hunk claiming zero lines is
    not a patch Gerrit will apply."""
    rec = GerritRecorder({("POST", "/a/changes/"): [(201, {"_number": 1})]})
    _client(rec).submit_change(
        "/app", source_branch="x", target_branch="main", title="t", files={"empty": ""}
    )
    assert _body(rec.requests[0])["patch"]["patch"] == (
        "diff --git a/empty b/empty\nnew file mode 100644\n"
    )


def test_binary_content_is_refused_rather_than_corrupted():
    """A text patch cannot carry bytes. Dropping the file or writing it mangled
    would surface much later and far away — a scaffold silently missing its gradle
    wrapper fails in the build, not here."""
    rec = GerritRecorder(
        {
            ("PUT", "/a/projects/app"): [(201, {"name": "app"})],
            ("PUT", "/a/projects/app/HEAD"): [(200, "refs/heads/main")],
        }
    )
    client = _client(rec)
    with pytest.raises(BinaryContentUnsupported, match="gradle-wrapper.jar"):
        client.create_repo(
            "/app", default_branch="main", files={"gradle-wrapper.jar": b"PK\x03\x04"}
        )


def test_merge_change_approves_before_submitting_and_leaves_verified_alone():
    """Gerrit refuses to submit until the labels hold their max value, so the client
    votes first. It votes Code-Review only: Verified is the platform's own verdict
    on the review pipeline, and casting it here would land a change whose pipeline
    was red."""
    rec = GerritRecorder(
        {
            ("POST", "/a/changes/42/revisions/current/review"): [(200, {})],
            ("POST", "/a/changes/42/revisions/current/submit"): [(200, {"status": "MERGED"})],
        }
    )
    _client(rec).merge_change("/app", CHANGE)
    assert [r.url.path for r in rec.requests] == [
        "/a/changes/42/revisions/current/review",
        "/a/changes/42/revisions/current/submit",
    ]
    assert _body(rec.requests[0]) == {"labels": {"Code-Review": 2}}


def test_merge_change_retries_while_the_change_is_not_submittable_yet():
    """409 answers both "a label is still missing its max vote" and a real conflict.
    Retrying is what lets a merge wait out the platform's Verified vote instead of
    racing the pipeline that casts it."""
    rec = GerritRecorder(
        {
            ("POST", "/a/changes/42/revisions/current/review"): [(200, {})],
            ("POST", "/a/changes/42/revisions/current/submit"): [
                (409, {"message": "blocked"}),
                (200, {"status": "MERGED"}),
            ],
        }
    )
    _client(rec).merge_change("/app", CHANGE)
    assert [r.url.path for r in rec.requests].count("/a/changes/42/revisions/current/submit") == 2


def test_merge_change_fails_when_the_change_never_becomes_submittable():
    """The retry is bounded by the merge budget, so a change that stays blocked
    reports a timeout instead of polling forever."""
    rec = GerritRecorder(
        {
            ("POST", "/a/changes/42/revisions/current/review"): [(200, {})],
            ("POST", "/a/changes/42/revisions/current/submit"): [(409, {"message": "blocked"})] * 8,
        }
    )
    client = _client(rec, merge_timeout=0.05, poll_interval=0.05)
    with pytest.raises(WaitTimeout):
        client.merge_change("/app", CHANGE)


@pytest.mark.parametrize("strategy", [MergeStrategy.SQUASH, MergeStrategy.FAST_FORWARD])
def test_merge_change_refuses_strategies_gerrit_decides_per_project(strategy: MergeStrategy):
    """submit_type is a project setting, not a submit parameter. Substituting a
    plain merge would leave a green test asserting something it never exercised."""
    with pytest.raises(UnsupportedMergeStrategy, match="submit_type"):
        _client(GerritRecorder({})).merge_change("/app", CHANGE, strategy=strategy)


def test_create_repo_pins_head_and_self_approves_the_seed():
    """An import seed is a repo the platform does not know yet, so no pipeline will
    ever vote Verified and the seeding change could never be submitted without it.
    HEAD is pinned because the import strategy resolves the default branch from it."""
    rec = GerritRecorder(
        {
            ("PUT", "/a/projects/app"): [(201, {"name": "app"})],
            ("PUT", "/a/projects/app/HEAD"): [(200, "refs/heads/main")],
            ("POST", "/a/changes/"): [(201, {"_number": 5})],
            ("POST", "/a/changes/5/revisions/current/review"): [(200, {})],
            ("POST", "/a/changes/5/revisions/current/submit"): [(200, {"status": "MERGED"})],
        }
    )
    _client(rec).create_repo("/app", default_branch="main", files={"main.py": "x = 1\n"})
    assert _body(rec.requests[0]) == {"create_empty_commit": True, "branches": ["main"]}
    assert _body(rec.requests[1]) == {"ref": "refs/heads/main"}
    approval = next(r for r in rec.requests if r.url.path.endswith("/review"))
    assert _body(approval) == {"labels": {"Code-Review": 2, "Verified": 1}}


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ({"approved": {"_account_id": 1}}, CIStatus.SUCCESS),
        ({"rejected": {"_account_id": 1}}, CIStatus.FAILED),
        ({"all": [{"value": 0}]}, CIStatus.RUNNING),
    ],
)
def test_change_statuses_read_the_platform_verdict_from_the_verified_label(
    label: dict, expected: CIStatus
):
    """Gerrit has no per-check status list. The review pipeline votes Verified — 0
    when it starts, +1 on success, -1 on failure — so that label IS the CI status."""
    rec = GerritRecorder(
        {("GET", "/a/changes/42/detail"): [(200, {"labels": {"Verified": label}})]}
    )
    statuses = _client(rec).change_statuses("/app", CHANGE)
    assert [(s.name, s.state) for s in statuses] == [("Verified", expected)]


def test_change_statuses_are_empty_when_nothing_has_reported():
    """No vote means no run has reported yet — an empty list, not a fabricated
    pending entry that would read as a real status."""
    rec = GerritRecorder({("GET", "/a/changes/42/detail"): [(200, {"labels": {}})]})
    assert _client(rec).change_statuses("/app", CHANGE) == []


def test_hierarchical_project_names_survive_as_one_path_segment():
    """Gerrit project names may contain '/', which is part of the NAME. Spliced raw
    it would address a different route. This is the opposite convention to the file
    paths inside a patch, which are body data and stay exactly as given."""
    rec = GerritRecorder({("GET", "/a/projects/team/app"): [(200, {"name": "team/app"})]})
    assert _client(rec).repo_exists("/team/app") is True
    assert rec.requests[0].url.raw_path.decode().endswith("/a/projects/team%2Fapp")


def test_repo_exists_reads_404_as_the_answer_no():
    rec = GerritRecorder({("GET", "/a/projects/app"): [(404, {})]})
    assert _client(rec).repo_exists("/app") is False


def test_delete_repo_tolerates_missing_project():
    rec = GerritRecorder({("POST", "/a/projects/app/delete-project~delete"): [(404, {})]})
    _client(rec).delete_repo("/app")  # must not raise


def test_comment_change_posts_a_review_message():
    rec = GerritRecorder({("POST", "/a/changes/42/revisions/current/review"): [(200, {})]})
    _client(rec).comment_change("/app", CHANGE, "/recheck")
    assert _body(rec.requests[0]) == {"message": "/recheck"}


def test_gerrit_client_satisfies_protocol():
    assert isinstance(_client(GerritRecorder({})), VCSProvider)


def test_gerrit_reads_the_http_password_beside_its_ssh_key():
    """The GitServer names only the SSH key the platform pushes with; the REST API
    needs an HTTP password, which the platform keeps in a secret of its own."""
    assert credential_secrets(_gitserver()) == ["gerrit-ciuser-sshkey", "gerrit-ciuser-password"]
    assert credential_secrets(_gitserver("github")) == ["gerrit-ciuser-sshkey"]


def test_vcs_client_builds_gerrit_from_the_merged_credentials():
    client = vcs_client(_gitserver(), {"id_rsa": "-----", "user": "edp-ci", "password": "pw"})
    assert isinstance(client, GerritClient)


def test_vcs_client_names_the_secrets_it_read_when_a_key_is_missing():
    """A bare KeyError says nothing about which secret to go and fix; the message
    has to name the key AND the secrets that were read — never their values."""
    with pytest.raises(MissingCredential) as err:
        vcs_client(_gitserver(), {"id_rsa": "-----BEGIN KEY-----"})
    message = str(err.value)
    assert "'user'" in message
    assert "gerrit-ciuser-password" in message
    assert "BEGIN KEY" not in message


def test_gerrit_defaults_to_the_in_cluster_endpoint_and_honours_an_override():
    """gitHost is a Kubernetes service name that resolves nowhere else, so the
    derived endpoint only works from inside the cluster; a run from outside says
    where the API answers."""
    creds = {"user": "edp-ci", "password": "pw"}
    # The resolved endpoint is read off the client itself: vcs_client takes no
    # transport, so there is no request to observe it through, and getting this
    # wrong is silent until a live run cannot reach the server at all.
    default = vcs_client(_gitserver(), creds)
    assert str(default._http.base_url) == "http://gerrit.krci:8080/a/"  # pyright: ignore[reportAttributeAccessIssue]
    override = vcs_client(_gitserver(), creds, api_url="https://gerrit.example.test")
    assert str(override._http.base_url) == "https://gerrit.example.test/a/"  # pyright: ignore[reportAttributeAccessIssue]


def test_basic_auth_header_is_sent_on_the_authenticated_prefix():
    """Only the /a/ tree is authenticated; the rest is anonymous and read-only."""
    rec = GerritRecorder({("GET", "/a/config/server/version"): [(200, "3.14.2")]})
    _client(rec).ping()
    expected = base64.b64encode(b"edp-ci:pw").decode()
    assert rec.requests[0].headers["Authorization"] == f"Basic {expected}"
