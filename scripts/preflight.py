"""Pre-pytest environment verification.

Every check failing here would otherwise surface as a confusing mid-test error.
Run via `make preflight` locally and as the first step of any in-cluster runner.
"""

import sys

import httpx

from krci_testkit.auth import portal_token_identity
from krci_testkit.clients import vcs_client
from krci_testkit.clusters import Cluster, NotFound
from krci_testkit.config import load_config
from krci_testkit.git_servers import connected_git_server, git_credentials
from krci_testkit.models import CDPipeline, Codebase, PipelineRun, Stage, name_of


def main() -> int:
    failures: list[str] = []
    cfg = load_config()

    try:
        cluster = Cluster(cfg)
        cluster.ping()
    except Exception as exc:  # noqa: BLE001 - each failed check must be reported, not raised
        print(f"FAIL cluster: cannot reach API server ({exc})")
        return 1

    try:
        git_server = connected_git_server(cluster, cfg.git_server)
        print(
            f"OK   gitserver: {name_of(git_server)} "
            f"({git_server.spec.gitProvider.value}) connected [KRCI_GIT_SERVER]"
        )
        try:
            credentials = git_credentials(cluster, git_server)
            client = vcs_client(
                git_server, credentials, api_url=cfg.git_api_url, verify=cfg.httpx_verify
            )
            print(f"OK   vcs: API authenticated (version {client.ping()})")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"vcs API check failed: {exc}")
    except NotFound as exc:
        failures.append(f"gitserver selection failed: {exc}")

    unreadable = cluster.unreadable_kinds([Codebase, CDPipeline, Stage, PipelineRun])
    if unreadable:
        failures.append("namespaced CR access failed:\n       " + "\n       ".join(unreadable))
    else:
        print(f"OK   rbac: test CR kinds readable in namespace '{cluster.namespace}'")

    # The portal checks gate the UI suite alone. An API-only run leaves KRCI_PORTAL_*
    # unset, and reporting that as a failure would train the reader to ignore the
    # verdict — so an unset value is announced as a skip and the exit code stays clean.
    if cfg.portal_url is None:
        print("SKIP portal: KRCI_PORTAL_URL unset (UI tests cannot run)")
    else:
        try:
            resp = httpx.get(
                cfg.portal_url, verify=cfg.httpx_verify, follow_redirects=True, timeout=30
            )
            resp.raise_for_status()
            print(f"OK   portal: {cfg.portal_url} -> {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"portal check failed: {exc}")

    # The import seed fetches template tarballs from api.github.com. Anonymous
    # access is capped (~60/hour/IP) — enough for a few cases, not for a catalog
    # sweep — so unset is a skip with the consequence named, and a set token that
    # GitHub rejects must fail HERE, not as a mid-sweep 403 that reads like a
    # network fault.
    if cfg.github_token is None:
        print(
            "SKIP github token: KRCI_GITHUB_TOKEN unset "
            "(anonymous tarball fetches, ~60/hour — too few for import-matrix)"
        )
    else:
        try:
            resp = httpx.get(
                "https://api.github.com/rate_limit",
                headers={"Authorization": f"Bearer {cfg.github_token.get_secret_value()}"},
                timeout=30,
            )
            resp.raise_for_status()
            remaining = resp.json()["resources"]["core"]["remaining"]
            print(f"OK   github token: accepted ({remaining} API calls remaining)")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"github token check failed: {exc}")

    if cfg.portal_token is None:
        print("SKIP portal token: KRCI_PORTAL_TOKEN unset (UI tests cannot run)")
    else:
        try:
            # Reachability above says nothing about the token, and the token is what
            # every UI test logs in with — an expired one must fail HERE, not mid-suite.
            identity = portal_token_identity(cfg, cluster.api_server, verify=cluster.api_server_ca)
            print(f"OK   portal token: accepted as '{identity}'")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"portal token check failed: {exc}")

    for failure in failures:
        print(f"FAIL {failure}")
    print("preflight:", "FAILED" if failures else "OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
