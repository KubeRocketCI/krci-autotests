"""Codebase test data — no literals in test bodies.

A codebase is described by two independent things, kept apart:

- WHAT is onboarded — the `Stack` (tests/test_data/stacks.py), which is the
  platform's pipeline selector.
- HOW it is onboarded — the platform's three strategies, one builder each:
  `created_codebase` / `imported_codebase` / `cloned_codebase`, each taking the
  versioning scheme as a keyword.

Every stack therefore works with every strategy and every versioning scheme
without a new factory.

PREFIX RULE: unique_name(prefix) is deterministic per prefix within a process and
the owned_codebase factory refuses a prefix already claimed by another test, so a
scenario that parametrizes over stacks must derive its prefix from BOTH its own
tag and the stack's slug — f"{scenario}-{stack.slug}", never the slug alone, or
two parametrized scenarios collide on one name.
"""

from dataclasses import dataclass, field

from krci_testkit import labels
from krci_testkit.clients.protocol import MergeStrategy
from krci_testkit.models import CodebaseStrategy
from krci_testkit.naming import unique_name
from krci_testkit.platform import VersioningType
from tests.test_data.stacks import CodebaseType, Stack

# The version a semver codebase starts from. Semver is a scheme, not a number:
# scenarios select the scheme and the start version travels with it.
SEMVER_START = "0.1.0-SNAPSHOT"


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
    source_git_url_path: str | None = None,
    *,
    name: str | None = None,
    versioning: VersioningType = VersioningType.DEFAULT,
) -> CodebaseTestData:
    """Import strategy: onboard an EXISTING repo at source_git_url_path
    (None -> the /{git_group}/{name} default, matching where the seed lands).

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
        repository_url=repository_url or stack.template_repo_url,
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


def simple_change(
    prefix: str = "chg", merge_strategy: MergeStrategy = MergeStrategy.MERGE
) -> ChangeTestData:
    """A one-file change: the smallest payload that still drives the real trigger
    path (review run, merge, build run)."""
    marker = unique_name(prefix)
    return ChangeTestData(
        source_branch=marker,
        title=f"test: krci-autotests change {marker}",
        files={f"{marker}.txt": "krci-autotests change\n"},
        merge_strategy=merge_strategy,
    )


def recheck_comment() -> str:
    """Platform convention (edp-tekton event processor): a comment STARTING with
    /recheck re-renders the review pipeline for an open change. The negative
    (non-conforming comment ignored) is covered by edp-tekton's own unit tests
    and deliberately NOT re-tested here."""
    return "/recheck"
