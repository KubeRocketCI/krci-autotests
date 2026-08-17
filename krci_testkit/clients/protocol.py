"""Provider-neutral VCS contract every client in this package implements.

A "change" is a unit of proposed work submitted for review: GitLab merge request,
GitHub/Bitbucket pull request, (future) Gerrit change. Clients translate the
neutral verbs to their native mechanics; nothing outside krci_testkit/clients
may depend on a concrete provider class.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from urllib.parse import quote

import httpx

from krci_testkit.platform import CIStatus
from krci_testkit.waits import wait_for

log = logging.getLogger(__name__)

# Cap on pages a status listing will walk. A change with more statuses than this
# has a runaway CI loop, not a pagination need — the cap turns that into a bounded
# request count instead of a client that never returns.
_MAX_PAGES = 20

# One connection/merge-wait policy for every provider client AND the vcs_client()
# factory — a default bumped in one signature but not the others would silently
# hand different budgets to different providers.
DEFAULT_MERGE_TIMEOUT = 180.0
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_REQUEST_TIMEOUT = 30.0


class UnsupportedMergeStrategy(Exception):
    """The provider has no native equivalent of the requested neutral strategy.
    Raised instead of silently substituting a near-equivalent, which would leave
    a green test asserting something it never exercised."""


class MergeStrategy(StrEnum):
    """Neutral merge strategies. Clients translate to their native mechanics, or
    raise UnsupportedMergeStrategy — they never substitute (GitHub, for example,
    has no fast-forward merge method)."""

    MERGE = "merge"
    SQUASH = "squash"
    FAST_FORWARD = "fast_forward"


def path_segment(value: str) -> str:
    """One URL path segment. Branch names are caller-supplied and legitimately
    contain '/' (release/1.0); spliced raw they address a different route."""
    return quote(value, safe="")


def http_client(
    base_url: str,
    headers: dict[str, str],
    *,
    verify: bool | str,
    transport: httpx.BaseTransport | None,
    request_timeout: float,
) -> httpx.Client:
    """Shared client plumbing for the provider adapters (uniform timeout/transport).

    request_timeout is a caller-supplied run knob, not a literal: a transport-level
    timeout shorter than the wait it sits inside surfaces an opaque httpx.ReadTimeout
    instead of the WaitTimeout diagnostics, so it has to be tunable with the rest."""
    return httpx.Client(
        base_url=base_url,
        headers=headers,
        verify=verify,
        timeout=request_timeout,
        transport=transport,
    )


def normalize_ci_state(raw: object, native: dict[str, CIStatus]) -> CIStatus:
    """A provider's native CI state as neutral vocabulary.

    An unrecognised state becomes UNKNOWN and is logged with its raw value — it must
    never fall through to something that reads as a pass, and it must not raise
    either: a status listing is diagnostic input, not an assertion."""
    text = str(raw)
    mapped = native.get(text)
    if mapped is not None:
        return mapped
    try:
        return CIStatus(text.lower())
    except ValueError:
        log.warning("unrecognised CI state %r; reporting as %s", text, CIStatus.UNKNOWN)
        return CIStatus.UNKNOWN


Request = tuple[str, dict[str, str | int] | None]


def paginate(
    client: httpx.Client,
    first: Request,
    *,
    next_request: Callable[[httpx.Response], Request | None],
    items: Callable[[httpx.Response], list[dict]],
) -> Iterator[dict]:
    """Walk a paginated listing to exhaustion.

    Reading only the first page silently truncates the result, which is worse than
    failing: an assertion over "all statuses on this change" would quietly stop
    seeing the ones that matter once a change accumulates more than one page.

    next_request returns the FULL next request rather than a bare URL, because the
    providers page differently — GitLab re-requests the same path with a new page
    number, Bitbucket hands back an absolute URL with the cursor baked in."""
    request: Request | None = first
    for _ in range(_MAX_PAGES):
        url, params = request  # pyright: ignore[reportOptionalIterable]
        resp = client.get(url, params=params)
        resp.raise_for_status()
        yield from items(resp)
        request = next_request(resp)
        if request is None:
            return
    log.warning("stopped paginating %s after %s pages", first[0], _MAX_PAGES)


def poll_merge(
    attempt: Callable[[], httpx.Response | None],
    accepted: Callable[[httpx.Response], bool],
    *,
    retry_statuses: frozenset[int],
    timeout: float,
    interval: float,
    describe: str,
) -> None:
    """Retry a merge until it lands, with ONE terminal/transient policy for every provider.

    `attempt` performs a single merge try and returns its response, or None when
    the change is not mergeable yet (each provider probes that differently, or —
    Bitbucket — cannot probe at all and just retries the merge). `accepted` reads
    the response body and says whether the merge really happened.

    What is centralised is the status policy, which is the hard-won part and the
    part a new provider client must not re-derive: 5xx and the provider's own
    "not mergeable yet" codes are worth another poll, while every other 4xx
    (revoked token, deleted change) is TERMINAL and must surface immediately
    instead of silently burning the whole merge timeout behind a misleading
    "not mergeable yet" message.
    """

    def landed() -> bool:
        resp = attempt()
        if resp is None:
            return False
        if resp.status_code in retry_statuses or resp.is_server_error:
            return False
        resp.raise_for_status()
        return accepted(resp)

    wait_for(landed, bool, timeout=timeout, interval=interval, describe=describe)


@dataclass(frozen=True)
class Change:
    """A change submitted for review (id is the provider's change identifier)."""

    id: str
    source_branch: str
    url: str


@dataclass(frozen=True)
class CommitStatus:
    """A CI status reported on the change's head commit, in neutral vocabulary
    (clients normalize their native states via normalize_ci_state)."""

    name: str
    state: CIStatus


@runtime_checkable
class VCSProvider(Protocol):
    def ping(self) -> str: ...

    def repo_exists(self, git_url_path: str) -> bool: ...

    def submit_change(
        self,
        git_url_path: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        files: dict[str, str],
    ) -> Change: ...

    def merge_change(
        self, git_url_path: str, change: Change, *, strategy: MergeStrategy = MergeStrategy.MERGE
    ) -> None: ...

    def comment_change(self, git_url_path: str, change: Change, body: str) -> None: ...

    def change_statuses(self, git_url_path: str, change: Change) -> list[CommitStatus]: ...

    def delete_repo(self, git_url_path: str) -> None: ...
