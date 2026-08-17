"""GitHub provider client — the ONLY module that speaks the GitHub REST API.

A GitHub pull request is a "change". Live validation requires a GitHub-connected
cluster; endpoint translation is unit-tested.
"""

import base64
import logging
from urllib.parse import quote

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

# GitHub's merge API has no fast-forward method. Rebase is NOT the same thing
# (it rewrites the commits), so FAST_FORWARD is absent on purpose: a test asking
# for it must fail loudly here rather than pass while testing rebase — the same
# silent-degradation rule the GitLab client's squash assertion enforces.
_STRATEGY_TO_METHOD = {
    MergeStrategy.MERGE: "merge",
    MergeStrategy.SQUASH: "squash",
}

# Merge statuses that mean "not mergeable yet" and are worth another poll: 405 not
# mergeable, 409 head moved. Anything else 4xx (401/403/404) is terminal and must
# surface instead of burning the merge timeout. 5xx goes through is_server_error.
_MERGE_RETRY_STATUSES = frozenset({405, 409})

# GitHub returns 405 both for "not mergeable yet" and for "this merge method is
# disabled on the repository" — the latter is a permanent misconfiguration that must
# not be retried until the merge timeout expires behind a misleading message. The
# two are only distinguishable by the response body's message.
_METHOD_DISABLED = "is not allowed"

# GitHub commit states are already the neutral vocabulary except for "error", and
# it has no distinct canceled state on the combined-status API.
_STATE_TO_NEUTRAL = {
    "success": CIStatus.SUCCESS,
    "failure": CIStatus.FAILED,
    "error": CIStatus.FAILED,
    "pending": CIStatus.PENDING,
}

_PAGE_SIZE = 100


class GitHubClient:
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
            {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            verify=verify,
            transport=transport,
            request_timeout=request_timeout,
        )
        self._merge_timeout = merge_timeout
        self._poll_interval = poll_interval

    def ping(self) -> str:
        resp = self._http.get("/user")
        resp.raise_for_status()
        return resp.json()["login"]

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
        resp = self._http.get(f"{repo}/branches/{path_segment(target_branch)}")
        resp.raise_for_status()
        base_sha = resp.json()["commit"]["sha"]
        self._http.post(
            f"{repo}/git/refs", json={"ref": f"refs/heads/{source_branch}", "sha": base_sha}
        ).raise_for_status()
        for path, content in files.items():
            self._http.put(
                f"{repo}/contents/{quote(path.lstrip('/'))}",
                json={
                    "message": title,
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": source_branch,
                },
            ).raise_for_status()
        resp = self._http.post(
            f"{repo}/pulls",
            json={"title": title, "head": source_branch, "base": target_branch},
        )
        resp.raise_for_status()
        pr = resp.json()
        log.info(
            "submitted change #%s (%s -> %s) in %s",
            pr["number"],
            source_branch,
            target_branch,
            git_url_path,
        )
        return Change(id=str(pr["number"]), source_branch=source_branch, url=pr["html_url"])

    def merge_change(
        self, git_url_path: str, change: Change, *, strategy: MergeStrategy = MergeStrategy.MERGE
    ) -> None:
        strategy = MergeStrategy(strategy)
        repo = _repo(git_url_path)
        try:
            method = _STRATEGY_TO_METHOD[strategy]
        except KeyError as exc:
            raise UnsupportedMergeStrategy(
                f"GitHub has no '{strategy}' merge method "
                f"(supported: {sorted(s.value for s in _STRATEGY_TO_METHOD)})"
            ) from exc

        def attempt() -> httpx.Response | None:
            probe = self._http.get(f"{repo}/pulls/{change.id}")
            if probe.is_server_error:
                return None
            probe.raise_for_status()
            if probe.json().get("mergeable") is not True:
                return None
            resp = self._http.put(f"{repo}/pulls/{change.id}/merge", json={"merge_method": method})
            _reject_disabled_merge_method(resp, method)
            return resp

        poll_merge(
            attempt,
            lambda resp: resp.json().get("merged") is True,
            retry_statuses=_MERGE_RETRY_STATUSES,
            timeout=self._merge_timeout,
            interval=self._poll_interval,
            describe=f"change #{change.id} merged ({strategy})",
        )
        log.info("merged change #%s in %s (%s)", change.id, git_url_path, strategy)

    def comment_change(self, git_url_path: str, change: Change, body: str) -> None:
        self._http.post(
            f"{_repo(git_url_path)}/issues/{change.id}/comments", json={"body": body}
        ).raise_for_status()
        log.info("commented on change #%s in %s", change.id, git_url_path)

    def change_statuses(self, git_url_path: str, change: Change) -> list[CommitStatus]:
        """CI statuses on the change's head commit (GitHub states are already
        lowercase; context maps to the neutral name)."""
        repo = _repo(git_url_path)
        resp = self._http.get(f"{repo}/pulls/{change.id}")
        resp.raise_for_status()
        sha = resp.json()["head"]["sha"]
        path = f"{repo}/commits/{sha}/status"
        return [
            CommitStatus(name=s["context"], state=normalize_ci_state(s["state"], _STATE_TO_NEUTRAL))
            for s in paginate(
                self._http,
                (path, {"per_page": _PAGE_SIZE}),
                next_request=_next_page,
                items=lambda resp: resp.json().get("statuses", []),
            )
        ]

    def delete_repo(self, git_url_path: str) -> None:
        """Best-effort teardown — VCS leftovers must never fail a test run."""
        resp = self._http.delete(_repo(git_url_path))
        if resp.status_code not in (204, 404):
            log.warning("could not delete repo %s: HTTP %s", git_url_path, resp.status_code)


def _repo(git_url_path: str) -> str:
    return f"/repos/{git_url_path.strip('/')}"


def _reject_disabled_merge_method(resp: httpx.Response, method: str) -> None:
    """Turn a disabled merge method into an immediate, named failure.

    405 is in the retry set because it also means "not mergeable yet"; without this
    split a repo with squash merging turned off burns the whole merge timeout and
    then reports a timeout, naming neither the method nor the setting."""
    if resp.status_code != 405:
        return
    message = str(resp.json().get("message", ""))
    if _METHOD_DISABLED in message.lower():
        raise UnsupportedMergeStrategy(
            f"GitHub rejected merge_method '{method}': {message} "
            "(enable it in the repository's merge-button settings)"
        )


def _next_page(resp: httpx.Response) -> Request | None:
    """GitHub's Link-header pagination. The combined-status endpoint paginates its
    `statuses` array, so a commit with many contexts is otherwise truncated."""
    following = resp.links.get("next", {}).get("url")
    if not following:
        return None
    return following, None
