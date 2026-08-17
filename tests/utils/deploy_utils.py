"""Deploy mechanics shared by the CD flow tests.

Manual deploy replicates the PORTAL's own mechanism (krci-portal
createDeployPipelineRunDraft): fetch the Stage's TriggerTemplate, substitute the
tt.params into its embedded PipelineRun, create it. The run SHAPE is platform
state, not test code — only parameters are supplied, exactly as the portal does.
AutoDeploy runs are never created here: the platform renders them from
CodebaseImageStream updates.
"""

import copy
import json
import logging
import re
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import NotRequired, TypedDict

from krci_testkit.clients import VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.models import (
    Codebase,
    CodebaseImageStream,
    TriggerTemplate,
    git_url_path_of,
    tags_of,
)
from krci_testkit.naming import image_stream_name
from krci_testkit.waits import Timeouts, wait_for
from tests.test_data.codebase_data import CodebaseTestData
from tests.test_data.deploy_data import CDPipelineTestData, StageTestData
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.codebase_utils import CodebaseUtils

log = logging.getLogger(__name__)

# What codebase_with_cd_before_build hands a scenario. Published here, beside the
# function that produces it, so the three suites that consume it annotate one
# shared name instead of each restating the same three-tuple.
CodebaseWithCd = tuple[Codebase, CodebaseTestData, CDPipelineTestData]


def _created_at(tag: dict) -> datetime:
    """A tag's creation time as a real instant.

    Comparing the raw strings would be a lexicographic sort: the CRD types `created`
    as a bare string, and RFC3339 emitters drop trailing zero fractions, so
    '...:00Z' and '...:00.5Z' sort by '.' vs 'Z' rather than by time — silently
    electing an older tag as the newest."""
    raw = tag["created"]
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssertionError(
            f"tag {tag.get('name')!r} has unparsable created time {raw!r}"
        ) from exc
    # A naive and an aware datetime cannot be compared at all, so an offset-less
    # timestamp would turn the sort into a TypeError rather than a wrong answer.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# Registry digest shape the build pipeline records on a CBIS tag.
IMAGE_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def latest_tag_entry(cbis: CodebaseImageStream) -> dict:
    """Newest tag entry by creation time (the tag a build just pushed). The entry
    carries `digest` only when the build pipeline recorded one — container builds
    do, chart-only builds never will."""
    tags = tags_of(cbis)
    image_name = cbis.spec.imageName if cbis.spec else None
    assert tags, f"no tags in codebaseimagestream {image_name}"
    return max(tags, key=_created_at)


def latest_tag(cbis: CodebaseImageStream) -> str:
    """Newest tag name by creation time (the tag a build just pushed)."""
    return latest_tag_entry(cbis)["name"]


def wait_image_entry(cluster: Cluster, timeouts: Timeouts, codebase: str, branch: str) -> dict:
    """Latest tag entry of <codebase>-<branch> once the stream exists and carries one."""
    cbis = wait_for(
        lambda: cluster.get(CodebaseImageStream, image_stream_name(codebase, branch)),
        lambda s: bool(s.spec and s.spec.tags),
        timeout=timeouts.run_trigger,
        interval=timeouts.poll_interval,
        describe=f"codebaseimagestream {codebase}-{branch} has a tag",
    )
    return latest_tag_entry(cbis)


def wait_image_tag(cluster: Cluster, timeouts: Timeouts, codebase: str, branch: str) -> str:
    """Latest tag of <codebase>-<branch> once the stream exists and carries one."""
    return wait_image_entry(cluster, timeouts, codebase, branch)["name"]


def codebase_with_cd_before_build(
    codebase_utils: CodebaseUtils,
    vcs: VCSProvider,
    cd_utils: CDPipelineUtils,
    cluster: Cluster,
    timeouts: Timeouts,
    *,
    data: CodebaseTestData,
    pipeline_factory: Callable[[str, str], CDPipelineTestData],
) -> Generator[CodebaseWithCd]:
    """Fixture body (use with `yield from`): codebase + CD pipeline created BEFORE
    any build — an Auto stage reacts to the CodebaseImageStream UPDATE event, so
    the stage (and its env label on the stream) must pre-exist the merge.
    Safety-net teardown only; happy paths assert deletions inside the test. The
    CD pipeline teardown WAITS for full deletion before the codebase goes away —
    the reverse order wedges the Stage finalizer."""
    created = codebase_utils.create_codebase(data)
    wait_for(
        lambda: cluster.exists(
            CodebaseImageStream, image_stream_name(data.name, data.default_branch)
        ),
        bool,
        timeout=timeouts.run_trigger,
        interval=timeouts.poll_interval,
        describe=f"codebaseimagestream {data.name}-{data.default_branch} exists",
    )
    cd = pipeline_factory(data.name, data.default_branch)
    cd_utils.create_cdpipeline(cd)
    yield created, data, cd
    cd_utils.cleanup_cdpipeline(cd)
    codebase_utils.delete_codebase(data.name)
    vcs.delete_repo(git_url_path_of(created))


def _substitute[Node](node: Node, subs: dict[str, str]) -> Node:
    """Recursively substitute $(tt.params.X) markers in string values (list/dict
    structure preserved; input left untouched)."""
    if isinstance(node, str):
        substituted = node
        for marker, value in subs.items():
            substituted = substituted.replace(marker, value)
        # Narrowed to str inside this branch, but pyright can't prove a str is
        # assignable back to the unbound Node (it could be a str subtype).
        return substituted  # pyright: ignore[reportReturnType]
    if isinstance(node, dict):
        substituted_dict = {k: _substitute(v, subs) for k, v in node.items()}
        return substituted_dict  # pyright: ignore[reportReturnType]
    if isinstance(node, list):
        return [_substitute(v, subs) for v in node]  # pyright: ignore[reportReturnType]
    return node


class ApplicationPayload(TypedDict):
    """One app's entry in the portal's APPLICATIONS_PAYLOAD wire contract
    (krci-portal createDeployPipelineRunDraft) — keys are the portal's, not ours.
    imageDigest is spread in only when the deployed tag carries one: absent,
    never null, exactly as the portal serializes it."""

    imageTag: str
    customValues: bool
    imageDigest: NotRequired[str]


def apps_payload(
    app: str, tag: str, *, custom_values: bool = False, digest: str | None = None
) -> dict[str, ApplicationPayload]:
    """The portal payload for deploying one app at one tag. Multi-app deploys
    merge entries: apps_payload(a, t1) | apps_payload(b, t2)."""
    payload: ApplicationPayload = {"imageTag": tag, "customValues": custom_values}
    if digest is not None:
        payload["imageDigest"] = digest
    return {app: payload}


def render_deploy_run(
    cluster: Cluster,
    *,
    pipeline: str,
    stage: StageTestData,
    apps_payload: dict[str, ApplicationPayload],
) -> str:
    """Portal-parity manual deploy: render the stage's TriggerTemplate and create
    the PipelineRun. Returns the created run's name."""
    template = cluster.get_raw(TriggerTemplate, stage.trigger_template)
    manifest = copy.deepcopy(template["spec"]["resourcetemplates"][0])
    rendered = _substitute(
        manifest,
        {
            "$(tt.params.CDPIPELINE)": pipeline,
            "$(tt.params.CDSTAGE)": stage.name,
            "$(tt.params.APPLICATIONS_PAYLOAD)": json.dumps(apps_payload),
            "$(tt.params.KUBECONFIG_SECRET_NAME)": stage.cluster_name,
        },
    )
    created = cluster.create_from_manifest(rendered)
    name = created["metadata"]["name"]
    log.info("rendered manual deploy run %s (portal-parity) for %s/%s", name, pipeline, stage.name)
    return name
