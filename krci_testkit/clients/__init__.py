"""Provider clients. Provider selection happens HERE (dict dispatch) — never in tests
or tests/utils (CLAUDE.md bans `if provider ==` outside this boundary)."""

from collections.abc import Mapping
from typing import Protocol, TypedDict, Unpack

from krci_testkit.clients.bitbucket import BitbucketClient
from krci_testkit.clients.gerrit import GerritClient, in_cluster_api_url
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

# Credential secrets a provider needs BEYOND the one its GitServer names. Gerrit's
# nameSshKeySecret holds the SSH key the platform pushes with; the REST API needs
# an HTTP password, which the platform keeps in a secret of its own.
_EXTRA_CREDENTIAL_SECRETS: dict[GitProvider, tuple[str, ...]] = {
    GitProvider.gerrit: ("gerrit-ciuser-password",),
}


class UnsupportedProvider(Exception):
    """The cluster's GitServer provider has no client yet."""


class MissingCredential(ValueError):
    """A provider's credential secrets do not carry a key its client needs."""


def credential_secrets(git_server: GitServer) -> list[str]:
    """Every secret the provider's client needs, in read order (later wins).

    Returned rather than read here so this package keeps knowing WHICH secrets a
    provider needs without also depending on how the cluster is read."""
    provider = git_server.spec.gitProvider
    return [git_server.spec.nameSshKeySecret, *_EXTRA_CREDENTIAL_SECRETS.get(provider, ())]


class ClientBuilder(Protocol):
    """What a provider entry in _BUILDERS must accept.

    Spelled out instead of `**kw` so a new provider has a typed contract to
    conform to: a mismatched keyword is a pyright error at registration, not a
    generic TypeError on the first vcs_client() call in a live run.

    api_url is the caller's explicit API endpoint, or None to derive one from the
    GitServer's host. It exists because a host is not always an endpoint: Gerrit's
    is a cluster-internal service name."""

    def __call__(
        self,
        host: str,
        api_url: str | None,
        credentials: Mapping[str, str],
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


def _credential(credentials: Mapping[str, str], key: str) -> str:
    try:
        return credentials[key]
    except KeyError as exc:
        # Names the key and the ones that ARE present (never their values) — a bare
        # KeyError('token') says nothing about which secret is wrong.
        raise MissingCredential(
            f"no '{key}' key in the provider's credentials; they carry: {sorted(credentials)}"
        ) from exc


def _gitlab(
    host: str, api_url: str | None, credentials: Mapping[str, str], **kw: Unpack[_BuilderKwargs]
) -> VCSProvider:
    return GitLabClient(api_url or f"https://{host}", _credential(credentials, "token"), **kw)


def _github(
    host: str, api_url: str | None, credentials: Mapping[str, str], **kw: Unpack[_BuilderKwargs]
) -> VCSProvider:
    base = "https://api.github.com" if host == "github.com" else f"https://{host}/api/v3"
    return GitHubClient(api_url or base, _credential(credentials, "token"), **kw)


def _bitbucket(
    host: str, api_url: str | None, credentials: Mapping[str, str], **kw: Unpack[_BuilderKwargs]
) -> VCSProvider:
    # host unused by design: Bitbucket Cloud has one fixed API endpoint
    # regardless of the GitServer's gitHost (Server/DC is out of scope).
    return BitbucketClient(
        api_url or "https://api.bitbucket.org/2.0", _credential(credentials, "token"), **kw
    )


def _gerrit(
    host: str, api_url: str | None, credentials: Mapping[str, str], **kw: Unpack[_BuilderKwargs]
) -> VCSProvider:
    # The default is the in-cluster service address, the only endpoint derivable
    # from the GitServer: gitHost is a Kubernetes service name that resolves
    # nowhere else. A run from outside the cluster supplies api_url.
    return GerritClient(
        api_url or in_cluster_api_url(host),
        _credential(credentials, "user"),
        _credential(credentials, "password"),
        **kw,
    )


# Adding a provider is TWO edits: a client module, and one entry here. Keys are
# the generated GitProvider enum, so a typo here or at lookup is a pyright error.
_BUILDERS: dict[GitProvider, ClientBuilder] = {
    GitProvider.gitlab: _gitlab,
    GitProvider.github: _github,
    GitProvider.bitbucket: _bitbucket,
    GitProvider.gerrit: _gerrit,
}


def vcs_client(
    git_server: GitServer,
    credentials: Mapping[str, str],
    *,
    api_url: str | None = None,
    verify: bool | str = True,
    merge_timeout: float = DEFAULT_MERGE_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> VCSProvider:
    spec = git_server.spec
    available = sorted(p.value for p in _BUILDERS)
    git_provider = spec.gitProvider
    try:
        builder = _BUILDERS[git_provider]
    except KeyError as exc:
        raise UnsupportedProvider(
            f"no provider client for '{git_provider.value}' (available: {available})"
        ) from exc
    port = int(spec.httpsPort or 443)
    host = spec.gitHost if port == 443 else f"{spec.gitHost}:{port}"
    try:
        return builder(
            host,
            api_url,
            credentials,
            verify=verify,
            merge_timeout=merge_timeout,
            poll_interval=poll_interval,
            request_timeout=request_timeout,
        )
    except MissingCredential as exc:
        # The builder knows which key it wanted; only here is it known which
        # secrets were read, which is what the reader has to go and fix.
        raise MissingCredential(
            f"{exc} (GitServer/{name_of(git_server)} reads {credential_secrets(git_server)})"
        ) from exc


__all__ = [
    "BitbucketClient",
    "Change",
    "ClientBuilder",
    "GerritClient",
    "GitHubClient",
    "GitLabClient",
    "MergeStrategy",
    "MissingCredential",
    "UnsupportedMergeStrategy",
    "UnsupportedProvider",
    "VCSProvider",
    "credential_secrets",
    "vcs_client",
]
