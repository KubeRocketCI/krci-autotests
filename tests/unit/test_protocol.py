"""Unit tests for the provider-neutral CI-state normalization
(krci_testkit.clients.protocol.normalize_ci_state), shared by every VCS client."""

from krci_testkit.clients.protocol import normalize_ci_state
from krci_testkit.platform import CIStatus


def test_unrecognised_ci_state_maps_to_unknown_without_raising():
    """An unrecognised provider state must never masquerade as a pass (or any
    other known status), and the lookup itself must not raise — a status listing
    is diagnostic input, not an assertion."""
    assert (
        normalize_ci_state("some-new-provider-state", {"success": CIStatus.SUCCESS})
        == CIStatus.UNKNOWN
    )


def test_recognised_native_state_maps_via_the_provider_table():
    assert normalize_ci_state("SUCCESSFUL", {"SUCCESSFUL": CIStatus.SUCCESS}) == CIStatus.SUCCESS
