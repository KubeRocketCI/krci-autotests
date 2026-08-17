"""Print every test's ID and its Given/When/Then docstring — the scenario catalog.

Usage: make scenarios
"""

import sys
import textwrap
from typing import cast

import pytest


class _Collector:
    def __init__(self) -> None:
        self.items: list[pytest.Item] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.items = session.items


def main() -> int:
    collector = _Collector()
    code = pytest.main(
        ["--collect-only", "-q", "--no-header", "-p", "no:cacheprovider", "-o", "addopts="],
        plugins=[collector],
    )
    for item in collector.items:
        function = cast(pytest.Function, item)
        doc = (function.function.__doc__ or "(no scenario docstring)").rstrip()
        print(f"\n=== {item.nodeid} ===")
        print(textwrap.dedent(doc))
    return 0 if collector.items else code


if __name__ == "__main__":
    sys.exit(main())
