"""Identity of the platform's gitops system codebase.

The cd-pipeline-operator requires exactly one system codebase labeled
systemType=gitops per namespace and bakes its repo URL into every ApplicationSet.
This module carries WHO that codebase is — nothing that provisions it: onboarding
is an environment step (scripts/bootstrap.py), and a test that needs the repo
resolves it here the same way the operator does, by label rather than by name.

Absence is deliberately not handled: a namespace without a gitops codebase is a
platform state tests must observe, not one they repair.
"""

from krci_testkit import labels
from krci_testkit.clusters import Cluster
from krci_testkit.errors import NotFound
from krci_testkit.models import Codebase

# Portal default. Only bootstrap addresses the codebase by name; lookups go
# through the selector, which is what the operator itself keys on.
GITOPS_NAME = "krci-gitops"

GITOPS_SELECTOR = {
    labels.CODEBASE_TYPE: "system",
    labels.SYSTEM_TYPE: "gitops",
}


def find_gitops(cluster: Cluster) -> Codebase:
    """The namespace's gitops codebase, resolved by the operator's own selector.

    Raises NotFound when the namespace has none — the caller is a test writing to
    the repo, and failing there reports the platform's actual state instead of
    provisioning around it."""
    found = cluster.list(Codebase, labels=GITOPS_SELECTOR)
    if not found:
        raise NotFound(f"no gitops codebase ({GITOPS_SELECTOR}) in {cluster.namespace}")
    if len(found) > 1:
        # The operator keys on exactly one match; with several, which repo backs
        # the ApplicationSets is arbitrary — refuse rather than silently pick one.
        names = ", ".join(sorted(c.metadata["name"] if c.metadata else "?" for c in found))
        raise RuntimeError(
            f"expected one gitops codebase ({GITOPS_SELECTOR}) in {cluster.namespace}, "
            f"found {len(found)}: {names}"
        )
    return found[0]
