from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import zipfile
from typing import Any

from living_runtime import ValidationError, ConflictError, IntegrityError, NotFoundError, canonical_json, sha256_text

MASTER_GEO_PATHS = {
    "BIOMES": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_BIOME_MODEL_V1_0.json",
    "CLIMATE": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_CLIMATE_SPATIAL_MODEL_V1_0.json",
    "HYDROLOGY": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_HYDROLOGY_V1_0.json",
    "REGIONS": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_REGIONS_V1_0.json",
    "LOCATIONS": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_MAJOR_LOCATIONS_V1_0.json",
    "ROUTES": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_ROUTE_SKELETON_V1_0.json",
    "TERRITORIES": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_TERRITORIES_V1_0.json",
    "RELIEF": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_RELIEF_MODEL_V1_0.json",
}

EXPECTED_CANON_COUNTS = {
    "biomes": 10,
    "climate_zones": 8,
    "basins": 6,
    "rivers": 7,
    "water_bodies": 8,
    "aquifers": 4,
    "regions": 8,
    "locations": 18,
    "routes": 25,
    "territories": 13,
}


def _point_in_bbox(lon: float, lat: float, bbox: list[float]) -> bool:
    return float(bbox[0]) <= lon <= float(bbox[2]) and float(bbox[1]) <= lat <= float(bbox[3])


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class ARPGWorldCore:
    """Stage08 world/biome authority for the ARPG runtime.

    Canonical geography is loaded READ_ONLY from Master V2.0.1.  Runtime zones, encounter
    anchors, waypoint discovery and environment samples are derived gameplay state.  The current
    playable scope remains one country only (TER-011 / Terras Livres).  Canonical records from
    other territories may be indexed for completeness but cannot become playable through this core.
    """

    VERSION = "V0.9.0"
    STAGE = "08/23"
    AUTHORITY = "ARPG_WORLD_BIOMES_GAMEPLAY_DERIVATION"
    PILOT_TERRITORY_ID = "TER-011"
    PILOT_TERRITORY_NAME = "Terras Livres"
    PRIMARY_BIOME_ID = "BIO-008"
    MAJOR_BIOME_ID = "BIO-002"
    CLIMATE_ID = "CLM-002"
    HYDROLOGY_IDS = ("BAS-001", "RIV-VARDEN")
    ART_DEPENDENCY = "NONE_PLACEHOLDER_READY"

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = world_instance_id
        self.country = engine.country(world_instance_id)
        self._init_schema()
        self._canon = self._load_canon()
        self._validate_pilot_authority()
        self._bootstrap_zones()
        self._bootstrap_existing_profiles()

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_world_canon_snapshots(
                    category TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS arpg_world_zones(
                    world_instance_id TEXT NOT NULL,
                    zone_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, zone_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_world_profile_state(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_world_events(
                    server_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id, event_ref)
                );
                CREATE TRIGGER IF NOT EXISTS arpg_world_canon_no_update
                  BEFORE UPDATE ON arpg_world_canon_snapshots BEGIN SELECT RAISE(ABORT,'world canon snapshot immutable'); END;
                CREATE TRIGGER IF NOT EXISTS arpg_world_canon_no_delete
                  BEFORE DELETE ON arpg_world_canon_snapshots BEGIN SELECT RAISE(ABORT,'world canon snapshot immutable'); END;
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_world_core_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def _payload(payload: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(payload)
        return text, sha256_text(text)

    def _load_canon(self) -> dict[str, Any]:
        path = self.runtime.master_release_path
        if not path:
            raise IntegrityError("Master release required for Stage08 world source")
        docs: dict[str, Any] = {}
        with zipfile.ZipFile(path, "r") as zf:
            for category, source in MASTER_GEO_PATHS.items():
                payload = json.loads(zf.read(source))
                docs[category] = payload
                text, h = self._payload(payload)
                row = self.runtime.conn.execute(
                    "SELECT payload_hash FROM arpg_world_canon_snapshots WHERE category=?", (category,)
                ).fetchone()
                if row:
                    if row["payload_hash"] != h:
                        raise IntegrityError("ARPG world canonical snapshot drift:" + category)
                else:
                    with self.runtime._write_lock:
                        self.runtime.conn.execute(
                            "INSERT INTO arpg_world_canon_snapshots(category,source_path,payload_json,payload_hash) VALUES(?,?,?,?)",
                            (category, source, text, h),
                        )
        return docs

    def _records(self) -> dict[str, dict[str, Any]]:
        return {
            "biomes": {x["id"]: x for x in self._canon["BIOMES"].get("biomes", [])},
            "climate": {x["id"]: x for x in self._canon["CLIMATE"].get("climate_zones", [])},
            "basins": {x["id"]: x for x in self._canon["HYDROLOGY"].get("basins", [])},
            "rivers": {x["id"]: x for x in self._canon["HYDROLOGY"].get("rivers", [])},
            "water_bodies": {x["id"]: x for x in self._canon["HYDROLOGY"].get("water_bodies", [])},
            "aquifers": {x["id"]: x for x in self._canon["HYDROLOGY"].get("aquifers", [])},
            "regions": {x["id"]: x for x in self._canon["REGIONS"].get("regions", [])},
            "locations": {x["id"]: x for x in self._canon["LOCATIONS"].get("locations", [])},
            "routes": {x["id"]: x for x in self._canon["ROUTES"].get("routes", [])},
            "territories": {x["id"]: x for x in self._canon["TERRITORIES"].get("territories", [])},
        }

    def _validate_pilot_authority(self) -> None:
        r = self._records()
        ter = r["territories"].get(self.PILOT_TERRITORY_ID)
        if not ter or ter.get("name") != self.PILOT_TERRITORY_NAME:
            raise IntegrityError("Stage08 pilot territory authority mismatch")
        if set(ter.get("biome_ids", [])) != {self.MAJOR_BIOME_ID, self.PRIMARY_BIOME_ID}:
            raise IntegrityError("Stage08 pilot biome authority mismatch")
        if list(ter.get("climate_ids", [])) != [self.CLIMATE_ID]:
            raise IntegrityError("Stage08 pilot climate authority mismatch")
        if not set(self.HYDROLOGY_IDS).issubset(set(ter.get("hydrology_ids", []))):
            raise IntegrityError("Stage08 pilot hydrology authority mismatch")
        primary = r["biomes"][self.PRIMARY_BIOME_ID]
        if primary.get("geometry") != ter.get("geometry"):
            raise IntegrityError("BIO-008 no longer exactly matches TER-011 canonical geometry")

    def canonical_catalog(self) -> dict[str, Any]:
        r = self._records()
        return {
            "status": "PASS",
            "authority": "MASTER_V2_0_1_READ_ONLY",
            "counts": {
                "biomes": len(r["biomes"]),
                "climate_zones": len(r["climate"]),
                "basins": len(r["basins"]),
                "rivers": len(r["rivers"]),
                "water_bodies": len(r["water_bodies"]),
                "aquifers": len(r["aquifers"]),
                "regions": len(r["regions"]),
                "locations": len(r["locations"]),
                "routes": len(r["routes"]),
                "territories": len(r["territories"]),
            },
            "biomes": [copy.deepcopy(x) for x in r["biomes"].values()],
            "playable_scope": {
                "country_count": 1,
                "territory_id": self.PILOT_TERRITORY_ID,
                "territory_name": self.PILOT_TERRITORY_NAME,
                "other_territories": "INDEXED_READ_ONLY_NOT_PLAYABLE",
            },
        }

    def _save_zone(self, zone: dict[str, Any]) -> None:
        text, h = self._payload(zone)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_world_zones(world_instance_id,zone_ref,payload_json,payload_hash) VALUES(?,?,?,?)",
                (self.world_instance_id, zone["zone_ref"], text, h),
            )

    def _location_zone(self, lon: float, lat: float, zones: list[dict[str, Any]]) -> str | None:
        for z in zones:
            if _point_in_bbox(lon, lat, z["bounding_region"]):
                return z["zone_ref"]
        return None

    def _route_scope(self, route: dict[str, Any], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
        locs = records["locations"]
        a = locs.get(route.get("origin_id"), {})
        b = locs.get(route.get("destination_id"), {})
        a_in = a.get("territory_id") == self.PILOT_TERRITORY_ID
        b_in = b.get("territory_id") == self.PILOT_TERRITORY_ID
        if a_in and b_in:
            return {"playability": "PLAYABLE_INTERNAL", "boundary_locked": False}
        if a_in or b_in:
            return {
                "playability": "BOUNDARY_GATE_ONLY",
                "boundary_locked": True,
                "lock_reason": "ONE_COUNTRY_SCOPE_OTHER_COUNTRY_DEFERRED",
            }
        return {"playability": "INDEX_ONLY", "boundary_locked": True, "lock_reason": "OUTSIDE_PILOT_COUNTRY"}

    def _canonical_environment(self, block: dict[str, Any]) -> dict[str, Any]:
        r = self._records()
        climate = r["climate"][self.CLIMATE_ID]
        legacy = copy.deepcopy(block.get("climate") or {})
        temp_rng = list(map(float, climate.get("temperature_c_typical", [2, 33])))
        precip_rng = list(map(float, climate.get("annual_precipitation_mm", [420, 950])))
        legacy_temp = float(legacy.get("temperature_c", sum(temp_rng) / 2.0))
        legacy_rain = float(legacy.get("rainfall_mm_y", legacy.get("rainfall_mm", sum(precip_rng) / 2.0)))
        return {
            "canonical_climate_id": self.CLIMATE_ID,
            "canonical_climate_name": climate.get("name"),
            "temperature_c_typical": temp_rng,
            "annual_precipitation_mm": precip_rng,
            "seasonality": climate.get("seasonality"),
            "wind": climate.get("wind"),
            "hazards": copy.deepcopy(climate.get("hazards", [])),
            "runtime_baseline": {
                "temperature_c": round(_clamp(legacy_temp, temp_rng[0], temp_rng[1]), 2),
                "annual_precipitation_mm": round(_clamp(legacy_rain, precip_rng[0], precip_rng[1]), 2),
                "humidity_pct": round(_clamp(float(legacy.get("humidity_pct", legacy.get("humidity", 55.0))), 10.0, 98.0), 2),
                "source": "COUNTRY_PROCEDURAL_CLAMPED_TO_CANONICAL_CLIMATE",
            },
            "legacy_procedural_climate": legacy,
        }

    def _bootstrap_zones(self) -> dict[str, Any]:
        records = self._records()
        ter = records["territories"][self.PILOT_TERRITORY_ID]
        location_ids = set(ter.get("major_location_ids", []))
        route_ids = set(ter.get("route_ids", []))
        zones: list[dict[str, Any]] = []
        blocks: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for state in self.country.world["country"].get("states", []):
            for block in state.get("blocks", []):
                blocks.append((state, block))

        for state, block in blocks:
            zone_ref = "ZONE-" + block["id"]
            zone = {
                "zone_ref": zone_ref,
                "country_ref": self.PILOT_TERRITORY_ID,
                "country_name": self.PILOT_TERRITORY_NAME,
                "state_ref": state["id"],
                "state_name": state.get("name"),
                "block_ref": block["id"],
                "bounding_region": copy.deepcopy(block.get("bounding_region")),
                "coordinate_center": copy.deepcopy(block.get("coordinate_center")),
                "vertical_layer": "surface",
                "biome": {
                    "primary_id": self.PRIMARY_BIOME_ID,
                    "primary_name": records["biomes"][self.PRIMARY_BIOME_ID].get("name"),
                    "major_system_id": self.MAJOR_BIOME_ID,
                    "major_system_name": records["biomes"][self.MAJOR_BIOME_ID].get("name"),
                    "binding_basis": "BIO_008_EXACT_TER_011_MASK_WITH_BIO_002_MAJOR_OVERLAY",
                    "legacy_procedural_classification": copy.deepcopy(block.get("biome")),
                    "authority": "MASTER_CANONICAL_BINDING_RUNTIME_ZONE",
                },
                "anomaly_overlay": ({
                    "overlay_id": "BIO-ROOT-DEEP",
                    "overlay_name": "Bioma da Raiz Profunda",
                    "overlay_scope": "LOCAL_RUNTIME_ANOMALY_OVER_CANONICAL_GEOGRAPHY",
                    "predator_only": True,
                    "normal_city_allowed": False,
                    "normal_flora_allowed": False,
                    "source_authority": "COUNTRY_SCALE_STRUCTURAL_AUTHORIZATION_PENDING_MASTER_CONSOLIDATION",
                } if bool(block.get("root_deep")) else None),
                "environment": self._canonical_environment(block),
                "hydrology_context": {
                    "ids": list(self.HYDROLOGY_IDS),
                    "basin": copy.deepcopy(records["basins"].get("BAS-001")),
                    "river": copy.deepcopy(records["rivers"].get("RIV-VARDEN")),
                    "binding_scope": "TERRITORY_CONTEXT_STAGE08",
                },
                "locations": [],
                "routes": [],
                "dungeons": [],
                "waypoints": [],
                "encounter_anchors": [],
                "resource_system_gate": "STAGE09_GATHERING_HUNTING_FISHING_WORK",
                "mobility_system_gate": "STAGE10_MOBILITY_INFRASTRUCTURE",
                "art_dependency": self.ART_DEPENDENCY,
                "authority": self.AUTHORITY,
            }
            for dungeon in block.get("dungeons", []):
                zone["dungeons"].append({
                    "dungeon_ref": dungeon.get("id"),
                    "name": dungeon.get("name"),
                    "source_authority": "COUNTRY_SCALE_RUNTIME_DERIVED",
                    "root_deep": bool(dungeon.get("root_deep")),
                    "darkness_level": dungeon.get("darkness_level"),
                    "recommended_light": dungeon.get("recommended_light"),
                    "room_count": len((dungeon.get("graph_v2") or {}).get("rooms", [])),
                    "entrance_room_id": (dungeon.get("graph_v2") or {}).get("entrance_room_id"),
                    "final_room_id": (dungeon.get("graph_v2") or {}).get("final_room_id"),
                })
            zones.append(zone)

        for lid in sorted(location_ids):
            loc = records["locations"].get(lid)
            if not loc:
                continue
            c = loc.get("coordinate") or {}
            zref = self._location_zone(float(c.get("longitude", 0.0)), float(c.get("latitude", 0.0)), zones)
            if zref:
                z = next(x for x in zones if x["zone_ref"] == zref)
                z["locations"].append(copy.deepcopy(loc))
                z["waypoints"].append({
                    "waypoint_ref": "WP-CANON-" + lid,
                    "name": loc.get("name"),
                    "zone_ref": zref,
                    "coordinate": copy.deepcopy(c),
                    "source_authority": "MASTER_LOCATION_READ_ONLY",
                    "unlock_policy": "DISCOVER_ON_PROFILE_BOOTSTRAP_IF_START_LOCATION",
                    "fast_travel": True,
                })

        # Runtime state anchors guarantee usable one-country fast travel without inventing canonical locations.
        for state in self.country.world["country"].get("states", []):
            c = state.get("coordinate_center") or {}
            zref = self._location_zone(float(c.get("longitude", 0.0)), float(c.get("latitude", 0.0)), zones)
            if zref:
                z = next(x for x in zones if x["zone_ref"] == zref)
                z["waypoints"].append({
                    "waypoint_ref": "WP-RUNTIME-" + state["id"],
                    "name": "Runtime Travel Anchor " + state["id"],
                    "zone_ref": zref,
                    "coordinate": copy.deepcopy(c),
                    "source_authority": "GAMEPLAY_DERIVED_REPLACEABLE",
                    "unlock_policy": "DISCOVERY_REQUIRED",
                    "fast_travel": True,
                })

        for rid in sorted(route_ids):
            route = records["routes"].get(rid)
            if not route:
                continue
            scope = self._route_scope(route, records)
            payload = {
                "route_ref": rid,
                "name": route.get("name"),
                "type": route.get("type"),
                "origin_id": route.get("origin_id"),
                "destination_id": route.get("destination_id"),
                "transport_modes": copy.deepcopy(route.get("transport_modes", [])),
                **scope,
                "source_authority": "MASTER_ROUTE_READ_ONLY",
            }
            candidate_zone = None
            for endpoint in (route.get("origin_id"), route.get("destination_id")):
                loc = records["locations"].get(endpoint)
                if loc and loc.get("territory_id") == self.PILOT_TERRITORY_ID:
                    c = loc.get("coordinate") or {}
                    candidate_zone = self._location_zone(float(c.get("longitude", 0.0)), float(c.get("latitude", 0.0)), zones)
                    if candidate_zone:
                        break
            if candidate_zone:
                next(x for x in zones if x["zone_ref"] == candidate_zone)["routes"].append(payload)

        # Deterministic encounter anchors are gameplay slots only. Actor spawning remains Stage07 authority.
        for z in zones:
            state_ref = z["state_ref"]
            for i in range(2):
                digest = hashlib.sha256(f"{self._world_seed()}|{z['zone_ref']}|encounter|{i}".encode()).hexdigest()
                u = int(digest[:8], 16) / 0xFFFFFFFF
                v = int(digest[8:16], 16) / 0xFFFFFFFF
                bb = z["bounding_region"]
                lon = float(bb[0]) + (float(bb[2])-float(bb[0])) * u
                lat = float(bb[1]) + (float(bb[3])-float(bb[1])) * v
                z["encounter_anchors"].append({
                    "anchor_ref": f"ENC-{z['zone_ref']}-{i+1:02d}",
                    "coordinate": {"longitude": round(lon, 6), "latitude": round(lat, 6), "altitude_m": 0.0},
                    "actor_authority": "STAGE07_ACTOR_CORE",
                    "spawn_policy": "GAMEPLAY_DERIVED_DETERMINISTIC_SLOT",
                    "state_ref": state_ref,
                })
            self._save_zone(z)
        return {"status": "PASS", "zones": len(zones), "dungeons": sum(len(z["dungeons"]) for z in zones)}

    def _world_seed(self) -> int:
        row = self.runtime.conn.execute("SELECT seed FROM worlds WHERE world_instance_id=?", (self.world_instance_id,)).fetchone()
        return int(row["seed"] if row else self.country.seed)

    def list_zones(self) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_world_zones WHERE world_instance_id=? ORDER BY zone_ref",
            (self.world_instance_id,),
        ).fetchall()
        out = []
        for row in rows:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise IntegrityError("ARPG world zone hash mismatch")
            out.append(json.loads(row["payload_json"]))
        return out

    def zone(self, zone_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_world_zones WHERE world_instance_id=? AND zone_ref=?",
            (self.world_instance_id, str(zone_ref)),
        ).fetchone()
        if not row:
            raise NotFoundError("world zone not found:" + str(zone_ref))
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("ARPG world zone hash mismatch")
        return json.loads(row["payload_json"])

    def _find_start_zone(self) -> tuple[str, str | None]:
        for z in self.list_zones():
            for wp in z.get("waypoints", []):
                if wp["waypoint_ref"] == "WP-CANON-CIT-001":
                    return z["zone_ref"], wp["waypoint_ref"]
        zones = self.list_zones()
        if not zones:
            raise IntegrityError("Stage08 has no playable zones")
        return zones[0]["zone_ref"], None

    def _profile_row(self, profile_ref: str):
        return self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_world_profile_state WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()

    def _save_profile(self, state: dict[str, Any]) -> None:
        text, h = self._payload(state)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_world_profile_state(world_instance_id,profile_ref,payload_json,payload_hash) VALUES(?,?,?,?)",
                (self.world_instance_id, state["profile_ref"], text, h),
            )

    def ensure_profile(self, profile_ref: str) -> dict[str, Any]:
        row = self._profile_row(profile_ref)
        if row:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise IntegrityError("ARPG world profile hash mismatch")
            return json.loads(row["payload_json"])
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        start_zone, start_wp = self._find_start_zone()
        state = {
            "profile_ref": profile_ref,
            "avatar_ref": profile["avatar_ref"],
            "country_ref": self.PILOT_TERRITORY_ID,
            "zone_ref": start_zone,
            "instance_context": {"kind": "OVERWORLD", "ref": start_zone},
            "discovered_waypoints": [start_wp] if start_wp else [],
            "visited_zones": [start_zone],
            "boundary_policy": "ONE_COUNTRY_ONLY",
            "art_dependency": self.ART_DEPENDENCY,
            "authority": self.AUTHORITY,
        }
        self._save_profile(state)
        return copy.deepcopy(state)

    def _bootstrap_existing_profiles(self) -> None:
        try:
            for p in self.engine.arpg(self.world_instance_id).list_profiles():
                self.ensure_profile(p["profile_ref"])
        except Exception:
            return

    def profile_state(self, profile_ref: str) -> dict[str, Any]:
        return self.ensure_profile(profile_ref)

    def _event_hash(self, profile_ref: str, event_type: str, payload: dict[str, Any]) -> str:
        return sha256_text(canonical_json({"profile_ref": profile_ref, "event_type": event_type, "payload": payload}))

    def _event(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        event_ref = str(event_ref).strip()
        if not event_ref or len(event_ref) > 180:
            raise ValidationError("event_ref must contain 1-180 characters")
        h = self._event_hash(profile_ref, event_type, payload)
        row = self.runtime.conn.execute(
            "SELECT * FROM arpg_world_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, event_ref),
        ).fetchone()
        if row:
            if row["event_hash"] != h:
                raise ConflictError("WORLD_EVENT_REF_CONFLICT")
            out = json.loads(row["result_json"])
            out["idempotent_replay"] = True
            out["world_server_sequence"] = int(row["server_sequence"])
            return out
        with self.runtime._write_lock:
            cur = self.runtime.conn.execute(
                "INSERT INTO arpg_world_events(world_instance_id,profile_ref,event_ref,event_type,payload_json,result_json,event_hash) VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, profile_ref, event_ref, event_type, canonical_json(payload), canonical_json(result), h),
            )
        out = copy.deepcopy(result)
        out["world_server_sequence"] = int(cur.lastrowid)
        return out

    def _waypoint(self, waypoint_ref: str) -> dict[str, Any]:
        for z in self.list_zones():
            for wp in z.get("waypoints", []):
                if wp.get("waypoint_ref") == waypoint_ref:
                    return copy.deepcopy(wp)
        raise NotFoundError("waypoint not found:" + str(waypoint_ref))

    def discover_waypoint(self, profile_ref: str, waypoint_ref: str, *, event_ref: str) -> dict[str, Any]:
        state = self.ensure_profile(profile_ref)
        wp = self._waypoint(waypoint_ref)
        payload = {"waypoint_ref": waypoint_ref}
        if waypoint_ref not in state["discovered_waypoints"]:
            state["discovered_waypoints"].append(waypoint_ref)
            state["discovered_waypoints"].sort()
            self._save_profile(state)
        result = {"status": "PASS", "profile_ref": profile_ref, "waypoint_ref": waypoint_ref, "zone_ref": wp["zone_ref"], "discovered": True}
        return self._event(profile_ref, event_ref, "WAYPOINT_DISCOVER", payload, result)

    def fast_travel(self, profile_ref: str, waypoint_ref: str, *, event_ref: str) -> dict[str, Any]:
        state = self.ensure_profile(profile_ref)
        wp = self._waypoint(waypoint_ref)
        payload = {"waypoint_ref": waypoint_ref}
        if waypoint_ref not in state.get("discovered_waypoints", []):
            return self._event(profile_ref, event_ref, "WAYPOINT_TRAVEL", payload, {"status": "REJECTED", "reason": "WAYPOINT_NOT_DISCOVERED"})
        try:
            if self.engine.character(self.world_instance_id).state(profile_ref).get("vital_state") == "DEAD":
                return self._event(profile_ref, event_ref, "WAYPOINT_TRAVEL", payload, {"status": "REJECTED", "reason": "CHARACTER_DEAD"})
        except Exception:
            pass
        state["zone_ref"] = wp["zone_ref"]
        state["instance_context"] = {"kind": "OVERWORLD", "ref": wp["zone_ref"]}
        if wp["zone_ref"] not in state["visited_zones"]:
            state["visited_zones"].append(wp["zone_ref"])
        self._save_profile(state)
        result = {"status": "PASS", "profile_ref": profile_ref, "waypoint_ref": waypoint_ref, "zone_ref": wp["zone_ref"], "coordinate": wp["coordinate"]}
        return self._event(profile_ref, event_ref, "WAYPOINT_TRAVEL", payload, result)

    def enter_dungeon(self, profile_ref: str, dungeon_ref: str, *, event_ref: str) -> dict[str, Any]:
        state = self.ensure_profile(profile_ref)
        zone = self.zone(state["zone_ref"])
        d = next((x for x in zone.get("dungeons", []) if x.get("dungeon_ref") == dungeon_ref), None)
        payload = {"dungeon_ref": dungeon_ref}
        if d is None:
            return self._event(profile_ref, event_ref, "DUNGEON_ENTER", payload, {"status": "REJECTED", "reason": "DUNGEON_NOT_IN_CURRENT_ZONE"})
        state["instance_context"] = {"kind": "DUNGEON", "ref": dungeon_ref, "zone_ref": zone["zone_ref"]}
        self._save_profile(state)
        return self._event(profile_ref, event_ref, "DUNGEON_ENTER", payload, {"status": "PASS", "profile_ref": profile_ref, "dungeon_ref": dungeon_ref, "zone_ref": zone["zone_ref"], "dungeon": d})

    def exit_dungeon(self, profile_ref: str, *, event_ref: str) -> dict[str, Any]:
        state = self.ensure_profile(profile_ref)
        payload = {"from": copy.deepcopy(state.get("instance_context"))}
        if (state.get("instance_context") or {}).get("kind") != "DUNGEON":
            return self._event(profile_ref, event_ref, "DUNGEON_EXIT", payload, {"status": "REJECTED", "reason": "NOT_IN_DUNGEON"})
        state["instance_context"] = {"kind": "OVERWORLD", "ref": state["zone_ref"]}
        self._save_profile(state)
        return self._event(profile_ref, event_ref, "DUNGEON_EXIT", payload, {"status": "PASS", "profile_ref": profile_ref, "zone_ref": state["zone_ref"]})

    def boundary_route(self, route_ref: str) -> dict[str, Any]:
        for z in self.list_zones():
            for route in z.get("routes", []):
                if route.get("route_ref") == route_ref:
                    return copy.deepcopy(route)
        records = self._records()
        route = records["routes"].get(route_ref)
        if not route:
            raise NotFoundError("route not found:" + str(route_ref))
        return {"route_ref": route_ref, **self._route_scope(route, records), "source_authority": "MASTER_ROUTE_READ_ONLY"}

    def environment_sample(self, zone_ref: str, *, step: int = 0) -> dict[str, Any]:
        zone = self.zone(zone_ref)
        env = zone["environment"]
        climate = self._records()["climate"][self.CLIMATE_ID]
        lo_t, hi_t = map(float, climate.get("temperature_c_typical", [2, 33]))
        lo_p, hi_p = map(float, climate.get("annual_precipitation_mm", [420, 950]))
        seed_material = f"{self._world_seed()}|{zone_ref}|weather|{int(step)}"
        digest = hashlib.sha256(seed_material.encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        temp = rng.uniform(lo_t, hi_t)
        annual_p = rng.uniform(lo_p, hi_p)
        rain_intensity = max(0.0, min(1.0, (annual_p-lo_p)/max(1.0, hi_p-lo_p) * rng.random()))
        hazards = list(climate.get("hazards", []))
        active_hazard = hazards[int(rng.random()*len(hazards)) % len(hazards)] if hazards and rng.random() < 0.18 else None
        return {
            "status": "PASS",
            "zone_ref": zone_ref,
            "step": int(step),
            "biome_primary": self.PRIMARY_BIOME_ID,
            "biome_major": self.MAJOR_BIOME_ID,
            "climate_ref": self.CLIMATE_ID,
            "temperature_c": round(temp, 2),
            "annual_precipitation_reference_mm": round(annual_p, 2),
            "rain_intensity_0_1": round(rain_intensity, 4),
            "wind": climate.get("wind"),
            "active_hazard_runtime": active_hazard,
            "hydrology_refs": list(self.HYDROLOGY_IDS),
            "determinism_basis": "WORLD_SEED+ZONE_REF+STEP",
            "canonical_limits_preserved": True,
            "authority": self.AUTHORITY,
        }

    def snapshot(self, profile_ref: str | None = None) -> dict[str, Any]:
        zones = self.list_zones()
        out = {
            "status": "PASS",
            "version": self.VERSION,
            "country": {"id": self.PILOT_TERRITORY_ID, "name": self.PILOT_TERRITORY_NAME, "playable_country_count": 1},
            "zones": zones,
            "zone_count": len(zones),
            "dungeon_count": sum(len(z.get("dungeons", [])) for z in zones),
            "waypoint_count": sum(len(z.get("waypoints", [])) for z in zones),
            "boundary_gate_count": sum(1 for z in zones for r in z.get("routes", []) if r.get("boundary_locked")),
            "canonical_catalog_counts": self.canonical_catalog()["counts"],
            "stage09_resource_gate": True,
            "stage10_mobility_gate": True,
            "art_dependency": self.ART_DEPENDENCY,
            "authority": self.AUTHORITY,
        }
        if profile_ref is not None:
            st = self.ensure_profile(profile_ref)
            out["profile_world_state"] = st
            out["environment"] = self.environment_sample(st["zone_ref"], step=0)
        return out

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        catalog = self.canonical_catalog()
        for key, expected in EXPECTED_CANON_COUNTS.items():
            got = catalog["counts"].get(key)
            if got != expected:
                failures.append(f"CANON_COUNT:{key}:{got}!={expected}")
        zones = self.list_zones()
        block_count = sum(len(s.get("blocks", [])) for s in self.country.world["country"].get("states", []))
        if len(zones) != block_count:
            failures.append("ZONE_BLOCK_COUNT_MISMATCH")
        if not zones:
            failures.append("NO_PLAYABLE_ZONES")
        for z in zones:
            if z.get("country_ref") != self.PILOT_TERRITORY_ID:
                failures.append("SECOND_COUNTRY_PLAYABLE:" + z.get("zone_ref", "?"))
            biome = z.get("biome") or {}
            if biome.get("primary_id") != self.PRIMARY_BIOME_ID or biome.get("major_system_id") != self.MAJOR_BIOME_ID:
                failures.append("BIOME_BINDING:" + z.get("zone_ref", "?"))
            if (z.get("environment") or {}).get("canonical_climate_id") != self.CLIMATE_ID:
                failures.append("CLIMATE_BINDING:" + z.get("zone_ref", "?"))
            legacy_biome = (biome.get("legacy_procedural_classification") or {})
            overlay = z.get("anomaly_overlay")
            if legacy_biome.get("class") == "ROOT_DEEP":
                if not overlay or overlay.get("overlay_id") != "BIO-ROOT-DEEP" or not overlay.get("predator_only"):
                    failures.append("ROOT_DEEP_OVERLAY_MISSING:" + z.get("zone_ref", "?"))
            elif overlay is not None:
                failures.append("ROOT_DEEP_OVERLAY_SPURIOUS:" + z.get("zone_ref", "?"))
            for route in z.get("routes", []):
                if route.get("playability") == "PLAYABLE_INTERNAL" and route.get("boundary_locked"):
                    failures.append("ROUTE_SCOPE_CONFLICT:" + route.get("route_ref", "?"))
        for rid in ("RTE-001", "RTE-003", "RTE-013"):
            rs = self.boundary_route(rid)
            if rs.get("playability") != "BOUNDARY_GATE_ONLY" or not rs.get("boundary_locked"):
                failures.append("PILOT_OUTBOUND_ROUTE_NOT_LOCKED:" + rid)
        start_zone, start_wp = self._find_start_zone()
        if not start_zone or start_wp != "WP-CANON-CIT-001":
            failures.append("CANONICAL_START_WAYPOINT_MISSING")
        return {
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "zones": len(zones),
            "dungeons": sum(len(z.get("dungeons", [])) for z in zones),
            "waypoints": sum(len(z.get("waypoints", [])) for z in zones),
            "boundary_gates": sum(1 for z in zones for r in z.get("routes", []) if r.get("boundary_locked")),
            "canonical_catalog_counts": catalog["counts"],
            "playable_country_count": 1,
            "authority": self.AUTHORITY,
        }
