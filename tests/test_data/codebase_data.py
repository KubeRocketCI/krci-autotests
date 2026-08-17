"""Test data factories — no literals in test bodies."""

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from krci_testkit import labels
from krci_testkit.clients.protocol import MergeStrategy
from krci_testkit.models import CodebaseStrategy
from krci_testkit.naming import unique_name
from krci_testkit.platform import VersioningType

# CR-spec vocabulary. Where the CRD declares an enum, the GENERATED enum is used
# directly (CodebaseStrategy) — a second hand-written copy would drift silently on
# the next `make generate`. Closed-but-unmarked-in-schema sets live in
# krci_testkit.platform (VersioningType); Literals cover the genuinely free fields.
CodebaseType = Literal["application", "library", "autotest", "system"]


@dataclass(frozen=True)
class ChangeTestData:
    """A change submitted through the provider (branch name, title, file payload).

    title doubles as the change's commit message (client contract); merge_strategy
    is the neutral vocabulary from krci_testkit.clients.protocol.MergeStrategy."""

    source_branch: str
    title: str
    files: dict[str, str]
    merge_strategy: MergeStrategy = MergeStrategy.MERGE


@dataclass(frozen=True)
class CodebaseTestData:
    name: str
    lang: str
    framework: str
    build_tool: str
    codebase_type: CodebaseType = "application"
    strategy: CodebaseStrategy = CodebaseStrategy.create
    default_branch: str = "main"
    deployment_script: str = "helm-chart"
    versioning_type: VersioningType = VersioningType.DEFAULT
    empty_project: bool = False
    git_url_path: str | None = None  # None -> derived as /{git_group}/{name}
    repository_url: str | None = None  # clone strategy: the source repo to clone
    versioning_start_from: str | None = None  # required when versioning type is not default
    # Workload-relative build cost. Effective build wait =
    # krci_timeout_build_success * build_timeout_factor: the run knob knows how
    # fast the CLUSTER is, the test data knows how heavy the WORKLOAD is —
    # the two compose instead of forcing one global number.
    build_timeout_factor: float = 1.0
    labels: dict[str, str] = field(default_factory=lambda: {labels.CREATED_BY: "krci-autotests"})


class _Triple(TypedDict, total=False):
    """Keyword shape of a lang/framework/build_tool triple, spread into
    CodebaseTestData factories — precise per-key types so `**_TRIPLE` type-checks
    against CodebaseTestData's actual field types instead of a single dict value type."""

    lang: str
    framework: str
    build_tool: str
    codebase_type: CodebaseType
    build_timeout_factor: float


# The platform's lightest triple (helm lint + template — no compile, no sonar,
# no container build): the default for every test that needs speed over depth.
_HELM_LIBRARY: _Triple = {
    "lang": "helm",
    "framework": "pipeline",
    "build_tool": "helm",
    "codebase_type": "library",
    "build_timeout_factor": 0.5,
}


def helm_pipeline_library(prefix: str = "helm") -> CodebaseTestData:
    """Smoke default (helm triple) for the fastest feedback loop.

    unique_name is deterministic per prefix within one process, so every consumer
    that owns its own codebase in the same run must pass a distinct prefix."""
    return CodebaseTestData(name=unique_name(prefix), **_HELM_LIBRARY)


def imported_helm_library(source_git_url_path: str) -> CodebaseTestData:
    """Import-strategy twin of the smoke triple, onboarding an EXISTING repo."""
    return CodebaseTestData(
        name=unique_name("imp"),
        strategy=CodebaseStrategy.import_,
        git_url_path=source_git_url_path,
        **_HELM_LIBRARY,
    )


def cloned_helm_library() -> CodebaseTestData:
    """Clone-strategy twin of the smoke triple. The source is the same public
    template repo the platform's create strategy clones internally
    (BuildTemplateRepoUrl: https://github.com/epmd-edp/<lang>-<buildTool>-<framework>),
    so no clone credentials are needed and the content matches the triple's
    pipelines. What differs from create is the operator path under test:
    spec.repository.url -> clone -> squash -> push (vs template provisioning)."""
    return CodebaseTestData(
        name=unique_name("cln"),
        strategy=CodebaseStrategy.clone,
        repository_url="https://github.com/epmd-edp/helm-helm-pipeline.git",
        **_HELM_LIBRARY,
    )


def semver_helm_library() -> CodebaseTestData:
    """Smoke triple with semver versioning — release branches need it. (The
    platform's pipeline library ships -default/-semver build pipelines; the
    legacy "edp" versioning name has no pipelines on current platform versions.)"""
    return CodebaseTestData(
        name=unique_name("vhelm"),
        versioning_type=VersioningType.SEMVER,
        versioning_start_from="0.1.0-SNAPSHOT",
        **_HELM_LIBRARY,
    )


@dataclass(frozen=True)
class BranchTestData:
    """A codebase branch created via CR (the platform creates the git branch)."""

    branch_name: str
    release: bool = False
    version: str | None = None


def feature_branch(prefix: str = "ftr") -> BranchTestData:
    return BranchTestData(branch_name=unique_name(prefix))


def release_branch() -> BranchTestData:
    return BranchTestData(branch_name=unique_name("rel"), release=True, version="0.1.0-RC.1")


def smoke_change(
    prefix: str = "chg", merge_strategy: MergeStrategy = MergeStrategy.MERGE
) -> ChangeTestData:
    marker = unique_name(prefix)
    return ChangeTestData(
        source_branch=marker,
        title=f"test: krci-autotests smoke change {marker}",
        files={f"{marker}.txt": "krci-autotests smoke change\n"},
        merge_strategy=merge_strategy,
    )


def recheck_comment() -> str:
    """Platform convention (edp-tekton event processor): a comment STARTING with
    /recheck re-renders the review pipeline for an open change. The negative
    (non-conforming comment ignored) is covered by edp-tekton's own unit tests
    and deliberately NOT re-tested here."""
    return "/recheck"


def cloned_semver_helm_library() -> CodebaseTestData:
    """Clone-strategy + semver smoke variant: one codebase carries both the clone
    operator path AND the semver pipeline selection (release branches need semver);
    the source is the same public template repo as cloned_helm_library."""
    return CodebaseTestData(
        name=unique_name("csl"),
        strategy=CodebaseStrategy.clone,
        repository_url="https://github.com/epmd-edp/helm-helm-pipeline.git",
        versioning_type=VersioningType.SEMVER,
        versioning_start_from="0.1.0-SNAPSHOT",
        **_HELM_LIBRARY,
    )


# Full python application path (pip install + sonar + kaniko image build). fastapi is
# the python tile the platform ships ENABLED by default (pipelines-library values:
# deployableResources.python.fastapi=true; the plain python3.13 flavor is disabled
# out of the box). Base image python:3.13-alpine is multi-arch (arm64-safe).
_PYTHON_FASTAPI: _Triple = {
    "lang": "python",
    "framework": "fastapi",
    "build_tool": "python",
}


def python_fastapi_application(prefix: str = "py") -> CodebaseTestData:
    """Deployable python application (create strategy)."""
    return CodebaseTestData(name=unique_name(prefix), **_PYTHON_FASTAPI)


def python_fastapi_imported(source_git_url_path: str, *, name: str) -> CodebaseTestData:
    """Import-strategy twin of the fastapi application, onboarding an EXISTING repo
    UNDER THE SEED'S NAME (the create->delete->re-import leg). The name reuse is
    also load-bearing for deploys: images push to <registry-space>/<codebase-name>,
    and GitLab's container registry only accepts paths matching an existing project."""
    return CodebaseTestData(
        name=name,
        strategy=CodebaseStrategy.import_,
        git_url_path=source_git_url_path,
        **_PYTHON_FASTAPI,
    )


def go_application(prefix: str = "go") -> CodebaseTestData:
    """Full application path (compile + sonar + container build) — heavier but
    exercises the complete build chain; used when depth matters over speed.

    unique_name is deterministic per prefix within one process, so every consumer
    that owns its own codebase in the same run must pass a distinct prefix."""
    return CodebaseTestData(name=unique_name(prefix), lang="go", framework="gin", build_tool="go")


def semver_go_application(prefix: str = "vgo") -> CodebaseTestData:
    """Semver twin of go_application: the deploy journey also
    exercises the go `*-build-semver` pipeline and semver image tags."""
    return CodebaseTestData(
        name=unique_name(prefix),
        lang="go",
        framework="gin",
        build_tool="go",
        versioning_type=VersioningType.SEMVER,
        versioning_start_from="0.1.0-SNAPSHOT",
    )


# Factories declare their own cost, e.g.:
#   java_maven_application() -> CodebaseTestData(..., build_timeout_factor=2.0)
