"""CD pipeline / stage test data. Names are run-ID-unique per prefix; stage names
are fixed ("dev"/"qa") — uniqueness comes from the pipeline name, which also keys
the deploy namespace `<platform-ns>-<pipeline>-<stage>`."""

from dataclasses import dataclass, field

from krci_testkit.models import TriggerType
from krci_testkit.naming import image_stream_name, unique_name
from krci_testkit.platform import DeploymentType, QualityGateType


@dataclass(frozen=True)
class StageTestData:
    name: str
    order: int
    trigger_type: TriggerType
    quality_gate_type: QualityGateType = QualityGateType.MANUAL
    step_name: str = "manual"
    trigger_template: str = "deploy"
    cluster_name: str = "in-cluster"
    source_type: str = "default"  # "library" would name an autotest source instead


@dataclass(frozen=True)
class CDPipelineTestData:
    name: str
    applications: list[str]
    input_streams: list[str]
    applications_to_promote: list[str] = field(default_factory=list)
    stages: list[StageTestData] = field(default_factory=list)
    deployment_type: DeploymentType = DeploymentType.CONTAINER


def manual_pipeline(app: str, branch: str) -> CDPipelineTestData:
    """One Manual stage; no promote list."""
    return CDPipelineTestData(
        name=unique_name("mdp"),
        applications=[app],
        input_streams=[image_stream_name(app, branch)],
        stages=[StageTestData(name="dev", order=0, trigger_type=TriggerType.Manual)],
    )


def auto_pipeline(app: str, branch: str) -> CDPipelineTestData:
    """One Auto stage; deploy is rendered by the platform on CBIS update."""
    return CDPipelineTestData(
        name=unique_name("adp"),
        applications=[app],
        input_streams=[image_stream_name(app, branch)],
        stages=[StageTestData(name="dev", order=0, trigger_type=TriggerType.Auto)],
    )


def journey_pipeline(app: str, branch: str, prefix: str = "jrn") -> CDPipelineTestData:
    """Full-chain journey shape (portal-default direction): Auto dev deploys on build,
    promote-images verifies, Manual qa is deployed from the promoted stream."""
    return CDPipelineTestData(
        name=unique_name(prefix),
        applications=[app],
        input_streams=[image_stream_name(app, branch)],
        applications_to_promote=[app],
        stages=[
            StageTestData(name="dev", order=0, trigger_type=TriggerType.Auto),
            StageTestData(name="qa", order=1, trigger_type=TriggerType.Manual),
        ],
    )


def feature_pipeline(app: str, branch: str, prefix: str = "ftp") -> CDPipelineTestData:
    """One Manual stage whose input stream is a NON-default (feature) branch:
    deploy provenance comes from the stream, so the deployed tag is provably the
    feature branch's build output."""
    return CDPipelineTestData(
        name=unique_name(prefix),
        applications=[app],
        input_streams=[image_stream_name(app, branch)],
        stages=[StageTestData(name="dev", order=0, trigger_type=TriggerType.Manual)],
    )


def replica_override_values(replicas: int) -> str:
    """Per-stage gitops values override payload. replicaCount is the assertable
    knob: the scaffolded chart defaults to 1, so an override to N != 1 proves the
    gitops source (not the chart) shaped the workload."""
    return f"replicaCount: {replicas}\n"


def promote_pipeline(app: str, branch: str) -> CDPipelineTestData:
    """Manual first stage + Auto second stage with promotion: promote-images on
    stage 1 updates the verified stream, which auto-triggers stage 2."""
    return CDPipelineTestData(
        name=unique_name("pdp"),
        applications=[app],
        input_streams=[image_stream_name(app, branch)],
        applications_to_promote=[app],
        stages=[
            StageTestData(name="dev", order=0, trigger_type=TriggerType.Manual),
            StageTestData(name="qa", order=1, trigger_type=TriggerType.Auto),
        ],
    )
