"""Guards on the stack catalog (no cluster).

The catalog mirrors the portal's language -> frameworks x buildTools mapping, and
the CRD types lang/framework/buildTool as free `str`, so a typo produces a Codebase
that reconciles fine and then never gets a matching pipeline — a failure that only
surfaces after the full build timeout. These guards hold the catalog's own shape;
whether a stack's pipelines are installed on a given cluster is a runtime question
(Stack.pipeline_stem is what answers it).
"""

import re

import pytest

from krci_testkit.naming import unique_name
from tests.test_data.codebase_data import created_codebase
from tests.test_data.stacks import CATALOG, MAX_SLUG, Stack, Tier, by_tier, deployable

_DNS1123 = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# The portal's create form offers 62 lang/framework/buildTool/type combinations.
# The gitops system codebase is deliberately absent: scripts/bootstrap.py owns it.
_PORTAL_COMBINATIONS = 62


def test_catalog_covers_the_portals_whole_combination_space():
    assert len(CATALOG) == _PORTAL_COMBINATIONS


def test_no_stack_onboards_the_gitops_system_codebase():
    """Tests never provision a platform prerequisite; bootstrap owns that codebase."""
    assert not [
        s
        for s in CATALOG.values()
        if s.codebase_type not in {"application", "library", "autotest", "infrastructure"}
    ]
    assert "gitops" not in {s.framework for s in CATALOG.values()}


def test_catalog_is_keyed_by_each_stacks_own_key():
    """The key is derived from the stack, so a dict entry cannot drift from its value."""
    assert all(key == stack.key for key, stack in CATALOG.items())


def test_stacks_are_distinct_combinations():
    combos = [(s.lang, s.framework, s.build_tool, s.codebase_type) for s in CATALOG.values()]
    assert len(combos) == len(set(combos))


def test_slugs_are_unique():
    """Two stacks sharing a slug would hand two parametrized cases one codebase name."""
    slugs = [s.slug for s in CATALOG.values()]
    assert len(slugs) == len(set(slugs))


@pytest.mark.parametrize("stack", CATALOG.values(), ids=lambda s: s.key)
def test_slug_survives_a_derived_prefix(stack: Stack):
    """Slugs are folded into a scenario's unique_name prefix. unique_name truncates
    the prefix to fit its 30-char DNS-1123 budget, so an over-long slug would be
    silently chopped and two cases sharing a truncated head would collide."""
    assert len(stack.slug) <= MAX_SLUG
    assert _DNS1123.match(stack.slug)


def test_a_parametrized_scenario_gets_one_name_per_stack():
    names = {s.key: created_codebase(s, f"x-{s.slug}").name for s in CATALOG.values()}
    assert len(set(names.values())) == len(CATALOG)


@pytest.mark.parametrize("stack", CATALOG.values(), ids=lambda s: s.key)
def test_pipeline_stem_matches_the_platforms_own_naming(stack: Stack):
    """The portal resolves a run as
    <gitProvider>-<buildTool>-<framework>-<type[:3]>-build-<versioning>; the stem is
    the part this stack decides, and it is what a cluster check matches against."""
    assert stack.pipeline_stem == f"{stack.build_tool}-{stack.framework}-{stack.codebase_type[:3]}"


def test_stacks_sharing_a_pipeline_stay_distinct_entries():
    """lang is absent from the pipeline name, so c and cpp resolve to one pipeline.
    They must still be separate catalog entries — the CRs differ."""
    stems = [s.pipeline_stem for s in CATALOG.values()]
    shared = {stem for stem in stems if stems.count(stem) > 1}
    assert shared, "expected at least one pipeline reachable from two languages"
    for stem in shared:
        langs = {s.lang for s in CATALOG.values() if s.pipeline_stem == stem}
        assert len(langs) > 1


def test_only_applications_are_deployable():
    """A CD stage deploys an image, and only applications produce one."""
    assert {s.codebase_type for s in deployable(CATALOG).values()} == {"application"}


def test_every_tier_is_populated_and_smoke_stays_small():
    """A scenario parametrizes over a tier because every stack costs a real build:
    the smoke tier has to stay something a smoke run can actually afford."""
    for tier in Tier:
        assert by_tier(tier), f"tier {tier} has no stacks"
    assert len(by_tier(Tier.SMOKE)) <= 3
    assert by_tier(Tier.SMOKE, Tier.REGRESSION, Tier.FULL).keys() == CATALOG.keys()


def test_template_repo_url_follows_the_scaffold_naming():
    stack = CATALOG["helm-helm-pipeline-lib"]
    assert stack.template_repo_url == "https://github.com/epmd-edp/helm-helm-pipeline.git"


def test_unique_name_accepts_the_longest_derived_prefix():
    """The budget this catalog is sized against, exercised end to end."""
    longest = max(CATALOG.values(), key=lambda s: len(s.slug))
    assert unique_name(f"x-{longest.slug}").startswith("at-x-")
