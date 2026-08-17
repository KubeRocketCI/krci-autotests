"""Platform VALUE vocabulary — the strings the platform computes and we select on.

Sibling of krci_testkit.labels, which owns label KEYS; this module owns the values
those labels carry and the status strings we assert against. Everything here is a
StrEnum, so it still formats and compares as the plain string the API returns
while a typo becomes an error at authoring time instead of a wait that burns its
whole timeout and reports "no pipelinerun appeared".

CR spec vocabulary the CRD declares as an enum (strategy, ciTool, trigger type)
is NOT here: it comes from the generated models in krci_testkit.models, which
are the CRD itself. Spec fields the CRD schema types as free `str` while the
platform treats them as a closed set get hand-written enums here — the schema
lost the fact, so a generated model cannot recover it.
"""

from enum import StrEnum


class PipelineType(StrEnum):
    """Value of the app.edp.epam.com/pipelinetype label on a PipelineRun —
    the platform's own classification of the run it rendered."""

    REVIEW = "review"
    BUILD = "build"
    DEPLOY = "deploy"


class ReconcileResult(StrEnum):
    """Value of status.result on every KRCI operator CR (Codebase, CodebaseBranch,
    CDPipeline, Stage all share the shape). Not taken from one CR's generated Result
    enum on purpose: reconciled()/succeeded() are deliberately duck-typed across
    kinds, so they need one kind-independent name for the verdict."""

    SUCCESS = "success"


class GitBranchStatus(StrEnum):
    """CodebaseBranch status.git — the codebase-operator's git-side progress marker,
    typed as free `str` by the CRD. Only the terminal value is named: it is the sole
    field that reports whether the remote branch exists, which status.result cannot
    (the operator turns result success on every intermediate reconcile)."""

    BRANCH_CREATED = "branch-created"


class CIStatus(StrEnum):
    """Neutral CI state reported on a change's head commit. Each provider client
    maps its native vocabulary onto these; UNKNOWN is the explicit escape hatch so
    an unrecognised provider state can never masquerade as a pass."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class SyncStatus(StrEnum):
    """ArgoCD Application status.sync.status."""

    SYNCED = "Synced"


class HealthStatus(StrEnum):
    """ArgoCD Application status.health.status."""

    HEALTHY = "Healthy"


class VersioningType(StrEnum):
    """Codebase spec.versioning.type — closed in the codebase-operator but unmarked
    in the CRD schema. The legacy "edp" value is deprecated and has no pipelines on
    current platform versions, so it is deliberately absent here."""

    DEFAULT = "default"
    SEMVER = "semver"


class QualityGateType(StrEnum):
    """Stage spec.qualityGates[].qualityGateType. The CRD types it as free `str`;
    the portal's vocabulary is manual/autotests."""

    MANUAL = "manual"
    AUTOTESTS = "autotests"


class DeploymentType(StrEnum):
    """CDPipeline spec.deploymentType. The CRD types it as free `str` with default
    "container"; the portal's vocabulary is container/custom."""

    CONTAINER = "container"
    CUSTOM = "custom"
