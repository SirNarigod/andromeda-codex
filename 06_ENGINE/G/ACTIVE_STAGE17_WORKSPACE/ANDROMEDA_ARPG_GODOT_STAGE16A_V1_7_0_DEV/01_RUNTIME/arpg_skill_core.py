from __future__ import annotations

import copy
import json
import math
import zipfile
from typing import Any

from living_runtime import ValidationError, ConflictError, IntegrityError, NotFoundError, canonical_json, sha256_text

MAGIC_PATH = "ANDROMEDA_CODEX_MASTER/05_MAR/FUNCTIONAL/01_MAR/MAR_MAGIC_FUNCTIONAL_V1_0.json"

# Replaceable gameplay scaffolding. These definitions prove the skill/build architecture and are
# not canonical lore. Canonical MAG-* records are imported separately as read-only source skills.
GAMEPLAY_SKILLS: dict[str, dict[str, Any]] = {
    "SKL-GP-POWER-STRIKE": {
        "name": "Power Strike (Gameplay)", "skill_kind": "ACTIVE", "targeting": "TARGET_ENEMY",
        "effect_model": "TARGET_DAMAGE", "damage_type": "PHYSICAL", "power_multiplier": 1.45,
        "range_bonus_m": 0.0, "accuracy_bonus": -3.0, "crit_bonus_pct": 2.0,
        "resource_cost": 14.0, "cooldown_s": 1.20, "global_cooldown_s": 0.25, "recovery_s": 0.55,
        "axes": {"MARTIAL": 1.0, "OFFENSE": 0.8, "POWER": 0.6},
    },
    "SKL-GP-PRECISION-STRIKE": {
        "name": "Precision Strike (Gameplay)", "skill_kind": "ACTIVE", "targeting": "TARGET_ENEMY",
        "effect_model": "TARGET_DAMAGE", "damage_type": "PHYSICAL", "power_multiplier": 1.05,
        "range_bonus_m": 0.5, "accuracy_bonus": 18.0, "crit_bonus_pct": 8.0,
        "resource_cost": 10.0, "cooldown_s": 0.80, "global_cooldown_s": 0.20, "recovery_s": 0.35,
        "axes": {"MARTIAL": 0.8, "PERCEPTION": 1.0, "OFFENSE": 0.5},
    },
    "SKL-GP-FOCUS-PULSE": {
        "name": "Focus Pulse (Gameplay)", "skill_kind": "ACTIVE", "targeting": "TARGET_ENEMY",
        "effect_model": "TARGET_DAMAGE", "damage_type": "ARCANE", "power_multiplier": 1.15,
        "range_bonus_m": 3.25, "accuracy_bonus": 6.0, "crit_bonus_pct": 3.0,
        "resource_cost": 22.0, "cooldown_s": 1.60, "global_cooldown_s": 0.30, "recovery_s": 0.45,
        "axes": {"ARCANE": 1.0, "OFFENSE": 0.7, "PERCEPTION": 0.3},
    },
    "SKL-GP-GUARD-DISCIPLINE": {
        "name": "Guard Discipline (Gameplay)", "skill_kind": "PASSIVE", "targeting": "NONE",
        "effect_model": "PASSIVE_COMBAT_MODIFIER", "passive_modifiers": {"armor_flat": 8.0, "resistance:PHYSICAL": 0.0},
        "axes": {"DEFENSE": 1.0, "MARTIAL": 0.4},
    },
    "SKL-GP-SWIFT-DISCIPLINE": {
        "name": "Swift Discipline (Gameplay)", "skill_kind": "PASSIVE", "targeting": "NONE",
        "effect_model": "PASSIVE_COMBAT_MODIFIER", "passive_modifiers": {"evasion_flat": 5.0, "attack_speed_pct": 3.0},
        "axes": {"MOBILITY": 1.0, "MARTIAL": 0.3},
    },
    "SKL-GP-FOCUS-DISCIPLINE": {
        "name": "Focus Discipline (Gameplay)", "skill_kind": "PASSIVE", "targeting": "NONE",
        "effect_model": "PASSIVE_COMBAT_MODIFIER", "passive_modifiers": {"accuracy_flat": 5.0, "crit_chance_pct": 1.0, "resistance:ARCANE": 3.0},
        "axes": {"PERCEPTION": 0.8, "ARCANE": 0.8, "DEFENSE": 0.2},
    },
}

AXES = ("MARTIAL", "ARCANE", "OFFENSE", "DEFENSE", "MOBILITY", "PERCEPTION", "SUPPORT", "UTILITY")


class ARPGSkillCore:
    """Stage06 skill and emergent-build authority.

    Canonical MAG-* entries are imported read-only as lore-bound skill sources, never silently
    converted into numeric player powers. Gameplay skill prototypes are explicitly derived and
    replaceable. Successful use accumulates evidence axes rather than assigning a fixed class.
    """

    VERSION = "V0.7.0"
    STAGE = "06/20"
    AUTHORITY = "ARPG_SKILLS_BUILD_PROGRESSION_GAMEPLAY_DERIVATION"
    ACTIVE_SLOTS = 8
    PASSIVE_SLOTS = 4
    MAX_SKILL_RANK = 10
    MASTERY_PER_USE = 10
    PASSIVE_MASTERY_SHARE = 2

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = world_instance_id
        self._init_schema()
        self.bootstrap_definitions()
        self.bootstrap_existing_profiles()

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_skill_definitions(
                    skill_ref TEXT PRIMARY KEY,
                    source_authority TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS arpg_skill_state(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref),
                    FOREIGN KEY(world_instance_id, profile_ref)
                      REFERENCES arpg_player_profiles(world_instance_id, profile_ref) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS arpg_skill_events(
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
                CREATE INDEX IF NOT EXISTS idx_arpg_skill_events_profile
                  ON arpg_skill_events(world_instance_id,profile_ref,server_sequence);
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_skill_core_version',?)", (self.VERSION,)
            )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(payload)
        return text, sha256_text(text)

    def _canonical_magic_definitions(self) -> list[dict[str, Any]]:
        path = self.runtime.master_release_path
        if not path:
            raise IntegrityError("Master release required for skill canon source import")
        with zipfile.ZipFile(path, "r") as zf:
            raw = json.loads(zf.read(MAGIC_PATH))
        out: list[dict[str, Any]] = []
        for rec in raw.get("magics", []):
            if not isinstance(rec, dict) or not rec.get("id"):
                continue
            out.append({
                "skill_ref": f"SKL-CANON-{rec['id']}",
                "name": rec.get("name") or rec["id"],
                "skill_kind": "CANONICAL_SOURCE",
                "targeting": "UNMAPPED",
                "effect_model": "LORE_BOUND_NO_RUNTIME_EFFECT",
                "canonical_ref": rec["id"],
                "canonical_status": rec.get("canonical_status"),
                "canonical_category": rec.get("category"),
                "canonical_effect": copy.deepcopy((rec.get("execution") or {}).get("effect")),
                "canonical_execution": copy.deepcopy(rec.get("execution") or {}),
                "canonical_limitations": copy.deepcopy(rec.get("limitations") or {}),
                "canonical_interoperability": copy.deepcopy(rec.get("interoperability") or {}),
                "player_castable_default": False,
                "runtime_mapping": "AUTHORIAL_OR_LATER_SYSTEM_MAPPING_REQUIRED",
                "source_authority": "MASTER_READ_ONLY",
                "art_dependency": "NONE",
                "authority": self.AUTHORITY,
            })
        return out

    def bootstrap_definitions(self) -> dict[str, Any]:
        defs: list[dict[str, Any]] = []
        for ref, spec in GAMEPLAY_SKILLS.items():
            d = copy.deepcopy(spec)
            d.update({
                "skill_ref": ref,
                "source_authority": "GAMEPLAY_DERIVED_REPLACEABLE",
                "canonical_ref": None,
                "player_castable_default": d.get("skill_kind") == "ACTIVE",
                "runtime_mapping": "ACTIVE_V0_7" if d.get("skill_kind") == "ACTIVE" else "PASSIVE_V0_7",
                "rank_policy": "USE_MASTERY_1_TO_10",
                "art_dependency": "NONE_PLACEHOLDER_READY",
                "authority": self.AUTHORITY,
            })
            defs.append(d)
        defs.extend(self._canonical_magic_definitions())
        inserted = 0
        with self.runtime._write_lock:
            for d in defs:
                text, h = self._hash_payload(d)
                row = self.runtime.conn.execute("SELECT payload_hash FROM arpg_skill_definitions WHERE skill_ref=?", (d["skill_ref"],)).fetchone()
                if row:
                    if row["payload_hash"] != h:
                        raise IntegrityError("ARPG skill definition drift:" + d["skill_ref"])
                    continue
                self.runtime.conn.execute("INSERT INTO arpg_skill_definitions VALUES(?,?,?,?)", (d["skill_ref"], d["source_authority"], text, h))
                inserted += 1
        return {"status": "PASS", "inserted": inserted, "definitions": len(defs), "canonical_sources": len(defs)-len(GAMEPLAY_SKILLS), "gameplay_prototypes": len(GAMEPLAY_SKILLS)}

    def definition(self, skill_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute("SELECT payload_json,payload_hash FROM arpg_skill_definitions WHERE skill_ref=?", (str(skill_ref),)).fetchone()
        if not row:
            raise NotFoundError("skill definition not found:" + str(skill_ref))
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("skill definition hash mismatch")
        return json.loads(row["payload_json"])

    def list_definitions(self) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute("SELECT payload_json,payload_hash FROM arpg_skill_definitions ORDER BY skill_ref").fetchall()
        out=[]
        for row in rows:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise IntegrityError("skill definition hash mismatch")
            out.append(json.loads(row["payload_json"]))
        return out

    def _initial_state(self, profile_ref: str) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        return {
            "profile_ref": profile_ref,
            "avatar_ref": profile["avatar_ref"],
            "learned": {},
            "active_loadout": {str(i): None for i in range(1, self.ACTIVE_SLOTS+1)},
            "passive_loadout": {str(i): None for i in range(1, self.PASSIVE_SLOTS+1)},
            "build_evidence": {axis: 0.0 for axis in AXES},
            "class_model": "EMERGENT_NO_FIXED_CLASS_LABEL",
            "canonical_magic_policy": "READ_ONLY_SOURCE_NOT_AUTO_CASTABLE",
            "authority": self.AUTHORITY,
        }

    def _row(self, profile_ref: str):
        return self.runtime.conn.execute("SELECT payload_json,payload_hash FROM arpg_skill_state WHERE world_instance_id=? AND profile_ref=?", (self.world_instance_id, profile_ref)).fetchone()

    def _save(self, state: dict[str, Any]) -> None:
        text,h=self._hash_payload(state)
        with self.runtime._write_lock:
            self.runtime.conn.execute("INSERT OR REPLACE INTO arpg_skill_state VALUES(?,?,?,?)", (self.world_instance_id,state["profile_ref"],text,h))

    def ensure_profile(self, profile_ref: str) -> dict[str, Any]:
        self.engine.character(self.world_instance_id).ensure_profile(profile_ref)
        row=self._row(profile_ref)
        if not row:
            self._save(self._initial_state(profile_ref))
        return self.state(profile_ref)

    def bootstrap_existing_profiles(self) -> None:
        try: profiles=self.engine.arpg(self.world_instance_id).list_profiles()
        except Exception: return
        for p in profiles:
            if not self._row(p["profile_ref"]): self._save(self._initial_state(p["profile_ref"]))

    def state(self, profile_ref: str) -> dict[str, Any]:
        row=self._row(profile_ref)
        if not row: raise KeyError(profile_ref)
        if sha256_text(row["payload_json"]) != row["payload_hash"]: raise IntegrityError("skill state hash mismatch")
        return json.loads(row["payload_json"])

    def _event_existing(self,event_ref:str):
        return self.runtime.conn.execute("SELECT * FROM arpg_skill_events WHERE world_instance_id=? AND event_ref=?",(self.world_instance_id,event_ref)).fetchone()

    def _event_hash(self, profile_ref:str,event_ref:str,event_type:str,payload:dict[str,Any])->str:
        return sha256_text(canonical_json({"profile_ref":profile_ref,"event_ref":event_ref,"event_type":event_type,"payload":payload}))

    def _existing_or_none(self,profile_ref:str,event_ref:str,event_type:str,payload:dict[str,Any])->dict[str,Any]|None:
        row=self._event_existing(event_ref)
        if not row: return None
        h=self._event_hash(profile_ref,event_ref,event_type,payload)
        if row["event_hash"] != h: raise ConflictError("skill event_ref conflict")
        out=json.loads(row["result_json"]); out["idempotent_replay"]=True; out["skill_server_sequence"]=row["server_sequence"]; return out

    def _record_event(self,profile_ref:str,event_ref:str,event_type:str,payload:dict[str,Any],result:dict[str,Any])->dict[str,Any]:
        h=self._event_hash(profile_ref,event_ref,event_type,payload)
        with self.runtime._write_lock:
            cur=self.runtime.conn.execute("INSERT INTO arpg_skill_events(world_instance_id,profile_ref,event_ref,event_type,payload_json,result_json,event_hash) VALUES(?,?,?,?,?,?,?)",(self.world_instance_id,profile_ref,event_ref,event_type,canonical_json(payload),canonical_json(result),h)); seq=cur.lastrowid
        out=copy.deepcopy(result); out["skill_server_sequence"]=seq; return out

    def _reject(self,profile_ref:str,event_ref:str,event_type:str,payload:dict[str,Any],reason:str,**extra:Any)->dict[str,Any]:
        return self._record_event(profile_ref,event_ref,event_type,payload,{"status":"REJECTED","reason":reason,"idempotent_replay":False,**extra})

    @staticmethod
    def _rank_from_mastery(mastery_xp:int)->int:
        return min(10, 1 + max(0,int(mastery_xp))//100)

    def learn_skill(self, profile_ref:str, skill_ref:str, *, event_ref:str, source_type:str="TRAINING", source_ref:str="SYSTEM") -> dict[str,Any]:
        skill_ref=str(skill_ref).strip().upper(); source_type=str(source_type).strip().upper(); source_ref=str(source_ref).strip()
        d=self.definition(skill_ref)
        payload={"skill_ref":skill_ref,"source_type":source_type,"source_ref":source_ref}
        existing=self._existing_or_none(profile_ref,event_ref,"SKILL_LEARN",payload)
        if existing is not None: return existing
        if not source_ref: raise ValidationError("skill learning requires source_ref")
        state=self.ensure_profile(profile_ref)
        if skill_ref in state["learned"]:
            return self._reject(profile_ref,event_ref,"SKILL_LEARN",payload,"SKILL_ALREADY_LEARNED")
        state["learned"][skill_ref]={"rank":1,"mastery_xp":0,"use_count":0,"learned_from":{"source_type":source_type,"source_ref":source_ref},"runtime_mapping":d["runtime_mapping"]}
        self._save(state)
        return self._record_event(profile_ref,event_ref,"SKILL_LEARN",payload,{"status":"PASS","skill_ref":skill_ref,"rank":1,"runtime_mapping":d["runtime_mapping"],"idempotent_replay":False})

    def assign_active(self, profile_ref:str, skill_ref:str, slot:int, *, event_ref:str)->dict[str,Any]:
        slot=int(slot); skill_ref=str(skill_ref).strip().upper(); d=self.definition(skill_ref)
        payload={"skill_ref":skill_ref,"slot":slot}
        existing=self._existing_or_none(profile_ref,event_ref,"ACTIVE_ASSIGN",payload)
        if existing is not None: return existing
        if slot<1 or slot>self.ACTIVE_SLOTS: raise ValidationError("active slot out of range")
        state=self.ensure_profile(profile_ref)
        if skill_ref not in state["learned"]: return self._reject(profile_ref,event_ref,"ACTIVE_ASSIGN",payload,"SKILL_NOT_LEARNED")
        if d["skill_kind"]!="ACTIVE": return self._reject(profile_ref,event_ref,"ACTIVE_ASSIGN",payload,"SKILL_NOT_ACTIVE")
        state["active_loadout"][str(slot)]=skill_ref; self._save(state)
        return self._record_event(profile_ref,event_ref,"ACTIVE_ASSIGN",payload,{"status":"PASS","slot":slot,"skill_ref":skill_ref,"idempotent_replay":False})

    def activate_passive(self, profile_ref:str, skill_ref:str, slot:int, *, event_ref:str)->dict[str,Any]:
        slot=int(slot); skill_ref=str(skill_ref).strip().upper(); d=self.definition(skill_ref)
        payload={"skill_ref":skill_ref,"slot":slot}
        existing=self._existing_or_none(profile_ref,event_ref,"PASSIVE_ASSIGN",payload)
        if existing is not None: return existing
        if slot<1 or slot>self.PASSIVE_SLOTS: raise ValidationError("passive slot out of range")
        state=self.ensure_profile(profile_ref)
        if skill_ref not in state["learned"]: return self._reject(profile_ref,event_ref,"PASSIVE_ASSIGN",payload,"SKILL_NOT_LEARNED")
        if d["skill_kind"]!="PASSIVE": return self._reject(profile_ref,event_ref,"PASSIVE_ASSIGN",payload,"SKILL_NOT_PASSIVE")
        # Prevent duplicate passive activation.
        for k,v in state["passive_loadout"].items():
            if v==skill_ref and k!=str(slot): state["passive_loadout"][k]=None
        state["passive_loadout"][str(slot)]=skill_ref; self._save(state)
        return self._record_event(profile_ref,event_ref,"PASSIVE_ASSIGN",payload,{"status":"PASS","slot":slot,"skill_ref":skill_ref,"idempotent_replay":False})

    def _apply_mastery(self,state:dict[str,Any],skill_ref:str,definition:dict[str,Any])->dict[str,Any]:
        rec=state["learned"][skill_ref]; before=int(rec["rank"])
        rec["use_count"]=int(rec.get("use_count",0))+1; rec["mastery_xp"]=int(rec.get("mastery_xp",0))+self.MASTERY_PER_USE; rec["rank"]=self._rank_from_mastery(rec["mastery_xp"])
        for axis,w in (definition.get("axes") or {}).items():
            if axis in state["build_evidence"]: state["build_evidence"][axis]=round(float(state["build_evidence"][axis])+float(w),6)
        # Active passives sharing an axis slowly improve from related practice.
        active_passives={x for x in state["passive_loadout"].values() if x}
        axes=set((definition.get("axes") or {}).keys())
        for pref in active_passives:
            pd=self.definition(pref); prec=state["learned"][pref]
            if axes.intersection((pd.get("axes") or {}).keys()):
                prec["mastery_xp"]=int(prec.get("mastery_xp",0))+self.PASSIVE_MASTERY_SHARE; prec["rank"]=self._rank_from_mastery(prec["mastery_xp"])
        return {"rank_before":before,"rank_after":int(rec["rank"]),"mastery_xp":int(rec["mastery_xp"]),"use_count":int(rec["use_count"])}

    def use_skill(self,profile_ref:str,skill_ref:str,*,event_ref:str,target_ref:str|None=None)->dict[str,Any]:
        skill_ref=str(skill_ref).strip().upper(); target_ref=None if target_ref is None else str(target_ref)
        d=self.definition(skill_ref); payload={"skill_ref":skill_ref,"target_ref":target_ref}
        existing=self._existing_or_none(profile_ref,event_ref,"SKILL_USE",payload)
        if existing is not None: return existing
        state=self.ensure_profile(profile_ref)
        if skill_ref not in state["learned"]: return self._reject(profile_ref,event_ref,"SKILL_USE",payload,"SKILL_NOT_LEARNED")
        if d["skill_kind"]!="ACTIVE": return self._reject(profile_ref,event_ref,"SKILL_USE",payload,"SKILL_NOT_ACTIVE")
        if d.get("runtime_mapping")!="ACTIVE_V0_7": return self._reject(profile_ref,event_ref,"SKILL_USE",payload,"SKILL_RUNTIME_MAPPING_REQUIRED")
        if d.get("targeting")=="TARGET_ENEMY" and not target_ref: return self._reject(profile_ref,event_ref,"SKILL_USE",payload,"SKILL_TARGET_REQUIRED")
        learned=state["learned"][skill_ref]; rank=int(learned["rank"])
        cooldown=max(0.05,float(d.get("cooldown_s",0.0))*(1.0-min(0.09,(rank-1)*0.01)))
        if d.get("effect_model")=="TARGET_DAMAGE":
            combat=self.engine.combat_arpg(self.world_instance_id)
            pre=combat.preview_player_skill_attack(profile_ref,target_ref,range_bonus_m=float(d.get("range_bonus_m",0.0)))
            if pre.get("status")!="PASS": return self._reject(profile_ref,event_ref,"SKILL_USE",payload,pre.get("reason","SKILL_PRECHECK_FAILED"),precheck=pre)
            reservation=self.engine.resources_arpg(self.world_instance_id).reserve_action(profile_ref,action_ref=skill_ref,resource_cost=float(d.get("resource_cost",0.0)),cooldown_s=cooldown,event_ref=f"{event_ref}:RESERVE",cooldown_group=skill_ref,global_cooldown_s=float(d.get("global_cooldown_s",0.0)))
            if reservation.get("status")!="PASS": return self._reject(profile_ref,event_ref,"SKILL_USE",payload,reservation.get("reason","RESOURCE_GATE"),resource=reservation)
            power=float(d.get("power_multiplier",1.0))*(1.0+(rank-1)*0.025)
            effect=combat.player_skill_attack(profile_ref,target_ref,event_ref=f"{event_ref}:COMBAT",skill_ref=skill_ref,damage_type=str(d.get("damage_type","PHYSICAL")),power_multiplier=power,range_bonus_m=float(d.get("range_bonus_m",0.0)),accuracy_bonus=float(d.get("accuracy_bonus",0.0)),crit_bonus_pct=float(d.get("crit_bonus_pct",0.0)),recovery_s=float(d.get("recovery_s",0.0)))
        else:
            return self._reject(profile_ref,event_ref,"SKILL_USE",payload,"UNSUPPORTED_SKILL_EFFECT_MODEL")
        state=self.ensure_profile(profile_ref); mastery=self._apply_mastery(state,skill_ref,d); self._save(state)
        return self._record_event(profile_ref,event_ref,"SKILL_USE",payload,{"status":"PASS","skill_ref":skill_ref,"target_ref":target_ref,"rank":rank,"mastery":mastery,"resource":reservation,"effect":effect,"idempotent_replay":False,"authority":self.AUTHORITY})

    def use_slot(self,profile_ref:str,slot:int,*,event_ref:str,target_ref:str|None=None)->dict[str,Any]:
        slot=int(slot)
        if slot<1 or slot>self.ACTIVE_SLOTS: raise ValidationError("active slot out of range")
        state=self.ensure_profile(profile_ref); ref=state["active_loadout"].get(str(slot))
        if not ref:
            payload={"slot":slot,"target_ref":target_ref}
            existing=self._existing_or_none(profile_ref,event_ref,"SKILL_USE_SLOT",payload)
            if existing is not None: return existing
            return self._reject(profile_ref,event_ref,"SKILL_USE_SLOT",payload,"SKILL_SLOT_EMPTY")
        return self.use_skill(profile_ref,ref,event_ref=event_ref,target_ref=target_ref)

    def combat_modifiers(self,profile_ref:str)->dict[str,Any]:
        state=self.ensure_profile(profile_ref)
        mods={"damage_flat":0.0,"damage_pct":0.0,"armor_flat":0.0,"accuracy_flat":0.0,"evasion_flat":0.0,"crit_chance_pct":0.0,"attack_speed_pct":0.0,"range_bonus_m":0.0,"resistances":{"FIRE":0.0,"COLD":0.0,"LIGHTNING":0.0,"TOXIC":0.0,"ARCANE":0.0}}
        active=[]
        for slot,ref in state["passive_loadout"].items():
            if not ref: continue
            d=self.definition(ref); rec=state["learned"].get(ref); rank=int((rec or {}).get("rank",1)); active.append({"slot":int(slot),"skill_ref":ref,"rank":rank})
            for key,val in (d.get("passive_modifiers") or {}).items():
                if key.startswith("resistance:"):
                    dt=key.split(":",1)[1]
                    if dt in mods["resistances"]: mods["resistances"][dt]+=float(val)*rank
                elif key in mods and key!="resistances": mods[key]+=float(val)*rank
        return {"status":"PASS","modifiers":mods,"active_passives":active,"authority":self.AUTHORITY}

    def build_signature(self,profile_ref:str)->dict[str,Any]:
        state=self.ensure_profile(profile_ref); scores={k:round(float(v),6) for k,v in state["build_evidence"].items()}; total=sum(scores.values())
        ordered=sorted(scores.items(),key=lambda kv:(-kv[1],kv[0])); dominant=[{"axis":k,"score":v,"share":round(v/total,6) if total else 0.0} for k,v in ordered[:3] if v>0]
        return {"model":"EMERGENT_FROM_PLAYER_CHOICES","fixed_class":None,"dominant_axes":dominant,"scores":scores,"evidence_total":round(total,6),"authority":"GAMEPLAY_DERIVED_NOT_CANON"}

    def snapshot(self,profile_ref:str)->dict[str,Any]:
        state=self.ensure_profile(profile_ref); out=copy.deepcopy(state); out["build_signature"]=self.build_signature(profile_ref); out["definition_count"]=self.runtime.conn.execute("SELECT COUNT(*) c FROM arpg_skill_definitions").fetchone()["c"]; out["authority"]=self.AUTHORITY; return out

    def event_history(self,profile_ref:str)->list[dict[str,Any]]:
        rows=self.runtime.conn.execute("SELECT server_sequence,event_ref,event_type,payload_json,result_json,event_hash FROM arpg_skill_events WHERE world_instance_id=? AND profile_ref=? ORDER BY server_sequence",(self.world_instance_id,profile_ref)).fetchall()
        return [{"server_sequence":r["server_sequence"],"event_ref":r["event_ref"],"event_type":r["event_type"],"payload":json.loads(r["payload_json"]),"result":json.loads(r["result_json"]),"event_hash":r["event_hash"]} for r in rows]

    def verify(self)->dict[str,Any]:
        failures=[]
        defs=self.list_definitions()
        if len(defs)!=36: failures.append(f"SKILL_DEFINITION_COUNT:{len(defs)}")
        if sum(1 for d in defs if d.get("source_authority")=="MASTER_READ_ONLY")!=30: failures.append("CANON_MAGIC_SOURCE_COUNT")
        for p in self.engine.arpg(self.world_instance_id).list_profiles():
            try:
                s=self.ensure_profile(p["profile_ref"])
                for ref in list(s["learned"]): self.definition(ref)
                for ref in list(s["active_loadout"].values())+list(s["passive_loadout"].values()):
                    if ref and ref not in s["learned"]: failures.append("LOADOUT_UNLEARNED:"+p["profile_ref"]+":"+ref)
            except Exception as exc: failures.append("PROFILE_SKILL_STATE:"+p["profile_ref"]+":"+type(exc).__name__)
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"definition_count":len(defs),"canonical_magic_sources":30,"gameplay_skill_prototypes":6,"authority":self.AUTHORITY}
