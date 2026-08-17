"""GitOps repo flow: per-stage values overrides.

Overrides land on the repo's default branch through the provider-neutral
submit+merge verbs — the portal itself never writes the file (it deep-links users
to commit out-of-band), so a VCS commit IS portal parity.

Onboarding the gitops codebase is NOT here: it is an environment prerequisite
(scripts/bootstrap.py). A namespace without one makes deploy scenarios fail, and
that failure is the platform's answer, not something the suite arranges away.
"""

import logging

from krci_testkit.clients import VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.gitops import find_gitops
from krci_testkit.models import default_branch_of, git_url_path_of
from krci_testkit.naming import unique_name

log = logging.getLogger(__name__)


def gitops_values_path(pipeline: str, stage: str, app: str) -> str:
    """Platform convention (cd-pipeline-operator ApplicationSet templatePatch):
    $values/<cdpipeline>/<stage>/<app>-values.yaml at the gitops repo root."""
    return f"{pipeline}/{stage}/{app}-values.yaml"


def merge_values_override(
    vcs: VCSProvider, cluster: Cluster, *, pipeline: str, stage: str, app: str, content: str
) -> None:
    """Land a per-stage values override on the gitops repo's default branch via
    the neutral submit+merge verbs (protected-branch-safe, Gerrit-mappable).
    The override's review/build runs on the gitops repo are NOT waited on —
    they are not the behavior under test.

    The repo is resolved here by the operator's own selector rather than taken as
    a fixture: the caller needs a commit target, and turning that into a declared
    prerequisite is what previously let the suite provision one for itself."""
    gitops = find_gitops(cluster)
    path = gitops_values_path(pipeline, stage, app)
    change = vcs.submit_change(
        git_url_path_of(gitops),
        # Scoped by PIPELINE, not just stage: stage names are a fixed vocabulary
        # ("dev"/"qa"), so a stage-only name is identical for every test in a worker.
        # An aborted override then leaves a branch the next test collides with, on
        # the one repo the whole suite shares.
        source_branch=unique_name(f"gvo-{pipeline}-{stage}"),
        target_branch=default_branch_of(gitops),
        title=f"test: values override for {pipeline}/{stage}/{app}",
        files={path: content},
    )
    vcs.merge_change(git_url_path_of(gitops), change)
    log.info("merged gitops values override %s", path)
