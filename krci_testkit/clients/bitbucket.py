"""Bitbucket Cloud provider client — the ONLY module that speaks the Bitbucket 2.0 API.

A Bitbucket pull request is a "change". Cloud only (api.bitbucket.org/2.0);
Server/Data Center is out of scope. Auth follows
the platform convention (codebase-operator BasicTokenAuthProvider): the GitServer
secret's token is a pre-encoded user:app_password sent as "Basic <token>". Live
validation requires a Bitbucket-connected cluster; translation is unit-tested.
"""

import logging

import httpx

from krci_testkit.clients.protocol import (
    DEFAULT_MERGE_TIMEOUT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REQUEST_TIMEOUT,
    Change,
    CommitStatus,
    MergeStrategy,
    Request,
    UnsupportedMergeStrategy,
    http_client,
    normalize_ci_state,
    paginate,
    path_segment,
    poll_merge,
)
from krci_testkit.platform import CIStatus

log = logging.getLogger(__name__)

_STRATEGY_TO_TYPE = {
    MergeStrategy.MERGE: "merge_commit",
    MergeStrategy.SQUASH: "squash",
    MergeStrategy.FAST_FORWARD: "fast_forward",
}

# 409 means the PR is still settling and is worth another poll; anything else 4xx
# (401/403/404) is terminal and must surface instead of burning the merge timeout.
# Bitbucket's own 555 is a 5xx, so it is covered by is_server_error.
_MERGE_RETRY_STATUSES = frozenset({409})

# Bitbucket build-status states -> the protocol's neutral vocabulary.
_STATE_TO_NEUTRAL = {
    "SUCCESSFUL": CIStatus.SUCCESS,
    "FAILED": CIStatus.FAILED,
    "INPROGRESS": CIStatus.RUNNING,
    "STOPPED": CIStatus.CANCELED,
}

# The /src form endpoint carries the commit metadata in the SAME body as the file
# paths, so a file named "branch" or "message" would overwrite it.
_RESERVED_SRC_FIELDS = frozenset({"branch", "message", "author", "parents", "files"})

_PAGE_SIZE = 100


class BitbucketClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        verify: bool | str = True,
        merge_timeout: float = DEFAULT_MERGE_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ):
        self._http = http_client(
            base_url,
            {"Authorization": f"Basic {token}"},
            verify=verify,
            transport=transport,
            request_timeout=request_timeout,
        )
        self._merge_timeout = merge_timeout
        self._poll_interval = poll_interval

    def ping(self) -> str:
        resp = self._http.get("/user")
        resp.raise_for_status()
        return resp.json()["username"]

    def repo_exists(self, git_url_path: str) -> bool:
        """Whether the remote repository is already there. 404 is the answer "no",
        not an error: a caller asks this precisely because either state is normal."""
        resp = self._http.get(_repo(git_url_path))
        if resp.status_code == httpx.codes.NOT_FOUND:
            return False
        resp.raise_for_status()
        return True

    def submit_change(
        self,
        git_url_path: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        files: dict[str, str],
    ) -> Change:
        repo = _repo(git_url_path)
        if collisions := _RESERVED_SRC_FIELDS & files.keys():
            raise ValueError(
                f"file path(s) {sorted(collisions)} collide with reserved Bitbucket "
                "/src form fields; the commit metadata would be overwritten silently"
            )
        resp = self._http.get(f"{repo}/refs/branches/{path_segment(target_branch)}")
        resp.raise_for_status()
        base_hash = resp.json()["target"]["hash"]
        self._http.post(
            f"{repo}/refs/branches",
            json={"name": source_branch, "target": {"hash": base_hash}},
        ).raise_for_status()
        self._http.post(
            f"{repo}/src",
            data={**files, "branch": source_branch, "message": title},
        ).raise_for_status()
        resp = self._http.post(
            f"{repo}/pullrequests",
            json={
                "title": title,
                "source": {"branch": {"name": source_branch}},
                "destination": {"branch": {"name": target_branch}},
                "close_source_branch": True,
            },
        )
        resp.raise_for_status()
        pr = resp.json()
        log.info(
            "submitted change #%s (%s -> %s) in %s",
            pr["id"],
            source_branch,
            target_branch,
            git_url_path,
        )
        return Change(
            id=str(pr["id"]), source_branch=source_branch, url=pr["links"]["html"]["href"]
        )

    def merge_change(
        self, git_url_path: str, change: Change, *, strategy: MergeStrategy = MergeStrategy.MERGE
    ) -> None:
        strategy = MergeStrategy(strategy)
        repo = _repo(git_url_path)
        try:
            merge_type = _STRATEGY_TO_TYPE[strategy]
        except KeyError as exc:
            raise UnsupportedMergeStrategy(
                f"Bitbucket has no '{strategy}' merge type "
                f"(supported: {sorted(s.value for s in _STRATEGY_TO_TYPE)})"
            ) from exc

        # Bitbucket has no mergeable probe; retry the merge itself until it lands
        # (409/555 while the PR is still settling after webhook delivery).
        poll_merge(
            lambda: self._http.post(
                f"{repo}/pullrequests/{change.id}/merge", json={"type": merge_type}
            ),
            lambda resp: resp.json().get("state") == "MERGED",
            retry_statuses=_MERGE_RETRY_STATUSES,
            timeout=self._merge_timeout,
            interval=self._poll_interval,
            describe=f"change #{change.id} merged ({strategy})",
        )
        log.info("merged change #%s in %s (%s)", change.id, git_url_path, strategy)

    def comment_change(self, git_url_path: str, change: Change, body: str) -> None:
        self._http.post(
            f"{_repo(git_url_path)}/pullrequests/{change.id}/comments",
            json={"content": {"raw": body}},
        ).raise_for_status()
        log.info("commented on change #%s in %s", change.id, git_url_path)

    def change_statuses(self, git_url_path: str, change: Change) -> list[CommitStatus]:
        """CI statuses on the change's head commit, normalized to the neutral
        state vocabulary."""
        repo = _repo(git_url_path)
        resp = self._http.get(f"{repo}/pullrequests/{change.id}")
        resp.raise_for_status()
        sha = resp.json()["source"]["commit"]["hash"]
        return [
            CommitStatus(name=s["name"], state=normalize_ci_state(s["state"], _STATE_TO_NEUTRAL))
            for s in paginate(
                self._http,
                (f"{repo}/commit/{sha}/statuses", {"pagelen": _PAGE_SIZE}),
                next_request=_next_page,
                items=lambda resp: resp.json().get("values", []),
            )
        ]

    def delete_repo(self, git_url_path: str) -> None:
        """Best-effort teardown — VCS leftovers must never fail a test run."""
        resp = self._http.delete(_repo(git_url_path))
        if resp.status_code not in (204, 404):
            log.warning("could not delete repo %s: HTTP %s", git_url_path, resp.status_code)


def _repo(git_url_path: str) -> str:
    return f"/repositories/{git_url_path.strip('/')}"


def _next_page(resp: httpx.Response) -> Request | None:
    """Bitbucket's cursor pagination: an absolute `next` URL, absent on the last page."""
    following = resp.json().get("next")
    if not following:
        return None
    return str(following), None
