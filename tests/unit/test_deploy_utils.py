"""Unit tests for the pure deploy helpers: TriggerTemplate substitution and
CodebaseImageStream tag selection."""

import json

import pytest

from krci_testkit.models import CodebaseImageStream
from tests.utils.deploy_utils import (
    IMAGE_DIGEST_PATTERN,
    _substitute,
    apps_payload,
    latest_tag,
    latest_tag_entry,
)


def test_substitute_walks_nested_structures_and_keeps_payload_json_valid():
    template = {
        "metadata": {"generateName": "deploy-$(tt.params.CDPIPELINE)-$(tt.params.CDSTAGE)-"},
        "spec": {
            "params": [
                {"name": "APPLICATIONS_PAYLOAD", "value": "$(tt.params.APPLICATIONS_PAYLOAD)"},
                {"name": "KUBECONFIG_SECRET_NAME", "value": "$(tt.params.KUBECONFIG_SECRET_NAME)"},
            ]
        },
    }
    payload = json.dumps(apps_payload("app", "0.1.0-1"))
    result = _substitute(
        template,
        {
            "$(tt.params.CDPIPELINE)": "demo",
            "$(tt.params.CDSTAGE)": "dev",
            "$(tt.params.APPLICATIONS_PAYLOAD)": payload,
            "$(tt.params.KUBECONFIG_SECRET_NAME)": "in-cluster",
        },
    )
    assert result["metadata"]["generateName"] == "deploy-demo-dev-"
    assert json.loads(result["spec"]["params"][0]["value"]) == {
        "app": {"imageTag": "0.1.0-1", "customValues": False}
    }
    assert result["spec"]["params"][1]["value"] == "in-cluster"
    assert template["metadata"]["generateName"].startswith("deploy-$(")  # input untouched


def test_apps_payload_matches_portal_wire_shape():
    """Portal contract (createDeployPipelineRunDraft): imageDigest is spread in
    only when the tag carries one — a digest-less payload must NOT carry the key
    at all (the portal's JSON.stringify drops it; null is never sent)."""
    assert apps_payload("app", "0.1.0-1") == {"app": {"imageTag": "0.1.0-1", "customValues": False}}
    assert apps_payload("app", "0.1.0-1", custom_values=True, digest="sha256:abc") == {
        "app": {"imageTag": "0.1.0-1", "customValues": True, "imageDigest": "sha256:abc"}
    }
    merged = apps_payload("a", "1") | apps_payload("b", "2")
    assert sorted(merged) == ["a", "b"]


def _cbis(tags: list[dict] | None) -> CodebaseImageStream:
    return CodebaseImageStream.model_validate(
        {
            "apiVersion": "v2.edp.epam.com/v1",
            "kind": "CodebaseImageStream",
            "metadata": {"name": "app-main"},
            "spec": {"codebase": "app", "imageName": "reg/app", "tags": tags},
        }
    )


def test_latest_tag_picks_newest_by_created():
    cbis = _cbis(
        [
            {"name": "0.1.0-2", "created": "2026-08-14T10:00:00Z"},
            {"name": "0.1.0-1", "created": "2026-08-14T09:00:00Z"},
        ]
    )
    assert latest_tag(cbis) == "0.1.0-2"


def test_latest_tag_raises_on_empty_stream():
    with pytest.raises(AssertionError, match="no tags"):
        latest_tag(_cbis(None))


def test_latest_tag_orders_by_real_time_not_lexicographic_string():
    """Old bug: tags were ordered by lexicographic string compare of `created`.
    '.' (0x2e) sorts before 'Z' (0x5a), so a whole-second timestamp ('...:00Z')
    lexicographically beat a later fractional one ('...:00.500Z') even though the
    fractional tag is chronologically newer — the build that just pushed would be
    silently skipped as 'latest'."""
    cbis = _cbis(
        [
            {"name": "whole-second", "created": "2026-08-14T10:00:00Z"},
            {"name": "fractional-later", "created": "2026-08-14T10:00:00.500Z"},
        ]
    )
    assert latest_tag(cbis) == "fractional-later"


def test_latest_tag_entry_carries_the_digest_when_the_build_recorded_one():
    """The digest rides the tag entry untouched; a chart-only build's tag has no
    digest key and .get() yields None."""
    digest = "sha256:" + "ab" * 32
    assert IMAGE_DIGEST_PATTERN.fullmatch(digest)
    cbis = _cbis(
        [
            {"name": "0.1.0-1", "created": "2026-08-14T09:00:00Z"},
            {"name": "0.1.0-2", "created": "2026-08-14T10:00:00Z", "digest": digest},
        ]
    )
    entry = latest_tag_entry(cbis)
    assert entry["name"] == "0.1.0-2"
    assert entry.get("digest") == digest
    assert (
        latest_tag_entry(_cbis([{"name": "t", "created": "2026-08-14T09:00:00Z"}])).get("digest")
        is None
    )


def test_latest_tag_raises_a_clear_error_on_unparsable_created_time():
    cbis = _cbis([{"name": "bad-tag", "created": "not-a-timestamp"}])
    with pytest.raises(AssertionError, match="unparsable"):
        latest_tag(cbis)


def test_image_matches_tag_with_and_without_digest():
    from tests.utils.cdpipeline_utils import _image_at_tag

    tag = "main-20260814-155531"
    assert _image_at_tag(f"reg/app:{tag}", tag)
    assert _image_at_tag(f"reg/app:{tag}@sha256:1cd9bf", tag)
    assert not _image_at_tag("reg/app:other-tag", tag)
    assert not _image_at_tag(f"reg/app:{tag}-suffix", tag)
