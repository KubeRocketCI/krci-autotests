from collections.abc import Iterator

import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.waits import Timeouts
from tests.test_data.codebase_data import go_application, smoke_change
from tests.test_data.deploy_data import auto_pipeline
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.deploy_utils import (
    CodebaseWithCd,
    codebase_with_cd_before_build,
    wait_image_tag,
)
from tests.utils.pipelinerun_utils import PipelineRuns, deploy_labels, submit_and_verify_change

# Published so any suite reusing codebase_with_cd_before_build's yield shape can
# annotate it without repeating the tuple at every call site.


@pytest.fixture
def auto_deploy_setup(
    codebase_utils: CodebaseUtils,
    vcs: VCSProvider,
    cd_utils: CDPipelineUtils,
    cluster: Cluster,
    timeouts: Timeouts,
) -> Iterator[CodebaseWithCd]:
    """Auto-stage CD pipeline over its own codebase (see codebase_with_cd_before_build)."""
    yield from codebase_with_cd_before_build(
        codebase_utils,
        vcs,
        cd_utils,
        cluster,
        timeouts,
        data=go_application(prefix="ago"),  # distinct from the shared built_codebase's "go"
        pipeline_factory=auto_pipeline,
    )


@pytest.mark.regression
@pytest.mark.api
def test_auto_deploy(
    auto_deploy_setup: CodebaseWithCd,
    codebase_utils: CodebaseUtils,
    cd_utils: CDPipelineUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
    cluster: Cluster,
    timeouts: Timeouts,
):
    """AutoDeploy: the platform deploys on its own after a merged build — the
    test triggers NOTHING deploy-side.

    Given a go application codebase and a CD pipeline whose single stage has
          triggerType Auto, both created before any build (the stage's env label
          must be on the image stream when the build updates it)
    When  a change is submitted and merged (real trigger path -> review + build)
    Then  the platform creates the deploy PipelineRun itself (CBIS update ->
          CDStageDeploy -> TriggerTemplate) and it succeeds
    And   the ArgoCD Application is Synced+Healthy running the freshly built tag
    When  pipeline, stages and codebase are deleted
    Then  all CRs and the stage namespace are fully removed

    Not asserted: the CDStageDeploy CR's own status transitions (internal
    machinery — the rendered run + healthy app are the observable outcomes);
    promotion (no applicationsToPromote here); the release-branch semver
    variant, which test_release_branch_lifecycle carries.
    """
    created, data, cd = auto_deploy_setup
    stage = cd.stages[0]
    labels = deploy_labels(cd.name)
    seen = pipeline_runs.baseline_for(labels)
    submit_and_verify_change(vcs, pipeline_runs, created, smoke_change())
    tag = wait_image_tag(cluster, timeouts, data.name, data.default_branch)
    pipeline_runs.wait_success_for(
        labels,
        since=seen,
        timeout=timeouts.deploy_success,
        describe_what=f"auto deploy for {cd.name}/{stage.name}",
    )
    cd_utils.wait_app_healthy(cd.name, stage.name, data.name, image_tag=tag)
    cd_utils.delete_cdpipeline(cd)
    cd_utils.wait_cdpipeline_deleted(cd)
    codebase_utils.delete_codebase(data.name)
    codebase_utils.wait_deleted(data.name)
