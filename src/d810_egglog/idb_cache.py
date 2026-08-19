"""Bounded host persistence for accepted Egglog composite rewrites.

The cache receives a namespace-scoped persistence service from D810's native
host facade.  The portable rewrite record remains the source of truth for the
serialized template; this module owns only persistence, exact bucket
selection, and deterministic entry/byte bounds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from d810.mba.extension_api import EgraphPersistenceService

from .composite_rewrite import (
    CompositeRewriteMalformed,
    EgglogCompositeRewrite,
)


MANIFEST_KEY = "manifest"
ENTRY_PREFIX = "entry:"
_MANIFEST_FIELDS = frozenset({"schema_version", "sequence", "total_bytes", "entries"})
_ENTRY_METADATA_FIELDS = frozenset(
    {
        "template_id",
        "bucket_key",
        "byte_size",
        "created_sequence",
        "last_used_sequence",
    }
)
_BUCKET_LENGTH = 8
_LOOKUP_STATUSES = frozenset({"miss", "hit", "malformed"})


@dataclass(frozen=True)
class EgglogCompositeCacheLookup:
    """Validated result for one exact cache bucket lookup."""

    status: str
    rewrites: tuple[EgglogCompositeRewrite, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in _LOOKUP_STATUSES:
            raise ValueError("unknown composite cache lookup status")
        if type(self.rewrites) is not tuple or any(
            not isinstance(rewrite, EgglogCompositeRewrite) for rewrite in self.rewrites
        ):
            raise ValueError(
                "composite cache lookup rewrites must be a tuple of rewrites"
            )


def require_positive_int(value: object) -> int:
    """Return one strict positive integer, rejecting ``bool`` explicitly."""

    if type(value) is not int or value <= 0:
        raise ValueError("cache bounds must be a positive integer")
    return value


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _normalize_bucket_key(value: object) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("bucket_key must be a sequence")
    if len(value) != _BUCKET_LENGTH:
        raise ValueError("bucket_key has the wrong length")
    normalized: list[object] = []
    for item in value:
        if item is None:
            normalized.append(None)
        elif type(item) is str:
            normalized.append(item)
        elif type(item) is int:
            normalized.append(item)
        else:
            raise ValueError("bucket_key contains a non-JSON value")
    return tuple(normalized)


def _entry_key(template_id: str) -> str:
    return f"{ENTRY_PREFIX}{template_id}"


def _rewrite_byte_size(rewrite: EgglogCompositeRewrite) -> int:
    return len(rewrite.to_json().encode("utf-8"))


def _entry_sort_key(metadata: Mapping[str, object]) -> tuple[int, int, str]:
    return (
        int(metadata["last_used_sequence"]),
        int(metadata["created_sequence"]),
        str(metadata["template_id"]),
    )


def _thaw_json(value: object) -> object:
    """Convert host-owned immutable JSON snapshots into parser input."""

    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


class EgglogIdbCompositeCache:
    """Persist bounded, accepted-only composite templates through the host.

    Unit tests inject an :class:`EgraphPersistenceService` implementation so
    malformed-state and write-failure behavior can be exercised without IDA.
    Native callers obtain the service from
    ``NativeMbaHostServices.persistence(namespace)`` before constructing the
    cache.  The cache never owns or inspects the native storage implementation.
    """

    NAMESPACE = "egglog-composite-rewrites"
    SCHEMA_VERSION = 1

    def __init__(
        self,
        persistence: EgraphPersistenceService,
        *,
        max_entries: int = 256,
        max_bytes: int = 2_097_152,
    ) -> None:
        for method_name in ("get_json", "put_json", "delete", "keys"):
            if not callable(getattr(persistence, method_name, None)):
                raise TypeError("persistence must implement EgraphPersistenceService")
        self._store = persistence
        self._max_entries = require_positive_int(max_entries)
        self._max_bytes = require_positive_int(max_bytes)

    def get(self, bucket_key: Sequence[object]) -> tuple[EgglogCompositeRewrite, ...]:
        """Return records in one bucket, preserving the legacy API."""

        return self.lookup(bucket_key).rewrites

    def lookup(self, bucket_key: Sequence[object]) -> EgglogCompositeCacheLookup:
        """Return valid records in one exact semantic bucket.

        Corrupt or missing entry records are removed individually.  A valid
        lookup advances one cache sequence for every matching entry, making
        the LRU ordering deterministic.  The manifest metadata and serialized
        rewrite sequence fields advance together transactionally.  ``status``
        is ``miss`` or ``hit`` for clean state and ``malformed`` whenever the
        existing validation path observes corrupt manifest or entry state.
        """

        try:
            requested_bucket = _normalize_bucket_key(bucket_key)
        except ValueError:
            return EgglogCompositeCacheLookup("malformed", ())

        state, malformed = self._load_manifest_with_status()
        entries: list[dict[str, object]] = list(state["entries"])
        matched: list[EgglogCompositeRewrite] = []
        matched_by_id: dict[str, tuple[dict[str, object], EgglogCompositeRewrite]] = {}
        removed_ids: list[str] = []

        for metadata in entries:
            if tuple(metadata["bucket_key"]) != requested_bucket:
                continue
            template_id = str(metadata["template_id"])
            rewrite = self._decode_entry(template_id)
            if rewrite is None:
                removed_ids.append(template_id)
                malformed = True
                continue
            try:
                encoded_size = len(rewrite.to_json().encode("utf-8"))
                valid = (
                    rewrite.template_id == template_id
                    and rewrite.bucket_key == requested_bucket
                    and encoded_size == metadata["byte_size"]
                    and rewrite.created_sequence == metadata["created_sequence"]
                    and rewrite.last_used_sequence == metadata["last_used_sequence"]
                )
            except (CompositeRewriteMalformed, TypeError, ValueError):
                valid = False
            if not valid:
                removed_ids.append(template_id)
                malformed = True
                continue
            matched.append(rewrite)
            matched_by_id[template_id] = (metadata, rewrite)

        if not matched and not removed_ids:
            return EgglogCompositeCacheLookup(
                "malformed" if malformed else "miss", tuple(matched)
            )

        removed_id_set = set(removed_ids)
        entries = [
            metadata
            for metadata in entries
            if str(metadata["template_id"]) not in removed_id_set
        ]
        state["total_bytes"] = sum(int(metadata["byte_size"]) for metadata in entries)
        updated_payloads: dict[str, object] = {}
        updated_rewrites: dict[str, EgglogCompositeRewrite] = {}
        if matched:
            sequence = int(state["sequence"]) + 1
            state["sequence"] = sequence
            for template_id, (metadata, rewrite) in matched_by_id.items():
                updated = rewrite.with_sequences(last_used_sequence=sequence)
                metadata["last_used_sequence"] = sequence
                metadata["byte_size"] = _rewrite_byte_size(updated)
                updated_payloads[template_id] = updated.to_dict()
                updated_rewrites[template_id] = updated
            state["total_bytes"] = sum(
                int(metadata["byte_size"]) for metadata in entries
            )

        while (
            len(entries) > self._max_entries
            or int(state["total_bytes"]) > self._max_bytes
        ):
            victim = min(entries, key=_entry_sort_key)
            entries.remove(victim)
            state["total_bytes"] = int(state["total_bytes"]) - int(victim["byte_size"])
            victim_id = str(victim["template_id"])
            removed_ids.append(victim_id)
            updated_payloads.pop(victim_id, None)
            updated_rewrites.pop(victim_id, None)

        state["entries"] = sorted(entries, key=_entry_sort_key)
        try:
            self._commit_manifest(
                state,
                payloads=updated_payloads,
                removed_ids=tuple(dict.fromkeys(removed_ids)),
            )
        except RuntimeError:
            # A cache maintenance write must never turn a valid replay into a
            # failure.  The commit helper restores its pre-write snapshot.
            return EgglogCompositeCacheLookup(
                "malformed" if malformed else "hit", tuple(matched)
            )
        return EgglogCompositeCacheLookup(
            "malformed" if malformed else "hit",
            tuple(
                updated_rewrites[str(metadata["template_id"])]
                for metadata in state["entries"]
                if str(metadata["template_id"]) in updated_rewrites
            ),
        )

    def store(self, rewrite: EgglogCompositeRewrite) -> None:
        """Store one accepted rewrite, evicting deterministic LRU victims."""

        if not isinstance(rewrite, EgglogCompositeRewrite):
            raise TypeError("rewrite must be an EgglogCompositeRewrite")

        state = self._load_manifest()
        previous_entries = list(state["entries"])
        sequence = int(state["sequence"]) + 1
        entries: list[dict[str, object]] = [
            dict(metadata)
            for metadata in state["entries"]
            if metadata["template_id"] != rewrite.template_id
        ]
        previous = next(
            (
                metadata
                for metadata in state["entries"]
                if metadata["template_id"] == rewrite.template_id
            ),
            None,
        )
        created_sequence = (
            int(previous["created_sequence"]) if previous is not None else sequence
        )
        stored_rewrite = rewrite.with_sequences(
            created_sequence=created_sequence,
            last_used_sequence=sequence,
        )
        encoded_size = _rewrite_byte_size(stored_rewrite)
        if encoded_size > self._max_bytes:
            return
        entries.append(
            {
                "template_id": rewrite.template_id,
                "bucket_key": list(rewrite.bucket_key),
                "byte_size": encoded_size,
                "created_sequence": created_sequence,
                "last_used_sequence": sequence,
            }
        )

        total_bytes = sum(int(metadata["byte_size"]) for metadata in entries)
        while len(entries) > self._max_entries or total_bytes > self._max_bytes:
            victim = min(entries, key=_entry_sort_key)
            entries.remove(victim)
            total_bytes -= int(victim["byte_size"])

        state = {
            "schema_version": self.SCHEMA_VERSION,
            "sequence": sequence,
            "total_bytes": total_bytes,
            "entries": sorted(entries, key=_entry_sort_key),
        }
        keep_ids = {str(metadata["template_id"]) for metadata in entries}
        removed_ids = [
            str(metadata["template_id"])
            for metadata in previous_entries
            if str(metadata["template_id"]) not in keep_ids
        ]
        removed_id_set = set(removed_ids)
        for key in self._feature_keys():
            if key.startswith(ENTRY_PREFIX):
                template_id = key[len(ENTRY_PREFIX) :]
                if template_id not in keep_ids and template_id not in removed_id_set:
                    removed_ids.append(template_id)
                    removed_id_set.add(template_id)
        payloads = (
            {stored_rewrite.template_id: stored_rewrite.to_dict()}
            if stored_rewrite.template_id in keep_ids
            else {}
        )
        self._commit_manifest(
            state,
            payloads=payloads,
            removed_ids=removed_ids,
        )

    def _decode_entry(self, template_id: str) -> EgglogCompositeRewrite | None:
        try:
            payload = self._store.get_json(_entry_key(template_id))
        except Exception:
            return None
        if payload is None:
            return None
        try:
            return EgglogCompositeRewrite.from_dict(_thaw_json(payload))
        except (CompositeRewriteMalformed, TypeError, ValueError, KeyError):
            return None

    def _load_manifest(self) -> dict[str, object]:
        return self._load_manifest_with_status()[0]

    def _load_manifest_with_status(self) -> tuple[dict[str, object], bool]:
        try:
            payload = self._store.get_json(MANIFEST_KEY)
        except Exception:
            self._clear_feature_state()
            return self._empty_manifest(), True
        if payload is None:
            return self._empty_manifest(), False

        try:
            return self._validate_manifest(_thaw_json(payload)), False
        except (TypeError, ValueError, KeyError):
            self._clear_feature_state()
            return self._empty_manifest(), True

    def _empty_manifest(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "sequence": 0,
            "total_bytes": 0,
            "entries": [],
        }

    def _validate_manifest(self, payload: object) -> dict[str, object]:
        if type(payload) is not dict or set(payload) != _MANIFEST_FIELDS:
            raise ValueError("invalid composite cache manifest")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != self.SCHEMA_VERSION
        ):
            raise ValueError("unknown composite cache schema")
        sequence = _require_nonnegative_int(payload["sequence"], "sequence")
        total_bytes = _require_nonnegative_int(payload["total_bytes"], "total_bytes")
        raw_entries = payload["entries"]
        if type(raw_entries) is not list:
            raise ValueError("manifest entries must be a list")
        if len(raw_entries) > self._max_entries:
            raise ValueError("manifest exceeds configured entry bound")
        if total_bytes > self._max_bytes:
            raise ValueError("manifest exceeds configured byte bound")

        entries: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for raw_metadata in raw_entries:
            metadata = self._validate_metadata(raw_metadata)
            if int(metadata["byte_size"]) > self._max_bytes:
                raise ValueError("entry exceeds configured byte bound")
            template_id = str(metadata["template_id"])
            if template_id in seen_ids:
                raise ValueError("manifest contains duplicate template IDs")
            seen_ids.add(template_id)
            entries.append(metadata)
        if total_bytes != sum(int(metadata["byte_size"]) for metadata in entries):
            raise ValueError("manifest byte total does not match entries")
        if any(int(metadata["last_used_sequence"]) > sequence for metadata in entries):
            raise ValueError("manifest sequence precedes an entry")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "sequence": sequence,
            "total_bytes": total_bytes,
            "entries": sorted(entries, key=_entry_sort_key),
        }

    def _validate_metadata(self, payload: object) -> dict[str, object]:
        if type(payload) is not dict or set(payload) != _ENTRY_METADATA_FIELDS:
            raise ValueError("invalid composite cache entry metadata")
        template_id = payload["template_id"]
        if type(template_id) is not str or not template_id:
            raise ValueError("entry template_id must be a non-empty string")
        bucket_key = _normalize_bucket_key(payload["bucket_key"])
        byte_size = _require_nonnegative_int(payload["byte_size"], "byte_size")
        if byte_size <= 0:
            raise ValueError("byte_size must be positive")
        created_sequence = _require_nonnegative_int(
            payload["created_sequence"], "created_sequence"
        )
        last_used_sequence = _require_nonnegative_int(
            payload["last_used_sequence"], "last_used_sequence"
        )
        if last_used_sequence < created_sequence:
            raise ValueError("last_used_sequence precedes created_sequence")
        return {
            "template_id": template_id,
            "bucket_key": list(bucket_key),
            "byte_size": byte_size,
            "created_sequence": created_sequence,
            "last_used_sequence": last_used_sequence,
        }

    def _commit_manifest(
        self,
        manifest: Mapping[str, object],
        *,
        payloads: Mapping[str, object] | None = None,
        removed_ids: Sequence[str] = (),
    ) -> None:
        snapshot = self._snapshot_feature_state()
        try:
            for template_id, payload in (payloads or {}).items():
                if not isinstance(payload, Mapping):
                    raise TypeError("cache entry payload must be a mapping")
                self._store.put_json(_entry_key(template_id), payload)
            for template_id in removed_ids:
                self._store.delete(_entry_key(str(template_id)))
            self._store.put_json(MANIFEST_KEY, manifest)
        except Exception as exc:
            self._restore_feature_state(snapshot)
            raise RuntimeError(f"cache write failed: {exc}") from exc

    def _snapshot_feature_state(self) -> dict[str, object]:
        snapshot: dict[str, object] = {}
        for key in self._feature_keys():
            try:
                payload = self._store.get_json(key)
                if payload is not None:
                    snapshot[key] = _thaw_json(payload)
            except Exception:
                continue
        return snapshot

    def _restore_feature_state(self, snapshot: Mapping[str, object]) -> None:
        for key in self._feature_keys():
            if key not in snapshot:
                try:
                    self._store.delete(key)
                except Exception:
                    pass
        for key, value in snapshot.items():
            try:
                if isinstance(value, Mapping):
                    self._store.put_json(key, value)
            except Exception:
                pass

    def _feature_keys(self) -> list[str]:
        # The manifest is part of this feature's state even when reading it
        # fails.  Cleanup must still attempt an idempotent delete rather than
        # retrying the failing read and leaving the manifest behind.
        feature_keys: set[str] = {MANIFEST_KEY}
        try:
            keys = self._store.keys(prefix=ENTRY_PREFIX)
        except Exception:
            keys = ()
        try:
            feature_keys.update(str(key) for key in keys)
        except Exception:
            pass
        return sorted(feature_keys)

    def _clear_feature_state(self) -> None:
        for key in self._feature_keys():
            try:
                self._store.delete(key)
            except Exception:
                pass


__all__ = [
    "EgglogCompositeCacheLookup",
    "EgglogIdbCompositeCache",
    "MANIFEST_KEY",
    "ENTRY_PREFIX",
    "require_positive_int",
]
