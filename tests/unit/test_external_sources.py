"""Guards over the external-sources vocabulary — offline, no cluster."""

import re

from tests.test_data.external_sources import (
    EXTERNAL_CLONE_SOURCES,
    EXTERNAL_IMPORT_SOURCES,
    ExternalSource,
)
from tests.test_data.stacks import CATALOG, MAX_SLUG

_ALL: tuple[ExternalSource, ...] = EXTERNAL_CLONE_SOURCES + EXTERNAL_IMPORT_SOURCES


def test_keys_and_slugs_are_unique():
    """Keys are case ids (suites address them); slugs feed unique_name prefixes —
    a repeat of either silently collides two scenarios."""
    keys = [s.key for s in _ALL]
    slugs = [s.slug for s in _ALL]
    assert len(keys) == len(set(keys))
    assert len(slugs) == len(set(slugs))


def test_slugs_fit_the_unique_name_budget():
    for source in _ALL:
        assert len(source.slug) <= MAX_SLUG, source.key
        assert re.fullmatch(r"[a-z0-9-]+", source.slug), source.key


def test_stacks_come_from_the_catalog():
    """An entry must name a stack the platform actually offers — the stack decides
    which pipelines grade the onboarded repo."""
    for source in _ALL:
        assert source.stack is CATALOG[source.stack.key], source.key


def test_import_sources_are_public_github_repos():
    """The import seed is fetched as a GitHub tarball (scaffolds.template_files);
    any other host fails at fetch time — reject it at data time instead."""
    for source in EXTERNAL_IMPORT_SOURCES:
        assert source.url.startswith("https://github.com/"), source.key
