"""Testkit exception types, decoupled from the underlying K8s client library."""


class NotFound(Exception):
    """A resource (or resource type) does not exist on the cluster."""


class AlreadyExists(Exception):
    """Creation conflicted with an existing resource (e.g. a concurrent xdist
    worker won an idempotent-ensure race)."""


class Malformed(Exception):
    """A resource on the cluster does not fit the generated model for its kind."""
