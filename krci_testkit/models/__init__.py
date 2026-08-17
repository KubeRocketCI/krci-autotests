"""Generated CRD models. Generated modules (codebase.py, ...) are never hand-edited;
this registry file is the only hand-written module in the package."""

from dataclasses import dataclass

from pydantic import BaseModel

from krci_testkit.models.application import Application
from krci_testkit.models.cdpipeline import CDPipeline
from krci_testkit.models.cdpipeline import Spec as CDPipelineSpec
from krci_testkit.models.codebase import Codebase
from krci_testkit.models.codebase import CiTool, Repository, Versioning
from krci_testkit.models.codebase import Spec as CodebaseSpec
from krci_testkit.models.codebase import Strategy as CodebaseStrategy
from krci_testkit.models.codebasebranch import CodebaseBranch
from krci_testkit.models.codebasebranch import Spec as CodebaseBranchSpec
from krci_testkit.models.codebaseimagestream import CodebaseImageStream
from krci_testkit.models.gitserver import GitProvider, GitServer
from krci_testkit.models.pipelinerun import PipelineRun
from krci_testkit.models.stage import QualityGate, Source, Stage
from krci_testkit.models.stage import Spec as StageSpec
from krci_testkit.models.stage import TriggerType
from krci_testkit.models.triggertemplate import TriggerTemplate


def spec_dict(spec: BaseModel) -> dict:
    """A built spec model as the manifest body kr8s sends.

    Sends exactly what the caller declared and nothing else:
    - exclude_unset keeps the MODEL's defaults off the wire. They are copies of
      the CRD's own defaults, so sending them would look deliberate while merely
      restating the CRD — and would silently pin a value the platform later
      changes the default of.
    - exclude_none drops declared-but-empty fields, so a builder cannot send an
      explicit null. That is deliberate: the CRDs here treat "field absent" as the
      only way to leave a field alone, and a builder that needs to CLEAR a field
      would need a different serializer, not this one. Falsy-but-present values
      (false, 0, "") are kept.
    - mode="json" renders the generated Enum members as their wire values."""
    return spec.model_dump(exclude_unset=True, exclude_none=True, mode="json")


@dataclass(frozen=True)
class GvkInfo:
    api_version: str
    kind: str
    plural: str  # explicit — kr8s guesses wrong for e.g. CodebaseBranch


def name_of(model) -> str:
    """metadata.name across generated-model shapes: plain dict (CRD-generated),
    RootModel[Any] wrapper (swagger-generated, e.g. Tekton's V1ObjectMeta), or attrs."""
    meta = model.metadata
    if hasattr(meta, "root"):
        meta = meta.root
    return meta["name"] if isinstance(meta, dict) else meta.name


def git_url_path_of(codebase) -> str:
    """A Codebase's spec.gitUrlPath. The generated model types spec as optional
    because the CRD schema cannot say "always present in practice", so every read
    would otherwise need its own assert; one accessor keeps that noise out of
    test bodies (same role as name_of)."""
    assert codebase.spec is not None, f"Codebase/{name_of(codebase)} has no spec"
    return codebase.spec.gitUrlPath


def default_branch_of(codebase) -> str:
    """A Codebase's spec.defaultBranch (see git_url_path_of for why accessors)."""
    assert codebase.spec is not None, f"Codebase/{name_of(codebase)} has no spec"
    return codebase.spec.defaultBranch


def tags_of(cbis) -> list[dict]:
    """CodebaseImageStream spec.tags normalized to plain dicts across
    generated-model shapes (pydantic submodels vs raw dicts)."""
    return [t.model_dump() if hasattr(t, "model_dump") else t for t in (cbis.spec.tags or [])]


GVK: dict[type, GvkInfo] = {
    Codebase: GvkInfo("v2.edp.epam.com/v1", "Codebase", "codebases"),
    CodebaseBranch: GvkInfo("v2.edp.epam.com/v1", "CodebaseBranch", "codebasebranches"),
    GitServer: GvkInfo("v2.edp.epam.com/v1", "GitServer", "gitservers"),
    PipelineRun: GvkInfo("tekton.dev/v1", "PipelineRun", "pipelineruns"),
    CDPipeline: GvkInfo("v2.edp.epam.com/v1", "CDPipeline", "cdpipelines"),
    Stage: GvkInfo("v2.edp.epam.com/v1", "Stage", "stages"),
    CodebaseImageStream: GvkInfo(
        "v2.edp.epam.com/v1", "CodebaseImageStream", "codebaseimagestreams"
    ),
    TriggerTemplate: GvkInfo("triggers.tekton.dev/v1beta1", "TriggerTemplate", "triggertemplates"),
    Application: GvkInfo("argoproj.io/v1alpha1", "Application", "applications"),
}

__all__ = [
    "GVK",
    "Application",
    "CDPipeline",
    "CDPipelineSpec",
    "Codebase",
    "CodebaseBranch",
    "CodebaseBranchSpec",
    "CodebaseImageStream",
    "CodebaseSpec",
    "CiTool",
    "CodebaseStrategy",
    "GitProvider",
    "GitServer",
    "GvkInfo",
    "PipelineRun",
    "QualityGate",
    "Repository",
    "Source",
    "Stage",
    "StageSpec",
    "TriggerTemplate",
    "TriggerType",
    "Versioning",
    "default_branch_of",
    "git_url_path_of",
    "name_of",
    "spec_dict",
    "tags_of",
]
