from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from living_runtime import ConflictError, ValidationError, canonical_json, sha256_text

# ============================================================================
# ARPG_STAGE17_CONSTRUCTION_PLACEMENT_RUNTIME_NOT_CANON
#
# Achado da auditoria de 13/09 (fase 5, vertical slice): as 24 pecas de
# construcao do jogador (STELLAR_BUILDING_PIECES_CATALOG_DEV_V1_0.json - 8
# piece_types x 3 tiers) existiam so como CATALOGO, sem nenhum sistema de
# runtime pra colocar/remover/consultar pecas no mundo (nao e o mesmo que
# EST-XXX, que sao locais fixos do mundo/lore - isso e construcao do JOGADOR).
# Este arquivo fecha essa lacuna, autocontido (so runtime/world_instance_id,
# nunca country/spatial/engine inteiro), mesmo molde de idempotencia por
# event_ref ja usado em vehicle_movement.py/projectile_system.py.
#
# Posicao e guardada como iso_x_m/iso_y_m/altitude_m diretos (quem chama ja
# resolveu geodetico->isometrico via SpatialCoordinateSystem se precisar,
# igual combat_distance_states.py recebe `movement` em vez de fazer a
# conversao ele mesmo) - mantem este arquivo testavel sem nenhuma dependencia
# externa alem do catalogo de conteudo (JSON puro, sem zip).
# ============================================================================

AUTHORITY = "ARPG_STAGE17_CONSTRUCTION_PLACEMENT_RUNTIME_NOT_CANON"
VERSION = "V0.1.0-PRE-GODOT"


def _hash_state(d: dict[str, Any]) -> str:
    return sha256_text(canonical_json(d))


class ConstructionPlacementSystem:
    VERSION = VERSION
    AUTHORITY = AUTHORITY

    def __init__(self, runtime: Any, world_instance_id: str, content_root: str | Path | None = None) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.content_root = Path(content_root) if content_root else self._default_content_root()
        self._pieces: dict[str, dict[str, Any]] = {}
        self._load_catalog()
        self._init_db()

    @staticmethod
    def _default_content_root() -> Path:
        return Path(__file__).resolve().parents[5]

    def _load_catalog(self) -> None:
        path = (self.content_root / "04_MECANICAS" / "CONSTRUCAO_JOGADOR" /
                "STELLAR_BUILDING_PIECES_CATALOG_DEV_V1_0.json")
        if not path.is_file():
            raise FileNotFoundError(
                f"ConstructionPlacementSystem: catalogo de pecas nao encontrado em {path} "
                "- passe content_root explicito apontando pra raiz do projeto (ANDROMEDA_CODEX_CLEAN)."
            )
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        for piece in doc.get("pieces", []):
            self._pieces[piece["piece_id"]] = piece

    def known_piece_ids(self) -> list[str]:
        return sorted(self._pieces)

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_construction_placements(
                    world_instance_id TEXT NOT NULL, placement_ref TEXT NOT NULL,
                    owner_ref TEXT NOT NULL, piece_ref TEXT NOT NULL,
                    piece_type TEXT NOT NULL, tier TEXT NOT NULL,
                    iso_x_m REAL NOT NULL, iso_y_m REAL NOT NULL, altitude_m REAL NOT NULL DEFAULT 0,
                    rotation_deg REAL NOT NULL DEFAULT 0,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, placement_ref))"""
            )
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_construction_events(
                    world_instance_id TEXT NOT NULL, event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, event_ref))"""
            )

    # ---------- idempotencia (mesmo padrao de vehicle_movement.py) ----------

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_construction_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, str(event_ref)),
        ).fetchone()
        if not row:
            return None
        if sha256_text(canonical_json(payload)) != row["payload_hash"]:
            raise ConflictError(f"construction event_ref {event_ref} already used with a different payload")
        if row["event_type"] != event_type:
            raise ConflictError(f"construction event_ref {event_ref} already used for a different event_type")
        result = json.loads(row["result_json"])
        if sha256_text(row["result_json"]) != row["result_hash"]:
            raise ValueError("construction event result hash mismatch")
        return {**result, "idempotent_replay": True}

    def _record_event(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ptext = canonical_json(payload)
        rtext = canonical_json(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO v17_construction_events VALUES(?,?,?,?,?,?)",
                (self.world_instance_id, str(event_ref), event_type, sha256_text(ptext), rtext, sha256_text(rtext)),
            )
        return result

    # ---------- estado por peca colocada (hash-verificado) ----------

    def _row_state(self, r: Any) -> dict[str, Any]:
        d = {"placement_ref": r["placement_ref"], "owner_ref": r["owner_ref"], "piece_ref": r["piece_ref"],
             "piece_type": r["piece_type"], "tier": r["tier"], "iso_x_m": float(r["iso_x_m"]),
             "iso_y_m": float(r["iso_y_m"]), "altitude_m": float(r["altitude_m"]), "rotation_deg": float(r["rotation_deg"])}
        if _hash_state(d) != r["payload_hash"]:
            raise ValueError("construction placement state hash mismatch")
        return d

    def _read_state(self, placement_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_construction_placements WHERE world_instance_id=? AND placement_ref=?",
            (self.world_instance_id, str(placement_ref)),
        ).fetchone()
        if not row:
            raise KeyError(placement_ref)
        return self._row_state(row)

    def state(self, placement_ref: str) -> dict[str, Any]:
        return {**self._read_state(placement_ref), "authority": self.AUTHORITY}

    # ---------- comandos ----------

    def place_piece(self, owner_ref: str, piece_ref: str, *, iso_x_m: float, iso_y_m: float,
                     altitude_m: float = 0.0, rotation_deg: float = 0.0,
                     placement_ref: str, event_ref: str) -> dict[str, Any]:
        payload = {"owner_ref": owner_ref, "piece_ref": piece_ref, "iso_x_m": iso_x_m, "iso_y_m": iso_y_m,
                   "altitude_m": altitude_m, "rotation_deg": rotation_deg, "placement_ref": placement_ref}
        replay = self._event_existing(event_ref, "PIECE_PLACED", payload)
        if replay is not None:
            return replay

        piece = self._pieces.get(piece_ref)
        if piece is None:
            result = {"status": "REJECTED", "reason": "UNKNOWN_PIECE_REF", "piece_ref": piece_ref}
            return self._record_event(event_ref, "PIECE_PLACED", payload, result)

        existing = self.runtime.conn.execute(
            "SELECT 1 FROM v17_construction_placements WHERE world_instance_id=? AND placement_ref=?",
            (self.world_instance_id, str(placement_ref)),
        ).fetchone()
        if existing:
            result = {"status": "REJECTED", "reason": "PLACEMENT_REF_ALREADY_IN_USE", "placement_ref": placement_ref}
            return self._record_event(event_ref, "PIECE_PLACED", payload, result)

        d = {"placement_ref": placement_ref, "owner_ref": owner_ref, "piece_ref": piece_ref,
             "piece_type": piece["piece_type"], "tier": piece["tier"], "iso_x_m": float(iso_x_m),
             "iso_y_m": float(iso_y_m), "altitude_m": float(altitude_m), "rotation_deg": float(rotation_deg) % 360.0}
        h = _hash_state(d)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO v17_construction_placements VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (self.world_instance_id, placement_ref, owner_ref, piece_ref, piece["piece_type"], piece["tier"],
                 d["iso_x_m"], d["iso_y_m"], d["altitude_m"], d["rotation_deg"], h),
            )
        result = {"status": "PASS", "event_ref": event_ref, **d, "authority": self.AUTHORITY, "idempotent_replay": False}
        return self._record_event(event_ref, "PIECE_PLACED", payload, result)

    def remove_piece(self, placement_ref: str, *, requested_by_ref: str, event_ref: str) -> dict[str, Any]:
        payload = {"placement_ref": placement_ref, "requested_by_ref": requested_by_ref}
        replay = self._event_existing(event_ref, "PIECE_REMOVED", payload)
        if replay is not None:
            return replay

        try:
            current = self._read_state(placement_ref)
        except KeyError:
            result = {"status": "REJECTED", "reason": "PLACEMENT_NOT_FOUND", "placement_ref": placement_ref}
            return self._record_event(event_ref, "PIECE_REMOVED", payload, result)

        if current["owner_ref"] != requested_by_ref:
            result = {"status": "REJECTED", "reason": "NOT_OWNER", "placement_ref": placement_ref}
            return self._record_event(event_ref, "PIECE_REMOVED", payload, result)

        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "DELETE FROM v17_construction_placements WHERE world_instance_id=? AND placement_ref=?",
                (self.world_instance_id, str(placement_ref)),
            )
        result = {"status": "PASS", "event_ref": event_ref, "placement_ref": placement_ref,
                  "authority": self.AUTHORITY, "idempotent_replay": False}
        return self._record_event(event_ref, "PIECE_REMOVED", payload, result)

    def pieces_in_area(self, center_x_m: float, center_y_m: float, radius_m: float) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_construction_placements WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        found = []
        for r in rows:
            d = self._row_state(r)
            if math.hypot(d["iso_x_m"] - center_x_m, d["iso_y_m"] - center_y_m) <= radius_m:
                found.append(d)
        return found

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_construction_placements WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in rows:
            try:
                self._row_state(r)
            except ValueError as e:
                failures.append(f"PLACEMENT_HASH:{r['placement_ref']}:{e}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "placements": len(rows)}
