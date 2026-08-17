import pytest

from krci_testkit.waits import Timeouts
from tests.api.deploy.conftest import BuiltCodebase
from tests.test_data.deploy_data import CDPipelineTestData
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.deploy_utils import apps_payload, render_deploy_run
from tests.utils.pipelinerun_utils import PipelineRuns, deploy_labels


@pytest.mark.regression
@pytest.mark.api
def test_manual_deploy(
    built_codebase: BuiltCodebase,
    manual_cd: CDPipelineTestData,
    cd_utils: CDPipelineUtils,
    pipeline_runs: PipelineRuns,
    timeouts: Timeouts,
):
    """Manual CD deploy through the portal's own trigger mechanism.

    Given a built go application (shared read-only prerequisite) and a CD
          pipeline with one Manual stage
          (fixture asserts CDPipeline/Stage available and the ArgoCD Application
          exists)
    When  a deploy PipelineRun is rendered from the stage's TriggerTemplate
          exactly as the portal does (CDPIPELINE/CDSTAGE/APPLICATIONS_PAYLOAD/
          KUBECONFIG_SECRET_NAME substituted — the run shape is platform state)
    Then  the deploy PipelineRun succeeds (timeout_deploy_success)
    And   the ArgoCD Application is Synced+Healthy running the built image tag
    And   the image is NOT promoted (no applicationsToPromote -> the verified
          stream stays empty)
    When  the stages and pipeline are deleted
    Then  the CRs and the stage namespace are fully removed

    Not asserted: pod-level details in the deploy namespace (ArgoCD health is
    the platform's own aggregate); ingress hosts (environment-specific, not
    ported); quality-gate blocking semantics (gate is manual/manual);
    custom-namespace/custom-values/ingress variants.
    """
    app = built_codebase.data.name
    stage = manual_cd.stages[0]
    labels = deploy_labels(manual_cd.name)
    seen = pipeline_runs.baseline_for(labels)
    render_deploy_run(
        cd_utils.cluster,
        pipeline=manual_cd.name,
        stage=stage,
        apps_payload=apps_payload(app, built_codebase.tag),
    )
    pipeline_runs.wait_success_for(
        labels,
        since=seen,
        timeout=timeouts.deploy_success,
        describe_what=f"deploy for {manual_cd.name}/{stage.name}",
    )
    cd_utils.wait_app_healthy(manual_cd.name, stage.name, app, image_tag=built_codebase.tag)
    cd_utils.assert_not_promoted(manual_cd.name, stage.name, app)
    cd_utils.delete_cdpipeline(manual_cd)
    cd_utils.wait_cdpipeline_deleted(manual_cd)
