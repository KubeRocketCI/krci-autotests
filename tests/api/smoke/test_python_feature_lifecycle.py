"""Import strategy + feature-branch lifecycle ending in a provenance deploy."""

import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.models import Codebase, name_of
from krci_testkit.naming import stage_cr_name
from krci_testkit.waits import Timeouts
from tests.api.smoke.conftest import OwnedPipeline
from tests.test_data.codebase_data import feature_branch, smoke_change
from tests.test_data.deploy_data import feature_pipeline
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.deploy_utils import apps_payload, render_deploy_run, wait_image_tag
from tests.utils.pipelinerun_utils import PipelineRuns, deploy_labels, submit_and_verify_change

# Mirrors the factory signature of owned_pipeline (tests/api/smoke/conftest.py).


@pytest.mark.smoke
@pytest.mark.api
def test_python_feature_lifecycle(
    imported_fastapi_codebase: Codebase,
    owned_pipeline: OwnedPipeline,
    codebase_utils: CodebaseUtils,
    cd_utils: CDPipelineUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
    cluster: Cluster,
    timeouts: Timeouts,
):
    """Feature-branch CRUD on an import-strategy python app, deployed FROM the branch.

    Given a fastapi application onboarded with the IMPORT strategy over a
          pre-seeded repo (fixture asserts readiness — proves the import path)
    When  a feature CodebaseBranch CR is created
    Then  the branch becomes ready (git branch + branch pipelines exist)
    When  a change is submitted to the feature branch and merged
    Then  review and build PipelineRuns labeled with the branch succeed, and the
          FEATURE branch's CodebaseImageStream carries the built tag
    When  a CD pipeline is created whose input stream IS the feature branch's
          stream, and its Manual dev stage is deployed (portal-parity render) at
          that platform-computed tag
    Then  the deploy run succeeds and the Application is Synced+Healthy at the
          feature tag — the workload provably runs the feature branch's build,
          not the default branch's
    When  the CD pipeline is deleted
    Then  all CD CRs and the stage namespace are fully removed
    When  the CodebaseBranch CR is deleted
    Then  it is fully removed from the cluster

    Not asserted: replica counts (gitops polarity belongs to test_go_deploy_journey; this deploy
    keeps customValues=false); default-branch stream contents; git-branch removal
    in the VCS; import content fidelity. The python/fastapi triple is the
    platform's enabled-by-default python tile (plain python-3.13 pipelines ship
    disabled).
    """
    name = name_of(imported_fastapi_codebase)
    branch = feature_branch(prefix="sft")
    codebase_utils.create_branch(name, branch)
    submit_and_verify_change(
        vcs,
        pipeline_runs,
        imported_fastapi_codebase,
        smoke_change(prefix="spc"),
        branch=branch.branch_name,
    )
    tag = wait_image_tag(cluster, timeouts, name, branch.branch_name)

    cd = owned_pipeline(feature_pipeline(name, branch.branch_name))
    (dev,) = cd.stages
    labels = deploy_labels(cd.name, stage_cr_name(cd.name, dev.name))
    seen = pipeline_runs.baseline_for(labels)
    render_deploy_run(
        cluster,
        pipeline=cd.name,
        stage=dev,
        apps_payload=apps_payload(name, tag),
    )
    pipeline_runs.wait_success_for(
        labels,
        since=seen,
        timeout=timeouts.deploy_success,
        describe_what=f"manual deploy from feature stream for {cd.name}/{dev.name}",
    )
    cd_utils.wait_app_healthy(cd.name, dev.name, name, image_tag=tag)

    cd_utils.delete_cdpipeline(cd)
    cd_utils.wait_cdpipeline_deleted(cd)

    codebase_utils.delete_branch(name, branch.branch_name)
    codebase_utils.wait_branch_deleted(name, branch.branch_name)
