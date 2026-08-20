"""Provision the environment prerequisites a test run does not create for itself.

Today that is the gitops system codebase. It is onboarded HERE and not by a
fixture on purpose: tests assert what the platform does, so a suite that quietly
provisioned its own prerequisites would be grading a state it had arranged. A
deploy run against a namespace without gitops is expected to fail, and that
failure is a finding.

Run via `make bootstrap`, once per environment, before the first deploy run.
"""

import logging
import sys

from krci_testkit.clients import vcs_client
from krci_testkit.clusters import Cluster
from krci_testkit.config import KrciConfig, load_config
from krci_testkit.errors import NotFound
from krci_testkit.git_servers import connected_git_server, git_credentials
from krci_testkit.gitops import GITOPS_NAME, GITOPS_SELECTOR, find_gitops
from krci_testkit.models import (
    CiTool,
    Codebase,
    CodebaseSpec,
    CodebaseStrategy,
    Versioning,
    git_url_path_of,
    name_of,
    spec_dict,
)
from krci_testkit.naming import repo_path
from krci_testkit.platform import VersioningType
from krci_testkit.waits import Timeouts, reconciled, wait_for

log = logging.getLogger("bootstrap")

# The testkit narrates its steps at INFO; the HTTP libraries narrate every request
# there too and would bury it. Same demotion tests/conftest.py applies to a run.
_NOISY_LOGGERS = ("httpx", "httpcore", "kr8s", "urllib3")


def _gitops_spec(cfg: KrciConfig, *, adopt_existing_repo: bool) -> dict:
    """The gitops Codebase manifest body.

    Strategy is the whole point of this script. `create` provisions a fresh repo
    from the platform's template; the codebase-operator refuses it outright when
    the remote already carries a default branch, which is the state left behind
    whenever the CR was removed but the repo was not. `import` adopts that repo
    instead, so re-onboarding is not a manual repair job."""
    spec = CodebaseSpec(
        # The portal's gitops-onboarding shape (CreateGitOpsForm defaults).
        type="system",
        lang="helm",
        framework="gitops",
        buildTool="helm",
        strategy=CodebaseStrategy.import_ if adopt_existing_repo else CodebaseStrategy.create,
        defaultBranch="main",
        emptyProject=False,
        gitServer=cfg.git_server,
        gitUrlPath=repo_path(cfg.git_group, GITOPS_NAME),
        deploymentScript="helm-chart",
        versioning=Versioning(type=VersioningType.SEMVER, startFrom="0.1.0-SNAPSHOT"),
        ciTool=CiTool.tekton,
    )
    return spec_dict(spec)


def _repo_exists(cfg: KrciConfig, cluster: Cluster) -> bool:
    git_server = connected_git_server(cluster, cfg.git_server)
    client = vcs_client(
        git_server,
        git_credentials(cluster, git_server),
        api_url=cfg.git_api_url,
        verify=cfg.httpx_verify,
    )
    return client.repo_exists(repo_path(cfg.git_group, GITOPS_NAME))


def ensure_gitops(cfg: KrciConfig, cluster: Cluster, timeouts: Timeouts) -> Codebase:
    """Idempotent: an already-onboarded namespace is left exactly as it is."""
    try:
        existing = find_gitops(cluster)
    except NotFound:
        pass
    else:
        log.info(
            "gitops codebase %s already onboarded (%s)",
            name_of(existing),
            git_url_path_of(existing),
        )
        return existing

    adopt = _repo_exists(cfg, cluster)
    log.info(
        "onboarding gitops codebase %s (%s strategy — repo %s)",
        GITOPS_NAME,
        "import" if adopt else "create",
        "already exists" if adopt else "will be provisioned",
    )
    cluster.create(
        Codebase,
        name=GITOPS_NAME,
        spec=_gitops_spec(cfg, adopt_existing_repo=adopt),
        labels=GITOPS_SELECTOR,
    )
    return wait_for(
        lambda: cluster.get(Codebase, GITOPS_NAME),
        reconciled,
        timeout=timeouts.codebase_ready,
        interval=timeouts.poll_interval,
        describe=f"gitops codebase {GITOPS_NAME} available",
        not_found="fail",
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    cfg = load_config()
    cluster = Cluster(cfg)
    try:
        gitops = ensure_gitops(cfg, cluster, Timeouts())
    except Exception as exc:  # noqa: BLE001 - a bootstrap failure is a report, not a traceback
        print(f"FAIL gitops: {exc}")
        return 1
    print(f"OK   gitops: {name_of(gitops)} -> {git_url_path_of(gitops)}")
    print("bootstrap: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
