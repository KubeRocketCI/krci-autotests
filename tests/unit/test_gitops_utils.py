"""Unit tests for the pure gitops helpers: values-path convention, override
payload, and the feature/fastapi test-data shapes."""

from krci_testkit import labels
from krci_testkit.gitops import GITOPS_SELECTOR
from tests.test_data.codebase_data import (
    python_fastapi_application,
    python_fastapi_imported,
)
from tests.test_data.deploy_data import feature_pipeline, replica_override_values
from tests.utils.gitops_utils import gitops_values_path


def test_values_path_follows_the_applicationset_template_convention():
    # cd-pipeline-operator templatePatch: $values/<cdpipeline>/<stage>/<app>-values.yaml
    assert gitops_values_path("pipe", "qa", "app") == "pipe/qa/app-values.yaml"


def test_replica_override_is_minimal_yaml():
    assert replica_override_values(2) == "replicaCount: 2\n"


def test_gitops_is_selected_the_way_the_operator_selects_it():
    """The repo is resolved by the cd-pipeline-operator's own labels, not by name:
    the name is a bootstrap default, while these labels are what the platform
    itself keys on when it bakes the repo URL into an ApplicationSet."""
    assert GITOPS_SELECTOR == {labels.CODEBASE_TYPE: "system", labels.SYSTEM_TYPE: "gitops"}


def test_feature_pipeline_streams_the_feature_branch():
    data = feature_pipeline("app", "at-sft-abc123")
    assert data.input_streams == ["app-at-sft-abc123"]
    assert data.applications == ["app"]
    assert data.applications_to_promote == []
    (dev,) = data.stages
    assert dev.trigger_type == "Manual"


def test_fastapi_factories_share_the_enabled_python_triple():
    created = python_fastapi_application()
    imported = python_fastapi_imported("/group/seed", name="seed")
    for data in (created, imported):
        assert (data.lang, data.framework, data.build_tool) == ("python", "fastapi", "python")
    assert created.strategy == "create"
    assert imported.strategy == "import"
    assert imported.git_url_path == "/group/seed"
    assert imported.name == "seed"  # name reuse: registry path must match the project
