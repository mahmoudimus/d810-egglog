from __future__ import annotations

import ast
from copy import deepcopy
import importlib
import inspect

import pytest

from d810.mba.extension_api import TypedBvTerm


class MemoryPersistence(dict[str, object]):
    def get_json(self, key: str):
        value = self.get(key)
        return deepcopy(value) if isinstance(value, dict) else None

    def put_json(self, key: str, value):
        self[key] = deepcopy(dict(value))

    def delete(self, key: str) -> None:
        self.pop(key, None)

    def keys(self, *, prefix: str = ""):
        return tuple(sorted(key for key in super().keys() if key.startswith(prefix)))


def _leaf(name: str) -> TypedBvTerm:
    return TypedBvTerm(None, 32, leaf_key=("register", name))


def _binary(operation: str, left: TypedBvTerm, right: TypedBvTerm) -> TypedBvTerm:
    return TypedBvTerm(operation, 32, children=(left, right))


class Host:
    def __init__(self) -> None:
        self.storage = MemoryPersistence()
        self.proof_verdict = False
        self.proof_calls = []
        self.mutations = []

    def persistence(self, namespace: str):
        assert namespace == "live-cache-safety"
        return self.storage

    def rebuild(self, candidate: object, replacement: TypedBvTerm):
        return (candidate, replacement)

    def prove(
        self,
        candidate: object,
        reconstruction: object,
        *,
        certificate: str | None,
        known_constants: object | None,
    ) -> bool:
        self.proof_calls.append((candidate, reconstruction))
        return self.proof_verdict


def test_cache_uses_host_persistence_instead_of_netnode() -> None:
    module = importlib.import_module("d810_egglog.idb_cache")
    tree = ast.parse(inspect.getsource(module))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert "d810.core.persistence" not in imported_modules
    assert "d810.mba.extension_api" in imported_modules


def test_live_cache_rebinds_and_proof_gates_native_mutation() -> None:
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
    cache = EgglogIdbCompositeCache(host.persistence("live-cache-safety"))
    cache.store(rewrite)
    persisted = repr(host.storage)
    assert "historical" not in persisted
    assert "mop" not in persisted
    assert "cfunc" not in persisted
    assert "source_ast" not in persisted

    fresh_leaf = _leaf("fresh")
    fresh_term = _binary("add", _binary("add", fresh_leaf, fresh_leaf), fresh_leaf)
    loaded = cache.get(rewrite.bucket_key)
    assert len(loaded) == 1
    bindings = loaded[0].match(fresh_term, semantics=semantics)
    assert bindings == {0: fresh_leaf}
    replacement = loaded[0].materialize(bindings, semantics=semantics)
    assert replacement.children[1] is fresh_leaf

    drifted = ActiveSemantics(
        canonicalizer_version=2,
        catalogue_digest=semantics.catalogue_digest,
        profile_digest=semantics.profile_digest,
        egglog_version=semantics.egglog_version,
        proof_mode=semantics.proof_mode,
        active_rule_names=semantics.active_rule_names,
    )
    with pytest.raises(ValueError, match="stale"):
        loaded[0].match(fresh_term, semantics=drifted)

    reconstruction = host.rebuild(object(), replacement)
    assert reconstruction is not None
    assert (
        host.prove(object(), reconstruction, certificate=None, known_constants=None)
        is False
    )
    assert host.proof_calls
    assert host.mutations == []

    host.proof_verdict = True
    candidate = object()
    reconstruction = host.rebuild(candidate, replacement)
    assert reconstruction is not None
    if host.prove(candidate, reconstruction, certificate=None, known_constants=None):
        host.mutations.append(replacement)
    assert host.mutations == [replacement]
