"""Provider clients. Provider selection happens HERE (dict dispatch) — never in tests
or tests/utils (CLAUDE.md bans `if provider ==` outside this boundary)."""

from typing import Protocol, TypedDict, Unpack

from krci_testkit.clients.bitbucket import BitbucketClient
from krci_testkit.clients.github import GitHubClient
from krci_testkit.clients.gitlab import GitLabClient
from krci_testkit.clients.protocol import (
    DEFAULT_MERGE_TIMEOUT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REQUEST_TIMEOUT,
    Change,
    MergeStrategy,
    UnsupportedMergeStrategy,
    VCSProvider,
)
from krci_testkit.models import GitProvider, GitServer, name_of


class UnsupportedProvider(Exception):
    """The cluster's GitServer provider has no client yet (gerrit remains open)."""


class ClientBuilder(Protocol):
    """What a provider entry in _BUILDERS must accept.

    Spelled out instead of `**kw` so a new provider has a typed contract to
    conform to: a mismatched keyword is a pyright error at registration, not a
    generic TypeError on the first vcs_client() call in a live run."""

    def __call__(
        self,
        host: str,
        token: str,
        *,
        verify: bool | str,
        merge_timeout: float,
        poll_interval: float,
        request_timeout: float,
    ) -> VCSProvider: ...


class _BuilderKwargs(TypedDict):
    """The keyword-only tail of `ClientBuilder.__call__`, spelled out so each
    provider function's `**kw` stays typed to the same contract."""

    verify: bool | str
    merge_timeout: float
    poll_interval: float
    request_timeout: float


def _gitlab(host: str, token: str, **kw: Unpack[_BuilderKwargs]) -> VCSProvider:
    return GitLabClient(f"https://{host}", token, **kw)


def _github(host: str, token: str, **kw: Unpack[_BuilderKwargs]) -> VCSProvider:
    base = "https://api.github.com" if host == "github.com" else f"https://{host}/api/v3"
    return GitHubClient(base, token, **kw)


def _bitbucket(host: str, token: str, **kw: Unpack[_BuilderKwargs]) -> VCSProvider:
    # host unused by design: Bitbucket Cloud has one fixed API endpoint
    # regardless of the GitServer's gitHost (Server/DC is out of scope).
    return BitbucketClient("https://api.bitbucket.org/2.0", token, **kw)


# Adding a provider is TWO edits: a client module, and one entry here. Keys are
# the generated GitProvider enum, so a typo here or at lookup is a pyright error.
_BUILDERS: dict[GitProvider, ClientBuilder] = {
    GitProvider.gitlab: _gitlab,
    GitProvider.github: _github,
    GitProvider.bitbucket: _bitbucket,
}


def vcs_client(
    git_server: GitServer,
    credentials: dict[str, str],
    *,
    verify: bool | str = True,
    merge_timeout: float = DEFAULT_MERGE_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> VCSProvider:
    spec = git_server.spec
    # Fetched-from-cluster GitServers always carry a spec; the model only allows
    # None because the generated schema doesn't distinguish "required in practice".
    assert spec is not None, f"GitServer/{name_of(git_server)} has no spec"
    available = sorted(p.value for p in _BUILDERS)
    git_provider = spec.gitProvider
    if git_provider is None:
        raise UnsupportedProvider(
            f"GitServer/{name_of(git_server)} declares no gitProvider (available: {available})"
        )
    try:
        builder = _BUILDERS[git_provider]
    except KeyError as exc:
        raise UnsupportedProvider(
            f"no provider client for '{git_provider.value}' (available: {available})"
        ) from exc
    port = int(spec.httpsPort or 443)
    host = spec.gitHost if port == 443 else f"{spec.gitHost}:{port}"
    try:
        token = credentials["token"]
    except KeyError as exc:
        # Names the secret and the keys it does carry (never their values) — a bare
        # KeyError('token') says nothing about which secret is wrong.
        raise ValueError(
            f"secret '{spec.nameSshKeySecret}' (GitServer/{name_of(git_server)}) has no 'token' "
            f"key; it carries: {sorted(credentials)}"
        ) from exc
    return builder(
        host,
        token,
        verify=verify,
        merge_timeout=merge_timeout,
        poll_interval=poll_interval,
        request_timeout=request_timeout,
    )


__all__ = [
    "BitbucketClient",
    "Change",
    "ClientBuilder",
    "GitHubClient",
    "GitLabClient",
    "MergeStrategy",
    "UnsupportedMergeStrategy",
    "UnsupportedProvider",
    "VCSProvider",
    "vcs_client",
]
