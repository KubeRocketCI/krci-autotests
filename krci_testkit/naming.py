"""Run-ID-suffixed unique resource names, so parallel runs never collide."""

import hashlib
import os
import re
import uuid

_cached_run_id: str | None = None
_TOKEN_LEN = 6
# External ids up to this length pass through verbatim (short CI run numbers stay
# recognizable); anything longer is hashed down to _TOKEN_LEN.
_HASH_OVER = 8


def run_id() -> str:
    """Per-run identifier: KRCI_RUN_ID env (set by CI) or generated once per process.

    Long external ids (e.g. CI job/run names) are hashed to a short deterministic
    token so unique_name() truncation can never chop off the unique part.

    The xdist worker id is appended when present. Without it, a CI-provided
    KRCI_RUN_ID is SHARED by every parallel worker, so two tests that happen to
    use the same name prefix on different workers would fight over one Codebase —
    the failure mode the per-test prefix discipline exists to avoid, and the one
    it cannot cover on its own."""
    global _cached_run_id
    if _cached_run_id is None:
        external = os.environ.get("KRCI_RUN_ID")
        if external and len(external) > _HASH_OVER:
            external = hashlib.sha1(external.encode()).hexdigest()[:_TOKEN_LEN]
        worker = os.environ.get("PYTEST_XDIST_WORKER", "")
        _cached_run_id = (external or uuid.uuid4().hex[:_TOKEN_LEN]) + worker
    return _cached_run_id


_MAX_NAME = 30


def _dns1123(value: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", value.lower())


def unique_name(prefix: str) -> str:
    """DNS-1123 name 'at-<prefix>-<run_id>', ≤ 30 chars (codebase names feed pipeline names).

    Only the PREFIX is truncated to fit. Truncating the assembled string instead
    would chop the run id off a long prefix, and two xdist workers would then
    compute the same name and fight over one CR — silently, since a collision
    only shows up as the other worker's resource changing under it."""
    run = _dns1123(run_id())
    budget = _MAX_NAME - len("at-") - len(run) - 1
    if budget < 1:
        raise ValueError(
            f"run id {run!r} leaves no room for a name prefix within {_MAX_NAME} chars"
        )
    return f"at-{_dns1123(prefix)[:budget]}-{run}".strip("-")


# Platform naming conventions. Each rule is written ONCE here; a platform-side
# rename becomes a one-line change instead of a hunt across tests/utils.


def repo_path(group: str, repo: str) -> str:
    """A repository's gitUrlPath.

    The group is a path PREFIX, not a required segment: Gerrit projects are flat,
    so their path is the bare name. An empty group must not leave the separator
    behind — the operator reads gitUrlPath as the project id, and a doubled slash
    becomes part of the name it asks the provider to create."""
    group = group.strip("/")
    return f"/{group}/{repo}" if group else f"/{repo}"


def branch_cr_name(codebase: str, branch: str) -> str:
    """CodebaseBranch CR name."""
    return f"{codebase}-{branch}"


def image_stream_name(codebase: str, branch: str) -> str:
    """CodebaseImageStream CR name (same rule as branch CRs, distinct meaning)."""
    return f"{codebase}-{branch}"


def stage_cr_name(pipeline: str, stage: str) -> str:
    """Stage CR name (webhook-enforced <cdPipeline>-<stage>)."""
    return f"{pipeline}-{stage}"


def argo_app_name(pipeline: str, stage: str, app: str) -> str:
    """ArgoCD Application name the cd-pipeline-operator generates."""
    return f"{pipeline}-{stage}-{app}"


def verified_stream_name(pipeline: str, stage: str, app: str) -> str:
    """CodebaseImageStream written by promote-images."""
    return f"{pipeline}-{stage}-{app}-verified"


def stage_namespace(platform_namespace: str, pipeline: str, stage: str) -> str:
    """Deploy namespace <platform-ns>-<pipeline>-<stage>."""
    return f"{platform_namespace}-{pipeline}-{stage}"
