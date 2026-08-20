"""Gerrit provider client — the ONLY module that speaks the Gerrit REST API.

A Gerrit change is a "change", and the neutral verbs map onto Gerrit's own
mechanics rather than onto a pull-request shape it does not have. Three of those
mappings are not obvious and are the reason this client differs most from its
siblings:

- There is no source branch. A change is a revision proposed against the target
  branch, and its content rides as a patch on creation, so `Change.source_branch`
  is carried for the protocol's sake and addresses nothing. Content does NOT go
  through a change edit: that endpoint names each file in the URL, and a path
  containing '/' has no form that survives there.
- Landing a change needs approval, not just a request. Gerrit refuses to submit
  until the `Code-Review` and `Verified` labels hold their maximum value, so
  `merge_change` votes before it submits.
- Merge strategy is a project setting (`submit_type`), not a request parameter,
  so anything but a plain merge raises rather than silently landing differently.

Authentication is HTTP Basic against the `/a/` prefix, which is what makes a
request authenticated at all; the unauthenticated tree is read-only.
"""

import base64
import json
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from krci_testkit.clients.protocol import (
    DEFAULT_MERGE_TIMEOUT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REQUEST_TIMEOUT,
    Change,
    CommitStatus,
    MergeStrategy,
    UnsupportedMergeStrategy,
    http_client,
    normalize_ci_state,
    path_segment,
    poll_merge,
)
from krci_testkit.platform import CIStatus

log = logging.getLogger(__name__)

# Gerrit guards every JSON response against cross-site script inclusion by
# prefixing it with this sentinel, which is not valid JSON.
_XSSI_PREFIX = ")]}'"

# Submit answers 409 both for "not submittable yet" (a label still missing its
# max vote) and for a genuine merge conflict, and the two are indistinguishable
# by status alone. Retrying is right for the first and merely slow for the
# second, and it is what lets a merge wait out the platform's own Verified vote
# instead of racing it. Everything else 4xx stays terminal.
_MERGE_RETRY_STATUSES = frozenset({409})

# The label the platform's review pipeline votes on: 0 when the run starts, +1
# when it succeeds, -1 when it fails. Gerrit has no per-check status list, so
# this single label carries the whole CI verdict.
_CI_LABEL = "Verified"

# Approval the CLIENT supplies. Verified is deliberately absent: the platform
# votes it from the review pipeline's own outcome, and voting it here would let
# a change land while its pipeline was red.
_APPROVAL = {"Code-Review": 2}

# Approval for a repository the platform does not know yet (an import seed).
# No codebase exists, so no pipeline will ever vote Verified, and without it the
# seeding change can never be submitted.
_SEED_APPROVAL = {"Code-Review": 2, _CI_LABEL: 1}

_STATE_TO_NEUTRAL = {
    "+1": CIStatus.SUCCESS,
    "-1": CIStatus.FAILED,
    "0": CIStatus.RUNNING,
}


class BinaryContentUnsupported(Exception):
    """Gerrit carries new content as a patch, and this client writes text patches
    only. Raised instead of dropping the file or writing it corrupted — a scaffold
    silently missing its gradle wrapper would fail much later and far away."""


def in_cluster_api_url(host: str) -> str:
    """The REST endpoint reachable from inside the cluster, the only one derivable
    from the GitServer. Its httpsPort 443 serves the git remote, which the REST
    API does not answer on; the API lives on the platform image's own HTTP port."""
    return f"http://{host}:8080"


class GerritClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        verify: bool | str = True,
        merge_timeout: float = DEFAULT_MERGE_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ):
        self._web_url = base_url.rstrip("/")
        basic = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._http = http_client(
            f"{self._web_url}/a",
            {"Authorization": f"Basic {basic}"},
            verify=verify,
            transport=transport,
            request_timeout=request_timeout,
        )
        self._merge_timeout = merge_timeout
        self._poll_interval = poll_interval

    def ping(self) -> str:
        resp = self._http.get("/config/server/version")
        resp.raise_for_status()
        return str(_body(resp))

    def repo_exists(self, git_url_path: str) -> bool:
        """Whether the remote project is already there. 404 is the answer "no",
        not an error: a caller asks this precisely because either state is normal."""
        resp = self._http.get(f"/projects/{_project(git_url_path)}")
        if resp.status_code == httpx.codes.NOT_FOUND:
            return False
        resp.raise_for_status()
        return True

    def create_repo(
        self,
        git_url_path: str,
        *,
        default_branch: str,
        files: dict[str, str | bytes],
    ) -> None:
        """Seed for an import source — a repo the platform did not shape; the
        project is never handed over empty, content lands before this returns.

        HEAD is set explicitly rather than left to follow from the created
        branch: the import strategy resolves the default branch from HEAD, and a
        project whose HEAD still points at Gerrit's own default would be adopted
        against a branch that does not exist."""
        project = _project(git_url_path)
        self._http.put(
            f"/projects/{project}",
            json={"create_empty_commit": True, "branches": [default_branch]},
        ).raise_for_status()
        self._http.put(
            f"/projects/{project}/HEAD", json={"ref": f"refs/heads/{default_branch}"}
        ).raise_for_status()
        if files:
            number = self._create_change(
                git_url_path, branch=default_branch, subject="Initial commit", files=files
            )
            self._approve(number, _SEED_APPROVAL)
            self._submit(number, describe=f"seed of {git_url_path}")
        log.info("created repo %s with %d files on %s", git_url_path, len(files), default_branch)

    def submit_change(
        self,
        git_url_path: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        files: dict[str, str],
    ) -> Change:
        """A change proposed against target_branch.

        source_branch is recorded but never addressed: Gerrit reviews a revision,
        not a branch, so there is nothing for it to name."""
        number = self._create_change(git_url_path, branch=target_branch, subject=title, files=files)
        url = f"{self._web_url}/c/{git_url_path.strip('/')}/+/{number}"
        log.info("submitted change %s (-> %s) in %s", number, target_branch, git_url_path)
        return Change(id=number, source_branch=source_branch, url=url)

    def merge_change(
        self, git_url_path: str, change: Change, *, strategy: MergeStrategy = MergeStrategy.MERGE
    ) -> None:
        strategy = MergeStrategy(strategy)
        if strategy is not MergeStrategy.MERGE:
            raise UnsupportedMergeStrategy(
                f"Gerrit decides '{strategy}' per project via submit_type, not per submit "
                f"request (supported here: {MergeStrategy.MERGE.value})"
            )
        self._approve(change.id, _APPROVAL)
        self._submit(change.id, describe=f"change {change.id} merged ({strategy})")
        log.info("merged change %s in %s (%s)", change.id, git_url_path, strategy)

    def comment_change(self, git_url_path: str, change: Change, body: str) -> None:
        self._http.post(
            f"/changes/{change.id}/revisions/current/review", json={"message": body}
        ).raise_for_status()
        log.info("commented on change %s in %s", change.id, git_url_path)

    def change_statuses(self, git_url_path: str, change: Change) -> list[CommitStatus]:
        """The platform's CI verdict on the change, read from the Verified label.

        Gerrit reports no per-check list, so this is one status or none — an
        unvoted label means no run has reported yet, which is an empty list
        rather than a fabricated pending entry."""
        resp = self._http.get(f"/changes/{change.id}/detail")
        resp.raise_for_status()
        label = (_body(resp).get("labels") or {}).get(_CI_LABEL)
        if not label:
            return []
        return [
            CommitStatus(name=_CI_LABEL, state=normalize_ci_state(_vote(label), _STATE_TO_NEUTRAL))
        ]

    def delete_repo(self, git_url_path: str) -> None:
        """Best-effort teardown — VCS leftovers must never fail a test run."""
        resp = self._http.post(
            f"/projects/{_project(git_url_path)}/delete-project~delete",
            json={"force": True, "preserve": False},
        )
        if resp.status_code not in (204, 404):
            log.warning("could not delete repo %s: HTTP %s", git_url_path, resp.status_code)

    def _create_change(
        self, git_url_path: str, *, branch: str, subject: str, files: Mapping[str, str | bytes]
    ) -> str:
        """The change, with its content, identified by its NUMBER.

        Content rides as a patch on creation rather than through a change edit.
        The edit endpoint addresses each file in the URL, and a path with a '/'
        in it has no form that survives: encoded, the separator is normalised
        away and answered with a redirect; decoded, the path is read as a
        resource and a view and answered 404. A patch carries the paths in the
        BODY, so nested paths are ordinary data and the whole change is one
        request instead of one per file plus a publish.

        Gerrit accepts several change identifiers; the number is the only one
        that is unambiguous server-wide and needs no escaping, and it is the same
        identifier the platform's trigger binding carries as changeNumber."""
        payload: dict[str, Any] = {
            "project": git_url_path.strip("/"),
            "branch": branch,
            "subject": subject,
        }
        if files:
            payload["patch"] = {"patch": _patch(files)}
        resp = self._http.post("/changes/", json=payload)
        resp.raise_for_status()
        return str(_body(resp)["_number"])

    def _approve(self, number: str, labels: dict[str, int]) -> None:
        self._http.post(
            f"/changes/{number}/revisions/current/review", json={"labels": labels}
        ).raise_for_status()

    def _submit(self, number: str, *, describe: str) -> None:
        def attempt() -> httpx.Response:
            return self._http.post(f"/changes/{number}/revisions/current/submit", json={})

        poll_merge(
            attempt,
            lambda resp: _body(resp).get("status") == "MERGED",
            retry_statuses=_MERGE_RETRY_STATUSES,
            timeout=self._merge_timeout,
            interval=self._poll_interval,
            describe=describe,
        )


def _project(git_url_path: str) -> str:
    """Gerrit project names are hierarchical, so '/' is part of the name and has
    to survive as data rather than become a path separator."""
    return path_segment(git_url_path.strip("/"))


def _body(resp: httpx.Response) -> Any:
    text = resp.text
    return json.loads(text.removeprefix(_XSSI_PREFIX) if text.startswith(_XSSI_PREFIX) else text)


def _patch(files: Mapping[str, str | bytes]) -> str:
    """A git patch adding every file, for ApplyPatchInput on change creation."""
    return "".join(_new_file_diff(path, content) for path, content in sorted(files.items()))


def _new_file_diff(path: str, content: str | bytes) -> str:
    if isinstance(content, bytes):
        raise BinaryContentUnsupported(
            f"{path!r} is binary; the Gerrit client writes text patches only"
        )
    header = f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
    if not content:
        # git emits no hunk for an empty new file, and a hunk claiming zero lines
        # is not a patch Gerrit will apply.
        return header
    lines = content.split("\n")
    ends_with_newline = lines[-1] == ""
    if ends_with_newline:
        lines.pop()
    body = "".join(f"+{line}\n" for line in lines)
    if not ends_with_newline:
        body += "\\ No newline at end of file\n"
    return f"{header}--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}"


def _vote(label: dict) -> str:
    """A MaxWithBlock label reports its extremes as flags rather than as the
    numeric value, so the verdict is read from those and defaults to the neutral
    'run in progress' vote the platform casts when it starts."""
    if "approved" in label:
        return "+1"
    if "rejected" in label:
        return "-1"
    return "0"
