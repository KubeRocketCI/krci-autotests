"""K8s access for the platform cluster. The ONLY module that talks to the API server.

Pydantic models (krci_testkit.models) validate what we read; kr8s carries raw dicts.
"""

import base64
from typing import TypeVar, cast

import kr8s
from kr8s.objects import APIObject, Namespace, Secret, new_class, object_from_spec
from pydantic import BaseModel, ValidationError

from krci_testkit.config import KrciConfig
from krci_testkit.errors import AlreadyExists, Malformed, NotFound
from krci_testkit.models import GVK

__all__ = [
    "AlreadyExists",
    "Cluster",
    "Malformed",
    "NotFound",
    "validate_manifest",
]

# Characters that carry meaning inside a label selector expression.
_SELECTOR_META = frozenset(",=")

_M = TypeVar("_M", bound=BaseModel)


def validate_manifest(model_cls: type, manifest: dict) -> None:
    """Fail fast, BEFORE the API call, when a built manifest does not fit the
    generated CRD model: wrong field type, unknown enum value, missing required
    field. Generated models ignore unknown keys, so this cannot catch a
    misspelled optional key — the API-server validation remains the backstop."""
    model_cls.model_validate(manifest)


def _parse[M: BaseModel](model_cls: type[M], raw: dict) -> M:
    """Every read goes through here so a malformed object names itself: pydantic
    reports the offending field but not which resource carried it, and a run that
    reads many objects of one kind cannot act on that alone."""
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        name = raw.get("metadata", {}).get("name", "?")
        raise Malformed(f"{model_cls.__name__}/{name}: {exc}") from exc


class Cluster:
    def __init__(self, cfg: KrciConfig):
        self.namespace = cfg.namespace
        self._api = kr8s.api(context=cfg.kube_context) if cfg.kube_context else kr8s.api()
        self._kr8s_classes: dict[type, type] = {}
        self._validate_gvk_registry()

    def _validate_gvk_registry(self) -> None:
        """Fail fast if a registered plural is not served by the cluster.

        A wrong plural otherwise surfaces as phantom 404s that creation waits
        happily retry until timeout — a 10-minute mystery instead of an instant,
        named error."""
        served = {
            (res.get("version") or res.get("groupVersion"), res.get("name"))
            for res in self._api.api_resources()
        }
        problems = [
            f"{gvk.kind}: plural '{gvk.plural}' not served for apiVersion '{gvk.api_version}'"
            for gvk in GVK.values()
            if (gvk.api_version, gvk.plural) not in served
        ]
        if problems:
            raise NotFound(
                "GVK registry does not match cluster API discovery:\n  " + "\n  ".join(problems)
            )

    @property
    def api_server(self) -> str:
        """URL of the API server this cluster talks to (the portal proxies the SA
        token to the same endpoint, so it is where a portal token is validated)."""
        return str(self._api.auth.server)

    @property
    def api_server_ca(self) -> str | bool:
        """The kubeconfig's CA bundle path, or False when it has none — shaped as
        httpx's `verify` argument so callers pass it straight through."""
        return str(self._api.auth.server_ca_file or "") or False

    def unreadable_kinds(self, model_classes: list[type[BaseModel]]) -> list[str]:
        """Which of the given kinds the current identity cannot LIST in this namespace.

        Asked up front because RBAC scoped to the wrong resources otherwise passes
        every reachability check and then 403s on the first CR a test touches —
        minutes into a run, far from the cause. Read access is what can be probed
        without creating anything; a write-only RBAC gap still surfaces later."""
        unreadable = []
        for model_cls in model_classes:
            try:
                self.list(model_cls, labels={})
            except Exception as exc:  # noqa: BLE001 - the reason is reported, not raised
                unreadable.append(f"{model_cls.__name__}: {exc}")
        return unreadable

    def _kr8s_cls(self, model_cls: type) -> type:
        if model_cls not in self._kr8s_classes:
            gvk = GVK[model_cls]
            self._kr8s_classes[model_cls] = new_class(
                kind=gvk.kind,
                version=gvk.api_version,
                namespaced=True,
                asyncio=False,
                plural=gvk.plural,
            )
        return self._kr8s_classes[model_cls]

    def create(
        self,
        model_cls: type[BaseModel],
        *,
        name: str | None = None,
        generate_name: str | None = None,
        spec: dict,
        labels: dict[str, str] | None = None,
    ) -> dict:
        gvk = GVK[model_cls]
        metadata: dict = {"namespace": self.namespace}
        if name:
            metadata["name"] = name
        if generate_name:
            metadata["generateName"] = generate_name
        if labels:
            metadata["labels"] = labels
        manifest = {
            "apiVersion": gvk.api_version,
            "kind": gvk.kind,
            "metadata": metadata,
            "spec": spec,
        }
        validate_manifest(model_cls, manifest)
        obj = self._kr8s_cls(model_cls)(manifest, namespace=self.namespace, api=self._api)
        self._create(obj, gvk.kind, name)
        return obj.raw

    def _create(self, obj: APIObject, kind: str, name: str | None) -> None:
        """Create with the module's uniform error contract: a 409 conflict
        surfaces as AlreadyExists on every create path, so idempotent ensures
        never depend on which creation entry point they were built on."""
        try:
            obj.create()
        except kr8s.ServerError as exc:
            if exc.response is not None and exc.response.status_code == 409:
                raise AlreadyExists(f"{kind}/{name} in {self.namespace}") from exc
            raise

    def get_raw(self, model_cls: type[_M], name: str) -> dict:
        try:
            obj = self._kr8s_cls(model_cls).get(name, namespace=self.namespace, api=self._api)
        except kr8s.NotFoundError as exc:
            raise NotFound(f"{model_cls.__name__}/{name} in {self.namespace}") from exc
        return obj.raw

    def get(self, model_cls: type[_M], name: str) -> _M:
        return _parse(model_cls, self.get_raw(model_cls, name))

    def delete(self, model_cls: type[BaseModel], name: str, *, ignore_missing: bool = True) -> None:
        try:
            obj = self._kr8s_cls(model_cls).get(name, namespace=self.namespace, api=self._api)
            obj.delete()
        except kr8s.NotFoundError:
            if not ignore_missing:
                raise

    def exists(self, model_cls: type[BaseModel], name: str) -> bool:
        try:
            self.get_raw(model_cls, name)
        except NotFound:
            return False
        return True

    def get_secret(self, name: str) -> dict[str, str]:
        """Decoded data of a namespaced Secret (e.g. a GitServer's credential secret)."""
        try:
            secret = Secret.get(name, namespace=self.namespace, api=self._api)
        except kr8s.NotFoundError as exc:
            raise NotFound(f"Secret/{name} in {self.namespace}") from exc
        return {k: base64.b64decode(v).decode() for k, v in secret.raw.get("data", {}).items()}

    def list(self, model_cls: type[_M], *, labels: dict[str, str]) -> list[_M]:
        """Every CR carrying the given labels (all of the kind when labels is empty).

        Label VALUES are expected to be selector-safe: CR names from
        naming.unique_name (DNS-1123) or krci_testkit.platform enums. That is
        ASSERTED rather than assumed, because a value containing ',' or '=' would
        silently select the wrong set — a false green, which is the one failure
        mode a test suite must never produce quietly."""
        gvk = GVK[model_cls]
        unsafe = {k: v for k, v in labels.items() if _SELECTOR_META & set(str(v))}
        assert not unsafe, (
            f"label values must not contain {sorted(_SELECTOR_META)} — they would "
            f"silently change the selector's meaning: {unsafe}"
        )
        selector = ",".join(f"{k}={v}" for k, v in labels.items())
        # kr8s.Api.get()'s declared return type covers a raw=True dict branch we
        # never take (raw defaults to False); cast narrows to the APIObject branch we get.
        objs = cast(
            "list[APIObject]",
            list(self._api.get(gvk.plural, namespace=self.namespace, label_selector=selector)),
        )
        return [_parse(model_cls, obj.raw) for obj in objs]

    def create_from_manifest(self, manifest: dict) -> dict:
        """Create a resource from a full manifest (e.g. a PipelineRun rendered from a
        TriggerTemplate, portal-parity). Namespace is forced to the platform namespace."""
        manifest.setdefault("metadata", {})["namespace"] = self.namespace
        obj = object_from_spec(manifest, api=self._api, allow_unknown_type=True)
        self._create(obj, manifest.get("kind", "?"), manifest["metadata"].get("name"))
        return obj.raw

    def deployments(self, namespace: str) -> list[dict]:
        """Raw apps/v1 Deployments of an arbitrary namespace. Deploy tests read
        workloads from stage namespaces (`<platform-ns>-<pipeline>-<stage>`),
        which live outside the platform namespace all other reads are pinned to."""
        deployments = cast(
            "list[APIObject]", list(self._api.get("deployments", namespace=namespace))
        )
        return [d.raw for d in deployments]

    def namespace_raw(self, name: str) -> dict:
        """Raw manifest of a cluster-scoped Namespace (deletion waits read its
        metadata for evidence); raises NotFound when absent."""
        try:
            return Namespace.get(name, api=self._api).raw
        except kr8s.NotFoundError as exc:
            raise NotFound(f"Namespace/{name}") from exc

    def ping(self) -> str:
        """Cheap API-server reachability probe; returns the server version string."""
        return str(self._api.version())
