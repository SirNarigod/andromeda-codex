"""Offline Stage17 bake for authoritative metric resource placements.

The Godot scene is an authoring input only.  This tool resolves its explicitly
named authoring proxies against real protected ``GTH-*`` logical nodes and a
canonical territorial waypoint, validates the resulting points against the
authoritative zone, and emits one deterministic canonical manifest.  Runtime
gameplay never reads Godot transforms as authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = WORKSPACE_ROOT / "12_AUTHORITY_BACKEND_STAGE17"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import load_config  # noqa: E402
from resource_metric_placement import (  # noqa: E402
    GATHER_RANGE_M,
    PLACEMENT_AUTHORITY,
    POSITION_AUTHORITY,
    SCHEMA_VERSION,
    canonical_json,
    canonical_manifest_hash,
    stable_placement_ref,
)


AUTHORING_PATH = (
    WORKSPACE_ROOT
    / "STAGE17_CONTENT"
    / "RESOURCE_PLACEMENT"
    / "S17_PLAYABLE_V0_RESOURCE_AUTHORING_V0_1_0_DEV.json"
)
DEFAULT_OUTPUT = (
    WORKSPACE_ROOT
    / "STAGE17_CONTENT"
    / "RESOURCE_PLACEMENT"
    / "CANONICAL"
    / "S17_RESOURCE_METRIC_PLACEMENTS_R0001.json"
)
NODE_HEADER_RE = re.compile(r'^\[node name="([^"]+)"(?: type="[^"]+")? parent="([^"]+)"(?: .*)?\]$')
SUBRESOURCE_HEADER_RE = re.compile(r'^\[sub_resource type="([^"]+)" id="([^"]+)"\]$')
VECTOR3_RE = re.compile(
    r"^Vector3\(\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\)$"
)
SUBRESOURCE_REF_RE = re.compile(r'^SubResource\("([^"]+)"\)$')


class BakeError(RuntimeError):
    """The authoring source cannot produce a safe canonical manifest."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _finite_vector(value: Any, field: str) -> tuple[float, float, float]:
    if not isinstance(value, str):
        raise BakeError(f"{field}:VECTOR3_REQUIRED")
    match = VECTOR3_RE.fullmatch(value.strip())
    if match is None:
        raise BakeError(f"{field}:UNSUPPORTED_VECTOR3:{value}")
    result = tuple(float(part) for part in match.groups())
    if not all(math.isfinite(part) for part in result):
        raise BakeError(f"{field}:NON_FINITE")
    return result  # type: ignore[return-value]


def _parse_tscn(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    nodes: dict[str, dict[str, str]] = {}
    subresources: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    current_kind = ""
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        sub_match = SUBRESOURCE_HEADER_RE.fullmatch(line)
        if sub_match:
            current = {"type": sub_match.group(1), "id": sub_match.group(2)}
            subresources[sub_match.group(2)] = current
            current_kind = "subresource"
            continue
        node_match = NODE_HEADER_RE.fullmatch(line)
        if node_match:
            name, parent = node_match.groups()
            path_key = name if parent == "." else f"{parent}/{name}"
            current = {"name": name, "parent": parent, "path": path_key}
            nodes[path_key] = current
            current_kind = "node"
            continue
        if line.startswith("["):
            current = None
            current_kind = ""
            continue
        if current is None or " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        current[key.strip()] = value.strip()
    if not nodes:
        raise BakeError("TSCN_HAS_NO_NODES")
    if not subresources:
        raise BakeError("TSCN_HAS_NO_SUBRESOURCES")
    return nodes, subresources


def _node_local_position(node: dict[str, str]) -> tuple[float, float, float]:
    return _finite_vector(node.get("position", "Vector3(0, 0, 0)"), node["path"])


def _global_position(nodes: dict[str, dict[str, str]], node_path: str) -> tuple[float, float, float]:
    if node_path not in nodes:
        raise BakeError(f"AUTHORING_NODE_NOT_FOUND:{node_path}")
    total = [0.0, 0.0, 0.0]
    cursor = nodes[node_path]
    seen: set[str] = set()
    while True:
        cursor_path = cursor["path"]
        if cursor_path in seen:
            raise BakeError(f"AUTHORING_NODE_PARENT_CYCLE:{cursor_path}")
        seen.add(cursor_path)
        for forbidden in ("rotation", "rotation_degrees", "scale", "transform"):
            if forbidden in cursor:
                raise BakeError(f"UNSUPPORTED_AUTHORED_TRANSFORM:{cursor_path}:{forbidden}")
        position = _node_local_position(cursor)
        for index in range(3):
            total[index] += position[index]
        parent = cursor.get("parent", ".")
        if parent == "." or parent not in nodes:
            break
        cursor = nodes[parent]
    return tuple(total)  # type: ignore[return-value]


def _shape_size(
    nodes: dict[str, dict[str, str]],
    subresources: dict[str, dict[str, str]],
    body_path: str,
    child_name: str,
) -> tuple[float, float, float]:
    child_path = f"{body_path}/{child_name}"
    child = nodes.get(child_path)
    if child is None:
        raise BakeError(f"CONSTRAINT_SHAPE_NODE_NOT_FOUND:{child_path}")
    if _node_local_position(child) != (0.0, 0.0, 0.0):
        raise BakeError(f"OFFSET_CONSTRAINT_SHAPE_UNSUPPORTED:{child_path}")
    shape_match = SUBRESOURCE_REF_RE.fullmatch(child.get("shape", ""))
    if shape_match is None:
        raise BakeError(f"CONSTRAINT_SUBRESOURCE_REQUIRED:{child_path}")
    shape = subresources.get(shape_match.group(1))
    if shape is None or shape.get("type") != "BoxShape3D":
        raise BakeError(f"AXIS_ALIGNED_BOX_SHAPE_REQUIRED:{child_path}")
    size = _finite_vector(shape.get("size"), f"{child_path}:size")
    if any(component <= 0.0 for component in size):
        raise BakeError(f"POSITIVE_CONSTRAINT_SIZE_REQUIRED:{child_path}")
    return size


def _inside_bbox(point: dict[str, Any], bbox: Any) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise BakeError("ZONE_BOUNDING_REGION_INVALID")
    lon0, lat0, lon1, lat1 = (float(value) for value in bbox)
    lon = float(point["longitude"])
    lat = float(point["latitude"])
    return lon0 - 1e-9 <= lon <= lon1 + 1e-9 and lat0 - 1e-9 <= lat <= lat1 + 1e-9


def _select_logical_node(nodes: list[dict[str, Any]], selector: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for node in nodes:
        if any(str(node.get(key)) != str(value) for key, value in selector.items()):
            continue
        candidates.append(node)
    if len(candidates) != 1:
        raise BakeError(
            "RESOURCE_LOGICAL_SELECTOR_MUST_RESOLVE_EXACTLY_ONE:"
            + canonical_json({"selector": selector, "matches": [row.get("node_ref") for row in candidates]})
        )
    return candidates[0]


def bake(authoring_path: Path, output_path: Path) -> dict[str, Any]:
    authoring_bytes = authoring_path.read_bytes()
    try:
        authoring = json.loads(authoring_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BakeError(f"AUTHORING_JSON_INVALID:{exc}") from exc
    if str(authoring.get("schema_version")) != "S17_RESOURCE_PLACEMENT_AUTHORING_V1":
        raise BakeError("AUTHORING_SCHEMA_UNSUPPORTED")

    scene_path = WORKSPACE_ROOT / str(authoring["source_scene"])
    nodes, subresources = _parse_tscn(scene_path)
    scene_hash = _sha256_bytes(scene_path.read_bytes())
    authoring_hash = _sha256_bytes(authoring_bytes)

    config = replace(load_config(), resource_placement_manifest_path=None)
    adapter = Stage16BAuthorityAdapter(config)
    try:
        world = adapter._engine.world_arpg(adapter.world_instance_id)
        profile_state = world.profile_state(adapter.profile_ref)
        zone_ref = str(profile_state["zone_ref"])
        zone = world.zone(zone_ref)
        spatial = adapter._engine.spatial(adapter.world_instance_id)
        anchor_contract = dict(authoring["world_binding"]["authority_anchor"])
        anchor_kind = str(anchor_contract.get("kind", ""))
        if anchor_kind != "SERVER_AUTHORITATIVE_PLAYER_MOTION_SNAPSHOT_DEV_AUTHORING_ANCHOR":
            raise BakeError(f"UNSUPPORTED_AUTHORITY_ANCHOR:{anchor_kind}")
        if anchor_contract.get("gameplay_client_supplied") is not False:
            raise BakeError("AUTHORING_ANCHOR_MUST_NOT_BE_CLIENT_SUPPLIED")
        anchor_state = adapter._engine.movement(adapter.world_instance_id).state(
            adapter._player_ref
        )
        anchor = {
            "iso_x_m": float(anchor_state["iso_x_m"]),
            "iso_y_m": float(anchor_state["iso_y_m"]),
            "altitude_m": float(anchor_state["altitude_m"]),
            "authority": str(anchor_state["authority"]),
        }
        anchor_snapshot_hash = _sha256_bytes(
            canonical_json(
                {
                    "world_instance_id": adapter.world_instance_id,
                    "player_ref": adapter._player_ref,
                    "iso_x_m": anchor["iso_x_m"],
                    "iso_y_m": anchor["iso_y_m"],
                    "altitude_m": anchor["altitude_m"],
                    "authority": anchor["authority"],
                }
            ).encode("utf-8")
        )
        explicit_altitude = float(authoring["coordinate_contract"]["surface_altitude_m"])
        if not math.isfinite(explicit_altitude):
            raise BakeError("AUTHORING_SURFACE_ALTITUDE_NON_FINITE")
        anchor_local = _global_position(
            nodes, str(authoring["coordinate_contract"]["local_anchor_node_path"])
        )
        gathering = adapter._engine.gathering_arpg(adapter.world_instance_id)
        logical_nodes = gathering.list_nodes(zone_ref=zone_ref)

        placements: list[dict[str, Any]] = []
        common_block_ref = ""
        revision = str(authoring["placement_revision"])
        for definition in authoring["resources"]:
            logical = _select_logical_node(logical_nodes, dict(definition["logical_selector"]))
            node_local = _global_position(nodes, str(definition["node_path"]))
            position = {
                "iso_x_m": float(anchor["iso_x_m"]) + node_local[0] - anchor_local[0],
                "iso_y_m": float(anchor["iso_y_m"]) + node_local[2] - anchor_local[2],
                "altitude_m": explicit_altitude + node_local[1] - anchor_local[1],
            }
            if not all(math.isfinite(value) for value in position.values()):
                raise BakeError("MATERIALIZED_RESOURCE_POSITION_NON_FINITE")
            geodetic = spatial.isometric_to_geodetic(**position)
            country_bbox = adapter._engine.country(adapter.world_instance_id).world[
                "country"
            ]["bounding_region"]
            if not _inside_bbox(geodetic, country_bbox):
                raise BakeError(f"RESOURCE_OUTSIDE_COUNTRY:{logical['node_ref']}")
            block_ref = str(logical["block_ref"])
            if common_block_ref and common_block_ref != block_ref:
                raise BakeError("PLAYABLE_V0_RESOURCES_MUST_SHARE_BLOCK")
            common_block_ref = block_ref
            placement_ref = stable_placement_ref(
                adapter.world_instance_id,
                str(logical["node_ref"]),
                str(definition["authoring_object_ref"]),
                revision,
                int(definition["ordinal"]),
            )
            placements.append(
                {
                    "placement_ref": placement_ref,
                    "logical_node_ref": str(logical["node_ref"]),
                    "world_instance_id": adapter.world_instance_id,
                    "zone_ref": zone_ref,
                    "block_ref": block_ref,
                    "resource_kind": str(definition["resource_kind"]),
                    "source_kind": str(logical["source_kind"]),
                    "source_ref": str(logical["source_ref"]),
                    "position": position,
                    "position_authority": POSITION_AUTHORITY,
                    "placement_mode": str(definition["placement_mode"]),
                    "placement_revision": revision,
                    "schema_version": SCHEMA_VERSION,
                    "source_authoring_hash": authoring_hash,
                    "authoring_source": {
                        "object_ref": str(definition["authoring_object_ref"]),
                        "node_path": str(definition["node_path"]),
                        "scene_path": str(authoring["source_scene"]),
                        "scene_sha256": scene_hash,
                        "runtime_authority": False,
                    },
                    "ordinal": int(definition["ordinal"]),
                    "active": True,
                }
            )

        constraints: list[dict[str, Any]] = []
        for definition in authoring["solid_constraints"]:
            body_path = str(definition["node_path"])
            body_position = _global_position(nodes, body_path)
            size = _shape_size(
                nodes,
                subresources,
                body_path,
                str(definition["shape_child_path"]),
            )
            center_x = float(anchor["iso_x_m"]) + body_position[0] - anchor_local[0]
            center_y = float(anchor["iso_y_m"]) + body_position[2] - anchor_local[2]
            center_altitude = explicit_altitude + body_position[1] - anchor_local[1]
            constraints.append(
                {
                    "constraint_ref": str(definition["constraint_ref"]),
                    "world_instance_id": adapter.world_instance_id,
                    "zone_ref": zone_ref,
                    "block_ref": common_block_ref,
                    "constraint_kind": str(definition["constraint_kind"]),
                    "bounds": {
                        "min_iso_x_m": center_x - size[0] / 2.0,
                        "max_iso_x_m": center_x + size[0] / 2.0,
                        "min_iso_y_m": center_y - size[2] / 2.0,
                        "max_iso_y_m": center_y + size[2] / 2.0,
                        "min_altitude_m": center_altitude - size[1] / 2.0,
                        "max_altitude_m": center_altitude + size[1] / 2.0,
                    },
                    "blocks_los": bool(definition["blocks_los"]),
                    "active": bool(definition["active"]),
                    "placement_revision": revision,
                    "source_authoring_hash": authoring_hash,
                    "authoring_source": {
                        "node_path": body_path,
                        "shape_child_path": str(definition["shape_child_path"]),
                        "scene_path": str(authoring["source_scene"]),
                        "scene_sha256": scene_hash,
                        "runtime_authority": False,
                    },
                }
            )

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "placement_revision": revision,
            "placement_model": str(authoring["placement_model"]),
            "placement_algorithm_version": str(authoring["placement_algorithm_version"]),
            "placement_authority": PLACEMENT_AUTHORITY,
            "world_binding": {
                "world_instance_id": adapter.world_instance_id,
                "owner_scope": config.owner_scope,
                "world_seed": config.world_seed,
                "zone_ref": zone_ref,
                "block_ref": common_block_ref,
                "anchor_kind": anchor_kind,
                "anchor_player_ref": adapter._player_ref,
                "anchor_snapshot_hash": anchor_snapshot_hash,
                "anchor_position": {
                    "iso_x_m": float(anchor["iso_x_m"]),
                    "iso_y_m": float(anchor["iso_y_m"]),
                    "altitude_m": explicit_altitude,
                },
                "coordinate_authority": str(anchor["authority"]),
                "logical_zone_binding_authority": "PROTECTED_GTH_ZONE_BLOCK",
                "metric_country_containment": "VALIDATED",
                "metric_zone_containment": (
                    "VALIDATED"
                    if _inside_bbox(
                        spatial.isometric_to_geodetic(
                            anchor["iso_x_m"], anchor["iso_y_m"], anchor["altitude_m"]
                        ),
                        zone.get("bounding_region"),
                    )
                    else "NOT_ENFORCED_STAGE17_GREYBOX_PROFILE_MOTION_DIVERGENCE"
                ),
            },
            "coordinate_contract": {
                "mapping": "AUTHORITY_ORIGIN_PLUS_LOCAL_OFFSET_METRES",
                "local_anchor_node_path": str(
                    authoring["coordinate_contract"]["local_anchor_node_path"]
                ),
                "local_anchor_position": {
                    "x": anchor_local[0],
                    "y": anchor_local[1],
                    "z": anchor_local[2],
                },
                "scale_m_per_local_unit": 1.0,
                "local_x_axis": "+ISO_X_M",
                "local_z_axis": "+ISO_Y_M",
                "altitude_source": str(authoring["coordinate_contract"]["altitude_source"]),
            },
            "gather_policy": {
                "metric_range_m": GATHER_RANGE_M,
                "distance_authority": "SERVER_MOVEMENT_STATE_TO_MATERIALIZED_RESOURCE_POSITION",
                "blocker_los_required": True,
                "blocker_geometry_authority": "OFFLINE_BAKED_RUNTIME_MATERIALIZED",
                "client_position_accepted": False,
            },
            "source": {
                "authoring_path": str(authoring_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                "authoring_sha256": authoring_hash,
                "scene_path": str(scene_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                "scene_sha256": scene_hash,
                "offline_bake": True,
                "runtime_generation": False,
            },
            "placements": sorted(placements, key=lambda entry: entry["placement_ref"]),
            "constraints": sorted(constraints, key=lambda entry: entry["constraint_ref"]),
            "logical_identity_policy": {
                "gth_owns_gathering_and_depletion": True,
                "physical_placement_identity_is_separate": True,
                "multiple_physical_placements_per_gth_supported": True,
            },
        }
        manifest_hash = canonical_manifest_hash(manifest)
        envelope = {
            "schema": "S17_RESOURCE_METRIC_PLACEMENT_MANIFEST_ENVELOPE_V1",
            "canonical_manifest_hash": manifest_hash,
            "canonical_manifest": manifest,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "status": "PASS",
            "output_path": str(output_path),
            "canonical_manifest_hash": manifest_hash,
            "world_instance_id": adapter.world_instance_id,
            "zone_ref": zone_ref,
            "block_ref": common_block_ref,
            "placement_count": len(placements),
            "constraint_count": len(constraints),
            "placement_refs": [entry["placement_ref"] for entry in placements],
            "logical_node_refs": [entry["logical_node_ref"] for entry in placements],
            "source_authoring_sha256": authoring_hash,
            "source_scene_sha256": scene_hash,
            "authority": PLACEMENT_AUTHORITY,
        }
    finally:
        adapter.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authoring", type=Path, default=AUTHORING_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = bake(args.authoring.resolve(), args.output.resolve())
    except Exception as exc:  # the CLI must produce a single auditable failure marker
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
