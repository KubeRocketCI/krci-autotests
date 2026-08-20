"""Central environment config. NOTHING environment-specific is hardcoded anywhere else.

Precedence: process env > .env file.

Run-level tuning knobs (timeouts, poll interval) do NOT belong here — they are
pytest ini options (see tests/conftest.py); this object holds target facts only.
"""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class KrciConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KRCI_", env_file=".env", extra="ignore")

    kube_context: str | None = None  # None → kubeconfig current-context or in-cluster
    namespace: str  # platform namespace holding KRCI CRs
    # Portal facts are UI-only: an API-only run must not have to invent them. Both
    # are read through krci_testkit.auth, which raises a named error when a UI test
    # needs one that is unset.
    portal_url: str | None = None
    portal_token: SecretStr | None = None  # ServiceAccount token (the only auth strategy)
    git_group: str  # VCS group/org path prefix for created repos
    # GitServer CR name to test — REQUIRED (explicit provider selection: on
    # multi-provider clusters an implicit "first connected" pick would silently
    # test an arbitrary provider). Change KRCI_GIT_GROUP together with this.
    git_server: str
    # Explicit API endpoint, for a provider whose host is not one. Gerrit's gitHost
    # is a cluster-internal service name, so a run from OUTSIDE the cluster has to
    # say where the API answers; a run inside it derives the endpoint and needs
    # nothing. Left unset for every provider whose host IS its endpoint.
    git_api_url: str | None = None
    # Optional token for fetching template tarballs from api.github.com: anonymous
    # calls are capped at ~60/hour/IP, which an import sweep over the catalog exceeds.
    github_token: SecretStr | None = None
    verify_ssl: bool = True
    ca_bundle: Path | None = None

    @property
    def httpx_verify(self) -> bool | str:
        """Value for httpx verify=: the CA bundle path when set, else the flag."""
        return str(self.ca_bundle) if self.ca_bundle else self.verify_ssl

    @property
    def browser_ignore_https_errors(self) -> bool:
        """Playwright counterpart of httpx_verify, in ONE place instead of once per
        browser context. A CA bundle cannot be passed per-context — the browser
        trusts it through NODE_EXTRA_CA_CERTS (see tests/ui/conftest.py) — so only
        verify_ssl=false makes the browser skip verification."""
        return not self.verify_ssl


def load_config() -> KrciConfig:
    """Named entry point for the suite; precedence is pydantic-settings' own
    (process env above the .env file)."""
    # pydantic-settings populates required fields from the environment/.env file, not
    # from constructor arguments; pyright can't see that binding, only the bare signature.
    return KrciConfig()  # pyright: ignore[reportCallIssue]
