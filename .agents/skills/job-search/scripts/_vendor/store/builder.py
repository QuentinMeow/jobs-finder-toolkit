"""Materialization machinery — the ledger-ordered deterministic fold.

The store-core determinism contract requires that derived state be a pure function
of the *processed set*, with incremental and full builds sharing one code path.
This module provides that machinery generically; the real posting builder (Stage 2)
supplies the ``key_fn`` (manifest → entity key) and ``reduce_fn`` (an entity's
manifests, in canonical order → entity state).

Determinism comes from two pins:

- manifests are grouped by entity key and each group is sorted **canonically**
  (by ``fetched_at`` then ``fetch_id``) before reduction, so the result never
  depends on filesystem walk order;
- ``reduce_fn`` sees the entity's full manifest history, so recomputing only the
  entities a delta touched (incremental) yields byte-identical state to recomputing
  everything (full rebuild). Equivalence is therefore structural, not hoped-for.
"""
from __future__ import annotations

from typing import Callable

# reduce_fn(entity_key, sorted_manifests) -> entity_state (any serializable value)
ReduceFn = Callable[[str, list[dict]], object]
# key_fn(manifest) -> entity_key or None (None = this manifest materializes nothing)
KeyFn = Callable[[dict], "str | None"]


def _manifest_sort_key(env: dict) -> tuple:
    return (env.get("fetched_at", ""), env.get("fetch_id", ""))


def group_by_entity(manifests: list[dict], key_fn: KeyFn) -> dict[str, list[dict]]:
    """Group manifests by entity key, each group sorted canonically."""
    groups: dict[str, list[dict]] = {}
    for env in manifests:
        key = key_fn(env)
        if key is None:
            continue
        groups.setdefault(key, []).append(env)
    for key in groups:
        groups[key].sort(key=_manifest_sort_key)
    return groups


def materialize_full(manifests: list[dict], key_fn: KeyFn,
                     reduce_fn: ReduceFn) -> dict[str, object]:
    """Materialize every entity from the full manifest set (a pure set-function)."""
    groups = group_by_entity(manifests, key_fn)
    return {key: reduce_fn(key, group) for key, group in groups.items()}


def affected_keys(pending: list[dict], key_fn: KeyFn) -> set[str]:
    """Entity keys touched by the pending (set-difference) manifests."""
    keys: set[str] = set()
    for env in pending:
        key = key_fn(env)
        if key is not None:
            keys.add(key)
    return keys


def materialize_incremental(all_manifests: list[dict], prior_state: dict[str, object],
                            pending: list[dict], key_fn: KeyFn,
                            reduce_fn: ReduceFn) -> dict[str, object]:
    """Recompute only the entities a delta touched, from their *full* histories.

    Returns state byte-identical to :func:`materialize_full` over ``all_manifests``
    — that equivalence is the CI-tested property. ``prior_state`` is carried for
    untouched entities; touched entities are re-reduced over all their manifests
    (so out-of-order/late-committed manifests reorder correctly).
    """
    state = dict(prior_state)
    touched = affected_keys(pending, key_fn)
    if not touched:
        return state
    groups = group_by_entity(all_manifests, key_fn)
    for key in touched:
        group = groups.get(key)
        if group:
            state[key] = reduce_fn(key, group)
        else:
            state.pop(key, None)
    return state
