"""Typed waits with an explicit transient-error allowlist.

Never swallow arbitrary exceptions: only not-found-yet and transport-level errors
are retried. On timeout the last-seen state is embedded in the failure message so
it lands in ReportPortal logs (symmetric with UI screenshot-on-failure).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from typing import Any, Literal

import httpx
import yaml

from krci_testkit.errors import NotFound
from krci_testkit.platform import GitBranchStatus, ReconcileResult

log = logging.getLogger(__name__)

TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TransportError,  # connection blips to the API server
    ConnectionError,
    TimeoutError,
)


class WaitTimeout(AssertionError):
    pass


def _knob(default: int, description: str, *, ini: str = "") -> Any:
    """Declare a run knob once: its default, its `-o` name and its help text.

    Returning Any is what lets pyright keep seeing an `int` attribute on the
    dataclass instead of a Field object."""
    return field(default=default, metadata={"ini": ini, "description": description})


@dataclass(frozen=True)
class Timeouts:
    """Run-level wait tuning. Values are resolved by the pytest option system in
    tests/conftest.py (ini < -o < PYTEST_ADDOPTS), NOT by KrciConfig — timeouts
    are run knobs, not target-environment facts.

    Each field carries its own ini name and help text, so adding a knob is ONE
    edit here — pytest's option registration and the `timeouts` fixture both
    derive from timeout_knobs()."""

    codebase_ready: int = _knob(600, "seconds to wait for Codebase/branch readiness")
    build_success: int = _knob(900, "seconds to wait for build PipelineRun success")
    codebase_delete: int = _knob(180, "seconds to wait for Codebase deletion")
    run_trigger: int = _knob(
        300, "seconds for the platform to render a PipelineRun after a VCS event"
    )
    change_merge: int = _knob(180, "seconds for a submitted change to become mergeable and merge")
    deploy_success: int = _knob(
        900, "seconds for a deploy PipelineRun to succeed (incl. ArgoCD sync)"
    )
    vcs_request: int = _knob(30, "seconds for a single VCS API request before it is abandoned")
    poll_interval: int = _knob(5, "wait poll interval in seconds", ini="krci_poll_interval")
    ui_expect: int = _knob(15, "seconds for Playwright expect() assertions (UI suite default)")


@dataclass(frozen=True)
class Knob:
    """One run knob, flattened for the pytest option layer (no pytest import here)."""

    name: str
    ini: str
    description: str
    default: int


def timeout_knobs() -> list[Knob]:
    """Every Timeouts field as a Knob. The ini name defaults to `krci_timeout_<field>`;
    poll_interval keeps its historical name via the field's own metadata."""
    return [
        Knob(
            name=f.name,
            ini=f.metadata["ini"] or f"krci_timeout_{f.name}",
            description=f.metadata["description"],
            default=f.default,  # pyright: ignore[reportArgumentType]
        )
        for f in fields(Timeouts)
    ]


class FailFast(AssertionError):
    """Raised by predicates to abort polling on terminal failure states."""


# The operator retries a failed reconcile, so a single `result: error` is not
# terminal — but a climbing failure count is a CR that will not recover, and
# polling on only burns the whole timeout.
_MAX_RECONCILE_FAILURES = 3


def _fail_if_stuck(status: Any) -> None:
    """Abort on a CR the operator has given up on. Only Codebase and
    CodebaseBranch count failures; CDPipeline and Stage carry no such field and
    are left to poll, since `result: error` alone is a state they recover from.

    status is deliberately duck-typed: it is the .status of whichever generated
    model class is being polled (Codebase, CodebaseBranch, CDPipeline, Stage all
    share the shape this reads but have no common base type)."""
    if (getattr(status, "failureCount", None) or 0) < _MAX_RECONCILE_FAILURES:
        return
    raise FailFast(
        f"operator failed to reconcile {status.failureCount}x "
        f"(action={status.action}, result={status.result.value}): {status.detailedMessage}"
    )


def reconciled(cr: Any) -> bool:
    """KRCI operator convention: a reconciled CR is ready when status.available
    is true AND status.result is success — available alone can accompany an
    error result (Codebase, CDPipeline and Stage all share this status shape).

    cr is deliberately duck-typed across generated model classes (see
    platform.ReconcileResult's docstring)."""
    status = cr.status
    if not status:
        return False
    _fail_if_stuck(status)
    return bool(
        status.available and status.result and status.result.value == ReconcileResult.SUCCESS
    )


def branch_ready(cr: Any) -> bool:
    """Readiness for CodebaseBranch, which carries no `available` flag: reconciled
    AND the remote git branch pushed.

    status.result is not readiness on its own. The operator turns it success after
    every intermediate reconcile, so a wait on it alone returns on the first poll
    and the caller then addresses a git branch that does not exist yet — the VCS
    answers 400 for the unknown ref, far from the wait that should have caught it.
    status.git is the operator's own git-side marker and the only field that
    distinguishes the two.

    cr is deliberately duck-typed across generated model classes (see
    platform.ReconcileResult's docstring)."""
    status = cr.status
    if not status:
        return False
    _fail_if_stuck(status)
    return bool(
        status.result
        and status.result.value == ReconcileResult.SUCCESS
        and status.git == GitBranchStatus.BRANCH_CREATED
    )


def wait_for[T](
    fetch: Callable[[], T],
    predicate: Callable[[T], bool],
    *,
    timeout: float,
    interval: float = 5.0,
    describe: str = "",
    not_found: Literal["retry", "fail"] = "retry",
) -> T:
    """Poll fetch() until predicate() is true.

    not_found policy: "retry" (default) treats NotFound as 'not created yet' —
    correct for creation waits. Use "fail" for post-creation waits where the
    resource is known to exist: absence then means it was deleted mid-wait, and
    failing immediately beats burning the whole timeout on a misleading message.
    """
    log.info("waiting for %s (timeout %ss)", describe, timeout)
    started = time.monotonic()
    deadline = started + timeout
    last: T | None = None
    last_error: BaseException | None = None
    while True:
        try:
            last = fetch()
        except NotFound as exc:
            if not_found == "fail":
                raise NotFound(
                    f"resource disappeared while waiting for: {describe} ({exc})"
                ) from exc
            last_error = exc
            log.info("wait[%s]: not found yet: %s", describe, exc)
        except TRANSIENT_ERRORS as exc:
            last_error = exc
            log.info("wait[%s]: transient %s: %s", describe, type(exc).__name__, exc)
        else:
            last_error = None
            if predicate(last):
                log.info("done: %s (%.0fs)", describe, time.monotonic() - started)
                return last
        # Sleep only the remaining budget, and always fetch one final time AT the
        # deadline: a state change during the last sleep must count, and the
        # reported duration must be measured, not the configured number.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    state = (
        yaml.safe_dump(_dumpable(last), default_flow_style=False)
        if last is not None
        else repr(last_error)
    )
    raise WaitTimeout(
        f"timed out after {time.monotonic() - started:.0f}s (limit {timeout}s) "
        f"waiting for: {describe}\nlast seen state:\n{state}"
    )


def wait_gone(
    fetch: Callable[[], dict], *, timeout: float, interval: float = 5.0, describe: str = ""
) -> None:
    """Poll until fetch() raises NotFound — the deletion-wait counterpart of wait_for.

    fetch returns the RAW manifest of the resource that should disappear. On
    timeout the failure answers "whose bug is this" by itself: metadata without a
    deletionTimestamp means deletion was never requested (caller bug); a
    deletionTimestamp plus finalizers means cleanup is wedged, and the message
    names the blocking finalizer (operator bug)."""
    log.info("waiting for %s (timeout %ss)", describe, timeout)
    started = time.monotonic()
    deadline = started + timeout
    last: dict | None = None
    last_error: BaseException | None = None
    while True:
        try:
            last = fetch()
        except NotFound:
            log.info("done: %s (%.0fs)", describe, time.monotonic() - started)
            return
        except TRANSIENT_ERRORS as exc:
            last_error = exc
            log.info("wait[%s]: transient %s: %s", describe, type(exc).__name__, exc)
        # Same contract as wait_for: sleep only the remaining budget, final fetch
        # AT the deadline (a deletion landing during the last sleep must count),
        # measured duration in the failure.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    detail = _deletion_evidence(last) if last is not None else f"last error: {last_error!r}"
    raise WaitTimeout(
        f"timed out after {time.monotonic() - started:.0f}s (limit {timeout}s) "
        f"waiting for: {describe}\n{detail}"
    )


def _deletion_evidence(manifest: dict) -> str:
    """The metadata that attributes a stuck deletion (deletionTimestamp and
    finalizers only — the full raw manifest would bury them in managedFields)."""
    meta = manifest.get("metadata", {})
    timestamp = meta.get("deletionTimestamp")
    finalizers = meta.get("finalizers")
    if not timestamp:
        verdict = "deletion was NEVER requested — the caller did not delete this resource"
    elif finalizers:
        verdict = "deletion requested but cleanup is wedged — the finalizer(s) above are blocking"
    else:
        verdict = "deletion in progress with no finalizers left — likely a timeout tuned too low"
    # Plain str/list coercion is load-bearing: kr8s raw manifests carry Box/BoxList
    # wrappers, which yaml.safe_dump refuses — the dump would blow up instead of
    # reporting, on the very path that exists to diagnose.
    evidence = {
        "deletionTimestamp": str(timestamp) if timestamp else None,
        "finalizers": [str(f) for f in finalizers] if finalizers else None,
    }
    return "deletion evidence:\n" + yaml.safe_dump(evidence, default_flow_style=False) + verdict


def _dumpable(value: Any) -> Any:
    # mode="json" is load-bearing: a plain model_dump leaves Enum and datetime fields
    # as Python objects, which yaml.safe_dump refuses (RepresenterError) — the dump
    # would blow up instead of reporting, on the very path that exists to diagnose.
    # Sequences and mappings are walked, not passed through: the pipeline-run waits
    # fetch a LIST of models, and that is the most common timeout path of all.
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True, mode="json")
    if isinstance(value, (list, tuple)):
        return [_dumpable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _dumpable(v) for k, v in value.items()}
    return value
