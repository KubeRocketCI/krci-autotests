"""Flow-level wrappers for CDPipeline/Stage lifecycles and deploy assertions.

Stage CR names follow the webhook-enforced `<cdPipeline>-<stage>` convention;
deploy namespaces follow `<platform-ns>-<pipeline>-<stage>`.
"""

import logging

from krci_testkit.clusters import Cluster
from krci_testkit.models import (
    Application,
    CDPipeline,
    CDPipelineSpec,
    CodebaseImageStream,
    QualityGate,
    Source,
    Stage,
    StageSpec,
    spec_dict,
    tags_of,
)
from krci_testkit.naming import argo_app_name, stage_cr_name, verified_stream_name
from krci_testkit.naming import stage_namespace as stage_namespace_of
from krci_testkit.platform import HealthStatus, SyncStatus
from krci_testkit.waits import FailFast, Timeouts, WaitTimeout, reconciled, wait_for, wait_gone
from tests.test_data.deploy_data import CDPipelineTestData, StageTestData

log = logging.getLogger(__name__)

# Cosmetic CR field the platform requires to be non-empty; it is not asserted on.
_STAGE_DESCRIPTION = "krci-autotests stage"


def _image_at_tag(image: str, tag: str) -> bool:
    """True when the image reference runs the tag; auto-deploy payloads pin a
    digest too (repo:tag@sha256:...), so a trailing digest is stripped first."""
    return image.rsplit("@", 1)[0].endswith(f":{tag}")


def cdpipeline_spec(data: CDPipelineTestData) -> dict:
    """The CDPipeline manifest body, built from the generated CRD model. Pure, so
    the wire shape is unit-tested without a cluster."""
    spec = CDPipelineSpec(
        name=data.name,
        deploymentType=data.deployment_type,
        applications=data.applications,
        inputDockerStreams=data.input_streams,
        # `or None` keeps an empty list off the wire: spec_dict drops unset and None
        # fields, so passing [] would be the one builder that declares a field the
        # scenario never asked for.
        applicationsToPromote=data.applications_to_promote or None,
    )
    return spec_dict(spec)


def stage_spec(data: CDPipelineTestData, stage: StageTestData, *, namespace: str) -> dict:
    """The Stage manifest body (same model-first contract as cdpipeline_spec)."""
    spec = StageSpec(
        name=stage.name,
        cdPipeline=data.name,
        description=_STAGE_DESCRIPTION,
        namespace=namespace,
        order=stage.order,
        triggerType=stage.trigger_type,
        triggerTemplate=stage.trigger_template,
        clusterName=stage.cluster_name,
        source=Source(type=stage.source_type),
        qualityGates=[
            QualityGate(qualityGateType=stage.quality_gate_type, stepName=stage.step_name)
        ],
    )
    return spec_dict(spec)


class CDPipelineUtils:
    def __init__(self, cluster: Cluster, timeouts: Timeouts):
        self.cluster = cluster
        self.timeouts = timeouts

    def _stage_cr_name(self, data: CDPipelineTestData, stage: StageTestData) -> str:
        return stage_cr_name(data.name, stage.name)

    def stage_namespace(self, data: CDPipelineTestData, stage: StageTestData) -> str:
        return stage_namespace_of(self.cluster.namespace, data.name, stage.name)

    def create_cdpipeline(self, data: CDPipelineTestData) -> CDPipeline:
        """Create a CDPipeline and its stages."""
        log.info("creating cdpipeline %s (apps=%s)", data.name, data.applications)
        self.cluster.create(CDPipeline, name=data.name, spec=cdpipeline_spec(data))
        pipeline = wait_for(
            lambda: self.cluster.get(CDPipeline, data.name),
            reconciled,
            timeout=self.timeouts.codebase_ready,
            interval=self.timeouts.poll_interval,
            describe=f"cdpipeline {data.name} available",
            not_found="fail",
        )
        for stage in data.stages:
            self._create_stage(data, stage)
        return pipeline

    def _create_stage(self, data: CDPipelineTestData, stage: StageTestData) -> None:
        cr_name = self._stage_cr_name(data, stage)
        log.info("creating stage %s (trigger=%s)", cr_name, stage.trigger_type)
        self.cluster.create(
            Stage,
            name=cr_name,
            spec=stage_spec(data, stage, namespace=self.stage_namespace(data, stage)),
        )
        wait_for(
            lambda: self.cluster.get(Stage, cr_name),
            reconciled,
            timeout=self.timeouts.codebase_ready,
            interval=self.timeouts.poll_interval,
            describe=f"stage {cr_name} available",
        )
        for app in data.applications:
            wait_for(
                lambda app=app: self.cluster.exists(
                    Application, argo_app_name(data.name, stage.name, app)
                ),
                bool,
                timeout=self.timeouts.run_trigger,
                interval=self.timeouts.poll_interval,
                describe=f"argocd application {argo_app_name(data.name, stage.name, app)} exists",
            )

    def delete_stage(self, data: CDPipelineTestData, stage: StageTestData) -> None:
        self.cluster.delete(Stage, self._stage_cr_name(data, stage))

    def wait_stage_deleted(self, data: CDPipelineTestData, stage: StageTestData) -> None:
        """Assert a single stage's teardown: CR gone AND its namespace removed."""
        cr_name = self._stage_cr_name(data, stage)
        wait_gone(
            lambda: self.cluster.get_raw(Stage, cr_name),
            timeout=self.timeouts.codebase_delete,
            interval=self.timeouts.poll_interval,
            describe=f"stage {cr_name} deleted",
        )
        ns = self.stage_namespace(data, stage)
        wait_gone(
            lambda: self.cluster.namespace_raw(ns),
            timeout=self.timeouts.codebase_delete,
            interval=self.timeouts.poll_interval,
            describe=f"namespace {ns} deleted",
        )

    def delete_cdpipeline(self, data: CDPipelineTestData) -> None:
        for stage in reversed(data.stages):
            self.delete_stage(data, stage)
        self.cluster.delete(CDPipeline, data.name)

    def wait_cdpipeline_deleted(self, data: CDPipelineTestData) -> None:
        """Assert the platform's CD teardown: CRs gone AND stage namespaces removed."""
        for stage in reversed(data.stages):
            self.wait_stage_deleted(data, stage)
        wait_gone(
            lambda: self.cluster.get_raw(CDPipeline, data.name),
            timeout=self.timeouts.codebase_delete,
            interval=self.timeouts.poll_interval,
            describe=f"cdpipeline {data.name} deleted",
        )

    def cleanup_cdpipeline(self, data: CDPipelineTestData) -> None:
        """Assertion-free safety net for fixture teardown: request deletion and WAIT
        for it before the caller deletes the codebase. Deleting the codebase while a
        Stage finalizer still needs its CodebaseImageStream wedges Stage and
        CDPipeline in Terminating forever (operator finalizer bug). A timeout is logged, not
        raised — teardown must never mask the test's own failure."""
        self.delete_cdpipeline(data)
        try:
            self.wait_cdpipeline_deleted(data)
        except WaitTimeout:
            log.warning(
                "cdpipeline %s not fully deleted before teardown moved on; "
                "cluster leftovers are possible",
                data.name,
            )

    def wait_app_healthy(
        self,
        pipeline: str,
        stage: str,
        app: str,
        *,
        image_tag: str,
        image_digest: str | None = None,
    ) -> Application:
        """ArgoCD Application Synced+Healthy and actually running the given tag.
        When image_digest is given, the running image must ALSO be pinned to it
        (repo:tag@sha256:...)."""

        def ready(a: Application) -> bool:
            status = a.status
            if not status:
                return False
            synced = bool(status.sync and status.sync.status == SyncStatus.SYNCED)
            healthy = bool(status.health and status.health.status == HealthStatus.HEALTHY)
            images = (status.summary.images if status.summary else None) or []
            at_tag = [i for i in images if _image_at_tag(i, image_tag)]
            pinned = image_digest is None or any(i.endswith(f"@{image_digest}") for i in at_tag)
            return synced and healthy and bool(at_tag) and pinned

        pin = f" pinned @{image_digest}" if image_digest else ""
        return wait_for(
            lambda: self.cluster.get(Application, argo_app_name(pipeline, stage, app)),
            ready,
            timeout=self.timeouts.run_trigger,
            interval=self.timeouts.poll_interval,
            describe=(
                f"argocd app {argo_app_name(pipeline, stage, app)} "
                f"Synced+Healthy at :{image_tag}{pin}"
            ),
            not_found="fail",
        )

    def wait_workload_replicas(
        self, data: CDPipelineTestData, stage: StageTestData, app: str, *, expected: int
    ) -> None:
        """The stage's single Deployment settled at the expected replica count —
        BOTH spec.replicas (what the values source rendered) and readyReplicas
        (a stuck rollout must not pass). This is the observable gitops polarity:
        chart default (1) without overrides vs the override value with them."""

        def settled(deployments: list[dict]) -> bool:
            if len(deployments) > 1:
                # One app per stage namespace is a suite invariant — more than one
                # Deployment is a wrong-shape config error, not a not-yet state.
                names = ", ".join(d["metadata"]["name"] for d in deployments)
                raise FailFast(
                    f"expected the single {app} deployment in its stage namespace, "
                    f"found {len(deployments)}: {names}"
                )
            if not deployments:
                return False
            workload = deployments[0]
            desired = workload.get("spec", {}).get("replicas")
            ready = workload.get("status", {}).get("readyReplicas")
            return desired == expected and ready == expected

        ns = self.stage_namespace(data, stage)
        wait_for(
            lambda: self.cluster.deployments(ns),
            settled,
            timeout=self.timeouts.run_trigger,
            interval=self.timeouts.poll_interval,
            describe=f"deployment of {app} in {ns} at {expected} ready replica(s)",
        )

    def wait_promoted(
        self, pipeline: str, stage: str, app: str, tag: str, *, digest: str | None = None
    ) -> None:
        """promote-images wrote the deployed tag into the verified stream. When
        digest is given, the promoted tag must carry the SAME digest — promote
        writes name+digest in one atomic patch, so a present tag with a wrong or
        missing digest will never self-heal and fails fast instead of waiting."""
        verified = verified_stream_name(pipeline, stage, app)

        def promoted(s: CodebaseImageStream) -> bool:
            entries = [t for t in tags_of(s) if t["name"] == tag]
            if not entries:
                return False
            if digest is not None and entries[0].get("digest") != digest:
                raise FailFast(
                    f"verified stream {verified} tag {tag} carries digest "
                    f"{entries[0].get('digest')!r}, expected {digest!r}"
                )
            return True

        wait_for(
            lambda: self.cluster.get(CodebaseImageStream, verified),
            promoted,
            timeout=self.timeouts.run_trigger,
            interval=self.timeouts.poll_interval,
            describe=f"verified stream {verified} carries tag {tag}"
            + (f" with digest {digest}" if digest else ""),
        )

    def assert_not_promoted(self, pipeline: str, stage: str, app: str) -> None:
        """No promote list -> the verified stream must stay empty (instant check)."""
        verified = verified_stream_name(pipeline, stage, app)
        if self.cluster.exists(CodebaseImageStream, verified):
            stream = self.cluster.get(CodebaseImageStream, verified)
            assert not stream.spec.tags, f"unexpected promoted tags in {verified}"
