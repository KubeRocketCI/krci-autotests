"""Maximum-e2e smoke leg — full delivery chain with both gitops polarities.

Every deploy assert here is something only its configuration could produce:
chart-default replicas (gitops off), override replicas (gitops on), promoted
tag (promotion). Feature-branch coverage lives in test_python_feature_lifecycle.
Designed to run in parallel with the other two smoke tests (distinct
unique_name prefixes, own resources).
"""

import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.naming import stage_cr_name
from krci_testkit.waits import Timeouts
from tests.test_data.codebase_data import simple_change
from tests.test_data.deploy_data import replica_override_values
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.deploy_utils import (
    CodebaseWithCd,
    apps_payload,
    render_deploy_run,
    wait_image_tag,
)
from tests.utils.gitops_utils import merge_values_override
from tests.utils.pipelinerun_utils import PipelineRuns, deploy_labels, submit_and_verify_change


@pytest.mark.api
def test_go_deploy_journey(
    deploy_journey_setup: CodebaseWithCd,
    codebase_utils: CodebaseUtils,
    cd_utils: CDPipelineUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
    cluster: Cluster,
    timeouts: Timeouts,
):
    """Smoke delivery chain: create-strategy go app through both gitops polarities.

    Given a go application (create
          strategy, SEMVER versioning — the journey also exercises the go
          *-build-semver pipeline and semver image tags) and a promoting CD
          pipeline with stages dev (Auto, order 0) and qa (Manual, order 1),
          created before any build
    When  a qa values override (replicaCount: 2) is merged into the gitops repo
          at <cdpipeline>/qa/<app>-values.yaml (submit+merge on the default branch)
    And   a change is submitted and merged (real trigger path -> review + build)
    Then  the platform auto-deploys dev WITHOUT gitops (customValues stays false)
          and the dev Application is Synced+Healthy at the built tag
    And   the dev workload runs exactly 1 replica — the chart scaffold default,
          proving the gitops repo was NOT consulted
    And   promote-images writes the tag into the dev verified stream
    When  qa is deployed manually (portal-parity TriggerTemplate render) with the
          promoted tag and customValues=true
    Then  the qa deploy succeeds, the qa Application is Synced+Healthy at the
          promoted tag, and the qa workload runs exactly 2 replicas — proving the
          gitops override (not the chart) shaped the workload
    And   promote-images writes the tag into the qa verified stream
    When  the qa Stage alone is deleted
    Then  its CR and namespace are removed while dev stays Synced+Healthy
    When  the CDPipeline and remaining dev stage are deleted
    Then  all CD CRs and both stage namespaces are fully removed
    When  the Codebase is deleted
    Then  the Codebase CR is fully removed

    Not asserted: the override values file's later fate (left in the gitops repo
    by design — cleanup is environmental: ephemeral Gerrit / group-scoped GitLab);
    the gitops repo's own review/build runs for the override commit (not the
    behavior under test); Sonar quality-gate status (green pipeline containing
    the sonar step is the evidence); semver version-bump semantics
    (regression scope — versioning specifics are deliberately out of smoke).
    The dev replicas=1 assert leans on the operator scaffold's replicaCount
    default — a documented assumption.
    Smoke-scoped sibling of test_platform_journey, adding the gitops polarity
    asserts.
    """
    created, data, cd = deploy_journey_setup
    app = data.name
    dev, qa = cd.stages
    dev_labels = deploy_labels(cd.name, stage_cr_name(cd.name, dev.name))
    qa_labels = deploy_labels(cd.name, stage_cr_name(cd.name, qa.name))
    dev_seen = pipeline_runs.baseline_for(dev_labels)
    qa_seen = pipeline_runs.baseline_for(qa_labels)

    merge_values_override(
        vcs,
        cluster,
        pipeline=cd.name,
        stage=qa.name,
        app=app,
        content=replica_override_values(2),
    )

    submit_and_verify_change(vcs, pipeline_runs, created, simple_change(prefix="sjc"))
    tag = wait_image_tag(cluster, timeouts, app, data.default_branch)

    pipeline_runs.wait_success_for(
        dev_labels,
        since=dev_seen,
        timeout=timeouts.deploy_success,
        describe_what=f"auto deploy for {cd.name}/{dev.name}",
    )
    cd_utils.wait_app_healthy(cd.name, dev.name, app, image_tag=tag)
    cd_utils.wait_workload_replicas(cd, dev, app, expected=1)
    cd_utils.wait_promoted(cd.name, dev.name, app, tag)

    render_deploy_run(
        cd_utils.cluster,
        pipeline=cd.name,
        stage=qa,
        apps_payload=apps_payload(app, tag, custom_values=True),
    )
    pipeline_runs.wait_success_for(
        qa_labels,
        since=qa_seen,
        timeout=timeouts.deploy_success,
        describe_what=f"manual gitops deploy from promoted for {cd.name}/{qa.name}",
    )
    cd_utils.wait_app_healthy(cd.name, qa.name, app, image_tag=tag)
    cd_utils.wait_workload_replicas(cd, qa, app, expected=2)
    cd_utils.wait_promoted(cd.name, qa.name, app, tag)

    cd_utils.delete_stage(cd, qa)
    cd_utils.wait_stage_deleted(cd, qa)
    cd_utils.wait_app_healthy(cd.name, dev.name, app, image_tag=tag)

    cd_utils.delete_cdpipeline(cd)
    cd_utils.wait_cdpipeline_deleted(cd)

    codebase_utils.delete_codebase(app)
    codebase_utils.wait_deleted(app)
