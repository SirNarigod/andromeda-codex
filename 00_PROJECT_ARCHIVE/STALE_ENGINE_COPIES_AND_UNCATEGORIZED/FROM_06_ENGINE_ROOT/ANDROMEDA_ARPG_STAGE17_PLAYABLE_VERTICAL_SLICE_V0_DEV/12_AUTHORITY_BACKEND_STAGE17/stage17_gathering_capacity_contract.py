"""Stage17 / Etapa 31 -- S17-C3R4A versioned mutable-capacity gathering contract.

Additive, Stage17-only module. Never edits any 01_RUNTIME file on disk.
Installs a single, narrowly-scoped monkeypatch of
``ARPGGatheringWorkCore._insert_node`` (imported live from the protected
``01_RUNTIME/arpg_gathering_work_core.py`` module -- never copied) that
relaxes the bootstrap drift guard in exactly one case:

    the ONLY field that differs between a freshly recomputed node
    definition and its already-persisted definition is ``capacity_units``,
    AND the node's ``renewability`` label is ``LIVING_ECOLOGY_STAGE14``
    (the protected core's own semantic marker for FLORA/FAUNA/FISHING
    sources -- i.e. populations/stocks that legitimately fluctuate through
    ordinary gameplay, as opposed to MINERAL's
    ``NON_RENEWABLE_WITHIN_STAGE09``).

Any other difference -- in ``source_ref``, ``activity_type``,
``output_item_ref``, ``zone_ref``, ``block_ref``, ``world_instance_id``,
``authority``, ``art_dependency``, ``source_meta.*``, or any other field,
for ANY source_kind including FAUNA/FLORA/FISHING -- still raises
``IntegrityError`` exactly as the protected core does today. MINERAL
sources never qualify for the relaxed path regardless of which field
differs, because their ``renewability`` is never
``LIVING_ECOLOGY_STAGE14``.

Root cause (see STAGE17_RECORDS/S17_C3R2_*, S17_C3R3_*): the protected
core's own data model already separates a stable maximum
(``capacity_units``) from a live current quantity (``remaining_units``)
for MINERAL and FLORA. It has no such split for FAUNA -- ``count`` plays
both roles -- so a node bootstrapped once with a given population size
permanently disagrees with itself the moment that population is hunted.
This module does not change that data model (forbidden -- would require
editing 01_RUNTIME/country_scale.py); it changes only how the *bootstrap
guard* reacts when the sole disagreement is that already-known-mutable
field.

Contract name : S17_GATHERING_NODE_DEFINITION_SCHEMA_V2
Legacy label  : V1_LEGACY_UNVERSIONED (implicit; never formally named
                before S17-C3R3/S17-C3R4)

This module never constructs an engine, never opens a database connection
of its own, and never touches ``country_scale_state``. It only ever adds
a conditional branch to a single already-existing write path
(``arpg_gathering_nodes`` UPDATE) that the protected core itself already
performs unconditionally on first INSERT.
"""
from __future__ import annotations

import json
from typing import Any

CONTRACT_SCHEMA_V2 = "S17_GATHERING_NODE_DEFINITION_SCHEMA_V2"
CONTRACT_SCHEMA_V1_LEGACY = "V1_LEGACY_UNVERSIONED"
MUTABLE_RENEWABILITY_LABEL = "LIVING_ECOLOGY_STAGE14"
ALLOWED_MUTABLE_FIELDS = frozenset({"capacity_units"})

#: In-process audit trail of every reconciliation the installed patch has
#: performed since import. Purely additive/observational -- never read by
#: the patch itself, never required for correctness. Tests and callers may
#: inspect/clear it.
RECONCILIATION_LOG: list[dict[str, Any]] = []

_INSTALLED: dict[str, Any] = {"target_cls": None, "original_insert_node": None}


def classify_definition_diff(persisted: dict[str, Any], expected: dict[str, Any]) -> tuple[str, list[str]]:
    """Pure function. No DB, no engine, no I/O of any kind.

    Compares two already-materialized node-definition dicts field by field
    and returns ``(verdict, sorted_diff_field_names)`` where verdict is one
    of:

      * ``MATCH``                          -- no field differs.
      * ``ALLOWED_MUTABLE_CAPACITY_DRIFT``  -- the only differing field is
        ``capacity_units`` AND ``expected["renewability"]`` is
        ``LIVING_ECOLOGY_STAGE14``.
      * ``STRUCTURAL_DRIFT``                -- anything else.

    A field present in only one of the two dicts counts as differing (its
    absent-side value is treated as missing, never silently defaulted),
    so schema-shape changes are always structural, never accidentally
    swallowed by the allow-list.
    """
    fields = sorted(set(persisted.keys()) | set(expected.keys()))
    diff = [f for f in fields if persisted.get(f) != expected.get(f)]
    if not diff:
        return "MATCH", []
    if set(diff) == ALLOWED_MUTABLE_FIELDS and _is_mutable_capacity_eligible(expected):
        return "ALLOWED_MUTABLE_CAPACITY_DRIFT", diff
    return "STRUCTURAL_DRIFT", diff


def _is_mutable_capacity_eligible(expected: dict[str, Any]) -> bool:
    """Semantic gate -- keyed on the core's own renewability label, not on
    an arbitrary source_kind allow-list. MINERAL (NON_RENEWABLE_WITHIN_
    STAGE09) never qualifies. FLORA/FISHING share the same label as FAUNA
    and are therefore eligible in principle, but the protected core's own
    data model (see module docstring) makes a capacity_units-only diff
    structurally impossible for them today -- confirmed by full-world scan
    (S17-C3R3: 0/56 FLORA, 0/3 FISHING drifted). Nothing here special-cases
    FAUNA by name.
    """
    return str(expected.get("renewability")) == MUTABLE_RENEWABILITY_LABEL


def install(gathering_core_cls: type) -> type:
    """Monkeypatch ``gathering_core_cls._insert_node`` with the V2-aware version.

    Idempotent: calling install() again with the same class is a no-op
    (the first captured original is kept, so repeated installs never chain
    wrappers). Returns the class unchanged (for call-site chaining/clarity).
    Never touches the class's source file on disk.
    """
    if _INSTALLED["target_cls"] is gathering_core_cls:
        return gathering_core_cls

    original = gathering_core_cls._insert_node

    def _insert_node_v2(self: Any, d: dict[str, Any], *, state_remaining: int | None = None) -> None:
        text, h = self._payload(d)
        with self.runtime._write_lock:
            row = self.runtime.conn.execute(
                "SELECT definition_json, definition_hash FROM arpg_gathering_nodes "
                "WHERE world_instance_id=? AND node_ref=?",
                (self.world_instance_id, d["node_ref"]),
            ).fetchone()
            if row is None:
                return original(self, d, state_remaining=state_remaining)
            if row["definition_hash"] == h:
                return
            persisted = json.loads(row["definition_json"])
            verdict, diff_fields = classify_definition_diff(persisted, d)
            if verdict != "ALLOWED_MUTABLE_CAPACITY_DRIFT":
                # Import lazily so this module never needs 01_RUNTIME on
                # sys.path just to be imported/tested for its pure helpers.
                from living_runtime import IntegrityError  # noqa: PLC0415

                raise IntegrityError("gathering node drift:" + d["node_ref"])
            self.runtime.conn.execute(
                "UPDATE arpg_gathering_nodes SET definition_json=?, definition_hash=? "
                "WHERE world_instance_id=? AND node_ref=?",
                (text, h, self.world_instance_id, d["node_ref"]),
            )
            RECONCILIATION_LOG.append(
                {
                    "node_ref": d["node_ref"],
                    "world_instance_id": self.world_instance_id,
                    "diff_fields": diff_fields,
                    "persisted_capacity_units": persisted.get("capacity_units"),
                    "reconciled_capacity_units": d.get("capacity_units"),
                    "contract": CONTRACT_SCHEMA_V2,
                }
            )
            return None

    gathering_core_cls._insert_node = _insert_node_v2
    _INSTALLED["target_cls"] = gathering_core_cls
    _INSTALLED["original_insert_node"] = original
    return gathering_core_cls


def uninstall() -> None:
    """Restore the original ``_insert_node``. Test-teardown / safety valve only."""
    cls = _INSTALLED["target_cls"]
    original = _INSTALLED["original_insert_node"]
    if cls is not None and original is not None:
        cls._insert_node = original
    _INSTALLED["target_cls"] = None
    _INSTALLED["original_insert_node"] = None


def is_installed(gathering_core_cls: type | None = None) -> bool:
    if gathering_core_cls is None:
        return _INSTALLED["target_cls"] is not None
    return _INSTALLED["target_cls"] is gathering_core_cls


def install_on_import_path(runtime_dir: str) -> type:
    """Convenience for callers (migration tool, tests, R4B resume script)
    that have not yet imported the protected module. Adds ``runtime_dir``
    to ``sys.path`` if needed, imports ``ARPGGatheringWorkCore`` live, and
    installs the patch on it. Never writes to ``runtime_dir``.
    """
    import sys

    if runtime_dir not in sys.path:
        sys.path.insert(0, runtime_dir)
    from arpg_gathering_work_core import ARPGGatheringWorkCore  # noqa: PLC0415

    return install(ARPGGatheringWorkCore)
