"""Guards on the test-data vocabulary itself (no cluster).

lang/framework/buildTool is the platform's pipeline-library SELECTOR, and the CRD
types all three as free `str` — so a typo produces a Codebase that reconciles
fine and then never gets a matching pipeline. The failure only shows up after the
full readiness/trigger timeout, which is exactly the 10-minute mystery the rest of
the suite is built to avoid. Nothing can validate a stack offline against the
platform, but we CAN keep the vocabulary closed: every Stack the module declares
must be reachable through CATALOG, and every codebase must be built from one.
"""

import re

import pytest

from krci_testkit.naming import unique_name
from krci_testkit.platform import VersioningType
from tests.test_data import codebase_data
from tests.test_data.codebase_data import (
    CATALOG,
    HELM_LIBRARY,
    MAX_CATALOG_KEY,
    SEMVER_START,
    CodebaseTestData,
    Stack,
    cloned_codebase,
    created_codebase,
    imported_codebase,
    template_repo_url,
)

_DNS1123 = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def _declared_stacks() -> dict[str, Stack]:
    return {name: obj for name, obj in vars(codebase_data).items() if isinstance(obj, Stack)}


def test_every_declared_stack_is_reachable_through_the_catalog():
    """A Stack constant outside CATALOG is vocabulary nobody can parametrize over,
    and the next scenario that wants it would sooner declare a fourth loose one."""
    orphans = {
        name: stack for name, stack in _declared_stacks().items() if stack not in CATALOG.values()
    }
    assert not orphans, f"stacks declared but absent from CATALOG: {sorted(orphans)}"


def test_catalog_holds_no_duplicate_stacks():
    """Two keys for one stack would run a parametrized scenario twice over
    identical data while claiming two names' worth of coverage."""
    selectors = [(s.lang, s.framework, s.build_tool) for s in CATALOG.values()]
    assert len(selectors) == len(set(selectors)), f"duplicate stacks in CATALOG: {selectors}"


@pytest.mark.parametrize("key", CATALOG)
def test_catalog_keys_survive_a_derived_prefix(key: str):
    """Keys are folded into a scenario's unique_name prefix (f"{scenario}-{key}").
    unique_name truncates the prefix to fit its 30-char DNS-1123 budget, so a long
    or non-DNS key would be silently chopped — and two parametrized cases whose
    keys share a truncated head would then compute the SAME codebase name."""
    assert len(key) <= MAX_CATALOG_KEY, f"catalog key {key!r} is too long to embed in a prefix"
    assert _DNS1123.match(key), f"catalog key {key!r} is not DNS-1123 safe"


def test_a_parametrized_scenario_gets_a_distinct_name_per_catalog_key():
    """The prefix rule the module docstring states, exercised: scenario tag + key
    must yield one name per stack, with the key still legible in the result."""
    names = {key: created_codebase(stack, f"life-{key}").name for key, stack in CATALOG.items()}
    assert len(set(names.values())) == len(CATALOG), f"prefix collision across catalog: {names}"


@pytest.mark.parametrize("key", CATALOG)
def test_builders_carry_the_whole_stack_onto_the_test_data(key: str):
    """Every strategy spreads the same stack fields, so a new Stack field cannot
    reach one builder and quietly miss the other two."""
    stack = CATALOG[key]
    built = [
        created_codebase(stack, f"c-{key}"),
        imported_codebase(stack, f"i-{key}", "/group/seed"),
        cloned_codebase(stack, f"l-{key}"),
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


def test_clone_defaults_to_the_platforms_own_template_repo():
    data = cloned_codebase(HELM_LIBRARY, "l")
    assert data.repository_url == template_repo_url(HELM_LIBRARY)
    assert data.repository_url == "https://github.com/epmd-edp/helm-helm-pipeline.git"


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
