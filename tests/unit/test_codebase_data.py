"""Guards on the test-data vocabulary itself (no cluster).

lang/framework/buildTool is the platform's pipeline-library SELECTOR, and the CRD
types all three as free `str` — so a typo produces a Codebase that reconciles
fine and then never gets a matching pipeline. The failure only shows up after the
full readiness/trigger timeout, which is exactly the 10-minute mystery the rest of
the suite is built to avoid. Nothing can validate a triple offline against the
platform, but we CAN stop a new factory from inventing an untracked one: every
factory must spread a declared triple constant.
"""

import inspect

from tests.test_data import codebase_data
from tests.test_data.codebase_data import CodebaseTestData

# The triples this suite is allowed to onboard, declared once. Adding a language or
# build tool means adding a constant here (and a factory that spreads it), not
# typing three loose strings into a new factory.
_DECLARED_TRIPLES = {
    ("helm", "pipeline", "helm"),
    ("python", "fastapi", "python"),
    ("go", "gin", "go"),
}


def _codebase_factories() -> dict[str, CodebaseTestData]:
    """Every public factory that yields a CodebaseTestData from defaults alone.

    Factories needing an argument (the import twins, which take the seeded repo
    path) are covered by their create-strategy seed, which IS callable bare."""
    found = {}
    for name, obj in vars(codebase_data).items():
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        params = inspect.signature(obj).parameters.values()
        if any(p.default is inspect.Parameter.empty for p in params):
            continue
        produced = obj()
        if isinstance(produced, CodebaseTestData):
            found[name] = produced
    return found


def test_every_codebase_factory_uses_a_declared_triple():
    unknown = {
        name: (data.lang, data.framework, data.build_tool)
        for name, data in _codebase_factories().items()
        if (data.lang, data.framework, data.build_tool) not in _DECLARED_TRIPLES
    }
    assert not unknown, (
        f"factories using an undeclared lang/framework/buildTool triple: {unknown}. "
        "Add the triple to _DECLARED_TRIPLES once you have confirmed the platform "
        "ships pipelines for it."
    )


def test_declared_triples_are_all_in_use():
    """A triple nobody onboards is dead vocabulary — it would quietly outlive the
    pipeline it names."""
    used = {(data.lang, data.framework, data.build_tool) for data in _codebase_factories().values()}
    assert _DECLARED_TRIPLES - used == set()


def test_factories_produce_distinct_names_per_prefix():
    """Two factories sharing a default prefix would hand two scenarios the SAME
    codebase name; owned_codebase raises at runtime, this catches it at dev time."""
    names = [data.name for data in _codebase_factories().values()]
    assert len(names) == len(set(names)), f"duplicate default names: {names}"
