"""Stage17 resource metric-placement authority.

This additive Stage17 service materializes an offline-baked, canonical content
manifest into the isolated runtime SQLite world.  It owns only physical
placement identity and metric position.  Logical gathering/depletion remains in
the protected ``GTH-*`` cores.

Runtime clients can name a ``placement_ref`` but can never create, move or
override one.  Authoring transforms and blocker shapes enter only through the
offline bake; the rows in this registry are the runtime authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "S17_RESOURCE_METRIC_PLACEMENT_V1"
PLACEMENT_AUTHORITY = "STAGE17_RESOURCE_METRIC_PLACEMENT_AUTHORITY"
POSITION_AUTHORITY = "STAGE17_RESOURCE_METRIC_PLACEMENT_MATERIALIZED"
PLACEMENT_REF_PREFIX = "RESOURCE-PLACEMENT-S17-"
GATHER_RANGE_M = 1.5


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_manifest_hash(manifest: dict[str, Any]) -> str:
    return sha256_text(canonical_json(manifest))


def stable_placement_ref(
    world_instance_id: str,
    logical_node_ref: str,
    authoring_object_ref: str,
    placement_revision: str,
    ordinal: int,
) -> str:
    identity = "|".join(
        (
            world_instance_id,
            logical_node_ref,
            authoring_object_ref,
            placement_revision,
            str(int(ordinal)),
        )
    )
    return PLACEMENT_REF_PREFIX + sha256_text(identity)[:20].upper()


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


class ResourcePlacementError(ValueError):
    """A canonical manifest or materialization violated its contract."""


class ResourceMetricPlacementRegistry:
    """Persisted world-scoped placement and LOS-constraint registry."""

    def __init__(self, runtime: Any, world_instance_id: str) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.last_materialization: dict[str, Any] = {
            "status": "NOT_CONFIGURED",
            "authority": PLACEMENT_AUTHORITY,
        }
        self._schema()

    def _schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS s17_resource_placement_manifests(
                    world_instance_id TEXT NOT NULL,
                    placement_revision TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    canonical_manifest_hash TEXT NOT NULL,
                    canonical_manifest_json TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, placement_revision)
                );
                CREATE TABLE IF NOT EXISTS s17_resource_metric_placements(
                    placement_ref TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    logical_node_ref TEXT NOT NULL,
                    zone_ref TEXT NOT NULL,
                    block_ref TEXT NOT NULL,
                    resource_kind TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    iso_x_m REAL NOT NULL,
                    iso_y_m REAL NOT NULL,
                    altitude_m REAL NOT NULL,
                    placement_mode TEXT NOT NULL,
                    placement_revision TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    source_manifest_hash TEXT NOT NULL,
                    position_authority TEXT NOT NULL,
                    authoring_object_ref TEXT NOT NULL,
                    authoring_node_path TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)),
                    payload_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_s17_resource_placement_world
                    ON s17_resource_metric_placements(world_instance_id,active);
                CREATE INDEX IF NOT EXISTS idx_s17_resource_placement_zone_block
                    ON s17_resource_metric_placements(world_instance_id,zone_ref,block_ref,active);
                CREATE INDEX IF NOT EXISTS idx_s17_resource_placement_logical
                    ON s17_resource_metric_placements(world_instance_id,logical_node_ref,active);
                CREATE TABLE IF NOT EXISTS s17_resource_metric_constraints(
                    constraint_ref TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    zone_ref TEXT NOT NULL,
                    block_ref TEXT NOT NULL,
                    constraint_kind TEXT NOT NULL,
                    min_iso_x_m REAL NOT NULL,
                    max_iso_x_m REAL NOT NULL,
                    min_iso_y_m REAL NOT NULL,
                    max_iso_y_m REAL NOT NULL,
                    min_altitude_m REAL NOT NULL,
                    max_altitude_m REAL NOT NULL,
                    blocks_los INTEGER NOT NULL CHECK(blocks_los IN (0,1)),
                    placement_revision TEXT NOT NULL,
                    source_manifest_hash TEXT NOT NULL,
                    authoring_node_path TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)),
                    payload_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_s17_resource_constraint_scope
                    ON s17_resource_metric_constraints(world_instance_id,zone_ref,block_ref,active);
                """
            )

    @staticmethod
    def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
        if not path.is_file():
            raise ResourcePlacementError(f"PLACEMENT_MANIFEST_NOT_FOUND:{path}")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResourcePlacementError(f"PLACEMENT_MANIFEST_INVALID_JSON:{exc}") from exc
        if not isinstance(envelope, dict) or not isinstance(
            envelope.get("canonical_manifest"), dict
        ):
            raise ResourcePlacementError("CANONICAL_MANIFEST_ENVELOPE_REQUIRED")
        manifest = dict(envelope["canonical_manifest"])
        actual = canonical_manifest_hash(manifest)
        expected = str(envelope.get("canonical_manifest_hash", "")).strip().lower()
        if actual != expected:
            raise ResourcePlacementError(
                f"CANONICAL_MANIFEST_HASH_MISMATCH:{expected}:{actual}"
            )
        return manifest, actual

    def validate_manifest(self, manifest: dict[str, Any], manifest_hash: str) -> None:
        if str(manifest.get("schema_version")) != SCHEMA_VERSION:
            raise ResourcePlacementError("UNSUPPORTED_RESOURCE_PLACEMENT_SCHEMA")
        revision = str(manifest.get("placement_revision", "")).strip()
        if not revision:
            raise ResourcePlacementError("PLACEMENT_REVISION_REQUIRED")
        world = manifest.get("world_binding")
        if not isinstance(world, dict):
            raise ResourcePlacementError("WORLD_BINDING_REQUIRED")
        if str(world.get("world_instance_id", "")) != self.world_instance_id:
            raise ResourcePlacementError("RESOURCE_PLACEMENT_WORLD_MISMATCH")
        if canonical_manifest_hash(manifest) != manifest_hash:
            raise ResourcePlacementError("CANONICAL_MANIFEST_HASH_INVALID")
        placements = manifest.get("placements")
        constraints = manifest.get("constraints")
        if not isinstance(placements, list) or not placements:
            raise ResourcePlacementError("RESOURCE_PLACEMENTS_REQUIRED")
        if not isinstance(constraints, list):
            raise ResourcePlacementError("RESOURCE_CONSTRAINT_LIST_REQUIRED")
        refs: set[str] = set()
        for entry in placements:
            self._validate_placement(entry, revision, manifest_hash)
            ref = str(entry["placement_ref"])
            if ref in refs:
                raise ResourcePlacementError("DUPLICATE_RESOURCE_PLACEMENT_REF")
            refs.add(ref)
        constraint_refs: set[str] = set()
        for entry in constraints:
            self._validate_constraint(entry, revision)
            ref = str(entry["constraint_ref"])
            if ref in constraint_refs:
                raise ResourcePlacementError("DUPLICATE_RESOURCE_CONSTRAINT_REF")
            constraint_refs.add(ref)

    def _validate_placement(
        self, entry: Any, revision: str, manifest_hash: str
    ) -> None:
        if not isinstance(entry, dict):
            raise ResourcePlacementError("INVALID_RESOURCE_PLACEMENT_ENTRY")
        required = (
            "placement_ref", "logical_node_ref", "world_instance_id", "zone_ref",
            "block_ref", "resource_kind", "source_kind", "source_ref", "position",
            "placement_mode", "placement_revision", "schema_version",
            "authoring_source", "ordinal", "active",
        )
        if any(key not in entry for key in required):
            raise ResourcePlacementError("RESOURCE_PLACEMENT_REQUIRED_FIELD_MISSING")
        if str(entry["world_instance_id"]) != self.world_instance_id:
            raise ResourcePlacementError("RESOURCE_PLACEMENT_WORLD_MISMATCH")
        if str(entry["placement_revision"]) != revision:
            raise ResourcePlacementError("RESOURCE_PLACEMENT_REVISION_MISMATCH")
        if str(entry["schema_version"]) != SCHEMA_VERSION:
            raise ResourcePlacementError("RESOURCE_PLACEMENT_SCHEMA_MISMATCH")
        if str(entry.get("position_authority", "")) != POSITION_AUTHORITY:
            raise ResourcePlacementError("RESOURCE_POSITION_AUTHORITY_MISMATCH")
        if str(entry["placement_mode"]) not in {"EXPLICIT", "GENERATED"}:
            raise ResourcePlacementError("INVALID_RESOURCE_PLACEMENT_MODE")
        if not str(entry["placement_ref"]).startswith(PLACEMENT_REF_PREFIX):
            raise ResourcePlacementError("INVALID_RESOURCE_PLACEMENT_REF_PREFIX")
        if not str(entry["logical_node_ref"]).startswith("GTH-"):
            raise ResourcePlacementError("INVALID_LOGICAL_GATHERING_NODE_REF")
        position = entry["position"]
        if not isinstance(position, dict) or any(
            not _finite(position.get(key))
            for key in ("iso_x_m", "iso_y_m", "altitude_m")
        ):
            raise ResourcePlacementError("INVALID_RESOURCE_PLACEMENT_POSITION")
        if not isinstance(entry["active"], bool):
            raise ResourcePlacementError("RESOURCE_PLACEMENT_ACTIVE_BOOL_REQUIRED")
        authoring = entry["authoring_source"]
        if not isinstance(authoring, dict) or not str(
            authoring.get("object_ref", "")
        ).strip() or not str(authoring.get("node_path", "")).strip():
            raise ResourcePlacementError("RESOURCE_AUTHORING_SOURCE_REQUIRED")
        expected_ref = stable_placement_ref(
            self.world_instance_id,
            str(entry["logical_node_ref"]),
            str(authoring["object_ref"]),
            revision,
            int(entry["ordinal"]),
        )
        if str(entry["placement_ref"]) != expected_ref:
            raise ResourcePlacementError("RESOURCE_PLACEMENT_REF_NOT_DETERMINISTIC")
        # The per-entry source hash is the immutable authoring input hash.  The
        # materialized row separately stores the canonical manifest hash.
        if not str(entry.get("source_authoring_hash", "")).strip():
            raise ResourcePlacementError("RESOURCE_SOURCE_AUTHORING_HASH_REQUIRED")
        if not manifest_hash:
            raise ResourcePlacementError("RESOURCE_SOURCE_MANIFEST_HASH_REQUIRED")
        logical_row = self.runtime.conn.execute(
            "SELECT definition_json FROM arpg_gathering_nodes "
            "WHERE world_instance_id=? AND node_ref=?",
            (self.world_instance_id, str(entry["logical_node_ref"])),
        ).fetchone()
        if logical_row is None:
            raise ResourcePlacementError("RESOURCE_LOGICAL_GATHERING_NODE_NOT_FOUND")
        logical = json.loads(str(logical_row["definition_json"]))
        for key in ("zone_ref", "block_ref", "source_kind", "source_ref"):
            if str(entry[key]) != str(logical.get(key, "")):
                raise ResourcePlacementError(
                    f"RESOURCE_LOGICAL_GATHERING_BINDING_MISMATCH:{key}"
                )

    def _validate_constraint(self, entry: Any, revision: str) -> None:
        if not isinstance(entry, dict):
            raise ResourcePlacementError("INVALID_RESOURCE_CONSTRAINT_ENTRY")
        if str(entry.get("world_instance_id", "")) != self.world_instance_id:
            raise ResourcePlacementError("RESOURCE_CONSTRAINT_WORLD_MISMATCH")
        if str(entry.get("placement_revision", "")) != revision:
            raise ResourcePlacementError("RESOURCE_CONSTRAINT_REVISION_MISMATCH")
        if str(entry.get("constraint_kind", "")) != "AXIS_ALIGNED_SOLID_BLOCKER":
            raise ResourcePlacementError("UNSUPPORTED_RESOURCE_CONSTRAINT_KIND")
        bounds = entry.get("bounds")
        if not isinstance(bounds, dict) or any(
            not _finite(bounds.get(key))
            for key in (
                "min_iso_x_m", "max_iso_x_m", "min_iso_y_m", "max_iso_y_m",
                "min_altitude_m", "max_altitude_m",
            )
        ):
            raise ResourcePlacementError("INVALID_RESOURCE_CONSTRAINT_BOUNDS")
        if float(bounds["min_iso_x_m"]) >= float(bounds["max_iso_x_m"]):
            raise ResourcePlacementError("INVALID_RESOURCE_CONSTRAINT_X_BOUNDS")
        if float(bounds["min_iso_y_m"]) >= float(bounds["max_iso_y_m"]):
            raise ResourcePlacementError("INVALID_RESOURCE_CONSTRAINT_Y_BOUNDS")
        if float(bounds["min_altitude_m"]) >= float(bounds["max_altitude_m"]):
            raise ResourcePlacementError("INVALID_RESOURCE_CONSTRAINT_ALTITUDE_BOUNDS")
        if entry.get("blocks_los") is not True:
            raise ResourcePlacementError("RESOURCE_CONSTRAINT_MUST_BLOCK_LOS")

    def materialize_path(self, path: Path) -> dict[str, Any]:
        manifest, manifest_hash = self.load_manifest(path)
        return self.materialize(manifest, manifest_hash)

    def materialize(
        self, manifest: dict[str, Any], manifest_hash: str | None = None
    ) -> dict[str, Any]:
        actual_hash = manifest_hash or canonical_manifest_hash(manifest)
        self.validate_manifest(manifest, actual_hash)
        revision = str(manifest["placement_revision"])
        manifest_text = canonical_json(manifest)
        inserted = 0
        replayed = 0
        constraints_inserted = 0
        constraints_replayed = 0
        with self.runtime._write_lock:
            existing_manifest = self.runtime.conn.execute(
                "SELECT canonical_manifest_hash FROM s17_resource_placement_manifests "
                "WHERE world_instance_id=? AND placement_revision=?",
                (self.world_instance_id, revision),
            ).fetchone()
            if existing_manifest is not None and str(
                existing_manifest["canonical_manifest_hash"]
            ) != actual_hash:
                raise ResourcePlacementError("RESOURCE_PLACEMENT_REVISION_CONFLICT")
            if existing_manifest is None:
                self.runtime.conn.execute(
                    "INSERT INTO s17_resource_placement_manifests"
                    "(world_instance_id,placement_revision,schema_version,"
                    "canonical_manifest_hash,canonical_manifest_json) VALUES(?,?,?,?,?)",
                    (
                        self.world_instance_id,
                        revision,
                        SCHEMA_VERSION,
                        actual_hash,
                        manifest_text,
                    ),
                )
            for entry in manifest["placements"]:
                row = self._placement_row(entry, actual_hash)
                existing = self.runtime.conn.execute(
                    "SELECT payload_hash FROM s17_resource_metric_placements "
                    "WHERE placement_ref=?", (row["placement_ref"],)
                ).fetchone()
                if existing is not None:
                    if str(existing["payload_hash"]) != row["payload_hash"]:
                        raise ResourcePlacementError("RESOURCE_PLACEMENT_IDENTITY_CONFLICT")
                    replayed += 1
                    continue
                self.runtime.conn.execute(
                    "INSERT INTO s17_resource_metric_placements("
                    "placement_ref,world_instance_id,logical_node_ref,zone_ref,block_ref,"
                    "resource_kind,source_kind,source_ref,iso_x_m,iso_y_m,altitude_m,"
                    "placement_mode,placement_revision,schema_version,source_manifest_hash,"
                    "position_authority,authoring_object_ref,authoring_node_path,ordinal,active,"
                    "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row[key] for key in self._placement_columns()),
                )
                inserted += 1
            for entry in manifest["constraints"]:
                row = self._constraint_row(entry, actual_hash)
                existing = self.runtime.conn.execute(
                    "SELECT payload_hash FROM s17_resource_metric_constraints "
                    "WHERE constraint_ref=?", (row["constraint_ref"],)
                ).fetchone()
                if existing is not None:
                    if str(existing["payload_hash"]) != row["payload_hash"]:
                        raise ResourcePlacementError("RESOURCE_CONSTRAINT_IDENTITY_CONFLICT")
                    constraints_replayed += 1
                    continue
                self.runtime.conn.execute(
                    "INSERT INTO s17_resource_metric_constraints("
                    "constraint_ref,world_instance_id,zone_ref,block_ref,constraint_kind,"
                    "min_iso_x_m,max_iso_x_m,min_iso_y_m,max_iso_y_m,min_altitude_m,"
                    "max_altitude_m,blocks_los,placement_revision,source_manifest_hash,"
                    "authoring_node_path,active,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row[key] for key in self._constraint_columns()),
                )
                constraints_inserted += 1
        self.last_materialization = {
            "status": "PASS",
            "world_instance_id": self.world_instance_id,
            "placement_revision": revision,
            "canonical_manifest_hash": actual_hash,
            "inserted": inserted,
            "replayed": replayed,
            "constraint_inserted": constraints_inserted,
            "constraint_replayed": constraints_replayed,
            "placement_count": len(manifest["placements"]),
            "constraint_count": len(manifest["constraints"]),
            "idempotent": inserted == 0 and constraints_inserted == 0,
            "authority": PLACEMENT_AUTHORITY,
        }
        return dict(self.last_materialization)

    @staticmethod
    def _placement_columns() -> tuple[str, ...]:
        return (
            "placement_ref", "world_instance_id", "logical_node_ref", "zone_ref",
            "block_ref", "resource_kind", "source_kind", "source_ref", "iso_x_m",
            "iso_y_m", "altitude_m", "placement_mode", "placement_revision",
            "schema_version", "source_manifest_hash", "position_authority",
            "authoring_object_ref", "authoring_node_path", "ordinal", "active",
            "payload_hash",
        )

    @staticmethod
    def _constraint_columns() -> tuple[str, ...]:
        return (
            "constraint_ref", "world_instance_id", "zone_ref", "block_ref",
            "constraint_kind", "min_iso_x_m", "max_iso_x_m", "min_iso_y_m",
            "max_iso_y_m", "min_altitude_m", "max_altitude_m", "blocks_los",
            "placement_revision", "source_manifest_hash", "authoring_node_path",
            "active", "payload_hash",
        )

    def _placement_row(
        self, entry: dict[str, Any], manifest_hash: str
    ) -> dict[str, Any]:
        position = entry["position"]
        authoring = entry["authoring_source"]
        payload = {
            "placement_ref": str(entry["placement_ref"]),
            "world_instance_id": self.world_instance_id,
            "logical_node_ref": str(entry["logical_node_ref"]),
            "zone_ref": str(entry["zone_ref"]),
            "block_ref": str(entry["block_ref"]),
            "resource_kind": str(entry["resource_kind"]),
            "source_kind": str(entry["source_kind"]),
            "source_ref": str(entry["source_ref"]),
            "iso_x_m": float(position["iso_x_m"]),
            "iso_y_m": float(position["iso_y_m"]),
            "altitude_m": float(position["altitude_m"]),
            "placement_mode": str(entry["placement_mode"]),
            "placement_revision": str(entry["placement_revision"]),
            "schema_version": str(entry["schema_version"]),
            "source_manifest_hash": manifest_hash,
            "position_authority": POSITION_AUTHORITY,
            "authoring_object_ref": str(authoring["object_ref"]),
            "authoring_node_path": str(authoring["node_path"]),
            "ordinal": int(entry["ordinal"]),
            "active": 1 if entry["active"] else 0,
        }
        payload["payload_hash"] = sha256_text(canonical_json(payload))
        return payload

    def _constraint_row(
        self, entry: dict[str, Any], manifest_hash: str
    ) -> dict[str, Any]:
        bounds = entry["bounds"]
        payload = {
            "constraint_ref": str(entry["constraint_ref"]),
            "world_instance_id": self.world_instance_id,
            "zone_ref": str(entry["zone_ref"]),
            "block_ref": str(entry["block_ref"]),
            "constraint_kind": str(entry["constraint_kind"]),
            "min_iso_x_m": float(bounds["min_iso_x_m"]),
            "max_iso_x_m": float(bounds["max_iso_x_m"]),
            "min_iso_y_m": float(bounds["min_iso_y_m"]),
            "max_iso_y_m": float(bounds["max_iso_y_m"]),
            "min_altitude_m": float(bounds["min_altitude_m"]),
            "max_altitude_m": float(bounds["max_altitude_m"]),
            "blocks_los": 1 if entry["blocks_los"] else 0,
            "placement_revision": str(entry["placement_revision"]),
            "source_manifest_hash": manifest_hash,
            "authoring_node_path": str(entry["authoring_source"]["node_path"]),
            "active": 1 if entry.get("active", True) else 0,
        }
        payload["payload_hash"] = sha256_text(canonical_json(payload))
        return payload

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        out = dict(row)
        out["active"] = bool(out["active"])
        out["position"] = {
            "iso_x_m": float(out.pop("iso_x_m")),
            "iso_y_m": float(out.pop("iso_y_m")),
            "altitude_m": float(out.pop("altitude_m")),
        }
        out["server_authoritative"] = True
        out["authority"] = PLACEMENT_AUTHORITY
        return out

    def placement(self, placement_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT * FROM s17_resource_metric_placements WHERE placement_ref=?",
            (str(placement_ref),),
        ).fetchone()
        if row is None:
            raise KeyError(str(placement_ref))
        return self._row_dict(row)

    def active_placements(
        self, *, zone_ref: str | None = None, block_ref: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["world_instance_id=?", "active=1"]
        params: list[Any] = [self.world_instance_id]
        if zone_ref is not None:
            clauses.append("zone_ref=?")
            params.append(str(zone_ref))
        if block_ref is not None:
            clauses.append("block_ref=?")
            params.append(str(block_ref))
        rows = self.runtime.conn.execute(
            "SELECT * FROM s17_resource_metric_placements WHERE "
            + " AND ".join(clauses)
            + " ORDER BY placement_ref",
            tuple(params),
        ).fetchall()
        return [self._row_dict(row) for row in rows]

    def placements_for_logical(self, logical_node_ref: str) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT * FROM s17_resource_metric_placements "
            "WHERE world_instance_id=? AND logical_node_ref=? ORDER BY placement_ref",
            (self.world_instance_id, str(logical_node_ref)),
        ).fetchall()
        return [self._row_dict(row) for row in rows]

    def line_of_sight(
        self,
        start: dict[str, Any],
        end: dict[str, Any],
        *,
        zone_ref: str,
        block_ref: str,
    ) -> dict[str, Any]:
        if any(
            not _finite(start.get(key))
            for key in ("iso_x_m", "iso_y_m", "altitude_m")
        ) or any(
            not _finite(end.get(key))
            for key in ("iso_x_m", "iso_y_m", "altitude_m")
        ):
            raise ResourcePlacementError("INVALID_RESOURCE_LOS_ENDPOINT")
        rows = self.runtime.conn.execute(
            "SELECT * FROM s17_resource_metric_constraints "
            "WHERE world_instance_id=? AND zone_ref=? AND block_ref=? "
            "AND active=1 AND blocks_los=1 ORDER BY constraint_ref",
            (self.world_instance_id, str(zone_ref), str(block_ref)),
        ).fetchall()
        blocked_by: list[str] = []
        for row in rows:
            if self._segment_intersects_aabb_3d(
                float(start["iso_x_m"]),
                float(start["iso_y_m"]),
                float(start["altitude_m"]),
                float(end["iso_x_m"]),
                float(end["iso_y_m"]),
                float(end["altitude_m"]),
                float(row["min_iso_x_m"]),
                float(row["max_iso_x_m"]),
                float(row["min_iso_y_m"]),
                float(row["max_iso_y_m"]),
                float(row["min_altitude_m"]),
                float(row["max_altitude_m"]),
            ):
                blocked_by.append(str(row["constraint_ref"]))
        return {
            "status": "PASS",
            "clear": not blocked_by,
            "blocked": bool(blocked_by),
            "blocked_by": blocked_by,
            "constraint_count_evaluated": len(rows),
            "geometry_source": "OFFLINE_BAKED_MATERIALIZED_SERVER_CONSTRAINTS",
            "client_raycast_used": False,
            "server_authoritative": True,
            "authority": PLACEMENT_AUTHORITY,
        }

    @staticmethod
    def _segment_intersects_aabb(
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        min_x: float,
        max_x: float,
        min_y: float,
        max_y: float,
    ) -> bool:
        """Inclusive Liang-Barsky segment/AABB test in territorial metres."""
        dx = x1 - x0
        dy = y1 - y0
        t_min = 0.0
        t_max = 1.0
        for p, q in (
            (-dx, x0 - min_x),
            (dx, max_x - x0),
            (-dy, y0 - min_y),
            (dy, max_y - y0),
        ):
            if abs(p) <= 1e-15:
                if q < 0.0:
                    return False
                continue
            t = q / p
            if p < 0.0:
                if t > t_max:
                    return False
                t_min = max(t_min, t)
            else:
                if t < t_min:
                    return False
                t_max = min(t_max, t)
        return t_min <= t_max

    @staticmethod
    def _segment_intersects_aabb_3d(
        x0: float,
        y0: float,
        z0: float,
        x1: float,
        y1: float,
        z1: float,
        min_x: float,
        max_x: float,
        min_y: float,
        max_y: float,
        min_z: float,
        max_z: float,
    ) -> bool:
        """Inclusive slab test for a territorial-metric 3D segment/AABB."""
        t_min = 0.0
        t_max = 1.0
        for origin, delta, lower, upper in (
            (x0, x1 - x0, min_x, max_x),
            (y0, y1 - y0, min_y, max_y),
            (z0, z1 - z0, min_z, max_z),
        ):
            if abs(delta) <= 1e-15:
                if origin < lower or origin > upper:
                    return False
                continue
            first = (lower - origin) / delta
            second = (upper - origin) / delta
            if first > second:
                first, second = second, first
            t_min = max(t_min, first)
            t_max = min(t_max, second)
            if t_min > t_max:
                return False
        return True

    def metrics(self) -> dict[str, Any]:
        placement_count = int(
            self.runtime.conn.execute(
                "SELECT COUNT(*) FROM s17_resource_metric_placements "
                "WHERE world_instance_id=?", (self.world_instance_id,)
            ).fetchone()[0]
        )
        constraint_count = int(
            self.runtime.conn.execute(
                "SELECT COUNT(*) FROM s17_resource_metric_constraints "
                "WHERE world_instance_id=?", (self.world_instance_id,)
            ).fetchone()[0]
        )
        return {
            "status": "PASS",
            "world_instance_id": self.world_instance_id,
            "placement_count": placement_count,
            "constraint_count": constraint_count,
            "logical_gth_depletion_duplicated": False,
            "gather_range_m": GATHER_RANGE_M,
            "position_authority": POSITION_AUTHORITY,
            "authority": PLACEMENT_AUTHORITY,
        }
