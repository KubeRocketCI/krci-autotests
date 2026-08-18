"""The manifest bodies the spec builders send, pinned exactly (no cluster).

These builders replaced hand-rolled dicts with the generated CRD models, so the
risk they carry is a SHAPE change: a field silently renamed by a CRD bump, or an
optional that starts serialising as an explicit null. Comparing the whole dict —
not a few keys — is what catches that.
"""

from krci_testkit.platform import VersioningType
from tests.test_data.codebase_data import (
    HELM_LIBRARY,
    BranchTestData,
    cloned_codebase,
    created_codebase,
    imported_codebase,
)
from tests.test_data.deploy_data import manual_pipeline, promote_pipeline
from tests.utils.cdpipeline_utils import cdpipeline_spec, stage_spec
from tests.utils.codebase_utils import branch_spec, codebase_spec

_GIT = {"git_server": "gitlab", "git_group": "krci"}


def test_codebase_spec_is_the_full_manifest_body():
    data = created_codebase(HELM_LIBRARY, "helm")
    assert codebase_spec(data, **_GIT) == {
        "type": "library",
        "strategy": "create",
        "lang": "helm",
        "framework": "pipeline",
        "buildTool": "helm",
        "defaultBranch": "main",
        "emptyProject": False,
        "gitServer": "gitlab",
        "gitUrlPath": f"/krci/{data.name}",
        "deploymentScript": "helm-chart",
        "versioning": {"type": "default"},
        "ciTool": "tekton",
    }


def test_codebase_spec_does_not_leak_model_defaults_onto_the_wire():
    """The generated model carries the CRD's own defaults (private=True,
    clearSecretAfterUse=True, ...). Serialising them would restate the CRD as if
    the test meant it, and would pin values the platform may later change."""
    spec = codebase_spec(created_codebase(HELM_LIBRARY, "helm"), **_GIT)
    assert "private" not in spec
    assert "commitMessagePattern" not in spec


def test_codebase_spec_omits_unset_optionals_rather_than_sending_null():
    """An explicit null is not the same as an absent key to the API server: the
    default-versioning codebase must carry no startFrom and no repository at all."""
    spec = codebase_spec(created_codebase(HELM_LIBRARY, "helm"), **_GIT)
    assert "startFrom" not in spec["versioning"]
    assert "repository" not in spec


def test_codebase_spec_carries_semver_start_version():
    spec = codebase_spec(
        created_codebase(HELM_LIBRARY, "vhelm", versioning=VersioningType.SEMVER), **_GIT
    )
    assert spec["versioning"] == {"type": "semver", "startFrom": "0.1.0-SNAPSHOT"}


def test_codebase_spec_carries_the_clone_source():
    spec = codebase_spec(cloned_codebase(HELM_LIBRARY, "cln"), **_GIT)
    assert spec["strategy"] == "clone"
    assert spec["repository"] == {"url": "https://github.com/epmd-edp/helm-helm-pipeline.git"}


def test_codebase_spec_honours_an_explicit_git_url_path():
    """Import strategy onboards an EXISTING repo, so its path must survive verbatim
    instead of being derived from the run's git group."""
    imported = imported_codebase(HELM_LIBRARY, "imp", "/other-group/legacy-app")
    assert codebase_spec(imported, **_GIT)["gitUrlPath"] == "/other-group/legacy-app"


def test_branch_spec_omits_version_for_a_feature_branch():
    spec = branch_spec("at-helm-x", BranchTestData(branch_name="feat-1"))
    assert spec == {
        "codebaseName": "at-helm-x",
        "branchName": "feat-1",
        "fromCommit": "",
        "release": False,
    }


def test_branch_spec_carries_version_for_a_release_branch():
    spec = branch_spec(
        "at-helm-x", BranchTestData(branch_name="rel-1", release=True, version="0.1.0-RC.1")
    )
    assert spec["release"] is True
    assert spec["version"] == "0.1.0-RC.1"


def test_cdpipeline_spec_is_the_full_manifest_body():
    data = promote_pipeline("app", "main")
    assert cdpipeline_spec(data) == {
        "name": data.name,
        "deploymentType": "container",
        "applications": ["app"],
        "inputDockerStreams": ["app-main"],
        "applicationsToPromote": ["app"],
    }


def test_cdpipeline_spec_omits_applications_to_promote_when_empty():
    """An empty applications_to_promote must not appear on the wire at all: the
    generic `or None` guard that keeps unset optionals off the wire must also
    catch the empty-list case, or the operator sees an explicit empty promote list
    instead of 'no promotion configured'."""
    data = manual_pipeline("app", "main")
    assert "applicationsToPromote" not in cdpipeline_spec(data)


def test_stage_spec_is_the_full_manifest_body():
    data = promote_pipeline("app", "main")
    dev = data.stages[0]
    assert stage_spec(data, dev, namespace="krci-pdp-dev") == {
        "name": "dev",
        "cdPipeline": data.name,
        "description": "krci-autotests stage",
        "namespace": "krci-pdp-dev",
        "order": 0,
        "triggerType": "Manual",
        "triggerTemplate": "deploy",
        "clusterName": "in-cluster",
        "source": {"type": "default"},
        "qualityGates": [{"qualityGateType": "manual", "stepName": "manual"}],
    }


def test_stage_spec_renders_the_auto_trigger_type():
    data = promote_pipeline("app", "main")
    qa = data.stages[1]
    assert stage_spec(data, qa, namespace="ns")["triggerType"] == "Auto"
