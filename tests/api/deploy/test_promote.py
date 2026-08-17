import pytest

from krci_testkit.naming import stage_cr_name
from krci_testkit.waits import Timeouts
from tests.api.deploy.conftest import BuiltCodebase
from tests.test_data.deploy_data import CDPipelineTestData
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.deploy_utils import IMAGE_DIGEST_PATTERN, apps_payload, render_deploy_run
from tests.utils.pipelinerun_utils import PipelineRuns, deploy_labels


@pytest.mark.regression
@pytest.mark.api
def test_promote_between_stages(
    built_codebase: BuiltCodebase,
    promote_cd: CDPipelineTestData,
    cd_utils: CDPipelineUtils,
    pipeline_runs: PipelineRuns,
    timeouts: Timeouts,
):
    """Image promotion chains stages: stage 1 deploy promotes, stage 2 auto-deploys
    the promoted image, and the image DIGEST survives the whole chain.

    Given a built go application whose image-stream tag carries the registry
          digest the build recorded, and a promoting CD pipeline
          (applicationsToPromote set) with stages dev (Manual, order 0) and
          qa (Auto, order 1)
    When  dev is deployed via the portal-parity trigger with the built tag and
          its digest (exactly the payload the portal builds from the stream)
    Then  the dev deploy succeeds and its promote-images task writes the tag AND
          the same digest into the verified stream <pipeline>-dev-<app>-verified
    And   the verified-stream update auto-triggers the qa deploy (the platform
          labels the verified stream for the next Auto stage) and it succeeds
    And   the qa ArgoCD Application is Synced+Healthy running the promoted tag
          pinned to the same digest — the qa payload is built by the platform's
          own auto-deploy path, so the pin is platform-computed end to end
    When  stages and pipeline are deleted
    Then  all CRs and both stage namespaces are fully removed

    Not asserted: the autotest quality gate between stages; Stage annotations
    written by promote-images (internal bookkeeping); ApplicationSet generator
    internals (an intermediate hop — the pinned running image subsumes it); the
    dev payload's own digest round-trip (the test injected it; qa's is the
    platform-computed copy).
    """
    app = built_codebase.data.name
    digest = built_codebase.digest
    assert digest, "build did not record a registry digest on the image-stream tag"
    assert IMAGE_DIGEST_PATTERN.fullmatch(digest), f"malformed image digest {digest!r}"
    dev, qa = promote_cd.stages
    dev_labels = deploy_labels(promote_cd.name, stage_cr_name(promote_cd.name, dev.name))
    qa_labels = deploy_labels(promote_cd.name, stage_cr_name(promote_cd.name, qa.name))
    dev_seen = pipeline_runs.baseline_for(dev_labels)
    qa_seen = pipeline_runs.baseline_for(qa_labels)
    render_deploy_run(
        cd_utils.cluster,
        pipeline=promote_cd.name,
        stage=dev,
        apps_payload=apps_payload(app, built_codebase.tag, digest=digest),
    )
    pipeline_runs.wait_success_for(
        dev_labels,
        since=dev_seen,
        timeout=timeouts.deploy_success,
        describe_what=f"deploy for {promote_cd.name}/{dev.name}",
    )
    cd_utils.wait_promoted(promote_cd.name, dev.name, app, built_codebase.tag, digest=digest)
    pipeline_runs.wait_success_for(
        qa_labels,
        since=qa_seen,
        timeout=timeouts.deploy_success,
        describe_what=f"promoted auto deploy for {promote_cd.name}/{qa.name}",
    )
    cd_utils.wait_app_healthy(
        promote_cd.name, qa.name, app, image_tag=built_codebase.tag, image_digest=digest
    )
    cd_utils.delete_cdpipeline(promote_cd)
    cd_utils.wait_cdpipeline_deleted(promote_cd)
