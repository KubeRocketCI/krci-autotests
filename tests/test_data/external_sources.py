"""Named external source repos — the extension point for onboarding a repo the
catalog does not derive.

The catalog lifecycle tests stay URL-free (sources always derive from the Stack);
an entry here is how a SPECIFIC repo becomes a selectable case: one entry plus one
suites.yaml line, no test code. The baseline entries point at the platform's own
epmd-edp repos; replace or extend with any repo that has a real behavior to prove.

Import sources must be public github.com repos (the seed is fetched as a tarball);
clone sources can be any URL the operator can reach.
"""

from dataclasses import dataclass

from tests.test_data.stacks import CATALOG, Stack


@dataclass(frozen=True)
class ExternalSource:
    """One named source repo: the case id (key), a unique_name fragment (slug),
    the stack whose pipelines the content matches, and the source URL."""

    key: str
    slug: str
    stack: Stack
    url: str


EXTERNAL_CLONE_SOURCES: tuple[ExternalSource, ...] = (
    ExternalSource(
        key="epmd-edp-java-gradle-java21-lib",
        slug="jgl21",
        stack=CATALOG["java-gradle-java21-lib"],
        url="https://github.com/epmd-edp/java-gradle-java21.git",
    ),
)

EXTERNAL_IMPORT_SOURCES: tuple[ExternalSource, ...] = (
    ExternalSource(
        key="epmd-edp-java-maven-java21-app",
        slug="jma21",
        stack=CATALOG["java-maven-java21-app"],
        url="https://github.com/epmd-edp/java-maven-java21.git",
    ),
)
