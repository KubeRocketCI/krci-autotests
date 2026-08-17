"""The full-chain journey: one composed test certifying a provider end to end.

Onboarding strategies keep their own tests (create/import smoke, clone
regression) — the certification suite for a provider is smoke + clone + this
chain.
"""

from collections.abc import Iterator

import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.naming import stage_cr_name
from krci_testkit.waits import Timeouts
from tests.test_data.codebase_data import go_application, smoke_change
from tests.test_data.deploy_data import journey_pipeline
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.deploy_utils import (
    CodebaseWithCd,
    apps_payload,
    codebase_with_cd_before_build,
    render_deploy_run,
    wait_image_tag,
)
from tests.utils.pipelinerun_utils import PipelineRuns, deploy_labels, submit_and_verify_change

# Published so any suite reusing codebase_with_cd_before_build's yield shape can
# annotate it without repeating the tuple at every call site.


@pytest.fixture
def journey_setup(
    codebase_utils: CodebaseUtils,
    vcs: VCSProvider,
    cd_utils: CDPipelineUtils,
    cluster: Cluster,
    timeouts: Timeouts,
) -> Iterator[CodebaseWithCd]:
    """Journey CD pipeline (Auto dev -> Manual qa, promoting) over its own go
    codebase (see codebase_with_cd_before_build)."""
    yield from codebase_with_cd_before_build(
        codebase_utils,
        vcs,
        cd_utils,
        cluster,
        timeouts,
        data=go_application(prefix="jgo"),
        pipeline_factory=journey_pipeline,
    )


@pytest.mark.journey
@pytest.mark.api
@pytest.mark.serial
def test_platform_journey(
    journey_setup: CodebaseWithCd,
    codebase_utils: CodebaseUtils,
    cd_utils: CDPipelineUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
    cluster: Cluster,
    timeouts: Timeouts,
):
    """Full delivery chain in the portal-default direction, ending in an
    asserted teardown cascade.

    Given a go application (full build path: compile + sonar + container image —
          a green pipeline proves the sonar step; no separate quality-gate
          assert) and a promoting CD pipeline with stages
          dev (Auto, order 0) and qa (Manual, order 1), created before any build
    When  a change is submitted and merged (real trigger path -> review + build)
    Then  the platform auto-deploys dev (CBIS update -> CDStageDeploy ->
          TriggerTemplate) and the dev ArgoCD Application is Synced+Healthy at
          the freshly built tag
    And   promote-images writes the tag into the dev verified stream
    When  qa is deployed manually via the portal-parity TriggerTemplate render
          with the promoted tag
    Then  the qa deploy succeeds and the qa Application is Synced+Healthy at
          the promoted tag
    When  the qa Stage alone is deleted
    Then  the qa Stage CR and its namespace are removed while the dev
          Application stays Synced+Healthy (deletion does not cascade sideways)
    When  the CDPipeline and remaining dev stage are deleted
    Then  all CD CRs and both stage namespaces are fully removed
    When  the Codebase is deleted
    Then  the Codebase CR is fully removed

    Not asserted: gitops values override per stage (carried by the smoke
    sibling test_go_deploy_journey); the dev autotest quality gate;
    Sonar quality-gate status (a green pipeline containing the sonar step is the
    evidence); VCS repo removal (best-effort teardown — the operator
    never deletes remote repos).
    """
    created, data, cd = journey_setup
    app = data.name
    dev, qa = cd.stages
    dev_labels = deploy_labels(cd.name, stage_cr_name(cd.name, dev.name))
    qa_labels = deploy_labels(cd.name, stage_cr_name(cd.name, qa.name))
    dev_seen = pipeline_runs.baseline_for(dev_labels)
    qa_seen = pipeline_runs.baseline_for(qa_labels)

    submit_and_verify_change(vcs, pipeline_runs, created, smoke_change(prefix="jchg"))
    tag = wait_image_tag(cluster, timeouts, app, data.default_branch)

    pipeline_runs.wait_success_for(
        dev_labels,
        since=dev_seen,
        timeout=timeouts.deploy_success,
        describe_what=f"auto deploy for {cd.name}/{dev.name}",
    )
    cd_utils.wait_app_healthy(cd.name, dev.name, app, image_tag=tag)
    cd_utils.wait_promoted(cd.name, dev.name, app, tag)

    render_deploy_run(
        cd_utils.cluster,
        pipeline=cd.name,
        stage=qa,
        apps_payload=apps_payload(app, tag),
    )
    pipeline_runs.wait_success_for(
        qa_labels,
        since=qa_seen,
        timeout=timeouts.deploy_success,
        describe_what=f"manual deploy from promoted for {cd.name}/{qa.name}",
    )
    cd_utils.wait_app_healthy(cd.name, qa.name, app, image_tag=tag)

    cd_utils.delete_stage(cd, qa)
    cd_utils.wait_stage_deleted(cd, qa)
    cd_utils.wait_app_healthy(cd.name, dev.name, app, image_tag=tag)

    cd_utils.delete_cdpipeline(cd)
    cd_utils.wait_cdpipeline_deleted(cd)

    codebase_utils.delete_codebase(app)
    codebase_utils.wait_deleted(app)
