import logging
import os
from collections.abc import Callable, Iterator

import pytest
from dotenv import load_dotenv

from krci_testkit.clients import VCSProvider, vcs_client
from krci_testkit.clusters import Cluster, connected_git_server
from krci_testkit.config import KrciConfig, load_config
from krci_testkit.models import Codebase, GitServer, git_url_path_of
from krci_testkit.reporting import reportportal_reachable
from krci_testkit.waits import Timeouts, timeout_knobs
from tests.test_data.codebase_data import CodebaseTestData
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.pipelinerun_utils import PipelineRuns

log = logging.getLogger(__name__)

# Published so each suite's conftest can annotate the factory it consumes.
OwnedCodebase = Callable[[CodebaseTestData], Codebase]
OwnedImportedCodebase = Callable[[CodebaseTestData, Callable[[str], CodebaseTestData]], Codebase]


def pytest_addoption(parser: pytest.Parser) -> None:
    """Run-level wait knobs via pytest's native option system.

    Precedence (pytest built-in): code default < pyproject ini < `-o name=value` < PYTEST_ADDOPTS.
    Knobs are declared once on Timeouts and registered from there, so a new knob
    cannot be half-wired. Target-environment facts (URLs, tokens, namespace) stay
    in KrciConfig — never add them here.
    """
    for knob in timeout_knobs():
        parser.addini(knob.ini, knob.description, default=str(knob.default))


def _unit_only(args: list[str]) -> bool:
    paths = [a for a in args if not a.startswith("-")]
    return bool(paths) and all(a.startswith("tests/unit") for a in paths)


_RP_ENV_TO_INI = {
    "RP_ENDPOINT": "rp_endpoint",
    "RP_PROJECT": "rp_project",
    "RP_API_KEY": "rp_api_key",
    "RP_VERIFY_SSL": "rp_verify_ssl",
}


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Load .env (real env wins) and wire ReportPortal from the environment.

    RP values go through pytest's ini store because secrets must never reach argv.
    Must run tryfirst: conftest hooks execute before entry-point plugins, which is
    what lands these values before pytest-reportportal reads its config; popping
    the private-but-stable _inicache guards against an earlier cached read.
    """
    load_dotenv(override=False)
    # kr8s drives httpx, which logs every API request at INFO — that floods the
    # live log and buries the suite's own step lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Unit tests are a dev gate, not cluster test evidence — they never publish
    # to ReportPortal (a unit run would otherwise appear as a 23-test "smoke" launch).
    if not os.environ.get("RP_ENDPOINT") or _unit_only(config.args):
        return
    # Reporting is secondary: an unreachable RP server otherwise hangs startup and
    # crashes the xdist workers before any test runs — probe first.
    if not reportportal_reachable(os.environ["RP_ENDPOINT"]):
        return
    config.option.rp_enabled = True  # what --reportportal would have set
    for env_name, ini_name in _RP_ENV_TO_INI.items():
        value = os.environ.get(env_name)
        if value:
            config.inicfg[ini_name] = value
            config._inicache.pop(ini_name, None)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Make the `serial` marker mean what it says.

    The marker promises a test never runs under xdist, but a marker is inert
    metadata — without this hook a serial test selected into a parallel run is
    handed to an arbitrary worker and runs concurrently, silently. Refuse the run
    instead: the caller asked for something the selection cannot provide.

    trylast is load-bearing: conftest hooks run before pytest's own -m
    deselection, so an earlier hook would see every collected test and reject
    parallel suites over serial tests they never selected."""
    _apply_cluster_timeout(config, items)
    workers = config.getoption("numprocesses", None)
    if not workers:
        return
    serial = [item.nodeid for item in items if item.get_closest_marker("serial")]
    if serial:
        raise pytest.UsageError(
            f"serial-marked tests cannot run under xdist (-n {workers}); "
            "rerun this selection with -n 0:\n  " + "\n  ".join(serial)
        )


def _cluster_timeout_budget(timeouts: Timeouts) -> int:
    """Outer budget for one cluster test: two passes over the slowest legs the
    heaviest scenario performs (onboard, review+build, two deploys, two renders)."""
    return 2 * (
        timeouts.codebase_ready
        + timeouts.build_success
        + timeouts.deploy_success
        + timeouts.run_trigger
    )


def _apply_cluster_timeout(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Derive pytest-timeout's hard kill switch from the wait knobs.

    A per-test `@pytest.mark.timeout(5400)` literal silently defeats the knob
    system: raise krci_timeout_build_success as the README advertises and the test
    is killed by pytest-timeout with a generic message BEFORE its own WaitTimeout
    can report the last-seen state. One derived budget covers every cluster test —
    this is a backstop against a hung run, not a per-test measurement, so a single
    generous value is the honest shape. The ini `timeout` still guards unit tests.
    """
    budget = _cluster_timeout_budget(_resolve_timeouts(config))
    for item in items:
        if item.get_closest_marker("api") or item.get_closest_marker("ui"):
            item.add_marker(pytest.mark.timeout(budget))


def _resolve_timeouts(config: pytest.Config) -> Timeouts:
    return Timeouts(**{k.name: int(config.getini(k.ini)) for k in timeout_knobs()})


@pytest.fixture(scope="session")
def timeouts(pytestconfig: pytest.Config) -> Timeouts:
    return _resolve_timeouts(pytestconfig)


@pytest.fixture(scope="session")
def cfg() -> KrciConfig:
    return load_config()


@pytest.fixture(scope="session")
def cluster(cfg: KrciConfig) -> Cluster:
    return Cluster(cfg)


@pytest.fixture(scope="session")
def git_server(cluster: Cluster, cfg: KrciConfig) -> GitServer:
    """The GitServer under test — the ONLY source of provider facts.
    KRCI_GIT_SERVER (required) names it; selection is always explicit."""
    return connected_git_server(cluster, cfg.git_server)


@pytest.fixture(scope="session")
def vcs(
    cluster: Cluster, git_server: GitServer, cfg: KrciConfig, timeouts: Timeouts
) -> VCSProvider:
    """Provider client built purely from platform state: GitServer CR -> its
    credential secret -> provider API. No provider facts live in env config."""
    credentials = cluster.get_secret(git_server.spec.nameSshKeySecret)
    return vcs_client(
        git_server,
        credentials,
        verify=cfg.httpx_verify,
        merge_timeout=timeouts.change_merge,
        poll_interval=timeouts.poll_interval,
        request_timeout=timeouts.vcs_request,
    )


@pytest.fixture(scope="session")
def codebase_utils(
    cluster: Cluster, git_server: GitServer, cfg: KrciConfig, timeouts: Timeouts
) -> CodebaseUtils:
    return CodebaseUtils(cluster, git_server, cfg.git_group, timeouts)


@pytest.fixture(scope="session")
def pipeline_runs(cluster: Cluster, timeouts: Timeouts) -> PipelineRuns:
    return PipelineRuns(cluster, timeouts)


@pytest.fixture(scope="session")
def cd_utils(cluster: Cluster, timeouts: Timeouts) -> CDPipelineUtils:
    return CDPipelineUtils(cluster, timeouts)


@pytest.fixture(scope="session")
def _claimed_names() -> dict[str, str]:
    """Name -> the nodeid that claimed it this session — see owned_codebase."""
    return {}


def _claim(claimed: dict[str, str], name: str, owner: str) -> None:
    """unique_name(prefix) is stable per prefix within a process, so two scenarios
    sharing a prefix silently share ONE Codebase and corrupt each other. Turn that
    into an immediate, named error instead of a mystery mid-run failure.

    Keyed by the claiming test, not by the name alone: the SAME test re-running
    (pytest-rerunfailures) legitimately reclaims its name — its previous attempt
    tore the codebase down — and must not be rejected for a collision that is not one."""
    previous = claimed.get(name)
    if previous is not None and previous != owner:
        raise ValueError(
            f"codebase name '{name}' was already created in this session by {previous}. "
            "Two scenarios are using the same unique_name() prefix — give this one "
            "its own prefix, e.g. helm_pipeline_library(prefix='xyz')."
        )
    claimed[name] = owner


@pytest.fixture
def owned_codebase(
    request: pytest.FixtureRequest,
    codebase_utils: CodebaseUtils,
    vcs: VCSProvider,
    _claimed_names: dict[str, str],
) -> Iterator[OwnedCodebase]:
    """Factory: create codebases this test owns, torn down in reverse order.

    Call it with the test-data factory the scenario needs:
        codebase = owned_codebase(helm_pipeline_library(prefix="brch"))

    Scenarios declare their own data instead of the root conftest growing one
    bespoke fixture per scenario. Teardown is an assertion-free SAFETY NET for the
    early-failure path only — happy paths assert deletion inside the test; the VCS
    repo is removed best-effort (the operator never deletes remote repos)."""
    created: list[tuple[CodebaseTestData, Codebase]] = []

    def _create(data: CodebaseTestData) -> Codebase:
        _claim(_claimed_names, data.name, request.node.nodeid)
        codebase = codebase_utils.create_codebase(data)
        created.append((data, codebase))
        return codebase

    yield _create
    for data, codebase in reversed(created):
        # idempotent; a no-op when the test already asserted the deletion itself
        codebase_utils.delete_codebase(data.name)
        vcs.delete_repo(git_url_path_of(codebase))


@pytest.fixture
def owned_imported_codebase(
    request: pytest.FixtureRequest,
    codebase_utils: CodebaseUtils,
    vcs: VCSProvider,
    _claimed_names: dict[str, str],
) -> Iterator[OwnedImportedCodebase]:
    """Factory for the seed-then-import path: a create-strategy codebase seeds the
    repo, its CR is deleted (the repo survives), and an import-strategy codebase
    onboards the surviving repo.

        codebase = owned_imported_codebase(seed_data, lambda path: import_data(path))

    import_data_factory takes the seed's gitUrlPath and returns the import
    CodebaseTestData. Same safety-net teardown contract as owned_codebase."""
    created: list[tuple[str, str]] = []

    def _create(
        seed: CodebaseTestData,
        import_data_factory: Callable[[str], CodebaseTestData],
    ) -> Codebase:
        _claim(_claimed_names, seed.name, request.node.nodeid)
        seeded = codebase_utils.create_codebase(seed)
        source_path = git_url_path_of(seeded)
        codebase_utils.delete_codebase(seed.name)
        codebase_utils.wait_deleted(seed.name)
        data = import_data_factory(source_path)
        if data.name != seed.name:  # re-import under the seed's name is the norm
            _claim(_claimed_names, data.name, request.node.nodeid)
        codebase = codebase_utils.create_codebase(data)
        created.append((data.name, source_path))
        return codebase

    yield _create
    for name, source_path in reversed(created):
        codebase_utils.delete_codebase(name)
        vcs.delete_repo(source_path)
