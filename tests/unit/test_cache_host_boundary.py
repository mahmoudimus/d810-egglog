from __future__ import annotations

import ast
import importlib
import inspect
import math
from collections.abc import Mapping

import pytest

from d810.mba.extension_api import TypedBvTerm


def _copy_json(value: object, active: set[int] | None = None) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise TypeError("JSON values must contain finite floats")
        return value
    active = set() if active is None else active
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise TypeError("JSON values must not contain cycles")
        active.add(identity)
        try:
            if any(type(key) is not str for key in value):
                raise TypeError("JSON mapping keys must be strings")
            return {key: _copy_json(item, active) for key, item in value.items()}
        finally:
            active.remove(identity)
    if type(value) is list:
        identity = id(value)
        if identity in active:
            raise TypeError("JSON values must not contain cycles")
        active.add(identity)
        try:
            return [_copy_json(item, active) for item in value]
        finally:
            active.remove(identity)
    raise TypeError("JSON values must be scalar, list, or mapping")


class StrictJsonPersistence:
    """Host-style persistence that rejects arbitrary/native values."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    def get_json(self, key: str):
        if type(key) is not str or not key:
            raise ValueError("invalid persistence key")
        value = self.values.get(key)
        return None if value is None else _copy_json(value)

    def put_json(self, key: str, value: Mapping[str, object]) -> None:
        if type(key) is not str or not key:
            raise ValueError("invalid persistence key")
        copied = _copy_json(value)
        if not isinstance(copied, dict):
            raise TypeError("persistence values must be mappings")
        self.values[key] = copied

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def keys(self, *, prefix: str = "") -> tuple[str, ...]:
        if type(prefix) is not str:
            raise TypeError("invalid persistence prefix")
        return tuple(sorted(key for key in self.values if key.startswith(prefix)))


def _leaf(name: str) -> TypedBvTerm:
    return TypedBvTerm(None, 32, leaf_key=("register", name))


def _binary(operation: str, left: TypedBvTerm, right: TypedBvTerm) -> TypedBvTerm:
    return TypedBvTerm(operation, 32, children=(left, right))


class Host:
    def __init__(self) -> None:
        self.storage = StrictJsonPersistence()
        self.requested_namespaces: list[str] = []

    def persistence(self, namespace: str):
        self.requested_namespaces.append(namespace)
        return self.storage


def test_cache_uses_host_persistence_instead_of_netnode() -> None:
    module = importlib.import_module("d810_egglog.idb_cache")
    tree = ast.parse(inspect.getsource(module))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert "d810.core.persistence" not in imported_modules
    assert "d810.mba.extension_api" in imported_modules


def test_cache_has_no_legacy_get_surface() -> None:
    from d810_egglog.idb_cache import EgglogIdbCompositeCache

    assert not hasattr(EgglogIdbCompositeCache, "get")


def test_live_cache_persists_json_rebinds_leaves_and_rejects_semantic_drift() -> None:
    from d810_egglog.composite_rewrite import ActiveSemantics, EgglogCompositeRewrite
    from d810_egglog.idb_cache import EgglogIdbCompositeCache

    semantics = ActiveSemantics(
        canonicalizer_version=1,
        catalogue_digest="a" * 64,
        profile_digest="b" * 64,
        egglog_version="13.2.0",
        proof_mode="shadow",
        active_rule_names=(("add", "R"),),
    )
    old_leaf = _leaf("historical")
    rewrite = EgglogCompositeRewrite.from_extraction(
        input_term=_binary("add", _binary("add", old_leaf, old_leaf), old_leaf),
        output_term=_binary(
            "mul",
            TypedBvTerm(None, 32, value=3),
            old_leaf,
        ),
        derivation_trace=(("add", "R", ()),),
        semantics=semantics,
    )

    host = Host()
    cache = EgglogIdbCompositeCache(host.persistence(EgglogIdbCompositeCache.NAMESPACE))
    assert host.requested_namespaces == [EgglogIdbCompositeCache.NAMESPACE]
    cache.store(rewrite)

    with pytest.raises(TypeError, match="JSON"):
        host.storage.put_json("native", {"cfunc": object()})
    with pytest.raises(TypeError, match="strings"):
        host.storage.put_json("native", {1: "not-json"})  # type: ignore[dict-item]

    entry = host.storage.get_json(f"entry:{rewrite.template_id}")
    assert entry is not None
    assert set(entry) == {
        "schema_version",
        "template_id",
        "canonicalizer_version",
        "catalogue_digest",
        "profile_digest",
        "egglog_version",
        "proof_mode",
        "width",
        "root_operation",
        "coarse_arity",
        "input_template",
        "output_template",
        "raw_input_cost",
        "output_cost",
        "derivation_trace",
        "egraph_run_count",
        "created_sequence",
        "last_used_sequence",
    }
    assert entry["template_id"] == rewrite.template_id
    assert entry["input_template"]["children"][0]["children"][0]["leaf_slot"] == 0
    assert entry["output_template"]["children"][1]["leaf_slot"] == 0
    assert "leaf_key" not in entry["input_template"]

    fresh_leaf = _leaf("fresh")
    fresh_term = _binary("add", _binary("add", fresh_leaf, fresh_leaf), fresh_leaf)
    loaded = cache.lookup(rewrite.bucket_key).rewrites
    assert len(loaded) == 1
    bindings = loaded[0].match(fresh_term, semantics=semantics)
    assert bindings == {0: fresh_leaf}
    replacement = loaded[0].materialize(bindings, semantics=semantics)
    assert replacement.children[1] is fresh_leaf

    drifted = (
        ActiveSemantics(
            canonicalizer_version=2,
            catalogue_digest=semantics.catalogue_digest,
            profile_digest=semantics.profile_digest,
            egglog_version=semantics.egglog_version,
            proof_mode=semantics.proof_mode,
            active_rule_names=semantics.active_rule_names,
        ),
        ActiveSemantics(
            canonicalizer_version=semantics.canonicalizer_version,
            catalogue_digest="c" * 64,
            profile_digest=semantics.profile_digest,
            egglog_version=semantics.egglog_version,
            proof_mode=semantics.proof_mode,
            active_rule_names=semantics.active_rule_names,
        ),
        ActiveSemantics(
            canonicalizer_version=semantics.canonicalizer_version,
            catalogue_digest=semantics.catalogue_digest,
            profile_digest=semantics.profile_digest,
            egglog_version="13.2.1",
            proof_mode=semantics.proof_mode,
            active_rule_names=semantics.active_rule_names,
        ),
        ActiveSemantics(
            canonicalizer_version=semantics.canonicalizer_version,
            catalogue_digest=semantics.catalogue_digest,
            profile_digest=semantics.profile_digest,
            egglog_version=semantics.egglog_version,
            proof_mode="legacy",
            active_rule_names=semantics.active_rule_names,
        ),
        ActiveSemantics(
            canonicalizer_version=semantics.canonicalizer_version,
            catalogue_digest=semantics.catalogue_digest,
            profile_digest=semantics.profile_digest,
            egglog_version=semantics.egglog_version,
            proof_mode=semantics.proof_mode,
            active_rule_names=(("add", "other"),),
        ),
    )
    for stale in drifted[:-1]:
        with pytest.raises(ValueError, match="stale"):
            loaded[0].match(fresh_term, semantics=stale)
    with pytest.raises(ValueError, match="absent from active semantics"):
        loaded[0].match(fresh_term, semantics=drifted[-1])
