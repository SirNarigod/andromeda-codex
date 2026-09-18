from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from living_runtime import ValidationError, ConflictError, IntegrityError, canonical_json, sha256_text


class ARPGSaveRecoveryCore:
    """Stage 15 save/recovery authority.

    Full-state saves are SQLite snapshots protected by SHA-256, SQLite integrity/foreign-key
    checks and a compact continuity fingerprint. Death recovery is gameplay-derived and does
    not mutate canon. Snapshots never auto-repair corrupted bytes: rollback promotes only a
    previously verified generation.
    """

    VERSION = "V1.6.0"
    STAGE = "15/23"
    AUTHORITY = "ARPG_STAGE15_SAVE_PERSISTENCE_DEATH_RECOVERY"
    DEFAULT_WAYPOINT = "WP-CANON-CIT-001"
    HEALTH_RECOVERY_RATIO = 0.50
    RESOURCE_RECOVERY_RATIO = 0.35
    MAX_SLOTS = 8
    OFFLINE_CATCHUP_CAP_S = 6 * 60 * 60

    CRITICAL_TABLES = (
        "worlds", "clocks", "arpg_player_profiles", "arpg_character_state",
        "arpg_item_inventories", "arpg_item_instances", "arpg_world_profile_state",
        "arpg_quest_state", "arpg_economy_profile_state", "arpg_machine_state",
        "arpg_vehicle_state", "arpg_living_reconciliation_state",
    )

    def __init__(self, engine: Any, world_instance_id: str, *, save_root: str | Path | None = None) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = world_instance_id
        self.save_root = self._resolve_save_root(save_root)
        self.save_root.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._bootstrap_profiles()

    def _resolve_save_root(self, save_root: str | Path | None) -> Path:
        if save_root is not None:
            return Path(save_root)
        db = str(self.runtime.db_path)
        if db == ":memory:":
            raise ValidationError("Stage15 snapshots require save_root when db_path=':memory:'")
        p = Path(db).resolve()
        return p.parent / (p.stem + "_saves")

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_recovery_profiles(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_recovery_events(
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
                CREATE INDEX IF NOT EXISTS idx_arpg_recovery_events_profile
                    ON arpg_recovery_events(world_instance_id, profile_ref, server_sequence);
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_save_recovery_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def _file_sha256(path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _bootstrap_profiles(self) -> None:
        try:
            for p in self.engine.arpg(self.world_instance_id).list_profiles():
                self.ensure_profile(p["profile_ref"])
        except Exception:
            return

    def _profile_row(self, profile_ref: str):
        return self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_recovery_profiles WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()

    def _default_waypoint(self) -> str:
        try:
            self.engine.world_arpg(self.world_instance_id)._waypoint(self.DEFAULT_WAYPOINT)
            return self.DEFAULT_WAYPOINT
        except Exception:
            zones = self.engine.world_arpg(self.world_instance_id).list_zones()
            for z in zones:
                if z.get("waypoints"):
                    return str(z["waypoints"][0]["waypoint_ref"])
        raise IntegrityError("no safe waypoint available for recovery")

    def ensure_profile(self, profile_ref: str) -> dict[str, Any]:
        row = self._profile_row(profile_ref)
        if row:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise IntegrityError("recovery profile hash mismatch")
            return json.loads(row["payload_json"])
        self.engine.arpg(self.world_instance_id).profile(profile_ref)
        state = {
            "profile_ref": profile_ref,
            "last_safe_waypoint_ref": self._default_waypoint(),
            "death_count": 0,
            "last_recovery_event_ref": None,
            "death_policy": "NO_PERMANENT_XP_OR_ITEM_LOSS_STAGE15",
            "health_recovery_ratio": self.HEALTH_RECOVERY_RATIO,
            "resource_recovery_ratio": self.RESOURCE_RECOVERY_RATIO,
            "authority": self.AUTHORITY,
        }
        self._save_profile(state)
        return copy.deepcopy(state)

    def _save_profile(self, state: dict[str, Any]) -> None:
        text = canonical_json(state); h = sha256_text(text)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_recovery_profiles VALUES(?,?,?,?)",
                (self.world_instance_id, state["profile_ref"], text, h),
            )

    def set_safe_waypoint(self, profile_ref: str, waypoint_ref: str, *, event_ref: str) -> dict[str, Any]:
        wp = self.engine.world_arpg(self.world_instance_id)._waypoint(str(waypoint_ref))
        state = self.ensure_profile(profile_ref)
        payload = {"waypoint_ref": wp["waypoint_ref"]}
        existing = self._event_existing(event_ref, profile_ref, "SAFE_WAYPOINT", payload)
        if existing is not None:
            return existing
        state["last_safe_waypoint_ref"] = wp["waypoint_ref"]
        self._save_profile(state)
        return self._record_event(profile_ref, event_ref, "SAFE_WAYPOINT", payload, {
            "status": "PASS", "profile_ref": profile_ref, "waypoint_ref": wp["waypoint_ref"],
            "zone_ref": wp["zone_ref"], "idempotent_replay": False,
        })

    def _event_hash(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any]) -> str:
        return sha256_text(canonical_json({"profile_ref": profile_ref, "event_ref": event_ref, "event_type": event_type, "payload": payload}))

    def _event_existing(self, event_ref: str, profile_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        event_ref = str(event_ref).strip()
        if not event_ref or len(event_ref) > 180:
            raise ValidationError("event_ref must contain 1-180 characters")
        row = self.runtime.conn.execute(
            "SELECT * FROM arpg_recovery_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, event_ref),
        ).fetchone()
        if not row:
            return None
        expected = self._event_hash(profile_ref, event_ref, event_type, payload)
        if row["event_hash"] != expected or row["profile_ref"] != profile_ref or row["event_type"] != event_type:
            raise ConflictError("RECOVERY_EVENT_REF_CONFLICT")
        out = json.loads(row["result_json"]); out["idempotent_replay"] = True
        return out

    def _record_event(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        h = self._event_hash(profile_ref, event_ref, event_type, payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO arpg_recovery_events(world_instance_id,profile_ref,event_ref,event_type,payload_json,result_json,event_hash) VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, profile_ref, event_ref, event_type, canonical_json(payload), canonical_json(result), h),
            )
        return copy.deepcopy(result)

    def recover_death(self, profile_ref: str, *, event_ref: str) -> dict[str, Any]:
        state = self.ensure_profile(profile_ref)
        payload = {"policy": "SAFE_WAYPOINT_RECOVERY", "waypoint_ref": state["last_safe_waypoint_ref"]}
        existing = self._event_existing(event_ref, profile_ref, "DEATH_RECOVERY", payload)
        if existing is not None:
            return existing
        char_core = self.engine.character(self.world_instance_id)
        char = char_core.ensure_profile(profile_ref)
        if char["vitals"]["life_state"] != "DEAD":
            return self._record_event(profile_ref, event_ref, "DEATH_RECOVERY", payload, {
                "status": "REJECTED", "reason": "CHARACTER_NOT_DEAD", "idempotent_replay": False,
            })
        before_xp = int(char["experience"])
        inv_row = self.runtime.conn.execute(
            "SELECT payload_hash FROM arpg_item_inventories WHERE world_instance_id=? AND owner_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()
        before_inventory_hash = inv_row["payload_hash"] if inv_row else "EMPTY_NOT_MATERIALIZED"
        wp = self.engine.world_arpg(self.world_instance_id)._waypoint(state["last_safe_waypoint_ref"])

        char["vitals"]["life_state"] = "ALIVE"
        char["vitals"]["health"] = round(float(char["derived"]["max_health"]) * self.HEALTH_RECOVERY_RATIO, 6)
        char["vitals"]["resource"] = round(float(char["derived"]["max_resource"]) * self.RESOURCE_RECOVERY_RATIO, 6)
        char_core._save(char)

        world_core = self.engine.world_arpg(self.world_instance_id)
        world_state = world_core.ensure_profile(profile_ref)
        world_state["zone_ref"] = wp["zone_ref"]
        world_state["instance_context"] = {"kind": "OVERWORLD", "ref": wp["zone_ref"]}
        if wp["zone_ref"] not in world_state.get("visited_zones", []):
            world_state.setdefault("visited_zones", []).append(wp["zone_ref"])
        world_core._save_profile(world_state)

        game = self.engine.arpg(self.world_instance_id)
        inp = game._input(profile_ref)
        inp.update({"selected_target_ref": None, "selected_target_kind": None, "move_target": None, "action_state": "IDLE", "last_block_reason": None})
        game._save_input(profile_ref, inp)

        state["death_count"] = int(state.get("death_count", 0)) + 1
        state["last_recovery_event_ref"] = event_ref
        self._save_profile(state)

        inv_row_after = self.runtime.conn.execute(
            "SELECT payload_hash FROM arpg_item_inventories WHERE world_instance_id=? AND owner_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()
        after_inventory_hash = inv_row_after["payload_hash"] if inv_row_after else "EMPTY_NOT_MATERIALIZED"
        result = {
            "status": "PASS", "profile_ref": profile_ref, "waypoint_ref": wp["waypoint_ref"], "zone_ref": wp["zone_ref"],
            "health_after": char["vitals"]["health"], "resource_after": char["vitals"]["resource"],
            "experience_preserved": int(char["experience"]) == before_xp,
            "inventory_preserved": before_inventory_hash == after_inventory_hash,
            "left_dungeon": True, "death_count": state["death_count"], "idempotent_replay": False,
        }
        # Automatic post-death snapshot is intentionally best-effort; gameplay recovery must not be rolled back by I/O failure.
        try:
            auto = self.create_snapshot("autosave", kind="POST_DEATH_AUTOSAVE")
            result["autosave_status"] = auto["status"]
        except Exception as exc:
            result["autosave_status"] = "FAILED_NON_BLOCKING"
            result["autosave_error"] = type(exc).__name__
        return self._record_event(profile_ref, event_ref, "DEATH_RECOVERY", payload, result)

    @staticmethod
    def _safe_slot(slot_ref: str) -> str:
        s = str(slot_ref).strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", s):
            raise ValidationError("slot_ref must match [a-z0-9_-]{1,40}")
        return s

    def _paths(self, slot_ref: str, generation: str) -> tuple[Path, Path]:
        slot = self._safe_slot(slot_ref)
        gen = generation.lower()
        if gen not in {"current", "previous"}:
            raise ValidationError("generation must be current or previous")
        return self.save_root / f"{slot}.{gen}.sqlite", self.save_root / f"{slot}.{gen}.json"

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    def _fingerprint_conn(self, conn: sqlite3.Connection) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in self.CRITICAL_TABLES:
            if self._table_exists(conn, table):
                out[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        return out

    def _snapshot_meta(self, db_path: Path, slot_ref: str, kind: str, generation: str) -> dict[str, Any]:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
            row = conn.execute("SELECT world_instance_id,master_version,release_sha256,seed,status FROM worlds WHERE world_instance_id=?", (self.world_instance_id,)).fetchone()
            if not row:
                raise IntegrityError("snapshot world missing")
            fp = self._fingerprint_conn(conn)
        finally:
            conn.close()
        if integrity != "ok" or fk:
            raise IntegrityError("snapshot SQLite integrity failure")
        return {
            "version": self.VERSION, "authority": self.AUTHORITY, "slot_ref": slot_ref, "kind": kind,
            "generation": generation, "world_instance_id": self.world_instance_id,
            "master_version": row[1], "master_release_sha256": row[2], "seed": int(row[3]), "world_status": row[4],
            "created_unix": int(time.time()), "db_sha256": self._file_sha256(db_path), "fingerprint": fp,
            "offline_policy": {"mode": "EXPLICIT_CATCHUP_ONLY", "cap_seconds": self.OFFLINE_CATCHUP_CAP_S},
        }

    def create_snapshot(self, slot_ref: str, *, kind: str = "MANUAL") -> dict[str, Any]:
        slot = self._safe_slot(slot_ref)
        kind = str(kind).strip().upper() or "MANUAL"
        current_db, current_meta = self._paths(slot, "current")
        prev_db, prev_meta = self._paths(slot, "previous")
        tmp = self.save_root / f".{slot}.tmp.sqlite"
        tmp_meta = self.save_root / f".{slot}.tmp.json"
        for p in (tmp, tmp_meta):
            if p.exists(): p.unlink()
        # Rotate only a previously verified current generation.
        if current_db.exists() and current_meta.exists():
            v = self.verify_slot(slot, generation="current")
            if v["status"] != "PASS":
                raise IntegrityError("cannot rotate an invalid current save")
            shutil.copy2(current_db, prev_db)
            shutil.copy2(current_meta, prev_meta)
            pm = json.loads(prev_meta.read_text(encoding="utf-8")); pm["generation"] = "previous"
            prev_meta.write_text(json.dumps(pm, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        dest = sqlite3.connect(str(tmp))
        try:
            with dest:
                self.runtime.conn.backup(dest)
        finally:
            dest.close()
        meta = self._snapshot_meta(tmp, slot, kind, "current")
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        os.replace(tmp, current_db); os.replace(tmp_meta, current_meta)
        return {"status": "PASS", "slot_ref": slot, "generation": "current", "kind": kind, "sha256": meta["db_sha256"], "fingerprint": meta["fingerprint"]}

    def verify_slot(self, slot_ref: str, *, generation: str = "current") -> dict[str, Any]:
        slot = self._safe_slot(slot_ref)
        db_path, meta_path = self._paths(slot, generation)
        failures: list[str] = []
        if not db_path.exists(): failures.append("SNAPSHOT_MISSING")
        if not meta_path.exists(): failures.append("METADATA_MISSING")
        if failures: return {"status": "FAIL", "failures": failures, "slot_ref": slot, "generation": generation}
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "FAIL", "failures": ["METADATA_INVALID"], "slot_ref": slot, "generation": generation}
        actual = self._file_sha256(db_path)
        if actual != meta.get("db_sha256"): failures.append("SHA256_MISMATCH")
        conn = None
        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok": failures.append("SQLITE_INTEGRITY_FAIL")
            if conn.execute("PRAGMA foreign_key_check").fetchall(): failures.append("FOREIGN_KEY_FAIL")
            row = conn.execute("SELECT master_version,release_sha256 FROM worlds WHERE world_instance_id=?", (self.world_instance_id,)).fetchone()
            if not row: failures.append("WORLD_MISSING")
            else:
                if row[0] != self.runtime.master_version: failures.append("MASTER_VERSION_MISMATCH")
                if row[1] != self.runtime.master_release_sha256: failures.append("MASTER_RELEASE_MISMATCH")
            if self._fingerprint_conn(conn) != meta.get("fingerprint"): failures.append("FINGERPRINT_MISMATCH")
        except sqlite3.DatabaseError:
            failures.append("SQLITE_OPEN_FAIL")
        finally:
            if conn is not None: conn.close()
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "slot_ref": slot, "generation": generation, "sha256": actual}

    def rollback_slot(self, slot_ref: str) -> dict[str, Any]:
        slot = self._safe_slot(slot_ref)
        check = self.verify_slot(slot, generation="previous")
        if check["status"] != "PASS":
            raise IntegrityError("previous save generation is not valid")
        cur_db, cur_meta = self._paths(slot, "current"); prev_db, prev_meta = self._paths(slot, "previous")
        tmp_db = self.save_root / f".{slot}.rollback.sqlite"; tmp_meta = self.save_root / f".{slot}.rollback.json"
        shutil.copy2(prev_db, tmp_db); shutil.copy2(prev_meta, tmp_meta)
        meta = json.loads(tmp_meta.read_text(encoding="utf-8")); meta["generation"] = "current"
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        os.replace(tmp_db, cur_db); os.replace(tmp_meta, cur_meta)
        return {"status": "PASS", "slot_ref": slot, "generation": "current", "source_generation": "previous", "sha256": meta["db_sha256"]}

    def restore_slot_to(self, slot_ref: str, target_db_path: str | Path, *, generation: str = "current") -> dict[str, Any]:
        check = self.verify_slot(slot_ref, generation=generation)
        if check["status"] != "PASS": raise IntegrityError("cannot restore invalid snapshot")
        src, _ = self._paths(slot_ref, generation); target = Path(target_db_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        shutil.copy2(src, tmp); os.replace(tmp, target)
        return {"status": "PASS", "slot_ref": self._safe_slot(slot_ref), "generation": generation, "target_db_path": str(target), "sha256": self._file_sha256(target)}

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        for table in ("arpg_recovery_profiles", "arpg_recovery_events"):
            if not self._table_exists(self.runtime.conn, table): failures.append("TABLE_MISSING:"+table)
        row = self.runtime.conn.execute("SELECT value FROM runtime_meta WHERE key='arpg_save_recovery_version'").fetchone()
        if not row or row[0] != self.VERSION: failures.append("VERSION_META_MISMATCH")
        if self.runtime.master_version != "V2.0.1": failures.append("MASTER_VERSION_NOT_V2_0_1")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "version": self.VERSION, "authority": self.AUTHORITY, "save_root": str(self.save_root)}
