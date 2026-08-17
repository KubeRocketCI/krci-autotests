"""validate_manifest: built CR manifests must fit the generated CRD models."""

import pytest
from pydantic import ValidationError

from krci_testkit.clusters import validate_manifest
from krci_testkit.models import Codebase


def _manifest(spec: dict) -> dict:
    return {
        "apiVersion": "v2.edp.epam.com/v1",
        "kind": "Codebase",
        "metadata": {"name": "x", "namespace": "ns"},
        "spec": spec,
    }


_VALID_SPEC = {
    "type": "library",
    "strategy": "create",
    "lang": "helm",
    "framework": "pipeline",
    "buildTool": "helm",
    "defaultBranch": "main",
    "emptyProject": False,
    "gitServer": "gs",
    "gitUrlPath": "/g/x",
    "versioning": {"type": "default"},
    "ciTool": "tekton",
}


def test_valid_manifest_passes():
    validate_manifest(Codebase, _manifest(_VALID_SPEC))


def test_unknown_enum_value_rejected():
    with pytest.raises(ValidationError):
        validate_manifest(Codebase, _manifest({**_VALID_SPEC, "strategy": "cloone"}))


def test_wrong_type_rejected():
    with pytest.raises(ValidationError):
        validate_manifest(Codebase, _manifest({**_VALID_SPEC, "emptyProject": "nope"}))


def test_missing_required_field_rejected():
    spec = dict(_VALID_SPEC)
    del spec["gitServer"]
    with pytest.raises(ValidationError):
        validate_manifest(Codebase, _manifest(spec))
