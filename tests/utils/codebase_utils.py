"""Flow-level wrappers over krci_testkit for the codebase lifecycle.

Provider-neutral: all VCS facts come from the GitServer CR, never from conditionals.
Build/review runs are watched (never created) via tests/utils/pipelinerun_utils.
"""

import logging

from krci_testkit.clusters import Cluster
from krci_testkit.models import (
    CiTool,
    Codebase,
    CodebaseBranch,
    CodebaseBranchSpec,
    CodebaseSpec,
    GitServer,
    Repository,
    Versioning,
    name_of,
    spec_dict,
)
from krci_testkit.naming import branch_cr_name, repo_path
from krci_testkit.waits import Timeouts, branch_ready, reconciled, wait_for, wait_gone
from tests.test_data.codebase_data import BranchTestData, CodebaseTestData

log = logging.getLogger(__name__)


def derive_git_url_path(data: CodebaseTestData, git_group: str) -> str:
    """The repo path a Codebase lands at when the data does not pin one. A repo
    seeded ahead of the CR (the import flow) must land at the SAME path the CR
    will derive — one formula, or the two silently drift apart."""
    return data.git_url_path or repo_path(git_group, data.name)


def codebase_spec(data: CodebaseTestData, *, git_server: str, git_group: str) -> dict:
    """The Codebase manifest body, built as the generated CRD model rather than a
    hand-rolled dict: a wrong field name or enum value is a pyright error here
    instead of a 422 from the API server (or, worse, a silently ignored key).
    spec_dict drops the unset optionals — startFrom and repository disappear on
    their own. Pure, so the wire shape is unit-tested without a cluster."""
    spec = CodebaseSpec(
        type=data.codebase_type,
        strategy=data.strategy,
        lang=data.lang,
        framework=data.framework,
        buildTool=data.build_tool,
        defaultBranch=data.default_branch,
        emptyProject=data.empty_project,
        gitServer=git_server,
        gitUrlPath=derive_git_url_path(data, git_group),
        deploymentScript=data.deployment_script,
        versioning=Versioning(type=data.versioning_type, startFrom=data.versioning_start_from),
        ciTool=CiTool.tekton,
        repository=Repository(url=data.repository_url) if data.repository_url else None,
    )
    return spec_dict(spec)


def branch_spec(codebase_name: str, data: BranchTestData) -> dict:
    """The CodebaseBranch manifest body (same model-first contract as codebase_spec)."""
    spec = CodebaseBranchSpec(
        codebaseName=codebase_name,
        branchName=data.branch_name,
        fromCommit="",
        release=data.release,
        version=data.version,
    )
    return spec_dict(spec)


class CodebaseUtils:
    def __init__(self, cluster: Cluster, git_server: GitServer, git_group: str, timeouts: Timeouts):
        self.cluster = cluster
        self.git_server = git_server
        self.git_group = git_group
        self.timeouts = timeouts

    def create_codebase(self, data: CodebaseTestData) -> Codebase:
        log.info(
            "creating codebase %s (%s/%s via %s)",
            data.name,
            data.lang,
            data.framework,
            name_of(self.git_server),
        )
        self.cluster.create(
            Codebase,
            name=data.name,
            spec=codebase_spec(data, git_server=name_of(self.git_server), git_group=self.git_group),
            labels=data.labels,
        )
        codebase = wait_for(
            lambda: self.cluster.get(Codebase, data.name),
            reconciled,
            timeout=self.timeouts.codebase_ready,
            interval=self.timeouts.poll_interval,
            describe=f"codebase {data.name} available",
            not_found="fail",  # we just created it — absence means it was deleted
        )
        # The branch is created asynchronously by the operator — not-found IS the
        # expected initial state here, so the default retry policy applies.
        wait_for(
            lambda: self.cluster.get(
                CodebaseBranch, branch_cr_name(data.name, data.default_branch)
            ),
            branch_ready,
            timeout=self.timeouts.codebase_ready,
            interval=self.timeouts.poll_interval,
            describe=f"codebasebranch {data.name}-{data.default_branch} ready",
        )
        return codebase

    def create_branch(self, codebase_name: str, data: BranchTestData) -> CodebaseBranch:
        cr_name = branch_cr_name(codebase_name, data.branch_name)
        log.info("creating codebasebranch %s (release=%s)", cr_name, data.release)
        self.cluster.create(CodebaseBranch, name=cr_name, spec=branch_spec(codebase_name, data))
        return wait_for(
            lambda: self.cluster.get(CodebaseBranch, cr_name),
            branch_ready,
            timeout=self.timeouts.codebase_ready,
            interval=self.timeouts.poll_interval,
            describe=f"codebasebranch {cr_name} ready",
        )

    def delete_branch(self, codebase_name: str, branch_name: str) -> None:
        self.cluster.delete(CodebaseBranch, branch_cr_name(codebase_name, branch_name))

    def wait_branch_deleted(self, codebase_name: str, branch_name: str) -> None:
        """Assert the platform's branch deletion path: the CR must actually go away."""
        cr_name = branch_cr_name(codebase_name, branch_name)
        wait_gone(
            lambda: self.cluster.get_raw(CodebaseBranch, cr_name),
            timeout=self.timeouts.codebase_delete,
            interval=self.timeouts.poll_interval,
            describe=f"codebasebranch {cr_name} deleted",
        )

    def delete_codebase(self, name: str) -> None:
        self.cluster.delete(Codebase, name)

    def wait_deleted(self, name: str) -> None:
        """Assert the platform's deletion path: the Codebase CR must actually go away."""
        wait_gone(
            lambda: self.cluster.get_raw(Codebase, name),
            timeout=self.timeouts.codebase_delete,
            interval=self.timeouts.poll_interval,
            describe=f"codebase {name} deleted",
        )
