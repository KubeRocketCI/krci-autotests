"""Test data factories — no literals in test bodies.

A codebase is described by two independent things, and they are kept apart:

- WHAT is onboarded — the `Stack` (lang/framework/build_tool + codebase type +
  build cost). Every stack the suite may onboard is declared once in `CATALOG`.
- HOW it is onboarded — the platform's three strategies, one builder each:
  `created_codebase` / `imported_codebase` / `cloned_codebase`, each taking the
  versioning scheme as a keyword.

Every stack therefore works with every strategy and every versioning scheme
without a new factory, and a new language is one `CATALOG` entry.

PREFIX RULE: unique_name(prefix) is deterministic per prefix within a process and
the owned_codebase factory refuses a prefix already claimed by another test, so a
scenario that parametrizes over CATALOG must derive its prefix from BOTH its own
tag and the catalog key — f"{scenario}-{key}", never the bare key, or two
parametrized scenarios collide on one name. Catalog keys stay short for the same
reason: unique_name truncates the prefix to fit a 30-char DNS-1123 budget.
"""

from dataclasses import dataclass, field
from typing import Literal

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

# The version a semver codebase starts from. Semver is a scheme, not a number:
# scenarios select the scheme and the start version travels with it.
SEMVER_START = "0.1.0-SNAPSHOT"


@dataclass(frozen=True)
class Stack:
    """WHAT a codebase is built from: the lang/framework/build_tool selector the
    platform resolves its pipelines by, plus the codebase type and build cost that
    travel with that choice.

    The CRD types all three selector fields as free `str`, so a typo produces a
    Codebase that reconciles fine and then never gets a matching pipeline. Declaring
    stacks as constants in CATALOG is what keeps the vocabulary closed.
    """

    lang: str
    framework: str
    build_tool: str
    codebase_type: CodebaseType = "application"
    # Workload-relative build cost. Effective build wait =
    # krci_timeout_build_success * build_timeout_factor: the run knob knows how
    # fast the CLUSTER is, the stack knows how heavy the WORKLOAD is — the two
    # compose instead of forcing one global number.
    build_timeout_factor: float = 1.0


# The platform's lightest stack (helm lint + template — no compile, no sonar, no
# container build): the default for every test that needs speed over depth.
HELM_LIBRARY = Stack(
    lang="helm",
    framework="pipeline",
    build_tool="helm",
    codebase_type="library",
    build_timeout_factor=0.5,
)

# Full python application path (pip install + sonar + kaniko image build). fastapi is
# the python tile the platform ships ENABLED by default (pipelines-library values:
# deployableResources.python.fastapi=true; the plain python3.13 flavor is disabled
# out of the box). Base image python:3.13-alpine is multi-arch (arm64-safe).
PY_FASTAPI = Stack(lang="python", framework="fastapi", build_tool="python")

# Full application path (compile + sonar + container build) — heavier than helm but
# exercises the complete build chain; used when depth matters over speed.
GO_GIN = Stack(lang="go", framework="gin", build_tool="go")

# Every stack this suite may onboard. Adding a language is ONE entry here and it
# works with all three strategies and both versioning schemes immediately; the key
# is what a parametrized scenario iterates and folds into its unique_name prefix.
CATALOG: dict[str, Stack] = {
    "helm": HELM_LIBRARY,
    "py": PY_FASTAPI,
    "go": GO_GIN,
}

# Longest catalog key that still leaves room for a scenario tag inside
# unique_name's 30-char budget; asserted in tests/unit/test_codebase_data.py.
MAX_CATALOG_KEY = 4

_TEMPLATE_REPO_OWNER = "https://github.com/epmd-edp"


def template_repo_url(stack: Stack) -> str:
    """The public template repo the platform's own create strategy clones for a
    stack (BuildTemplateRepoUrl: <lang>-<buildTool>-<framework>).

    Clone scenarios use it as their source: the content matches the stack's
    pipelines and it needs no clone credentials, so what differs from create is
    purely the operator path under test (spec.repository.url -> clone -> squash ->
    push, vs template provisioning)."""
    return f"{_TEMPLATE_REPO_OWNER}/{stack.lang}-{stack.build_tool}-{stack.framework}.git"


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
    versioning_start_from: str | None = None  # derived from versioning_type
    build_timeout_factor: float = 1.0
    labels: dict[str, str] = field(default_factory=lambda: {labels.CREATED_BY: "krci-autotests"})

    def __post_init__(self) -> None:
        """Bind the start version to the versioning scheme.

        The operator requires a startFrom under semver and rejects the pair as
        contradictory under default versioning, but nothing in the CRD ties the two
        fields together — so an unset semver start reaches the API server as a 422,
        and a stray start under default versioning silently claims a scheme the
        codebase does not use."""
        if self.versioning_type is VersioningType.SEMVER and self.versioning_start_from is None:
            object.__setattr__(self, "versioning_start_from", SEMVER_START)
        if (
            self.versioning_type is VersioningType.DEFAULT
            and self.versioning_start_from is not None
        ):
            raise ValueError(
                f"versioning_start_from={self.versioning_start_from!r} needs "
                f"versioning_type={VersioningType.SEMVER}"
            )


def _codebase(
    stack: Stack,
    *,
    name: str,
    strategy: CodebaseStrategy,
    versioning: VersioningType,
    git_url_path: str | None = None,
    repository_url: str | None = None,
) -> CodebaseTestData:
    """Shared assembly for the three strategy builders: the stack's fields are
    spread verbatim, so a new Stack field reaches every strategy at once."""
    return CodebaseTestData(
        name=name,
        lang=stack.lang,
        framework=stack.framework,
        build_tool=stack.build_tool,
        codebase_type=stack.codebase_type,
        build_timeout_factor=stack.build_timeout_factor,
        strategy=strategy,
        versioning_type=versioning,
        git_url_path=git_url_path,
        repository_url=repository_url,
    )


def created_codebase(
    stack: Stack, prefix: str, *, versioning: VersioningType = VersioningType.DEFAULT
) -> CodebaseTestData:
    """Create strategy: the platform provisions a new repo from its own template.

    prefix owns the name for the whole session — see the module's PREFIX RULE."""
    return _codebase(
        stack,
        name=unique_name(prefix),
        strategy=CodebaseStrategy.create,
        versioning=versioning,
    )


def imported_codebase(
    stack: Stack,
    prefix: str,
    source_git_url_path: str,
    *,
    name: str | None = None,
    versioning: VersioningType = VersioningType.DEFAULT,
) -> CodebaseTestData:
    """Import strategy: onboard an EXISTING repo at source_git_url_path.

    name re-imports under a chosen name instead of a fresh one. That matters for
    deploys: images push to <registry-space>/<codebase-name>, and a registry only
    accepts paths matching an existing project — so the seed's name must be kept."""
    return _codebase(
        stack,
        name=name or unique_name(prefix),
        strategy=CodebaseStrategy.import_,
        versioning=versioning,
        git_url_path=source_git_url_path,
    )


def cloned_codebase(
    stack: Stack,
    prefix: str,
    *,
    repository_url: str | None = None,
    versioning: VersioningType = VersioningType.DEFAULT,
) -> CodebaseTestData:
    """Clone strategy: the operator clones an external repo into a new one.

    repository_url defaults to the stack's own template repo (see
    template_repo_url) — a public source, so no clone credentials are involved."""
    return _codebase(
        stack,
        name=unique_name(prefix),
        strategy=CodebaseStrategy.clone,
        versioning=versioning,
        repository_url=repository_url or template_repo_url(stack),
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
