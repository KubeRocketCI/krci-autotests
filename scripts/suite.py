"""Suite definitions: named lists of tests, resolved to pytest arguments.

Suite membership is data (suites.yaml), never a marker on a test, so one test can
belong to any number of suites and a new suite costs no test edits.

Usage:
    python scripts/suite.py run <name> [pytest args...]   run the suite
    python scripts/suite.py list                          names, descriptions, case counts
    python scripts/suite.py check                         entries resolve; report orphans

`run` invokes pytest directly rather than printing arguments for a shell to expand:
a parametrized case id carries brackets, which a shell would treat as a glob and
silently drop, leaving a suite that quietly runs nothing.
"""

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SUITES_FILE = ROOT / "suites.yaml"

# Collected tests no suite is expected to run. Empty by design: a test nothing
# runs is dead weight, and `check` is what stops one appearing unnoticed.
EXPECTED_ORPHANS: set[str] = set()


def _suites() -> dict:
    return yaml.safe_load(SUITES_FILE.read_text())


def _suite(name: str) -> dict:
    suites = _suites()
    if name not in suites:
        raise SystemExit(f"unknown suite {name!r} (defined: {', '.join(sorted(suites))})")
    return suites[name]


class CollectionError(RuntimeError):
    """pytest could not collect a target, so the node ids it would have yielded
    are unknown — not empty."""


# pytest's own exit codes: 0 collected something, 5 collected nothing. Anything
# else (2 interrupted, 3 internal, 4 usage) means collection did not complete.
_PYTEST_OK = 0
_PYTEST_NO_TESTS = 5


def _collect(targets: list[str]) -> set[str]:
    """Node ids pytest collects for the given targets.

    Collection needs no cluster, so this is the cheap way to prove a suite still
    names real tests — and the only way to catch an entry left behind by a rename.

    A failed collection raises instead of returning an empty set. Silently
    treating it as "no tests" is the worse answer twice over: a broken import is
    reported as a stale suite entry, and a directory that half-collects still
    yields ids from its healthy modules, so the orphan scan compares against a
    universe that quietly shrank and the check passes while blind.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            *targets,
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode not in (_PYTEST_OK, _PYTEST_NO_TESTS):
        detail = (result.stderr.strip() or result.stdout.strip()).splitlines()
        raise CollectionError(
            f"pytest exited {result.returncode} collecting {' '.join(targets)}:\n"
            + "\n".join(f"    {line}" for line in detail[-15:])
        )
    return {line.strip() for line in result.stdout.splitlines() if "::" in line}


def _args(name: str) -> list[str]:
    suite = _suite(name)
    return [*suite["tests"], "-n", str(suite.get("parallel", 0)), "--reruns", "0"]


def run(name: str, extra: list[str]) -> int:
    """Hand the suite to pytest in one process, arguments unquoted by any shell."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", *_args(name), *extra], cwd=ROOT
    ).returncode


def show_list() -> int:
    for name, suite in _suites().items():
        collected = _collect(suite["tests"])
        print(f"{name:14} {len(collected):4} cases  {suite.get('description', '')}")
    return 0


def check() -> int:
    """Every suite entry resolves, and every collected test belongs to a suite.

    Without markers a test declares nothing, so the failure mode moves: a new test
    that no suite names would simply never run. This is the guard for that."""
    problems: list[str] = []
    covered: set[str] = set()
    for name, suite in _suites().items():
        for entry in suite["tests"]:
            try:
                resolved = _collect([entry])
            except CollectionError as exc:
                # Report and keep going: one unimportable module should not hide
                # every other problem behind it.
                problems.append(f"suite {name!r}: {exc}")
                continue
            if not resolved:
                problems.append(f"suite {name!r}: entry resolves to no test: {entry}")
            covered |= resolved
    try:
        everything = _collect(["tests"])
    except CollectionError as exc:
        # The orphan scan needs the full set of tests; without it there is nothing
        # to compare against and a silent pass would be a lie.
        print(f"FAIL cannot scan for orphan tests: {exc}")
        for problem in problems:
            print(f"FAIL {problem}")
        print("suites: FAILED (collection incomplete)")
        return 1
    orphans = everything - covered - EXPECTED_ORPHANS
    problems += [f"no suite runs: {nodeid}" for nodeid in sorted(orphans)]
    for problem in problems:
        print(f"FAIL {problem}")
    print(f"suites: {'FAILED' if problems else 'OK'} ({len(covered)} of {len(everything)} covered)")
    return 1 if problems else 0


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    command = sys.argv[1]
    if command == "run":
        return run(sys.argv[2], sys.argv[3:])
    if command == "list":
        return show_list()
    if command == "check":
        return check()
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
