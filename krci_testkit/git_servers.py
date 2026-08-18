"""Identity of the GitServer under test.

A cluster may host several GitServer CRs (one per provider). This module carries
WHO the suite talks to — nothing that provisions it: selection is always explicit
by CR name, so a multi-provider cluster can never silently test an arbitrary
provider. A disconnected server is a platform state tests must observe, not one
they repair.
"""

from krci_testkit.clusters import Cluster
from krci_testkit.errors import NotFound
from krci_testkit.models import GitServer


def connected_git_server(cluster: Cluster, name: str) -> GitServer:
    """The GitServer under test — the suite's ONE provider-selection point.

    name comes from KRCI_GIT_SERVER (required) and picks the GitServer by CR name.
    Raises NotFound when the server exists but reports itself disconnected."""
    git_server = cluster.get(GitServer, name)
    if not (git_server.status and git_server.status.connected):
        raise NotFound(f"GitServer/{name} exists but is not connected")
    return git_server
