"""GitLab provider client — the ONLY module that speaks the GitLab REST API.

Verbs are provider-neutral (a GitLab merge request is a "change"): every other
provider client implements the same verbs natively, behind `VCSProvider`.
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
    http_client,
    normalize_ci_state,
    paginate,
    poll_merge,
)
from krci_testkit.platform import CIStatus

log = logging.getLogger(__name__)

# Merge statuses that mean "not mergeable yet" and are worth another poll: 405 not
# mergeable, 406 branch cannot be merged, 409 SHA mismatch. Anything else 4xx
# (401/403/404) is terminal and must surface instead of burning the merge timeout.
# 5xx is handled separately via is_server_error.
_MERGE_RETRY_STATUSES = frozenset({405, 406, 409})

# GitLab reports mergeability under two field names depending on version.
_MERGEABLE_STATUSES = frozenset({"mergeable", "can_be_merged"})

# GitLab pipeline states -> the protocol's neutral vocabulary. The names it shares
# with CIStatus still go through the map so the translation stays explicit.
_STATE_TO_NEUTRAL = {
    "success": CIStatus.SUCCESS,
    "failed": CIStatus.FAILED,
    "running": CIStatus.RUNNING,
    "pending": CIStatus.PENDING,
    "created": CIStatus.PENDING,
    "waiting_for_resource": CIStatus.PENDING,
    "preparing": CIStatus.PENDING,
    "manual": CIStatus.PENDING,
    "scheduled": CIStatus.PENDING,
    "canceled": CIStatus.CANCELED,
    "skipped": CIStatus.CANCELED,
}

# Statuses come back paginated (20/page by default); ask for the largest page so
# the common case is one request and pagination is the exception.
_PAGE_SIZE = 100


class GitLabClient:
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
            f"{base_url}/api/v4",
            {"PRIVATE-TOKEN": token},
            verify=verify,
            transport=transport,
            request_timeout=request_timeout,
        )
        self._merge_timeout = merge_timeout
        self._poll_interval = poll_interval

    def ping(self) -> str:
        resp = self._http.get("/version")
        resp.raise_for_status()
        return resp.json()["version"]

    def repo_exists(self, git_url_path: str) -> bool:
        """Whether the remote repository is already there. 404 is the answer "no",
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
        The first commit creates default_branch, and GitLab makes the first
        branch the default."""
        namespace, name = git_url_path.strip("/").rsplit("/", 1)
        resp = self._http.get("/namespaces", params={"search": namespace})
        resp.raise_for_status()
        # search matches substrings; only the exact full_path is the namespace asked for
        matches = [n for n in resp.json() if n["full_path"] == namespace]
        if not matches:
            raise ValueError(
                f"GitLab namespace {namespace!r} not found — the repo cannot be "
                "created under a group the token does not see"
            )
        self._http.post(
            "/projects",
            json={
                "path": name,
                "namespace_id": matches[0]["id"],
                "initialize_with_readme": False,
            },
        ).raise_for_status()
        actions = [_create_action(path, content) for path, content in files.items()]
        self._http.post(
            f"/projects/{_project(git_url_path)}/repository/commits",
            json={"branch": default_branch, "commit_message": "Initial commit", "actions": actions},
        ).raise_for_status()
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
        project = _project(git_url_path)
        self._http.post(
            f"/projects/{project}/repository/branches",
            params={"branch": source_branch, "ref": target_branch},
        ).raise_for_status()
        actions = [
            {"action": "create", "file_path": path, "content": content}
            for path, content in files.items()
        ]
        self._http.post(
            f"/projects/{project}/repository/commits",
            json={"branch": source_branch, "commit_message": title, "actions": actions},
        ).raise_for_status()
        resp = self._http.post(
            f"/projects/{project}/merge_requests",
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "remove_source_branch": True,
            },
        )
        resp.raise_for_status()
        mr = resp.json()
        log.info(
            "submitted change !%s (%s -> %s) in %s",
            mr["iid"],
            source_branch,
            target_branch,
            git_url_path,
        )
        return Change(id=str(mr["iid"]), source_branch=source_branch, url=mr["web_url"])

    def merge_change(
        self, git_url_path: str, change: Change, *, strategy: MergeStrategy = MergeStrategy.MERGE
    ) -> None:
        strategy = MergeStrategy(strategy)
        project = _project(git_url_path)
        if strategy is MergeStrategy.FAST_FORWARD:
            # GitLab's merge endpoint ignores merge_method — it is a PROJECT setting.
            # Safe per-test: every test owns its uniquely-named repo.
            resp = self._http.put(f"/projects/{project}", json={"merge_method": "ff"})
            resp.raise_for_status()
            # Same silent-degradation guard as the squash assertion below: a plan or
            # permission restriction can make GitLab accept this 200-OK and keep the
            # old merge_method, which would quietly turn this into a plain-merge test.
            assert resp.json().get("merge_method") == "ff", (
                "fast-forward requested but the project's merge_method stayed "
                f"{resp.json().get('merge_method')!r}"
            )
        merge_body = {"squash": True} if strategy is MergeStrategy.SQUASH else {}

        def attempt() -> httpx.Response | None:
            probe = self._http.get(f"/projects/{project}/merge_requests/{change.id}")
            if probe.is_server_error:
                return None
            probe.raise_for_status()
            state = probe.json()
            status = state.get("detailed_merge_status") or state.get("merge_status")
            if status not in _MERGEABLE_STATUSES:
                return None
            return self._http.put(
                f"/projects/{project}/merge_requests/{change.id}/merge", json=merge_body
            )

        def accepted(resp: httpx.Response) -> bool:
            result = resp.json()
            if result.get("state") != "merged":
                return False
            if strategy is MergeStrategy.SQUASH:
                # Guard against silent degradation: if GitLab ignored the squash
                # param this would quietly become a plain-merge test.
                assert result.get("squash_commit_sha"), (
                    "squash requested but merge response carries no squash_commit_sha"
                )
            return True

        poll_merge(
            attempt,
            accepted,
            retry_statuses=_MERGE_RETRY_STATUSES,
            timeout=self._merge_timeout,
            interval=self._poll_interval,
            describe=f"change !{change.id} merged ({strategy})",
        )
        log.info("merged change !%s in %s (%s)", change.id, git_url_path, strategy)

    def comment_change(self, git_url_path: str, change: Change, body: str) -> None:
        self._http.post(
            f"/projects/{_project(git_url_path)}/merge_requests/{change.id}/notes",
            json={"body": body},
        ).raise_for_status()
        log.info("commented on change !%s in %s", change.id, git_url_path)

    def change_statuses(self, git_url_path: str, change: Change) -> list[CommitStatus]:
        """CI statuses on the change's head commit (states are already the
        neutral vocabulary on GitLab)."""
        project = _project(git_url_path)
        resp = self._http.get(f"/projects/{project}/merge_requests/{change.id}")
        resp.raise_for_status()
        sha = resp.json()["sha"]
        path = f"/projects/{project}/repository/commits/{sha}/statuses"
        return [
            CommitStatus(name=s["name"], state=normalize_ci_state(s["status"], _STATE_TO_NEUTRAL))
            for s in paginate(
                self._http,
                (path, {"per_page": _PAGE_SIZE}),
                next_request=lambda resp: _next_page(resp, path),
                items=lambda resp: resp.json(),
            )
        ]

    def delete_repo(self, git_url_path: str) -> None:
        """Best-effort teardown — VCS leftovers must never fail a test run."""
        resp = self._http.delete(f"/projects/{_project(git_url_path)}")
        if resp.status_code not in (202, 204, 404):
            log.warning("could not delete repo %s: HTTP %s", git_url_path, resp.status_code)


def _project(git_url_path: str) -> str:
    return quote(git_url_path.strip("/"), safe="")


def _create_action(path: str, content: str | bytes) -> dict[str, str]:
    """Binary content rides as base64 — GitLab's text encoding rejects raw bytes."""
    if isinstance(content, bytes):
        return {
            "action": "create",
            "file_path": path,
            "content": base64.b64encode(content).decode(),
            "encoding": "base64",
        }
    return {"action": "create", "file_path": path, "content": content}


def _next_page(resp: httpx.Response, path: str) -> Request | None:
    """GitLab's offset pagination: X-Next-Page carries the next page number, and is
    empty on the last page. per_page must be repeated or the page size resets."""
    page = resp.headers.get("X-Next-Page", "")
    if not page:
        return None
    return path, {"per_page": _PAGE_SIZE, "page": page}
