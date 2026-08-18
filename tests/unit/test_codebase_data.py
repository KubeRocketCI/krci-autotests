"""Guards on the strategy builders (no cluster).

The catalog's own shape is held by tests/unit/test_stacks.py; these cover what the
builders do with a stack: carry it whole onto the test data, select the platform
strategy the scenario asked for, and bind the start version to the versioning scheme.
"""

import pytest

from krci_testkit.naming import unique_name
from krci_testkit.platform import VersioningType
from tests.test_data.codebase_data import (
    SEMVER_START,
    CodebaseTestData,
    cloned_codebase,
    created_codebase,
    imported_codebase,
)
from tests.test_data.stacks import CATALOG, HELM_LIBRARY, Stack


@pytest.mark.parametrize("stack", CATALOG.values(), ids=lambda s: s.key)
def test_builders_carry_the_whole_stack_onto_the_test_data(stack: Stack):
    """Every strategy spreads the same stack fields, so a new Stack field cannot
    reach one builder and quietly miss the other two."""
    built = [
        created_codebase(stack, f"c-{stack.slug}"),
        imported_codebase(stack, f"i-{stack.slug}", "/group/seed"),
        cloned_codebase(stack, f"l-{stack.slug}"),
    ]
    for data in built:
        assert (data.lang, data.framework, data.build_tool) == (
            stack.lang,
            stack.framework,
            stack.build_tool,
        )
        assert data.codebase_type == stack.codebase_type
        assert data.build_timeout_factor == stack.build_timeout_factor


def test_each_builder_selects_its_own_strategy():
    assert created_codebase(HELM_LIBRARY, "c").strategy == "create"
    assert imported_codebase(HELM_LIBRARY, "i", "/group/seed").strategy == "import"
    assert cloned_codebase(HELM_LIBRARY, "l").strategy == "clone"


def test_import_keeps_the_source_path_and_an_explicit_name():
    """Import onboards an EXISTING repo, and re-importing under the seed's name is
    the norm: image paths must keep matching the registry project."""
    data = imported_codebase(HELM_LIBRARY, "i", "/group/seed", name="seed")
    assert data.git_url_path == "/group/seed"
    assert data.name == "seed"


def test_clone_defaults_to_the_stacks_own_template_repo():
    data = cloned_codebase(HELM_LIBRARY, "l")
    assert data.repository_url == HELM_LIBRARY.template_repo_url


def test_clone_accepts_an_explicit_source():
    """Marketplace templates live outside the scaffold naming, so the source stays
    overridable rather than always derived."""
    data = cloned_codebase(HELM_LIBRARY, "l2", repository_url="https://example.test/x.git")
    assert data.repository_url == "https://example.test/x.git"


def test_semver_derives_its_start_version():
    """The operator rejects semver without a startFrom, and no CRD field ties the
    two together — so the pair is bound here rather than at every call site."""
    data = created_codebase(HELM_LIBRARY, "v", versioning=VersioningType.SEMVER)
    assert data.versioning_start_from == SEMVER_START


def test_a_start_version_without_semver_is_refused():
    with pytest.raises(ValueError, match="versioning_start_from"):
        CodebaseTestData(
            name=unique_name("bad"),
            lang="helm",
            framework="pipeline",
            build_tool="helm",
            versioning_start_from="1.2.3-SNAPSHOT",
        )
