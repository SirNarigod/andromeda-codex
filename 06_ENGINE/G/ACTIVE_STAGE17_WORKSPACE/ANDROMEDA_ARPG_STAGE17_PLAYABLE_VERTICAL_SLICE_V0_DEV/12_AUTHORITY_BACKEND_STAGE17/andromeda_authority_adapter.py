"""Stage16B authority adapter.

Transport/adaptation layer over the protected Stage01-16A ARPG/Living cores.

What this module does
---------------------
* boots / resumes one authoritative world through ``IntegratedARPGEngineV16A``
* resolves the player actor **server side** and binds it to a client ``session_ref``
* projects the authoritative snapshot with session identity, id and sequence
* validates command envelopes, refuses client-supplied authority fields and
  suppresses duplicate command replays

What this module must never do
------------------------------
It never resolves damage, inventory, currency, stamina, quests, death, crafting,
economy, TTL or canon. Every gameplay outcome is produced by the existing cores.
The single numeric decision taken here is the ``duration_s`` handed to the core
movement authority so a MOVE_TO_POINT step does not overshoot its target.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import threading
import time

from authority_npc_dialogue_content import resolve_dialogue_content
from pathlib import Path
from typing import Any

from authority_config import AuthorityConfig, load_config
from resource_metric_placement import (
    GATHER_RANGE_M,
    PLACEMENT_AUTHORITY,
    ResourceMetricPlacementRegistry,
    ResourcePlacementError,
)

# Mirrors of the core input bands, used only to validate/size an input before the
# core is called. The core remains the sole applier of the movement itself.
# Source: 01_RUNTIME/continuous_movement.py :: ContinuousMovementSystem.step_vector
STEP_DURATION_MAX_S = 10.0
ENV_FACTOR_MIN = 0.25
ENV_FACTOR_MAX = 1.25

# Float-noise tolerance at world-coordinate magnitude (~1e6 m), in metres. This is not a
# gameplay arrival radius: clients own their own arrival tolerance.
ARRIVAL_EPSILON_M = 1e-6

SESSION_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$")
COMMAND_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$")
COMMAND_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

ALLOWED_ENVELOPE_KEYS = frozenset({"session_ref", "command", "params", "command_ref", "idempotency_key"})

# Server-side mirror of andromeda_bridge.gd FORBIDDEN_AUTHORITY_KEYS, extended with the
# identity and projection fields only the server may decide. A client guard is never trusted.
FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {
        "player_ref", "entity_ref", "actor_ref", "owner_ref", "npc_ref", "target_entity_ref",
        "profile_ref", "avatar_ref", "world_instance_id", "role",
        "authority", "server_authoritative", "adapter_authority",
        "snapshot_id", "snapshot_sequence", "idempotent_replay", "replay_suppressed",
        "damage", "damage_amount", "damage_result",
        "inventory_grant", "grant_item", "currency_result",
        "quest_completion", "quest_completed",
        "canonical_mutation", "canon_mutation",
        "death_result", "bag_contents", "authoritative_ttl",
        "stamina", "moved_m", "geodetic", "chunk_id",
    }
)

# Server-side mirror of andromeda_bridge.gd FORBIDDEN_COMMAND_TOKENS.
FORBIDDEN_COMMAND_TOKENS = ("DAMAGE", "GRANT", "CURRENCY_RESULT", "QUEST_COMPLETION", "CANON", "DEATH_RESULT", "BAG_CONTENT", "TTL_RESULT")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class AuthorityBootError(RuntimeError):
    """Raised when the authoritative world cannot be booted or resumed."""


class Stage16BAuthorityAdapter:
    """HTTP-agnostic adapter over the Stage16A ARPG authority."""

    SERVICE = "ANDROMEDA_STAGE16B_AUTHORITY_ADAPTER"
    ADAPTER_VERSION = "V0.8.0-STAGE16B-AUTHORITY-ADAPTER"
    ADAPTER_AUTHORITY = "ANDROMEDA_STAGE16B_AUTHORITY_ADAPTER_TRANSPORT_ONLY"
    SESSION_ROLE = "PLAYER"
    MAX_DEV_TOOL_GRANT_ATTEMPTS = 16

    # Every command in this allowlist delegates to an existing protected core. Combat,
    # economy, loot and survival stay disabled until their own evidence round.
    ENABLED_COMMANDS = (
        "MOVE_TO_POINT",
        "SET_AUTO_PICKUP",
        "ACTIVATE_WEAPON_SLOT",
        "CYCLE_WEAPON_SLOT",
        "REQUEST_PICKUP",
        "REPORT_TRAVERSAL_SAMPLE",
        "REQUEST_GATHER",
        "CONFIRM_DROP_SETTLED",
        "REQUEST_ATTACK",
        "REQUEST_TRADE_QUOTE",
        "EXECUTE_TRADE",
        "REQUEST_EQUIP_BAG",
        "REQUEST_EQUIP_ITEM",
        "ACCEPT_QUEST",
        "REQUEST_SAVE",
        "REQUEST_AUTOSAVE",
        "REQUEST_RELOAD_RESYNC",
        "REPORT_WATER_TRAVERSAL",
        "REPORT_WATER_EXHAUSTION",
        "REPORT_GROUND_LOOT_WATER_STATE",
        "REQUEST_BAG_RECOVERY",
        "REQUEST_RESPAWN",
        "ADVANCE_DEVELOPMENT_WATER_TIME",
        "ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY",
        "ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC",
        "ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT",
        "REQUEST_NPC_DIALOGUE",
        # S17 causal bridge (16/09): first player-facing command for
        # construction_placement_system.py -- it existed complete and
        # tested since fase 5 but was never instantiated in production at
        # all, so building had no command to trigger it. Delegates 100% to
        # place_piece() (already protected/tested); the only new logic is
        # the material-cost bridge call after a successful placement.
        "REQUEST_PLACE_PIECE",
        # Fase 7.1 (Stage17, 13/09): unica adicao a este round - fecha a lacuna
        # documentada em ARPG_SKILL_CORE_CONTRACT_V0_7_0.json/skill_client.gd
        # (backend tinha ARPGSkillCore completo + skills_arpg() no engine, mas
        # nunca projetava skill_projection no snapshot nem aceitava nenhum
        # command de skill). Delega inteiramente a ARPGSkillCore.use_skill(),
        # ja protegido/testado - nenhuma logica de rank/custo/cooldown nova aqui.
        "REQUEST_USE_SKILL",
        # Fase 8.1 (Stage17, 14/09): fecha o resto da lacuna de skill iniciada na
        # fase 7.1 - aprender/atribuir, mesmo delegate-total ao ARPGSkillCore ja
        # protegido/testado.
        "REQUEST_LEARN_SKILL",
        "REQUEST_ASSIGN_ACTIVE_SKILL",
        "REQUEST_ACTIVATE_PASSIVE_SKILL",
        # Fase 8.3 (Stage17, 14/09): travessia fisica real de territorio -
        # transfere o profile pra um motor completo do territorio de destino
        # (cross_territory_transfer.py) e troca qual motor o resto do adapter
        # usa (active_territory_id). Fase 8.6 (14/09): expandido de so
        # RTE-003 pras 21 rotas cross-territorio confirmadas (ver
        # _CONFIRMED_ROUTE_TERRITORIES, mesmo mapa completo de
        # arpg_mobility_infrastructure_core.py).
        "REQUEST_CROSS_TERRITORY_TRAVEL",
    )

    # Fase 8.6: mesmo mapa completo de
    # arpg_mobility_infrastructure_core.py._CONFIRMED_ROUTE_TERRITORIES (21
    # das 25 rotas do canon sao cross-territorio com os dois lados
    # confirmados via STELLAR_ROUTE_SKELETON_V1_0.json x
    # STELLAR_TERRITORIES_V1_0.json.major_location_ids - grafo conexo
    # ligando os 13 territorios). Cada rota mapeia os 2 territorios que liga;
    # o destino valido e o que NAO e o territorio ativo atual.
    _CONFIRMED_ROUTE_TERRITORIES = {
        "RTE-001": ("TER-011", "TER-001"), "RTE-003": ("TER-011", "TER-003"), "RTE-005": ("TER-001", "TER-003"),
        "RTE-006": ("TER-003", "TER-002"), "RTE-007": ("TER-002", "TER-013"), "RTE-008": ("TER-002", "TER-006"),
        "RTE-009": ("TER-002", "TER-005"), "RTE-010": ("TER-005", "TER-010"), "RTE-011": ("TER-010", "TER-004"),
        "RTE-012": ("TER-005", "TER-007"), "RTE-013": ("TER-011", "TER-007"), "RTE-014": ("TER-001", "TER-008"),
        "RTE-015": ("TER-008", "TER-012"), "RTE-016": ("TER-012", "TER-009"), "RTE-017": ("TER-009", "TER-005"),
        "RTE-018": ("TER-004", "TER-006"), "RTE-019": ("TER-013", "TER-006"), "RTE-020": ("TER-001", "TER-012"),
        "RTE-023": ("TER-001", "TER-004"), "RTE-024": ("TER-003", "TER-006"), "RTE-025": ("TER-007", "TER-004"),
    }

    def __init__(self, config: AuthorityConfig | None = None) -> None:
        self.config = config or load_config()
        self._lock = threading.RLock()
        self._engine: Any = None
        self.world_instance_id: str = ""
        self.profile_ref: str = ""
        self.avatar_ref: str = ""
        self._player_ref: str = ""
        self.bootstrap_mode: str = ""
        self.active_territory_id: str = "TER-011"
        self._territory_engines: dict[str, Any] = {}
        self._territory_world_ids: dict[str, str] = {}
        # Fase 8.7 (Stage17, 14/09): WorldSystems (economia/faccoes macro,
        # ja nativamente multi-territorio sob 1 world_instance_id) roda num
        # LivingRuntime PROPRIO, separado de qualquer motor de territorio -
        # nao existe "o" motor unico do jogador mais (fase 8.3 deu 1 motor
        # completo POR territorio), entao economia/faccoes precisam viver
        # num lugar que sobrevive a troca de territorio, nao dentro de 1
        # motor especifico que pode deixar de ser o ativo a qualquer momento.
        self._planet_runtime: Any = None
        self._planet_world_instance_id: str = ""
        self._world_systems: Any = None
        self.resource_placement_registry: ResourceMetricPlacementRegistry | None = None
        self.resource_placement_materialization: dict[str, Any] = {
            "status": "NOT_CONFIGURED",
            "authority": PLACEMENT_AUTHORITY,
        }
        # Transport/projection cursors are deliberately not gameplay state.  Epoch
        # milliseconds stay exact in JSON (< 2**53) and remain monotonic across a
        # database restore that legitimately rolls authoritative state backwards.
        self._transport_sequence = int(time.time() * 1000)
        self._water_presence_monotonic: dict[str, float] = {}
        self._last_authoritative_water_tick = time.monotonic()
        # S17 causal bridge: WorldSimulationOrchestrator (ecology, NPC
        # decide(), social projection, consequence drain) is fully built and
        # wired by IntegratedLivingEngineV11.create_world(), but nothing ever
        # called run_tick() in production -- the world was frozen except for
        # direct player commands.
        #
        # Runs on its own daemon thread, never inline with a request: an
        # earlier inline-in-snapshot() attempt caused a real regression (a
        # long-idle catch-up burst of real ticks leaked 0.07-0.15s of actual
        # wall time into water-clock precision tests measuring the same
        # time.monotonic()). A dedicated thread on a fixed schedule, holding
        # the SAME self._lock every other command/snapshot path already
        # serializes on, means: (a) tick timing is decoupled from any
        # request's timing -- no request pays a bursty, unbounded cost;
        # (b) a tick and a command/snapshot/territory-switch can never run
        # concurrently -- reused locking, not new locking; (c) close() joins
        # this thread before tearing down any engine's connection, so a tick
        # can never run against a half-closed runtime.
        self._orchestrator_tick_stop = threading.Event()
        self._orchestrator_tick_thread = threading.Thread(
            target=self._orchestrator_tick_loop,
            name="andromeda-orchestrator-tick",
            daemon=True,
        )
        self._boot()
        self._orchestrator_tick_thread.start()

    # ------------------------------------------------------------------ bootstrap

    def _boot(self) -> None:
        runtime_dir = str(self.config.runtime_dir)
        if runtime_dir not in sys.path:
            sys.path.insert(0, runtime_dir)
        from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A  # noqa: PLC0415
        import system_causal_bridges  # noqa: PLC0415

        self._causal_bridges = system_causal_bridges

        db_path = Path(self.config.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        Path(self.config.save_root).mkdir(parents=True, exist_ok=True)

        self._engine = IntegratedARPGEngineV16A(
            str(db_path),
            master_release_path=str(self.config.master_release_path),
            save_root=str(self.config.save_root),
        )
        self._schema()

        stored_wid = self._bootstrap_get("world_instance_id")
        if stored_wid:
            report = self._resume_world_with_immutable_gathering_definitions(stored_wid)
            self.world_instance_id = stored_wid
            self.bootstrap_mode = "RESUMED"
        else:
            report = self._engine.create_world(
                self.config.owner_scope, self.config.world_seed, load_relationships=False
            )
            self.world_instance_id = report["world"]["world_instance_id"]
            self.bootstrap_mode = "CREATED"
            self._bootstrap_set("world_instance_id", self.world_instance_id)
            self._bootstrap_set("owner_scope", self.config.owner_scope)
            self._bootstrap_set("world_seed", str(self.config.world_seed))

        if report.get("arpg_health", {}).get("status") != "PASS":
            raise AuthorityBootError(f"ARPG health gate failed: {report.get('arpg_health')}")

        self.profile_ref = self._ensure_profile()
        self._player_ref = self._ensure_player_ref()
        # S17-C3R5: resource placement materialization moved BEFORE the
        # development profile/combat-encounter bootstrap below. That block
        # (via _ensure_development_combat_encounter) now needs
        # self.resource_placement_registry to enforce the COMMON/ALPHA
        # spatial eligibility bound -- with the old ordering the registry
        # was still None at that point, silently disabling the bound.
        # Purely a reorder of two independent, self-contained blocks; no
        # logic in either changed.
        if self.config.resource_placement_manifest_path is not None:
            self.resource_placement_registry = ResourceMetricPlacementRegistry(
                self._engine.runtime, self.world_instance_id
            )
            try:
                self.resource_placement_materialization = (
                    self.resource_placement_registry.materialize_path(
                        self.config.resource_placement_manifest_path
                    )
                )
            except ResourcePlacementError as exc:
                raise AuthorityBootError(
                    f"Stage17 resource placement materialization failed: {exc}"
                ) from exc
        self.development_profile_bootstrap: dict[str, Any] = {
            "enabled": bool(self.config.development_profile_bootstrap),
            "canonical_mutation": False,
            "fixture_scope": "STAGE16B_DEVELOPMENT_PROFILE_ONLY",
        }
        if self.config.development_profile_bootstrap:
            self.development_profile_bootstrap.update(self._ensure_development_profile_loadout())
        self._last_combat_pulse_monotonic = time.monotonic()
        self._last_authoritative_water_tick = time.monotonic()
        # Fase 8.3: TER-011 (o motor que acabou de bootar acima) sempre volta
        # a ser o territorio ativo apos _boot()/restore - qualquer outro
        # territorio registrado antes (por uma travessia anterior) e mantido
        # no dict (nao descartado), so deixa de ser o ativo.
        self.active_territory_id = "TER-011"
        self._territory_engines["TER-011"] = self._engine
        self._territory_world_ids["TER-011"] = self.world_instance_id
        self._boot_planet_world_systems()
        # S17 causal bridge (16/09): registers the player's own starting
        # block's NPCs as agent-brain participants, so the tick thread
        # actually has someone to decide() for from the very first tick --
        # otherwise the whole perception/agent-brain machinery stays
        # correct but permanently idle (an "empty ecosystem"). Deliberately
        # scoped to one block, not the whole territory/world: see
        # register_block_npcs_as_agents' docstring for why. Best-effort:
        # a registration failure must never fail boot.
        try:
            world_state = self._engine.world_arpg(self.world_instance_id).profile_state(
                self.profile_ref
            )
            zone = self._engine.world_arpg(self.world_instance_id).zone(
                str(world_state["zone_ref"])
            )
            starting_block = self._engine.country(self.world_instance_id).block(
                str(zone["block_ref"])
            )
            self._causal_bridges.register_block_npcs_as_agents(
                self._engine.runtime,
                self._engine.orchestrator,
                self.world_instance_id,
                starting_block,
            )
        except Exception:  # noqa: BLE001 - a frozen-by-default ecosystem must never block boot
            pass

    def _boot_planet_world_systems(self) -> None:
        """Fase 8.7: bootstrapa WorldSystems (economia/faccoes macro) num
        LivingRuntime proprio e persistente, independente de qual motor de
        territorio esta ativo. Idempotente: reidrata do arquivo se ja
        existir, e checa world_system_bindings antes de bootstrapar de novo
        (WorldSystems.bootstrap_world_contextual levanta ConflictError se
        chamado 2x - guard evita isso, mesmo padrao ja usado em
        planet_runtime.py)."""
        from living_runtime import LivingRuntime as _LivingRuntime  # noqa: PLC0415
        from world_systems import WorldSystems  # noqa: PLC0415

        base_db = Path(self.config.db_path)
        planet_db = base_db.with_name(f".{base_db.stem}.planet-worldsystems{base_db.suffix}")
        planet_db.parent.mkdir(parents=True, exist_ok=True)
        self._planet_runtime = _LivingRuntime(
            str(planet_db), master_release_path=str(self.config.master_release_path)
        )
        row = self._planet_runtime.conn.execute("SELECT world_instance_id FROM worlds LIMIT 1").fetchone()
        if row:
            self._planet_world_instance_id = row["world_instance_id"]
        else:
            w = self._planet_runtime.create_world(
                f"{self.config.owner_scope}:planet", self.config.world_seed
            )
            self._planet_world_instance_id = w["world_instance_id"]
        self._world_systems = WorldSystems(self._planet_runtime)
        self._world_systems.load_master_snapshots(str(self.config.master_release_path))
        already = self._world_systems.conn.execute(
            "SELECT 1 FROM world_system_bindings WHERE world_instance_id=? LIMIT 1",
            (self._planet_world_instance_id,),
        ).fetchone()
        if not already:
            self._world_systems.bootstrap_world_contextual(self._planet_world_instance_id)

    def _social_memory(self) -> Any:
        """Lazy, bound to the ACTIVE territory engine's own runtime -- fase
        8.2/8.3 pattern (each territory has its own independent LivingRuntime,
        never a single shared one)."""
        cache = getattr(self, "_social_memory_by_wid", None)
        if cache is None:
            cache = {}
            self._social_memory_by_wid = cache
        wid = self.world_instance_id
        if wid not in cache:
            from social_memory import SocialMemorySystem  # noqa: PLC0415

            cache[wid] = SocialMemorySystem(self._engine.runtime)
        return cache[wid]

    def _construction_placement(self) -> Any:
        """Lazy, bound to the ACTIVE territory engine's runtime -- same
        fase 8.2/8.3 per-territory pattern as _social_memory(). Never
        instantiated in production before this command."""
        cache = getattr(self, "_construction_by_wid", None)
        if cache is None:
            cache = {}
            self._construction_by_wid = cache
        wid = self.world_instance_id
        if wid not in cache:
            from construction_placement_system import ConstructionPlacementSystem  # noqa: PLC0415

            cache[wid] = ConstructionPlacementSystem(self._engine.runtime, wid)
        return cache[wid]

    def _request_place_piece(self, params: dict[str, Any], command_ref: str) -> dict[str, Any]:
        """First player command for construction_placement_system.py.
        Delegates identity/collision/ownership entirely to place_piece()
        (already protected/tested); only new logic is the S17 causal bridge
        that draws the piece's catalog materials down from the region's
        economy after a successful placement (see
        ANDROMEDA_CAUSAL_RULES_CATALOG_V1_0.md).
        """
        unexpected = sorted(set(params) - {"piece_ref", "placement_ref", "rotation_deg"})
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        piece_ref = str(params.get("piece_ref") or "").strip()
        if not piece_ref:
            return self._rejected("PIECE_REF_REQUIRED")
        placement_ref = str(params.get("placement_ref") or "").strip()
        if not placement_ref:
            return self._rejected("PLACEMENT_REF_REQUIRED")
        rotation_deg = params.get("rotation_deg", 0.0)
        if not isinstance(rotation_deg, (int, float)) or isinstance(rotation_deg, bool):
            return self._rejected("ROTATION_DEG_MUST_BE_NUMBER")

        construction = self._construction_placement()
        if piece_ref not in construction.known_piece_ids():
            return self._rejected("UNKNOWN_PIECE_REF", piece_ref=piece_ref)

        try:
            player_position = self._engine.movement(self.world_instance_id).state(self._player_ref)
        except (KeyError, TypeError, ValueError) as exc:
            return self._rejected("PLAYER_POSITION_UNAVAILABLE", detail=str(exc))

        core = construction.place_piece(
            self._player_ref,
            piece_ref,
            iso_x_m=float(player_position["iso_x_m"]),
            iso_y_m=float(player_position["iso_y_m"]),
            altitude_m=float(player_position.get("altitude_m", 0.0)),
            rotation_deg=float(rotation_deg),
            placement_ref=placement_ref,
            event_ref=command_ref,
        )

        material_cost: dict[str, Any] | None = None
        if core.get("status") == "PASS" and not core.get("idempotent_replay"):
            try:
                world_state = self._engine.world_arpg(self.world_instance_id).profile_state(
                    self.profile_ref
                )
                zone = self._engine.world_arpg(self.world_instance_id).zone(
                    str(world_state["zone_ref"])
                )
                block_ref = str(zone["block_ref"])
                piece_catalog = construction._pieces.get(piece_ref, {})
                material_refs = [
                    str(entry["resource_id"]) for entry in piece_catalog.get("inputs", [])
                ]
                material_cost = self._causal_bridges.apply_construction_material_cost(
                    self._engine.country(self.world_instance_id), block_ref, material_refs
                )
            except Exception as exc:  # noqa: BLE001 - best-effort side effect
                material_cost = {"status": "SKIPPED", "reason": str(exc)}

        return {
            **core,
            "command": "REQUEST_PLACE_PIECE",
            "material_cost": material_cost,
            "server_authoritative": True,
            "authority": construction.AUTHORITY,
        }

    def _economy_faction_projection(self) -> dict[str, Any]:
        """Fase 8.7: projeta economia/faccoes do WorldSystems pro territorio
        ATIVO no momento (segue o jogador atraves de travessias, sem
        recalcular nada - so filtra o que ja existe pro territorio certo)."""
        if self._world_systems is None:
            return {"status": "NOT_AVAILABLE"}
        ws = self._world_systems
        wid = self._planet_world_instance_id
        territory_id = self.active_territory_id
        faction_refs = [
            row["canonical_ref"]
            for row in ws.conn.execute(
                "SELECT DISTINCT canonical_ref FROM world_system_bindings "
                "WHERE world_instance_id=? AND system_kind='FACTION_RUNTIME'",
                (wid,),
            ).fetchall()
        ]
        local_factions = []
        for fac_ref in faction_refs:
            try:
                ctx = ws.faction_runtime_context(wid, fac_ref)
            except Exception:
                continue
            if ctx.get("territory_ref") == territory_id:
                local_factions.append(ctx)
        return {
            "status": "PASS",
            "territory_id": territory_id,
            "planet_summary": ws.summary(wid),
            "local_factions": local_factions,
            "food_pressure": ws.local_product_pressure(wid, territory_id, "FOOD"),
            "authority": "RUNTIME_CONTEXT_FROM_CANON_SCOPE_NOT_SOVEREIGNTY",
        }

    def _resume_world_with_immutable_gathering_definitions(self, world_instance_id: str) -> dict[str, Any]:
        """Resume Stage16A while preserving legitimate HUNTING depletion.

        The protected Stage09 core originally stores a fauna node's immutable
        ``capacity_units`` from ``fauna.count``.  After a successful hunt the same
        ``count`` is the mutable remaining quantity.  Its normal resume path then
        hashes that smaller remaining quantity as though it were the original
        capacity and rejects its own persisted node as definition drift.

        Stage16B must not edit the protected core, reset fauna progress, or rewrite
        an accepted node definition.  During *only* the protected resume call this
        compatibility wrapper supplies the original capacity already sealed in the
        node definition.  Current ``fauna.count`` remains untouched and therefore
        continues to be the authoritative remaining quantity.  Every other field is
        still rebuilt and hash-checked by Stage09, so genuine drift remains fatal.
        """
        from arpg_gathering_work_core import ARPGGatheringWorkCore  # noqa: PLC0415

        original = ARPGGatheringWorkCore._node_definition
        adjustments: list[dict[str, Any]] = []

        def immutable_capacity(core: Any, zone: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            candidate = original(core, zone, **kwargs)
            if str(kwargs.get("source_kind")) != "FAUNA":
                return candidate
            row = core.runtime.conn.execute(
                "SELECT definition_json FROM arpg_gathering_nodes "
                "WHERE world_instance_id=? AND node_ref=?",
                (core.world_instance_id, candidate["node_ref"]),
            ).fetchone()
            if row is None:
                return candidate
            persisted = json.loads(row["definition_json"])
            immutable = int(persisted.get("capacity_units", candidate["capacity_units"]))
            current = int(candidate["capacity_units"])
            if immutable == current:
                return candidate
            adjusted_kwargs = dict(kwargs)
            adjusted_kwargs["capacity"] = immutable
            adjusted = original(core, zone, **adjusted_kwargs)
            adjustments.append(
                {
                    "node_ref": candidate["node_ref"],
                    "source_ref": candidate["source_ref"],
                    "persisted_capacity_units": immutable,
                    "authoritative_remaining_count": current,
                }
            )
            return adjusted

        ARPGGatheringWorkCore._node_definition = immutable_capacity
        try:
            report = self._engine.resume_world(world_instance_id)
        finally:
            ARPGGatheringWorkCore._node_definition = original
        self.gathering_resume_compatibility = {
            "status": "APPLIED" if adjustments else "NOT_NEEDED",
            "adjustments": adjustments,
            "protected_core_modified_on_disk": False,
            "country_progress_reset": False,
            "authority": "STAGE09_PERSISTED_IMMUTABLE_NODE_DEFINITION",
        }
        return report

    def _schema(self) -> None:
        with self._engine.runtime._write_lock:
            self._engine.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS s16b_bootstrap(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS s16b_snapshot_cursor(
                    world_instance_id TEXT NOT NULL,
                    session_ref TEXT NOT NULL,
                    last_sequence INTEGER NOT NULL,
                    last_snapshot_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, session_ref)
                );
                CREATE TABLE IF NOT EXISTS s16b_command_journal(
                    world_instance_id TEXT NOT NULL,
                    command_ref TEXT NOT NULL,
                    session_ref TEXT NOT NULL,
                    command TEXT NOT NULL,
                    envelope_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, command_ref)
                );
                CREATE TABLE IF NOT EXISTS s16b_result_cursor(
                    world_instance_id TEXT NOT NULL,
                    scope_ref TEXT NOT NULL,
                    last_sequence INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, scope_ref)
                );
                """
            )

    def _capture_transport_state(self) -> dict[str, list[dict[str, Any]]]:
        """Capture adapter-owned monotonic state before a gameplay restore.

        Stage15 restores the authoritative world to a saved point.  Transport
        replay protection and wire cursors must never move backwards with that
        gameplay state, otherwise an already-applied client command could be
        applied again and a valid client would reject the next snapshot as stale.
        Only the three additive ``s16b_*`` transport tables are captured here.
        """
        tables = {
            "snapshot_cursors": (
                "SELECT session_ref,last_sequence,last_snapshot_id,payload_hash "
                "FROM s16b_snapshot_cursor WHERE world_instance_id=?",
                (self.world_instance_id,),
            ),
            "command_journal": (
                "SELECT command_ref,session_ref,command,envelope_hash,result_json,result_hash "
                "FROM s16b_command_journal WHERE world_instance_id=?",
                (self.world_instance_id,),
            ),
            "result_cursors": (
                "SELECT scope_ref,last_sequence,payload_hash FROM s16b_result_cursor "
                "WHERE world_instance_id=?",
                (self.world_instance_id,),
            ),
        }
        captured: dict[str, list[dict[str, Any]]] = {}
        for key, (statement, params) in tables.items():
            captured[key] = [dict(row) for row in self._engine.runtime.conn.execute(statement, params)]
        return captured

    def _merge_transport_state(self, captured: dict[str, list[dict[str, Any]]]) -> None:
        """Merge pre-restore transport state into the verified restored world."""
        world_ref = self.world_instance_id
        with self._engine.runtime._write_lock:
            for row in captured.get("snapshot_cursors", []):
                session_ref = str(row["session_ref"])
                sequence = int(row["last_sequence"])
                snapshot_id = str(row["last_snapshot_id"])
                expected = sha256_text(
                    f"{world_ref}|{session_ref}|{sequence}|{snapshot_id}"
                )
                if expected != str(row["payload_hash"]):
                    raise AuthorityBootError(
                        "CAPTURED_SNAPSHOT_CURSOR_HASH_MISMATCH:" + session_ref
                    )
                existing = self._engine.runtime.conn.execute(
                    "SELECT last_sequence FROM s16b_snapshot_cursor "
                    "WHERE world_instance_id=? AND session_ref=?",
                    (world_ref, session_ref),
                ).fetchone()
                if existing is None or sequence > int(existing["last_sequence"]):
                    self._engine.runtime.conn.execute(
                        "INSERT OR REPLACE INTO s16b_snapshot_cursor"
                        "(world_instance_id,session_ref,last_sequence,last_snapshot_id,payload_hash) "
                        "VALUES(?,?,?,?,?)",
                        (world_ref, session_ref, sequence, snapshot_id, expected),
                    )

            for row in captured.get("result_cursors", []):
                scope_ref = str(row["scope_ref"])
                sequence = int(row["last_sequence"])
                expected = sha256_text(f"{world_ref}|{scope_ref}|{sequence}")
                if expected != str(row["payload_hash"]):
                    raise AuthorityBootError(
                        "CAPTURED_RESULT_CURSOR_HASH_MISMATCH:" + scope_ref
                    )
                existing = self._engine.runtime.conn.execute(
                    "SELECT last_sequence FROM s16b_result_cursor "
                    "WHERE world_instance_id=? AND scope_ref=?",
                    (world_ref, scope_ref),
                ).fetchone()
                if existing is None or sequence > int(existing["last_sequence"]):
                    self._engine.runtime.conn.execute(
                        "INSERT OR REPLACE INTO s16b_result_cursor"
                        "(world_instance_id,scope_ref,last_sequence,payload_hash) VALUES(?,?,?,?)",
                        (world_ref, scope_ref, sequence, expected),
                    )

            for row in captured.get("command_journal", []):
                command_ref = str(row["command_ref"])
                expected_result_hash = sha256_text(str(row["result_json"]))
                if expected_result_hash != str(row["result_hash"]):
                    raise AuthorityBootError(
                        "CAPTURED_COMMAND_JOURNAL_HASH_MISMATCH:" + command_ref
                    )
                existing = self._engine.runtime.conn.execute(
                    "SELECT session_ref,command,envelope_hash,result_hash "
                    "FROM s16b_command_journal WHERE world_instance_id=? AND command_ref=?",
                    (world_ref, command_ref),
                ).fetchone()
                if existing is not None:
                    exact = (
                        str(existing["session_ref"]) == str(row["session_ref"])
                        and str(existing["command"]) == str(row["command"])
                        and str(existing["envelope_hash"]) == str(row["envelope_hash"])
                        and str(existing["result_hash"]) == str(row["result_hash"])
                    )
                    if not exact:
                        raise AuthorityBootError(
                            "RESTORED_COMMAND_JOURNAL_CONFLICT:" + command_ref
                        )
                    continue
                self._engine.runtime.conn.execute(
                    "INSERT INTO s16b_command_journal"
                    "(world_instance_id,command_ref,session_ref,command,envelope_hash,result_json,result_hash) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        world_ref,
                        command_ref,
                        str(row["session_ref"]),
                        str(row["command"]),
                        str(row["envelope_hash"]),
                        str(row["result_json"]),
                        str(row["result_hash"]),
                    ),
                )

    def _bootstrap_get(self, key: str) -> str | None:
        row = self._engine.runtime.conn.execute(
            "SELECT value FROM s16b_bootstrap WHERE key=?", (key,)
        ).fetchone()
        return None if row is None else str(row["value"])

    def _bootstrap_set(self, key: str, value: str) -> None:
        with self._engine.runtime._write_lock:
            self._engine.runtime.conn.execute(
                "INSERT OR REPLACE INTO s16b_bootstrap(key,value) VALUES(?,?)", (key, value)
            )

    def _ensure_profile(self) -> str:
        stored = self._bootstrap_get("profile_ref")
        arpg = self._engine.arpg(self.world_instance_id)
        if stored:
            profile = arpg.profile(stored)
            self.avatar_ref = str(profile.get("avatar_ref", ""))
            return stored
        existing = arpg.list_profiles()
        if existing:
            profile = existing[0]
        else:
            profile = arpg.create_profile(
                self.config.owner_scope, display_name="Stage16B Authority Player"
            )["profile"]
        profile_ref = str(profile["profile_ref"])
        self.avatar_ref = str(profile.get("avatar_ref", ""))
        self._bootstrap_set("profile_ref", profile_ref)
        return profile_ref

    def _ensure_player_ref(self) -> str:
        """Resolve the profile avatar server side. The client never supplies it.

        The Stage16A vertical-slice authorities (stamina, combat, gathering and
        world delivery) all resolve the actor through ``profile.avatar_ref``. An
        earlier transport-only probe selected an arbitrary country NPC instead,
        which split movement from the profile-owned gameplay state. Existing
        bootstrap rows are intentionally migrated to the real profile avatar.
        """
        country = self._engine.country(self.world_instance_id)
        profile = self._engine.arpg(self.world_instance_id).profile(self.profile_ref)
        avatar_ref = str(profile.get("avatar_ref", "")).strip()
        if not avatar_ref:
            raise AuthorityBootError("active Stage16B profile has no avatar_ref")
        try:
            country.npc(avatar_ref)
            self._engine.movement(self.world_instance_id).state(avatar_ref)
        except (KeyError, ValueError) as exc:
            raise AuthorityBootError(
                f"active Stage16B profile avatar is not a valid runtime actor: {avatar_ref}"
            ) from exc
        self._bootstrap_set("player_ref", avatar_ref)
        return avatar_ref

    # G16B-18/G16B-26 CLOTHES reachability: Stage16B-owned item DEFINITION
    # provider. The protected item core's own classification helper only
    # knows WEAPON/ARMOR/TOOL/CONSUMABLE/MATERIAL/COMPONENT/QUEST_UTILITY/
    # UTILITY/GENERIC by literal item_ref string match, and the protected
    # content catalog module's item list is equally byte-frozen -- neither is
    # touched here. The item-definitions table itself only forbids UPDATE/
    # DELETE (immutability triggers in the protected core's own schema
    # setup); INSERT of a brand-new item_ref is unrestricted, and the
    # protected layer already ships two of its own providers that insert
    # directly, bypassing that classification helper entirely, for their own
    # domain-owned, non-catalog items (the economy-crafting core's own
    # culinary/economy item helper, and the gathering-work core's own
    # fishing-catch item helper). This provider follows that exact,
    # already-shipped precedent for exactly one ref. The protected item
    # core's own integrity check (Stage16A checkpoint V0.8.1) now verifies
    # commerce-catalog refs are a subset of item-definition refs (real set
    # membership) instead of a source_kind prefix allowlist, so an
    # honestly-labeled Stage16B provider extra is never a failure -- this is
    # the fix that unblocked this provider; it was reverted in an earlier
    # round specifically because that check did not yet exist.
    DEV_CLOTHES_LEGS_ITEM_REF = "S16B-DEV-CLOTHES-LEGS-001"

    def _expected_dev_clothes_legs_definition(self) -> dict[str, Any]:
        """The exact, single-source-of-truth expected definition dict.

        Field set and shapes mirror the protected item core's own definition-
        building helper exactly (no invented fields) for an equippable, non-canonical,
        development-only item: item_kind="CLOTHES" (a real, distinct kind from
        "ARMOR", so equipped_clothes_refs/equipped_armor_refs stay separate),
        equip_slots=["LEGS"] (the author's chosen slot -- one of the 11 in
        EQUIPMENT_SLOTS that no Stage16B/Godot code reads or writes today),
        stack_max=1 and instance_policy="UNIQUE_INSTANCE" (a real, ownable,
        equippable instance -- not a stack). source_kind is an honest Stage16B
        label, never STAGE09_/STAGE13_ (those belong to the two real providers
        that already own them).
        """
        item_ref = self.DEV_CLOTHES_LEGS_ITEM_REF
        return {
            "item_ref": item_ref,
            "name": "Stage16B Development Clothes - Legs",
            "item_kind": "CLOTHES",
            "source_kind": "STAGE16B_DEVELOPMENT_ONLY",
            "canonical_identity": False,
            "canonical_status": "STAGE16B_DEVELOPMENT_ONLY_NOT_CANON",
            "source_authority": "GAMEPLAY_DERIVED_DEV_SOURCE",
            "source_category": "STAGE16B_DEV_EQUIPMENT",
            "stackable": False,
            "stack_max": 1,
            "unit_weight": 2.0,
            "equip_slots": ["LEGS"],
            "instance_policy": "UNIQUE_INSTANCE",
            "base_durability": 100.0,
            "quality_policy": "INSTANCE_1_100_GAMEPLAY_DERIVED",
            "rarity_policy": "INSTANCE_ROLL_GAMEPLAY_DERIVED",
            "rarity_display_names_authority": "GAMEPLAY_DERIVED_RENAMEABLE",
            "base_modifiers": {
                "damage_flat": 0.0, "damage_pct": 0.0, "armor_flat": 0.0,
                "accuracy_flat": 0.0, "evasion_flat": 0.0, "crit_chance_pct": 0.0,
                "attack_speed_pct": 0.0, "range_bonus_m": 0.0,
                "resistances": {"FIRE": 0.0, "COLD": 0.0, "LIGHTNING": 0.0, "TOXIC": 0.0, "ARCANE": 0.0},
            },
            "consumable_effect": None,
            "socket_support": {
                "supported": False,
                # Same values as the protected item core's own rarity-tier
                # socket-cap table, inlined rather than importing that module-level constant --
                # unused downstream anyway since supported=False (_new_instance()
                # only reads RARITY_TIERS directly, never this field, when
                # socket_support.supported is False).
                "capacity_by_rarity": {"COMMON": 0, "ATTUNED": 1, "EXCEPTIONAL": 1, "RELIC": 2, "SINGULAR": 3},
                "augmentation_binding": "DEFERRED_TO_RUNE_SKILL_WORK_INTEGRATION",
            },
            "source_snapshot_hash": sha256_text(f"STAGE16B:DEV_CLOTHES:{item_ref}"),
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": "ANDROMEDA_STAGE16B_DEVELOPMENT_CONTENT_PROVIDER",
        }

    def _ensure_development_clothes_definition(self) -> dict[str, Any]:
        """Insert-once, drift-checked definition provider for the one CLOTHES ref.

        arpg_item_definitions forbids UPDATE/DELETE by trigger, so this never
        attempts either: if the row is missing, insert exactly once; if it
        already exists, the stored bytes must match this function's own
        expected dict byte-for-byte, or this raises -- never silently accepted,
        never patched, never delete+reinsert.
        """
        item_ref = self.DEV_CLOTHES_LEGS_ITEM_REF
        expected = self._expected_dev_clothes_legs_definition()
        expected_text = canonical_json(expected)
        expected_hash = sha256_text(expected_text)
        conn = self._engine.runtime.conn
        row = conn.execute(
            "SELECT payload_json, payload_hash FROM arpg_item_definitions WHERE item_ref=?",
            (item_ref,),
        ).fetchone()
        created = False
        if row is None:
            with self._engine.runtime._write_lock:
                # Re-check inside the write lock: another concurrent boot path
                # may have inserted it between the read above and here.
                row = conn.execute(
                    "SELECT payload_json, payload_hash FROM arpg_item_definitions WHERE item_ref=?",
                    (item_ref,),
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO arpg_item_definitions(item_ref,source_kind,source_authority,payload_json,payload_hash) VALUES(?,?,?,?,?)",
                        (item_ref, expected["source_kind"], expected["source_authority"], expected_text, expected_hash),
                    )
                    created = True
        if row is not None and not created:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise AuthorityBootError(
                    f"development clothes definition integrity failure for {item_ref}: stored payload hash mismatch"
                )
            if row["payload_hash"] != expected_hash:
                raise AuthorityBootError(
                    f"development clothes definition drift detected for {item_ref}: stored definition no longer "
                    "matches this provider's expected schema (item_kind/equip_slots/stack_max/instance_policy or "
                    "another field changed) -- refusing to UPDATE or DELETE+INSERT"
                )
        # Read back through the real item core -- the same path every other
        # consumer (grant_item(), equip(), inventory_snapshot()) uses. This is
        # the authoritative confirmation the row is well-formed and reachable,
        # not just that our own INSERT succeeded.
        items = self._engine.items_arpg(self.world_instance_id)
        definition = items.definition(item_ref)
        if (
            definition.get("item_kind") != "CLOTHES"
            or definition.get("equip_slots") != ["LEGS"]
            or definition.get("stack_max") != 1
            or definition.get("instance_policy") != "UNIQUE_INSTANCE"
        ):
            raise AuthorityBootError(
                f"development clothes definition schema invalid after ensure: {definition}"
            )
        return {"status": "PASS", "item_ref": item_ref, "created_this_call": created, "definition": definition}

    def _ensure_development_profile_loadout(self) -> dict[str, Any]:
        """Create a playable non-canonical dev profile through Stage05/16A authorities.

        This is test/world bootstrap, not a client grant and not a new item rule. Item
        definitions come from the existing commerce-derived catalog; grant, assignment
        and MAIN_HAND equip are all performed by their protected cores with stable events.
        """
        items = self._engine.items_arpg(self.world_instance_id)
        stage16a = self._engine.stage16a(self.world_instance_id)
        items.ensure_inventory(self.profile_ref)
        stage16a.ensure_profile_preferences(self.profile_ref)
        loadout = stage16a.ensure_weapon_loadout(self.profile_ref)
        definitions = sorted(
            (d for d in items.list_definitions() if d.get("item_kind") == "WEAPON"),
            key=lambda d: str(d.get("item_ref", "")),
        )
        if len(definitions) < 2:
            raise AuthorityBootError("Stage16B development profile requires two catalog weapons")

        used = {str(ref) for ref in loadout.get("slots", {}).values() if ref}
        granted: list[str] = []
        for slot in (1, 2):
            if loadout.get("slots", {}).get(str(slot)):
                continue
            definition = definitions[slot - 1]
            grant = items.grant_item(
                self.profile_ref,
                str(definition["item_ref"]),
                1,
                event_ref=f"S16B:DEV_PROFILE:GRANT:WEAPON:{slot}",
            )
            if grant.get("status") != "PASS" or not grant.get("instance_refs"):
                raise AuthorityBootError(f"development weapon grant failed for slot {slot}: {grant}")
            instance_ref = str(grant["instance_refs"][0])
            if instance_ref in used:
                raise AuthorityBootError("development weapon bootstrap produced duplicate instance")
            assigned = stage16a.assign_weapon_slot(
                self.profile_ref,
                slot,
                instance_ref,
                event_ref=f"S16B:DEV_PROFILE:ASSIGN:WEAPON:{slot}",
            )
            if assigned.get("status") != "PASS":
                raise AuthorityBootError(f"development weapon assignment failed: {assigned}")
            used.add(instance_ref)
            granted.append(instance_ref)
            loadout = assigned["loadout"]

        if loadout.get("active_slot") not in (1, 2):
            activated = stage16a.activate_weapon_slot(
                self.profile_ref, 1, event_ref="S16B:DEV_PROFILE:ACTIVATE:WEAPON:1"
            )
            if activated.get("status") != "PASS":
                raise AuthorityBootError(f"development MAIN_HAND activation failed: {activated}")
            loadout = activated["loadout"]

        # The quick loadout exposes exactly two slots, but the contract also states the
        # inventory may hold more weapons than that. Carry a spare so the distinction is
        # observable instead of merely assumed.
        spare_weapon_instance_ref = self._ensure_spare_weapon(items, definitions, loadout)

        gathering = self._engine.gathering_arpg(self.world_instance_id)
        assigned_roles: list[str] = []
        for activity in gathering.ACTIVITIES:
            gathering.assign_role(self.profile_ref, activity)
            assigned_roles.append(str(activity))

        granted_tool_instance_ref: str | None = None
        work_tool_instance_ref = self._live_work_tool_instance(items)
        if work_tool_instance_ref is None:
            tools = sorted(
                (d for d in items.list_definitions() if d.get("item_kind") == "TOOL"),
                key=lambda d: str(d.get("item_ref", "")),
            )
            if not tools:
                raise AuthorityBootError("Stage16B development profile requires a catalog tool")
            granted_tool_instance_ref = self._ensure_live_work_tool(items, str(tools[0]["item_ref"]))
            work_tool_instance_ref = granted_tool_instance_ref

        # G16B-18/G16B-26 death-retention precondition: provision one real
        # ITEM-OLD-KEY (QUEST_UTILITY, already protected by the existing,
        # unmodified _is_protected_definition()) directly to the player, the
        # same way weapons/tool above are provisioned -- a fixed, deterministic
        # event_ref means the item core's own replay safety (grant_item()'s
        # _existing_or_none() check) makes this a one-time grant for the life
        # of this world+profile, no matter how many times this function itself
        # re-runs (e.g. on every REQUEST_RELOAD_RESYNC, which calls _boot()
        # again). No client command requests it; the server alone decides it.
        protected_item_grant = items.grant_item(
            self.profile_ref,
            "ITEM-OLD-KEY",
            1,
            event_ref="S16B:DEV_PROFILE:GRANT:PROTECTED_ITEM",
        )
        if protected_item_grant.get("status") != "PASS":
            raise AuthorityBootError(
                f"development protected-item grant failed: {protected_item_grant}"
            )

        # G16B-18/G16B-26 CLOTHES reachability: same pattern as the protected
        # item above -- server-side only, fixed deterministic event_ref, no
        # client command requests it. The definition must exist before the
        # grant (grant_item() -> definition() would raise NotFoundError
        # otherwise); _ensure_development_clothes_definition() guarantees that
        # ordering itself.
        clothes_definition = self._ensure_development_clothes_definition()
        clothes_grant = items.grant_item(
            self.profile_ref,
            self.DEV_CLOTHES_LEGS_ITEM_REF,
            1,
            event_ref="S16B:DEV_PROFILE:GRANT:CLOTHES_LEGS",
        )
        if clothes_grant.get("status") != "PASS":
            raise AuthorityBootError(
                f"development clothes grant failed: {clothes_grant}"
            )

        combat_encounter = self._ensure_development_combat_encounter()
        return {
            "status": "PASS",
            "granted_instance_refs_this_boot": granted,
            "granted_tool_instance_ref_this_boot": granted_tool_instance_ref,
            "work_tool_instance_ref": work_tool_instance_ref,
            "spare_weapon_instance_ref": spare_weapon_instance_ref,
            "assigned_gathering_roles": assigned_roles,
            "weapon_loadout": loadout,
            "protected_item_grant": protected_item_grant,
            "clothes_definition": clothes_definition,
            "clothes_grant": clothes_grant,
            "combat_encounter": combat_encounter,
            "authority": self._engine.stage16a(self.world_instance_id).AUTHORITY,
        }

    def _ensure_enemy_carried_bag(self, target_ref: str) -> dict[str, Any]:
        """Give a development enemy a real Bag holding real carried contents.

        Every mutation is executed by a protected core: the item core grants the carried
        item and Stage16A equips the Bag, which moves unprotected inventory into it.
        Nothing here decides what a defeated enemy drops. On death the existing Bag
        authority drops exactly what the actor was carrying.
        """
        items = self._engine.items_arpg(self.world_instance_id)
        stage16a = self._engine.stage16a(self.world_instance_id)
        water_bag = stage16a.water_bag

        items.ensure_inventory(target_ref)
        carry = water_bag.ensure_carry_profile(target_ref)
        existing = str(carry.get("equipped_bag_ref") or "")
        if existing:
            return {"status": "PASS", "bag_ref": existing, "seeded_this_boot": False}

        definitions = items.list_definitions()
        carried = sorted(
            (d for d in definitions if d.get("item_kind") == "MATERIAL"),
            key=lambda d: str(d.get("item_ref", "")),
        ) or sorted(
            (d for d in definitions if d.get("item_kind") not in {"WEAPON", "TOOL"}),
            key=lambda d: str(d.get("item_ref", "")),
        )
        if not carried:
            raise AuthorityBootError("Stage16B development encounter requires a catalog item")
        carried_item_ref = str(carried[0]["item_ref"])

        # Grant before equipping: equip_new_bag moves unprotected inventory into the Bag.
        # Each attempt carries its own event_ref because the item core replays a stored
        # grant whose instance may have already left the inventory.
        for attempt in range(1, self.MAX_DEV_TOOL_GRANT_ATTEMPTS + 1):
            grant = items.grant_item(
                target_ref,
                carried_item_ref,
                1,
                event_ref=f"S16B:DEV_ENCOUNTER:CARRIED:{target_ref}:{attempt}",
            )
            if grant.get("status") != "PASS":
                raise AuthorityBootError(f"development enemy carry grant failed: {grant}")
            snapshot = items.inventory_snapshot(target_ref)
            if snapshot.get("instance_refs") or snapshot.get("stacks"):
                break
        else:
            raise AuthorityBootError("development enemy carry grant produced no live item")

        # G16B-18/G16B-26 development acquisition route: this whole function is
        # unreachable outside development_profile_bootstrap (its only caller is
        # _ensure_development_combat_encounter(), itself only invoked from
        # _boot() and bind_session() under that same guard). Carry one
        # ITEM-ARMOR instance alongside the existing carried_item_ref, so the
        # already-proven G16B-05 ENEMY -> Ground Loot -> pickup pipeline is the
        # only thing that ever makes it reachable by the player.
        # carried_item_ref itself is untouched -- still the first item
        # granted, still the same proof G16B-05 already relies on.
        #
        # ITEM-OLD-KEY (QUEST_UTILITY) was deliberately NOT added here: proven
        # by running the real defeat sequence that _enemy_death_physical_output()
        # calls stage16a.drop_bag_for_death(target_ref, ...) first, which
        # returns protected items to their *current* owner -- the defeated
        # enemy itself in this context, not the player -- before the remaining
        # contents are read and spawned as Ground Loot. A protected item
        # carried by an enemy therefore never reaches the drop list at all; it
        # is silently stranded in the now-unreachable NPC's own inventory.
        # This is the existing rule working exactly as designed for the
        # player-death case; it was never written with an enemy-carried
        # protected item in mind. Reported, not routed around -- see the
        # round's final report.
        carried_armor_instance_ref = ""
        for attempt in range(1, self.MAX_DEV_TOOL_GRANT_ATTEMPTS + 1):
            armor_grant = items.grant_item(
                target_ref,
                "ITEM-ARMOR",
                1,
                event_ref=f"S16B:DEV_ENCOUNTER:CARRIED_ARMOR:{target_ref}:{attempt}",
            )
            if armor_grant.get("status") != "PASS":
                raise AuthorityBootError(f"development enemy armor carry grant failed: {armor_grant}")
            snapshot = items.inventory_snapshot(target_ref)
            live_armor_refs = [
                str(ref)
                for ref in snapshot.get("instance_refs", [])
                if items.instance(str(ref))["item_ref"] == "ITEM-ARMOR"
            ]
            if live_armor_refs:
                carried_armor_instance_ref = live_armor_refs[0]
                break
        else:
            raise AuthorityBootError("development enemy armor carry grant produced no live instance")

        for attempt in range(1, self.MAX_DEV_TOOL_GRANT_ATTEMPTS + 1):
            equipped = stage16a.equip_bag(
                target_ref, event_ref=f"S16B:DEV_ENCOUNTER:BAG:{target_ref}:{attempt}"
            )
            carry = water_bag.ensure_carry_profile(target_ref)
            bag_ref = str(carry.get("equipped_bag_ref") or "")
            if bag_ref:
                return {
                    "status": "PASS",
                    "bag_ref": bag_ref,
                    "seeded_this_boot": True,
                    "carried_item_ref": carried_item_ref,
                    "carried_armor_instance_ref": carried_armor_instance_ref,
                    "equip_status": equipped.get("status"),
                    "authority": stage16a.AUTHORITY,
                }
        raise AuthorityBootError("development enemy Bag bootstrap could not equip a live Bag")

    def _enemy_death_physical_output(
        self, target_ref: str, command_ref: str
    ) -> tuple[dict[str, Any] | None, str]:
        """Turn what the defeated actor carried into ENEMY Ground Loot.

        No protected core owns a loot table and none is invented here. The Bag
        authority drops the actor's own container first, because that is what returns
        quest/critical protected items to their owner. Whatever legitimately remains is
        then moved out by the item core and spawned through Stage16A's own
        ``spawn_defeated_enemy_drop``, so enemy output is physical, world-first and
        reaches Ground Loot before any inventory.
        """
        stage16a = self._engine.stage16a(self.world_instance_id)
        movement = self._engine.movement(self.world_instance_id)
        try:
            state = movement.state(target_ref)
        except KeyError:
            return None, "DEFEATED_TARGET_HAS_NO_POSITION"
        drop = stage16a.drop_bag_for_death(
            target_ref,
            in_water=False,
            position={
                "iso_x_m": float(state["iso_x_m"]),
                "iso_y_m": float(state["iso_y_m"]),
                "altitude_m": float(state["altitude_m"]),
            },
            event_ref=f"{command_ref}:ENEMY_BAG_DROP",
        )
        if drop.get("status") != "PASS":
            return None, str(drop.get("reason", "ENEMY_BAG_DROP_REJECTED"))
        bag_ref = str(drop.get("bag_ref") or "")
        if not drop.get("bag_dropped") or not bag_ref:
            return None, str(drop.get("reason", "NO_BAG_EQUIPPED"))

        items = self._engine.items_arpg(self.world_instance_id)
        carried = self._bag_contents_summary(bag_ref)
        # Pre-validate every definition so nothing is removed before it can be spawned.
        for entry in carried:
            try:
                items.definition(str(entry["item_ref"]))
            except (KeyError, ValueError) as exc:
                return None, f"ENEMY_LOOT_DEFINITION_UNKNOWN:{exc}"

        drops: list[dict[str, Any]] = []
        for index, entry in enumerate(carried, start=1):
            quantity = int(entry.get("quantity", 0))
            if quantity <= 0:
                continue
            item_ref = str(entry["item_ref"])
            instance_ref = entry.get("instance_ref")
            removed = items.remove_item(
                bag_ref,
                item_ref,
                quantity,
                event_ref=f"{command_ref}:ENEMY_LOOT_TAKE:{index}",
                instance_ref=str(instance_ref) if instance_ref else None,
            )
            if removed.get("status") != "PASS":
                continue
            spawned = stage16a.spawn_defeated_enemy_drop(
                target_ref,
                item_ref=item_ref,
                item_kind=str(entry.get("item_kind", "MISC")),
                quantity=quantity,
                event_ref=f"{command_ref}:ENEMY_LOOT_DROP:{index}",
            )
            if spawned.get("status") != "PASS":
                # Never destroy an item: put it back where the authority had it.
                items.grant_item(
                    bag_ref,
                    item_ref,
                    quantity,
                    event_ref=f"{command_ref}:ENEMY_LOOT_RESTORE:{index}",
                )
                return None, f"ENEMY_LOOT_SPAWN_FAILED:{spawned.get('reason', 'UNKNOWN')}"
            drops.append(
                {
                    "drop_ref": str(spawned["drop_ref"]),
                    "item_ref": item_ref,
                    "item_kind": str(entry.get("item_kind", "MISC")),
                    "quantity": quantity,
                    "drop": spawned.get("drop"),
                }
            )

        if not drops:
            return None, "NO_CARRIED_CONTENTS_TO_DROP"
        return (
            {
                "source_kind": "ENEMY",
                "output_form": "GROUND_LOOT",
                "drop_refs": [row["drop_ref"] for row in drops],
                "drops": drops,
                "bag_ref": bag_ref,
                "protected_returned": drop.get("protected_returned"),
                "physical_world_first": True,
                "direct_to_inventory": False,
                # No authoritative actor water state exists in this round; the land form
                # is explicit rather than silently assumed.
                "in_water_authority": "LAND_NO_ACTOR_WATER_STATE_THIS_ROUND",
                "authority": stage16a.AUTHORITY,
            },
            "STAGE16A_ENEMY_GROUND_LOOT_FROM_CARRIED_CONTENTS",
        )

    def _weapon_instances(self, items: Any) -> list[str]:
        """Every non-broken WEAPON instance the profile currently carries."""
        inventory = items.inventory_snapshot(self.profile_ref)
        found: list[str] = []
        for instance in inventory.get("instances", []):
            try:
                definition = items.definition(str(instance["item_ref"]))
            except (KeyError, ValueError):
                continue
            if definition.get("item_kind") == "WEAPON" and instance.get("condition") != "BROKEN":
                found.append(str(instance["instance_ref"]))
        return found

    def _ensure_spare_weapon(
        self, items: Any, definitions: list[dict[str, Any]], loadout: dict[str, Any]
    ) -> str | None:
        """Carry at least one weapon beyond the two quick slots.

        Grant is verified against the live inventory: the item core replays a stored
        grant, so a fixed event_ref would report PASS while granting nothing once the
        original instance has left the inventory.
        """
        slotted = {str(ref) for ref in loadout.get("slots", {}).values() if ref}
        carried = self._weapon_instances(items)
        spare = [ref for ref in carried if ref not in slotted]
        if spare:
            return spare[0]
        if not definitions:
            return None
        item_ref = str(definitions[-1]["item_ref"])
        for attempt in range(1, self.MAX_DEV_TOOL_GRANT_ATTEMPTS + 1):
            grant = items.grant_item(
                self.profile_ref,
                item_ref,
                1,
                event_ref=f"S16B:DEV_PROFILE:GRANT:SPARE_WEAPON:{attempt}",
            )
            if grant.get("status") != "PASS":
                raise AuthorityBootError(f"development spare weapon grant failed: {grant}")
            carried = self._weapon_instances(items)
            spare = [ref for ref in carried if ref not in slotted]
            if spare:
                return spare[0]
        raise AuthorityBootError("development spare weapon bootstrap produced no live instance")

    def _live_work_tool_instance(self, items: Any) -> str | None:
        """Return a live, non-BROKEN TOOL instance ref from the profile inventory."""
        inventory = items.inventory_snapshot(self.profile_ref)
        for instance in inventory.get("instances", []):
            try:
                definition = items.definition(str(instance["item_ref"]))
            except (KeyError, ValueError):
                continue
            if definition.get("item_kind") == "TOOL" and instance.get("condition") != "BROKEN":
                return str(instance["instance_ref"])
        return None

    def _ensure_live_work_tool(self, items: Any, item_ref: str) -> str:
        """Grant a work tool until one is actually present in the live inventory.

        A fixed event_ref cannot be reused here. The item core replays a stored grant, so
        once the original instance has left the inventory (death drop, Bag, trade) the
        replay reports PASS with the old instance_refs while granting nothing. Each attempt
        therefore carries its own event_ref and is verified against the live inventory.
        """
        for attempt in range(1, self.MAX_DEV_TOOL_GRANT_ATTEMPTS + 1):
            grant = items.grant_item(
                self.profile_ref,
                item_ref,
                1,
                event_ref=f"S16B:DEV_PROFILE:GRANT:WORK_TOOL:{attempt}",
            )
            if grant.get("status") != "PASS":
                raise AuthorityBootError(f"development work-tool grant failed: {grant}")
            live = self._live_work_tool_instance(items)
            if live is not None:
                return live
        raise AuthorityBootError(
            "development work-tool bootstrap could not produce a live TOOL instance after "
            f"{self.MAX_DEV_TOOL_GRANT_ATTEMPTS} attempts"
        )

    def _active_engagement_center_and_radius_m(self) -> tuple[dict[str, float] | None, float]:
        """A metric eligibility bound derived from the authored content
        cluster's own scale -- never a number observed from a test run.
        S17-C3R5: 'same block_id' was tried first and measured unreliable
        against this world's real data -- npc.block_id does not correlate
        with actual v15_motion_state position for these NPCs. Empirically:
        NPC-01-01-01-013 (block STA-01-BLK-01, a DIFFERENT block than the
        engagement's own STA-05-BLK-04) sits a genuine 9.6m from the TREE/
        ORE cluster, while NPC-05-04-03-002 (block STA-05-BLK-04, the SAME
        block as the engagement) sits a genuine ~2195km away. A block-only
        filter would have wrongly excluded the first and wrongly admitted
        the second. Real metric distance from the engagement's own content
        cluster is the reliable signal and is now the sole eligibility
        gate; block_id is left unused for this purpose (S17-C3R5 finding,
        see STAGE17_RECORDS/S17_C3R5_*).

        The centre is the centroid of the engagement's own active resource
        placements (TREE/ORE for this world); the radius is a generous
        multiple of how far those placements themselves spread from that
        centre. With only real, already-loaded placement data and no
        invented constant beyond the multiplier itself.
        """
        if self.resource_placement_registry is None:
            return None, 0.0
        try:
            placements = self.resource_placement_registry.active_placements()
        except Exception:
            return None, 0.0
        # active_placements() rows go through ResourceMetricPlacementRegistry.
        # _row_dict(), which nests iso_x_m/iso_y_m under "position" (popped
        # off the flat row) -- not top-level keys on the placement dict.
        points = [
            (float(p["position"]["iso_x_m"]), float(p["position"]["iso_y_m"]))
            for p in placements
            if isinstance(p.get("position"), dict)
            and _finite(p["position"].get("iso_x_m"))
            and _finite(p["position"].get("iso_y_m"))
        ]
        if not points:
            return None, 0.0
        center_x = sum(x for x, _ in points) / len(points)
        center_y = sum(y for _, y in points) / len(points)
        spread_m = max(math.hypot(x - center_x, y - center_y) for x, y in points)
        # The scene's own authored combat/vendor/dialogue placeholders sit
        # a few dozen metres from spawn (see Main.tscn ActorRoot children);
        # a wide safety multiple over the placement cluster's own spread
        # comfortably covers that without reintroducing an unbounded search.
        radius_m = max(spread_m, 1.0) * 20.0
        return {"iso_x_m": center_x, "iso_y_m": center_y}, radius_m

    def _within_active_engagement_metric_bound(self, iso_x_m: float, iso_y_m: float) -> bool:
        center, radius_m = self._active_engagement_center_and_radius_m()
        if center is None:
            return True  # no placement data loaded (e.g. legacy/test world); nothing to bound against
        distance_m = math.hypot(iso_x_m - center["iso_x_m"], iso_y_m - center["iso_y_m"])
        return distance_m <= radius_m

    def _ensure_development_combat_encounter(self) -> dict[str, Any]:
        """Materialize two runtime-only hostile actors through the Stage07 core.

        The protected ActorCore owns disposition, rank, AI eligibility and canonical
        identity protection.  This development-world bootstrap only chooses nearby
        eligible actors and asks that core to create a repeatable vertical-slice
        encounter.  It neither edits Country records nor invents combat outcomes.

        S17-C3R5: candidates (both a freshly searched one and a reused stored
        one) must fall inside the active engagement's own metric radius (see
        _active_engagement_center_and_radius_m). A stored target that has
        drifted outside that area (e.g. from before this boundary existed)
        is treated exactly like a dead/depleted one -- discarded, not reused
        -- so the slot re-selects a fresh, in-area candidate instead of perpetuating an
        out-of-area target forever.
        """
        country = self._engine.country(self.world_instance_id)
        engagement_center, _engagement_radius_m = self._active_engagement_center_and_radius_m()
        actor_core = self._engine.actors_arpg(self.world_instance_id)
        combat_core = self._engine.combat_arpg(self.world_instance_id)
        movement = self._engine.movement(self.world_instance_id)
        player_state = movement.state(self._player_ref)
        selected: list[dict[str, Any]] = []
        excluded = {self._player_ref}
        # Snapshot both slots' stored incumbents before either is touched this call, so
        # each slot's reselection can be barred from the OTHER slot's own target -- by
        # reuse or by fresh search -- regardless of which slot is processed first. Without
        # this, the slot processed first could rediscover and "steal" a target the other
        # slot already legitimately owns and is still using untouched, forcing an
        # unnecessary rotation of a pristine actor.
        stored_by_slot = {
            slot_name: str(self._bootstrap_get(f"combat_target_{slot_name}_ref") or "").strip()
            for slot_name in ("common", "alpha")
        }

        for slot_name, rank in (("common", "COMMON"), ("alpha", "CHAMPION")):
            bootstrap_key = f"combat_target_{slot_name}_ref"
            other_slot_name = "alpha" if slot_name == "common" else "common"
            reserved_ref = stored_by_slot[other_slot_name]
            slot_excluded = excluded | ({reserved_ref} if reserved_ref else set())
            stored = stored_by_slot[slot_name]
            target_ref = ""
            if stored and stored not in slot_excluded:
                try:
                    actor = actor_core.ensure_actor(stored)
                    state = combat_core.ensure_enemy(stored)
                    stored_position = movement.state(stored)
                    stored_in_metric_bound = self._within_active_engagement_metric_bound(
                        float(stored_position["iso_x_m"]), float(stored_position["iso_y_m"])
                    )
                    # Reuse only a pristine actor still inside the active engagement
                    # area's real metric radius. A stored target that already took
                    # damage in an earlier run would make the next encounter
                    # unreproducible, and healing it here would be an invented rule;
                    # a stored target that has drifted outside the active area
                    # (S17_G19_COMMON_TARGET_UNBOUNDED_SELECTION_GAP legacy
                    # selections) is treated the same as dead -- rotate to a fresh
                    # in-area candidate instead. Selecting a different untouched,
                    # in-area actor invents nothing.
                    if (
                        not actor.get("protected_identity")
                        and actor.get("combat_targetable", True)
                        and state.get("life_state") == "ALIVE"
                        and float(state.get("health", 0.0)) >= float(state.get("max_health", 0.0))
                        and stored_in_metric_bound
                    ):
                        target_ref = stored
                except Exception:
                    target_ref = ""
            if not target_ref:
                candidates: list[tuple[int, float, str]] = []
                for npc in country._all_npc_records():
                    ref = str(npc.get("id") or "").strip()
                    protection = npc.get("protection") or {}
                    if (
                        not ref
                        or ref in slot_excluded
                        or str(npc.get("status", "ACTIVE")).upper() != "ACTIVE"
                        or str(npc.get("class") or "").upper() in {"CHILD", "PLAYER_AVATAR"}
                        or bool(protection.get("protected", False))
                        or not bool(protection.get("combat_targetable", True))
                    ):
                        continue
                    try:
                        position = movement.state(ref)
                        state = combat_core.ensure_enemy(ref)
                    except Exception:
                        continue
                    if state.get("life_state") != "ALIVE":
                        continue
                    if float(state.get("health", 0.0)) < float(state.get("max_health", 0.0)):
                        continue
                    # S17-C3R5 spatial boundary: this is a hard ELIGIBILITY
                    # filter, not merely a sort preference, so a distant NPC
                    # can never win by default when nothing nearby qualifies
                    # (S17_G19_COMMON_TARGET_UNBOUNDED_SELECTION_GAP). Real
                    # metric distance from the engagement's own content
                    # cluster, not npc.block_id (measured unreliable against
                    # this world's actual NPC positions -- see
                    # _active_engagement_center_and_radius_m).
                    if not self._within_active_engagement_metric_bound(
                        float(position["iso_x_m"]), float(position["iso_y_m"])
                    ):
                        continue
                    distance = math.hypot(
                        float(position["iso_x_m"]) - float(player_state["iso_x_m"]),
                        float(position["iso_y_m"]) - float(player_state["iso_y_m"]),
                    )
                    # Prefer an actor visibly separate from the player and already in
                    # the Stage03 basic range.  The core still validates actual range.
                    preferred = 0 if 0.75 <= distance <= float(combat_core.BASIC_RANGE_M) else 1
                    candidates.append((preferred, distance, ref))
                candidates.sort(key=lambda row: (row[0], row[1], row[2]))
                if not candidates:
                    raise AuthorityBootError(
                        "NO_VALID_COMMON_TARGET_IN_ACTIVE_AREA"
                        if engagement_center is not None
                        else "no eligible Stage07 combat encounter actor"
                    )
                target_ref = candidates[0][2]
                self._bootstrap_set(bootstrap_key, target_ref)

            disposition = actor_core.set_disposition(
                target_ref,
                "HOSTILE",
                event_ref=f"S16B:DEV_ENCOUNTER:HOSTILE:{target_ref}",
                reason="STAGE16B_DEVELOPMENT_VERTICAL_SLICE",
            )
            ranked = actor_core.set_combat_rank(
                target_ref,
                rank,
                event_ref=f"S16B:DEV_ENCOUNTER:RANK:{rank}:{target_ref}",
                reason="STAGE16B_DEVELOPMENT_VERTICAL_SLICE",
            )
            actor = actor_core.ensure_actor(target_ref)
            state = combat_core.ensure_enemy(target_ref)
            position = movement.state(target_ref)
            distance = math.hypot(
                float(position["iso_x_m"]) - float(player_state["iso_x_m"]),
                float(position["iso_y_m"]) - float(player_state["iso_y_m"]),
            )
            carried_bag = self._ensure_enemy_carried_bag(target_ref)
            selected.append(
                {
                    "slot": slot_name.upper(),
                    "target_ref": target_ref,
                    "rank": rank,
                    "carried_bag": carried_bag,
                    "distance_m": round(distance, 6),
                    "disposition_result": disposition,
                    "rank_result": ranked,
                    "actor_authority": actor.get("authority"),
                    "combat_authority": state.get("authority"),
                    "canonical_identity_mutation": False,
                }
            )
            excluded.add(target_ref)
        return {
            "status": "PASS",
            "targets": selected,
            "runtime_gameplay_overlay_only": True,
            "canonical_identity_mutation": False,
            "authority": actor_core.AUTHORITY,
        }

    def close(self) -> None:
        # Stop and join the tick thread BEFORE touching any engine's
        # connection below -- joining happens outside self._lock (the tick
        # loop needs to acquire it to finish its current wake-up and notice
        # the stop signal); otherwise a tick could run against a runtime
        # this call is mid-way through closing.
        self._orchestrator_tick_stop.set()
        self._orchestrator_tick_thread.join(timeout=5.0)
        with self._lock:
            # Fase 8.3: self._engine e sempre o MESMO objeto que
            # self._territory_engines[self.active_territory_id] (mantido em
            # sincronia por switch_active_territory/_boot) - fecha cada motor
            # registrado uma unica vez por identidade, nunca duas.
            closed_ids = set()
            for engine in self._territory_engines.values():
                if engine is not None and id(engine) not in closed_ids:
                    engine.runtime.close()
                    closed_ids.add(id(engine))
            if self._engine is not None and id(self._engine) not in closed_ids:
                self._engine.runtime.close()
            self._territory_engines = {}
            self._engine = None
            if self._planet_runtime is not None:
                self._planet_runtime.close()
                self._planet_runtime = None

    # ------------------------------------------------------------------ fase 8.3: multi-territorio

    def _territory_engine(self, territory_id: str) -> tuple[Any, str]:
        """Retorna (engine, world_instance_id) pro territorio, criando um
        IntegratedARPGEngineV16A completo e independente (db proprio) sob
        demanda na primeira vez. Nunca recria um ja registrado."""
        if territory_id in self._territory_engines:
            return self._territory_engines[territory_id], self._territory_world_ids[territory_id]
        runtime_dir = str(self.config.runtime_dir)
        if runtime_dir not in sys.path:
            sys.path.insert(0, runtime_dir)
        from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A  # noqa: PLC0415

        base_db = Path(self.config.db_path)
        territory_db = base_db.with_name(f".{base_db.stem}.territory-{territory_id}{base_db.suffix}")
        territory_db.parent.mkdir(parents=True, exist_ok=True)
        territory_save_root = Path(self.config.save_root) / f"territory-{territory_id}"
        territory_save_root.mkdir(parents=True, exist_ok=True)
        engine = IntegratedARPGEngineV16A(
            str(territory_db),
            master_release_path=str(self.config.master_release_path),
            save_root=str(territory_save_root),
        )
        report = engine.create_world(
            f"{self.config.owner_scope}:territory:{territory_id}",
            self.config.world_seed,
            load_relationships=False,
            country_territory_id=territory_id,
        )
        wid = report["world"]["world_instance_id"]
        self._territory_engines[territory_id] = engine
        self._territory_world_ids[territory_id] = wid
        return engine, wid

    def switch_active_territory(self, territory_id: str) -> None:
        # Persiste o motor/wid atual no dict antes de trocar (protege contra
        # o caso de close()/restore terem mutado self._engine desde o
        # ultimo registro).
        self._territory_engines[self.active_territory_id] = self._engine
        self._territory_world_ids[self.active_territory_id] = self.world_instance_id
        engine, wid = self._territory_engine(territory_id)
        self._engine = engine
        self.world_instance_id = wid
        self.active_territory_id = territory_id
        # s16b_* (journal/cursor/bootstrap kv) sao tabelas proprias do
        # adapter, nunca criadas por IntegratedARPGEngineV16A.create_world() -
        # um motor de territorio recem-criado nunca passou por _schema()
        # ainda (so o motor de boot original passa, dentro de _boot()).
        # CREATE TABLE IF NOT EXISTS torna isso seguro de rodar de novo.
        self._schema()

    # ------------------------------------------------------------------ helpers

    def _godot(self) -> Any:
        return self._engine.godot(self.world_instance_id)

    def _rejected(self, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": "REJECTED",
            "reason": reason,
            "adapter_authority": self.ADAPTER_AUTHORITY,
            **extra,
        }

    def identity(self) -> dict[str, Any]:
        runtime = self._engine.runtime
        world = runtime.get_world(self.world_instance_id)
        return {
            "world_instance_id": self.world_instance_id,
            "owner_scope": world.get("owner_scope", self.config.owner_scope),
            "world_seed": world.get("seed", self.config.world_seed),
            "profile_ref": self.profile_ref,
            "avatar_ref": self.avatar_ref,
            "engine_class": type(self._engine).__name__,
            "engine_version": self._engine.VERSION,
            "engine_authority": self._engine.AUTHORITY,
            "master_version": runtime.master_version,
            "master_release_sha256": runtime.master_release_sha256,
        }

    @staticmethod
    def find_forbidden_field(value: Any, path: str = "$") -> str:
        """Recursive server-side authority-field scan. Returns '' when clean."""
        if isinstance(value, dict):
            for key, nested in value.items():
                child = f"{path}.{key}"
                if str(key).strip().lower() in FORBIDDEN_AUTHORITY_KEYS:
                    return child
                found = Stage16BAuthorityAdapter.find_forbidden_field(nested, child)
                if found:
                    return found
        elif isinstance(value, (list, tuple)):
            for index, nested in enumerate(value):
                found = Stage16BAuthorityAdapter.find_forbidden_field(nested, f"{path}[{index}]")
                if found:
                    return found
        return ""

    # ------------------------------------------------------------------ health

    def health(self) -> dict[str, Any]:
        with self._lock:
            health = self._engine.health_arpg_v16a(self.world_instance_id)
            status = "PASS" if health.get("status") == "PASS" else "FAIL"
            return {
                "status": status,
                "service": self.SERVICE,
                "server_authoritative": True,
                "adapter_version": self.ADAPTER_VERSION,
                "adapter_authority": self.ADAPTER_AUTHORITY,
                "bootstrap_mode": self.bootstrap_mode,
                "identity": self.identity(),
                "master": {
                    "version": self._engine.runtime.master_version,
                    "sha256": self._engine.runtime.master_release_sha256,
                    "path": str(self.config.master_release_path),
                    "read_only": True,
                },
                "arpg_health": health.get("status"),
                "stage15_health": health.get("stage15", {}).get("status"),
                "stage16a_health": health.get("stage16a", {}).get("status"),
                "failures": health.get("failures", []),
                "enabled_commands": list(self.ENABLED_COMMANDS),
                "snapshot_contract": {
                    "session_ref": True,
                    "snapshot_id": True,
                    "snapshot_sequence": "MONOTONIC_INT_PER_SESSION_PERSISTED",
                    "server_authoritative": True,
                },
                "command_contract": {
                    "command_ref": "REQUIRED_IDEMPOTENCY_KEY",
                    "client_authority_fields": "REJECTED",
                    "duplicate_replay": "SUPPRESSED_AND_REPLAYED_FROM_JOURNAL",
                },
                "development_profile_bootstrap": dict(self.development_profile_bootstrap),
                "resource_metric_placement": {
                    **self.resource_placement_materialization,
                    "configured": self.resource_placement_registry is not None,
                    "runtime_godot_transform_authority": False,
                },
            }

    # ------------------------------------------------------------------ sessions

    def bind_session(self, session_ref: Any) -> dict[str, Any]:
        with self._lock:
            normalized = str(session_ref or "").strip()
            if not normalized:
                return self._rejected("SESSION_REF_REQUIRED")
            if not SESSION_REF_RE.match(normalized):
                return self._rejected("INVALID_SESSION_REF")
            godot = self._godot()
            existing = godot._session(normalized) is not None
            result = godot.bind_session(normalized, self._player_ref, self.SESSION_ROLE)
            if result.get("status") != "PASS":
                return {**result, "adapter_authority": self.ADAPTER_AUTHORITY}
            if self.config.development_profile_bootstrap:
                # _ensure_development_combat_encounter() previously ran only once,
                # inside _boot(). A backend process that serves more than one Godot
                # session (e.g. two consecutive gate runs against the same running
                # process) never revalidated the development COMMON/ALPHA targets it
                # had already handed out, so a session bound after the first one had
                # defeated its target inherited a dead actor. The function itself
                # already reuses a pristine stored target untouched and only selects
                # a fresh one when the stored target is missing, dead or partially
                # damaged (never healing, never resurrecting) -- see its own body,
                # which this change does not modify. Re-running it on every bind just
                # moves that existing, already-correct revalidation to the point where
                # it is actually needed: the start of each development session, not
                # only the start of the process.
                self.development_profile_bootstrap["combat_encounter"] = (
                    self._ensure_development_combat_encounter()
                )
                # Section 5: test/dev convenience only -- REQUEST_NPC_DIALOGUE
                # itself never depends on this being set (see its own docstring).
                self.development_profile_bootstrap["dialogue_npc_ref"] = (
                    self._ensure_development_dialogue_npc()
                )
            return {
                **result,
                "rebound": existing,
                "identity": self.identity(),
                "cursor": self._cursor_state(normalized),
                "enabled_commands": list(self.ENABLED_COMMANDS),
                "adapter_authority": self.ADAPTER_AUTHORITY,
            }

    def revoke_session(self, session_ref: Any) -> dict[str, Any]:
        with self._lock:
            normalized = str(session_ref or "").strip()
            if not normalized:
                return self._rejected("SESSION_REF_REQUIRED")
            result = self._godot().revoke_session(normalized)
            return {**result, "adapter_authority": self.ADAPTER_AUTHORITY}

    # ------------------------------------------------------------------ snapshot

    def _cursor_row(self, session_ref: str):
        return self._engine.runtime.conn.execute(
            "SELECT last_sequence,last_snapshot_id,payload_hash FROM s16b_snapshot_cursor"
            " WHERE world_instance_id=? AND session_ref=?",
            (self.world_instance_id, session_ref),
        ).fetchone()

    def _cursor_state(self, session_ref: str) -> dict[str, Any]:
        row = self._cursor_row(session_ref)
        if row is None:
            return {"last_snapshot_sequence": None, "last_snapshot_id": None}
        expected = sha256_text(
            f"{self.world_instance_id}|{session_ref}|{int(row['last_sequence'])}|{row['last_snapshot_id']}"
        )
        if expected != row["payload_hash"]:
            raise AuthorityBootError("SNAPSHOT_CURSOR_HASH_MISMATCH:" + session_ref)
        return {
            "last_snapshot_sequence": int(row["last_sequence"]),
            "last_snapshot_id": str(row["last_snapshot_id"]),
        }

    def _advance_cursor(self, session_ref: str, projection: dict[str, Any]) -> tuple[int, str]:
        current = self._cursor_state(session_ref)
        last = current["last_snapshot_sequence"]
        sequence = 0 if last is None else int(last) + 1
        digest = sha256_text(canonical_json(projection))[:16]
        snapshot_id = f"S16B-{sequence:012d}-{digest}"
        payload_hash = sha256_text(
            f"{self.world_instance_id}|{session_ref}|{sequence}|{snapshot_id}"
        )
        with self._engine.runtime._write_lock:
            self._engine.runtime.conn.execute(
                "INSERT OR REPLACE INTO s16b_snapshot_cursor"
                "(world_instance_id,session_ref,last_sequence,last_snapshot_id,payload_hash)"
                " VALUES(?,?,?,?,?)",
                (self.world_instance_id, session_ref, sequence, snapshot_id, payload_hash),
            )
        return sequence, snapshot_id

    @staticmethod
    def _validate_projection(projection: dict[str, Any]) -> str:
        chunk = projection.get("chunk")
        if not isinstance(chunk, dict):
            return "INVALID_CHUNK"
        entities = chunk.get("entities", [])
        if not isinstance(entities, list):
            return "INVALID_ENTITY_LIST"
        seen: set[str] = set()
        for entry in entities:
            if not isinstance(entry, dict):
                return "INVALID_ENTITY_ENTRY"
            ref = str(entry.get("entity_ref", "")).strip()
            if not ref:
                return "EMPTY_ENTITY_REF"
            if ref in seen:
                return "DUPLICATE_ENTITY_REF"
            seen.add(ref)
        transform = projection.get("transform")
        if not isinstance(transform, dict):
            return "INVALID_TRANSFORM"
        if not _finite(transform.get("iso_x_m")) or not _finite(transform.get("iso_y_m")):
            return "INVALID_TRANSFORM"
        return ""

    @staticmethod
    def _godot_resource_kind(node: dict[str, Any]) -> str | None:
        """Map an existing gathering node to the B08 visual target taxonomy.

        This mapping never changes yield or Ground Loot source identity. In
        particular, Stage16A currently emits every MINING output as ORE; a stone
        node is presented as a ROCK target but its authoritative output remains ORE.
        """
        activity = str(node.get("activity_type") or "").upper()
        if activity == "LOGGING":
            return "TREE"
        if activity == "FORAGING":
            return "FLORA"
        if activity == "AGRICULTURE":
            return "AGRICULTURE"
        if activity == "MINING":
            source_meta = node.get("source_meta") or {}
            return "ROCK" if str(source_meta.get("kind") or "").upper() == "STONE" else "ORE"
        return None

    def _combat_projection(self) -> dict[str, Any]:
        """Build a read-only presentation from Stage03/07 combat authorities."""
        combat = self._engine.combat_arpg(self.world_instance_id)
        actors = self._engine.actors_arpg(self.world_instance_id)
        movement = self._engine.movement(self.world_instance_id)
        character = self._engine.character(self.world_instance_id).state(self.profile_ref)
        player_overlay = combat.ensure_player(self.profile_ref)
        max_health = float(character["derived"]["max_health"])
        player = {
            "actor_ref": self._player_ref,
            "health": float(character["vitals"]["health"]),
            "max_health": max_health,
            "hp_fraction": 0.0
            if max_health <= 0.0
            else max(0.0, min(1.0, float(character["vitals"]["health"]) / max_health)),
            "protection_fraction": 0.0,
            "protection_authority": "NOT_AVAILABLE_IN_STAGE16A_COMBAT_CORE",
            "life_state": str(character["vitals"]["life_state"]),
            "relevant": str(player_overlay.get("combat_state")) != "READY",
            "combat_state": str(player_overlay.get("combat_state", "READY")),
            "attack_cooldown_remaining_s": float(
                player_overlay.get("attack_cooldown_remaining_s", 0.0)
            ),
            "authority": combat.AUTHORITY,
        }
        targets: list[dict[str, Any]] = []
        for slot_name in ("common", "alpha"):
            target_ref = str(self._bootstrap_get(f"combat_target_{slot_name}_ref") or "").strip()
            if not target_ref:
                continue
            try:
                actor = actors.ensure_actor(target_ref)
                hostility = actors.hostility_to_profile(target_ref, self.profile_ref)
                state = combat.target_state(target_ref)
                position = movement.state(target_ref)
                npc = self._engine.country(self.world_instance_id).npc(target_ref)
            except Exception:
                continue
            if state is None:
                continue
            maximum = float(state.get("max_health", 0.0))
            current = float(state.get("health", 0.0))
            targets.append(
                {
                    "slot": slot_name.upper(),
                    "target_ref": target_ref,
                    "target_kind": "ACTOR",
                    "display_name": str(npc.get("name") or actor.get("source_class") or target_ref),
                    "source_class": actor.get("source_class"),
                    "hostile": bool(hostility.get("hostile", False)),
                    "disposition": str(actor.get("disposition", "NEUTRAL")),
                    "combat_rank": str(actor.get("combat_rank", "COMMON")),
                    "life_state": str(state.get("life_state", "ALIVE")),
                    "health": current,
                    "max_health": maximum,
                    "hp_fraction": 0.0
                    if maximum <= 0.0
                    else max(0.0, min(1.0, current / maximum)),
                    "shield_fraction": 0.0,
                    "shield_authority": "NOT_AVAILABLE_IN_STAGE16A_COMBAT_CORE",
                    "engaged": str(player_overlay.get("last_target_ref") or "") == target_ref,
                    "attack_range_m": float(combat.player_stats(self.profile_ref)["range_m"]),
                    "position": {
                        "iso_x_m": float(position["iso_x_m"]),
                        "iso_y_m": float(position["iso_y_m"]),
                        "altitude_m": float(position.get("altitude_m", 0.0)),
                    },
                    "position_authority": str(position.get("authority", movement.AUTHORITY)),
                    "canonical_identity_mutation": False,
                    "server_authoritative": True,
                    "authority": combat.AUTHORITY,
                    "hostility_authority": actors.AUTHORITY,
                }
            )
        return {
            "player": player,
            "targets": targets,
            "damage_decided_by_godot": False,
            "hit_decided_by_godot": False,
            "critical_decided_by_godot": False,
            "death_decided_by_godot": False,
            "cooldown_decided_by_godot": False,
            "authority": combat.AUTHORITY,
        }

    # Mirrors WaterBagSurvivalCore._is_protected_definition() exactly (same item_kind
    # set, same SINGULAR-rarity rule) so this transport-only projection can never
    # under-report what the real protection core (01_RUNTIME, untouched by this
    # constant) already treats as protected. Not a new protection rule -- the
    # existing one, read from a second place, kept in sync on purpose.
    _PROTECTED_ITEM_KINDS = {"QUEST", "QUEST_ITEM", "QUEST_UTILITY"}

    def _inventory_entries(self, inventory: dict[str, Any]) -> list[dict[str, Any]]:
        """Project item-core state without deriving stacks, capacity or ownership."""
        items = self._engine.items_arpg(self.world_instance_id)
        entries: list[dict[str, Any]] = []
        for item_ref, quantity in sorted(inventory.get("stacks", {}).items()):
            amount = int(quantity)
            if amount <= 0:
                continue
            definition = items.definition(str(item_ref))
            entries.append(
                {
                    "item_ref": str(item_ref),
                    "display_name": str(definition.get("name") or item_ref),
                    "quantity": amount,
                    "stackable": bool(definition.get("stackable", False)),
                    "item_kind": str(definition.get("item_kind", "MISC")),
                    "protected_or_critical": str(definition.get("item_kind", "")).upper() in self._PROTECTED_ITEM_KINDS,
                    "authority": items.AUTHORITY,
                }
            )
        for instance in inventory.get("instances", []):
            definition = items.definition(str(instance["item_ref"]))
            entries.append(
                {
                    "item_ref": str(instance["item_ref"]),
                    "instance_ref": str(instance["instance_ref"]),
                    "display_name": str(definition.get("name") or instance["item_ref"]),
                    "quantity": 1,
                    "stackable": False,
                    "item_kind": str(definition.get("item_kind", "MISC")),
                    "rarity": instance.get("rarity"),
                    "condition": instance.get("condition"),
                    "protected_or_critical": (
                        str(definition.get("item_kind", "")).upper() in self._PROTECTED_ITEM_KINDS
                        or str(instance.get("rarity", "")).upper() == "SINGULAR"
                    ),
                    "authority": items.AUTHORITY,
                }
            )
        return entries

    def _inventory_projection(self) -> dict[str, Any]:
        """Adapt Stage05/16A inventory and Bag state to the B09 UI contract."""
        stage16a = self._engine.stage16a(self.world_instance_id)
        items = self._engine.items_arpg(self.world_instance_id)
        base = items.inventory_snapshot(self.profile_ref)
        loadout = stage16a.ensure_weapon_loadout(self.profile_ref)
        carry = stage16a.water_bag.carry_metrics(self.profile_ref)
        effective_owner = stage16a.water_bag.effective_inventory_owner(self.profile_ref)
        bag_equipped = effective_owner != self.profile_ref
        bag_projection: dict[str, Any]
        bag_slot_capacity = 0
        if bag_equipped:
            bag = stage16a.water_bag.bag(effective_owner)
            bag_inventory = items.inventory_snapshot(effective_owner)
            bag_slot_capacity = int(bag.get("slot_capacity", bag_inventory["slot_capacity"]))
            bag_projection = {
                "state": "BAG_EQUIPPED",
                "bag_ref": effective_owner,
                "property_owner_ref": str(bag.get("property_owner_ref", self.profile_ref)),
                "carrier_ref": str(bag.get("carrier_ref", self.profile_ref)),
                "capacity_slots": bag_slot_capacity,
                "capacity_weight": float(
                    bag.get("weight_capacity", bag_inventory["weight_capacity"])
                ),
                "contents": self._inventory_entries(bag_inventory),
                "authority": stage16a.water_bag.AUTHORITY,
            }
        else:
            bag_projection = {
                "state": "NO_BAG",
                "bag_ref": "",
                "capacity_slots": 0,
                "capacity_weight": 0.0,
                "contents": [],
                "authority": stage16a.water_bag.AUTHORITY,
            }

        quick_slots: list[dict[str, Any]] = []
        for slot in (1, 2):
            instance_ref = str(loadout.get("slots", {}).get(str(slot)) or "")
            item_ref = ""
            if instance_ref:
                item_ref = str(items.instance(instance_ref)["item_ref"])
            quick_slots.append(
                {
                    "slot": slot,
                    "instance_ref": instance_ref,
                    "item_ref": item_ref,
                    "active": int(loadout.get("active_slot", 1)) == slot,
                }
            )

        equipment_slots = dict(base.get("equipped", {}))
        protected_refs = [
            str(entry.get("instance_ref") or entry.get("item_ref"))
            for entry in self._inventory_entries(base)
            if entry.get("protected_or_critical")
        ]
        max_slots = int(carry["base_slot_limit"]) + bag_slot_capacity
        return {
            "base_inventory": {
                "owner_ref": self.profile_ref,
                "slot_limit": int(carry["base_slot_limit"]),
                "weight_limit": float(base["weight_capacity"]),
                "stacks": self._inventory_entries(base),
                "authority": items.AUTHORITY,
            },
            "bag": bag_projection,
            "equipment": {
                "slots": equipment_slots,
                "protected_critical_refs": protected_refs,
                "authority": items.AUTHORITY,
            },
            "weapon_loadout": {
                "quick_slots": quick_slots,
                "active_slot": int(loadout["active_slot"]),
                "authority": loadout.get("authority"),
            },
            "carry": {
                "current_weight": float(carry["current_weight"]),
                "max_weight": float(carry["weight_capacity"]),
                "used_slots": int(carry["used_slots_total"]),
                "max_slots": max_slots,
                "authority": carry["inventory_authority"],
            },
            "routing": {
                "source": "EQUIPPED_BAG" if bag_equipped else "BASE_INVENTORY",
                "effective_inventory_owner_ref": effective_owner,
                "currency_wallet_owner_ref": self.profile_ref,
                "authority": stage16a.AUTHORITY,
            },
            "capacity_calculated_by_godot": False,
            "ownership_selected_by_godot": False,
            "authority": stage16a.AUTHORITY,
        }

    def _skill_projection(self) -> dict[str, Any]:
        """Fase 7.1 (Stage17): projeta ARPGSkillCore.snapshot() no formato exato
        que skill_client.gd ja espera (active_slots/passive_slots como Array de
        tamanho fixo, skills como Dictionary skill_ref->{rank, mastery_progress})
        - contrato definido do lado cliente antes deste metodo existir, nao
        inventado aqui. Nunca calcula rank/mastery - so reformata o que
        ARPGSkillCore ja decidiu."""
        skills = self._engine.skills_arpg(self.world_instance_id)
        state = skills.snapshot(self.profile_ref)
        active_slots = [
            state["active_loadout"].get(str(i)) for i in range(1, skills.ACTIVE_SLOTS + 1)
        ]
        passive_slots = [
            state["passive_loadout"].get(str(i)) for i in range(1, skills.PASSIVE_SLOTS + 1)
        ]
        projected_skills: dict[str, Any] = {}
        for skill_ref, rec in state["learned"].items():
            mastery_xp = int(rec.get("mastery_xp", 0))
            projected_skills[skill_ref] = {
                "rank": int(rec.get("rank", 1)),
                "mastery_progress": round((mastery_xp % 100) / 100.0, 4),
            }
        return {
            "active_slots": active_slots,
            "passive_slots": passive_slots,
            "skills": projected_skills,
            "build_signature": state.get("build_signature"),
            "authority": skills.AUTHORITY,
        }

    def _vendor_stock_projection(self) -> list[dict[str, Any]]:
        """Project real Stage13 stock. Numeric prices remain quote-only."""
        economy = self._engine.economy_arpg(self.world_instance_id)
        items = self._engine.items_arpg(self.world_instance_id)
        rows: list[dict[str, Any]] = []
        for vendor in economy.list_vendors():
            if str(vendor.get("location_ref")) != "POI-002":
                continue
            inventory = items.inventory_snapshot(str(vendor["vendor_ref"]))
            quantities: dict[str, int] = {
                str(item_ref): int(quantity)
                for item_ref, quantity in inventory.get("stacks", {}).items()
                if int(quantity) > 0
            }
            first_instances: dict[str, str] = {}
            for instance in inventory.get("instances", []):
                item_ref = str(instance["item_ref"])
                quantities[item_ref] = quantities.get(item_ref, 0) + 1
                first_instances.setdefault(item_ref, str(instance["instance_ref"]))
            stock: list[dict[str, Any]] = []
            for item_ref, quantity in sorted(quantities.items()):
                definition = items.definition(item_ref)
                entry = {
                    "item_ref": item_ref,
                    "display_name": str(definition.get("name") or item_ref),
                    "quantity": quantity,
                    "item_kind": str(definition.get("item_kind", "MISC")),
                    "operations": ["BUY"],
                    "price_requires_quote": True,
                    "authority": economy.AUTHORITY,
                }
                if item_ref in first_instances:
                    entry["instance_ref"] = first_instances[item_ref]
                stock.append(entry)
            rows.append(
                {
                    "vendor_ref": str(vendor["vendor_ref"]),
                    "location_ref": str(vendor["location_ref"]),
                    "display_name": str(vendor.get("name") or vendor["vendor_ref"]),
                    "items": stock,
                    "authority": economy.AUTHORITY,
                }
            )
        return rows

    @staticmethod
    def _quest_npc_ref(index: int) -> str:
        return (
            "NPC-B03-NEUTRAL-001"
            if index % 2 == 0
            else "NPC-B05-DIALOGUE-PEER-001"
        )

    def _quest_projection(self) -> dict[str, Any]:
        """Project only the five Stage12 templates and their persisted instances."""
        narrative = self._engine.narrative_arpg(self.world_instance_id)
        templates = narrative.list_quest_templates()
        active = {row["quest_ref"]: row for row in narrative.list_quests(self.profile_ref)}
        offers: list[dict[str, Any]] = []
        quests: list[dict[str, Any]] = []
        for index, template in enumerate(templates):
            quest_ref = str(template["quest_ref"])
            npc_ref = self._quest_npc_ref(index)
            objectives = []
            instance = active.get(quest_ref)
            objective_states = instance.get("objective_states", {}) if instance else {}
            for objective in template.get("objectives", []):
                objectives.append(
                    {
                        "objective_ref": str(objective["objective_ref"]),
                        "text": str(objective["objective_ref"]),
                        "type": str(objective["type"]),
                        "state": str(
                            objective_states.get(objective["objective_ref"], "PENDING")
                        ),
                        "authority": narrative.AUTHORITY,
                    }
                )
            common = {
                "quest_ref": quest_ref,
                "npc_ref": npc_ref,
                "title": str(template.get("name") or quest_ref),
                "objectives": objectives,
                "choices": [],
                "source_refs": list(template.get("source_refs", [])),
                "npc_binding_authority": "GODOT_LOCAL_PRESENTATION_ANCHOR_ONLY",
                "canonical_mutation": False,
                "authority": narrative.AUTHORITY,
            }
            if instance is None:
                offers.append(common)
            else:
                quests.append({**common, "state": str(instance["state"])})
        return {
            "offers": offers,
            "quests": quests,
            "template_count": len(templates),
            "objective_completion_decided_by_godot": False,
            "reward_decided_by_godot": False,
            "authority": narrative.AUTHORITY,
        }

    def _dialogue_npc_projection(self) -> dict[str, Any]:
        """Project the SAME dialogue_npc_ref already selected/validated once.

        G16B-19C1: closes DIALOGUE_TARGET_IDENTITY_PROJECTION_GAP. This is a
        pure read of self.development_profile_bootstrap["dialogue_npc_ref"],
        set only by _ensure_development_dialogue_npc() (bind_session()) --
        no new selection logic, no re-derivation, no fallback to a combat
        target. Exposes only npc_ref + an explicit non-canonical authority
        label, never the full development_profile_bootstrap dict (which also
        carries combat_encounter, item grants, weapon loadout, etc. -- none
        of that is dialogue-relevant and none of it is exposed here).

        If no development bootstrap ran this world (development_profile_bootstrap
        config disabled), there is no seeded dialogue_npc_ref to report --
        this returns "available": False rather than fabricating one. Any
        real npc_target_ref a production caller already knows about still
        works with REQUEST_NPC_DIALOGUE regardless of this projection; this
        block only exists so the current Stage16B development vertical slice
        has something authoritative to read.
        """
        npc_ref = str(self.development_profile_bootstrap.get("dialogue_npc_ref") or "").strip()
        if not npc_ref:
            return {
                "available": False,
                "npc_ref": None,
                "authority": "STAGE16B_SERVER_SELECTED_DEVELOPMENT_DIALOGUE_TARGET",
            }
        return {
            "available": True,
            "npc_ref": npc_ref,
            "canonical_identity": False,
            "authority": "STAGE16B_SERVER_SELECTED_DEVELOPMENT_DIALOGUE_TARGET",
        }

    def _next_transport_sequence(self) -> int:
        """Return a monotonic wire cursor without deciding any gameplay outcome."""
        self._transport_sequence = max(self._transport_sequence + 1, int(time.time() * 1000))
        return self._transport_sequence

    def _bag_contents_summary(self, bag_ref: str) -> list[dict[str, Any]]:
        try:
            inventory = self._engine.items_arpg(self.world_instance_id).inventory_snapshot(bag_ref)
        except KeyError:
            return []
        return self._inventory_entries(inventory)

    @staticmethod
    def _ground_loot_projection(drop: dict[str, Any]) -> dict[str, Any]:
        """Expose Stage16A ACTIVE+WATER using the already-contracted B07 alias."""
        entry = dict(drop)
        entry["target_ref"] = str(drop["drop_ref"])
        if (
            str(entry.get("state", "")).upper() == "ACTIVE"
            and str(entry.get("environment", "")).upper() == "WATER"
        ):
            entry["state"] = "RECOVERABLE_IN_WATER"
        return entry

    def _bag_projection(
        self,
        bag: dict[str, Any],
        *,
        sequence: int,
        state_override: str | None = None,
        environment_override: str | None = None,
    ) -> dict[str, Any]:
        """Translate a Stage16A Bag record to the existing Godot B10 vocabulary."""
        core_state = str(bag.get("state", "")).upper()
        state = str(state_override or core_state).upper()
        if state == "EQUIPPED":
            state = "RECOVERED"
        location = str(bag.get("location_kind") or "").upper()
        environment = str(environment_override or "").upper()
        if not environment:
            environment = "WATER" if location == "WATER" or state == "SUNK" else "LAND"
        position = bag.get("position")
        if not isinstance(position, dict):
            position = {"iso_x_m": 0.0, "iso_y_m": 0.0, "altitude_m": 0.0}
        active = state in {"DROPPED_LAND", "DROPPED_WATER_FLOATING"}
        owner_ref = str(bag.get("property_owner_ref") or "")
        bag_ref = str(bag.get("bag_ref") or "")
        return {
            "bag_ref": bag_ref,
            "target_ref": bag_ref,
            "original_owner_ref": owner_ref,
            "property_owner_ref": owner_ref,
            "carrier_ref": str(bag.get("carrier_ref") or ""),
            "state": state,
            "environment": environment,
            "location_kind": environment,
            "recoverable": active,
            "water_exposure_s": float(bag.get("water_exposure_s") or 0.0),
            "water_ttl_s": 1800.0 if environment == "WATER" else None,
            "contents_summary": self._bag_contents_summary(bag_ref),
            "context_metadata": {
                "origin": "STAGE16A_DROPPED_BAG_AUTHORITY",
                "property_owner_ref": owner_ref,
                "foreign_recovery_ref": bag.get("foreign_recovery_ref"),
                "canonical_mutation": False,
            },
            "position": {
                "iso_x_m": float(position.get("iso_x_m", 0.0)),
                "iso_y_m": float(position.get("iso_y_m", 0.0)),
                "altitude_m": float(position.get("altitude_m", 0.0)),
            },
            "projection_sequence": sequence,
            "server_authoritative": True,
            "authority": self._engine.stage16a(self.world_instance_id).water_bag.AUTHORITY,
        }

    def _dropped_bag_entries(self, *, sequence: int) -> list[dict[str, Any]]:
        rows = self._engine.runtime.conn.execute(
            "SELECT bag_ref FROM arpg_stage16a_bags WHERE world_instance_id=? ORDER BY bag_ref",
            (self.world_instance_id,),
        ).fetchall()
        water_bag = self._engine.stage16a(self.world_instance_id).water_bag
        entries: list[dict[str, Any]] = []
        for row in rows:
            bag = water_bag.bag(str(row["bag_ref"]))
            if str(bag.get("state", "")).upper() not in {
                "DROPPED_LAND", "DROPPED_WATER_FLOATING", "SUNK"
            }:
                continue
            entries.append(self._bag_projection(bag, sequence=sequence))
        return entries

    def _retention_projection(self) -> dict[str, Any]:
        inventory = self._inventory_projection()
        equipment = inventory["equipment"]
        items = self._engine.items_arpg(self.world_instance_id)
        armor_refs: list[str] = []
        clothes_refs: list[str] = []
        for slot, instance_ref in dict(equipment.get("slots", {})).items():
            if not instance_ref or str(slot).upper() == "MAIN_HAND":
                continue
            try:
                instance = items.instance(str(instance_ref))
                definition = items.definition(str(instance["item_ref"]))
            except KeyError:
                continue
            kind = str(definition.get("item_kind", "")).upper()
            if kind in {"CLOTHES", "CLOTHING", "GARMENT"}:
                clothes_refs.append(str(instance_ref))
            elif kind == "ARMOR":
                armor_refs.append(str(instance_ref))
        character = self._engine.character(self.world_instance_id).ensure_profile(self.profile_ref)
        return {
            "xp_retained": True,
            "experience": int(character.get("experience", 0)),
            "quick_slots": list(inventory["weapon_loadout"]["quick_slots"]),
            "active_slot": int(inventory["weapon_loadout"]["active_slot"]),
            "equipped_armor_refs": armor_refs,
            "equipped_clothes_refs": clothes_refs,
            "protected_critical_refs": list(equipment.get("protected_critical_refs", [])),
            "policy_projected_from_stage16a": True,
            "authority": self._engine.stage16a(self.world_instance_id).AUTHORITY,
        }

    def _death_recovery_projection(self, session_ref: str, *, sequence: int) -> dict[str, Any]:
        character = self._engine.character(self.world_instance_id).ensure_profile(self.profile_ref)
        life_state = str(character.get("vitals", {}).get("life_state", "ALIVE")).upper()
        recovery = self._engine.save_recovery(self.world_instance_id).ensure_profile(self.profile_ref)
        return {
            "server_authoritative": True,
            "session_ref": session_ref,
            "restore_sequence": sequence,
            "state": "DEAD_AWAITING_RESPAWN" if life_state == "DEAD" else "ALIVE",
            "retention_projection": self._retention_projection(),
            "recovery_state_ref": str(recovery.get("last_recovery_event_ref") or "NONE"),
            "authority": self._engine.save_recovery(self.world_instance_id).AUTHORITY,
        }

    def _restore_snapshot_payload(
        self,
        session_ref: str,
        *,
        slot_ref: str,
        save_sequence: int,
        restore_sequence: int,
    ) -> dict[str, Any]:
        """Rebuild every B10 presentation channel from the reopened authoritative DB."""
        live = self.snapshot(session_ref)
        if live.get("status") != "PASS":
            raise AuthorityBootError("RESTORED_AUTHORITY_SNAPSHOT_FAILED")
        transform = dict(live["transform"])
        inventory = dict(live["inventory_projection"])
        inventory.update(
            {
                "server_authoritative": True,
                "session_ref": session_ref,
                "snapshot_sequence": restore_sequence,
            }
        )
        quest = dict(live["quest_projection"])
        common = {
            "server_authoritative": True,
            "session_ref": session_ref,
            "snapshot_sequence": restore_sequence,
        }
        return {
            "server_authoritative": True,
            "session_ref": session_ref,
            "restore_ref": f"RESTORE-{slot_ref.upper()}-{restore_sequence}",
            "restore_sequence": restore_sequence,
            "save_sequence": save_sequence,
            "player": {
                "position": {
                    "iso_x_m": float(transform["iso_x_m"]),
                    "iso_y_m": float(transform["iso_y_m"]),
                    "altitude_m": float(transform.get("altitude_m", 0.0)),
                },
                "presentation": {
                    "stamina": dict(live["stamina"]),
                    "weapon_loadout": dict(live["weapon_loadout"]),
                    "profile_preferences": dict(live["profile_preferences"]),
                    "combat_presentation": dict(live["combat_presentation"]),
                },
            },
            "world": {
                # Godot cells are a smaller visual scale than Living macro chunks.
                "active_cell": {"x": 0, "y": 0},
                "living_chunk": dict(live.get("chunk", {})),
                "zone_ref": self._engine.world_arpg(self.world_instance_id)
                .profile_state(self.profile_ref)["zone_ref"],
                # Recomputed fresh from the restored world's real zone_ref/
                # position, never persisted -- same _streaming_projection()
                # the live snapshot() path uses, reused here via `live`
                # rather than called a second time (G16B-09B Section 10:
                # REQUEST_RELOAD_RESYNC must reconstruct, not duplicate).
                "streaming": dict(live.get("world_streaming", {})),
                "resource_snapshot": {
                    **common,
                    "resources": list(live.get("resources", [])),
                },
            },
            "ground_loot_snapshot": {
                **common,
                "ground_loot": list(live.get("ground_loot", [])),
            },
            "profile_preference": {
                "auto_pickup": bool(live["profile_preferences"]["auto_pickup"]),
                "preference_sequence": restore_sequence,
            },
            "inventory_snapshot": inventory,
            "economy_projection": dict(live["economy_projection"]),
            "quest_projection": {
                "offer_snapshot": {**common, "offers": list(quest.get("offers", []))},
                "state_snapshot": {**common, "quests": list(quest.get("quests", []))},
            },
            "dropped_bag_snapshot": {
                **common,
                "dropped_bags": self._dropped_bag_entries(sequence=restore_sequence),
                "complete_projection": True,
            },
            "death_recovery_snapshot": self._death_recovery_projection(
                session_ref, sequence=restore_sequence
            ),
            "save_loaded_by_godot": False,
            "authority": self._engine.save_recovery(self.world_instance_id).AUTHORITY,
        }

    def _active_water_exposure_exists(self) -> bool:
        loot_rows = self._engine.runtime.conn.execute(
            "SELECT payload_json FROM arpg_ground_loot WHERE world_instance_id=? AND state='ACTIVE'",
            (self.world_instance_id,),
        ).fetchall()
        loot = any(
            str(json.loads(str(row["payload_json"])).get("environment", "")).upper()
            == "WATER"
            for row in loot_rows
        )
        bag = self._engine.runtime.conn.execute(
            "SELECT 1 FROM arpg_stage16a_bags WHERE world_instance_id=? AND state='DROPPED_WATER_FLOATING' LIMIT 1",
            (self.world_instance_id,),
        ).fetchone()
        return loot or bag is not None

    # Real seconds between world-orchestrator ticks (1 tick = 1 game hour at
    # the default ticks_per_day=24). Dev/presentation pacing, not a canon
    # value: a full game day passes every 240 real seconds. Tunable later.
    ORCHESTRATOR_TICK_INTERVAL_S = 10.0

    def _orchestrator_tick_loop(self) -> None:
        """Background daemon thread body. Wakes up every
        ORCHESTRATOR_TICK_INTERVAL_S real seconds and runs exactly ONE
        run_tick() per currently-registered territory engine -- fixed,
        bounded cost per wake-up regardless of how long the process has been
        idle (no catch-up burst; that was the earlier regression's root
        cause). Holds the SAME self._lock every command/snapshot path
        already serializes on, so a tick can never interleave with a
        command, a snapshot read, or a territory switch mutating
        self._territory_engines mid-iteration.

        Never raises out of the thread: an uncaught exception here would
        silently kill background ticking for the rest of the process with
        no signal to anyone, which is worse than one skipped tick.
        """
        from living_runtime import (  # noqa: PLC0415
            ConflictError,
            NotFoundError,
            OfflinePolicyError,
            ValidationError,
        )

        while not self._orchestrator_tick_stop.wait(self.ORCHESTRATOR_TICK_INTERVAL_S):
            try:
                with self._lock:
                    engines_by_territory = list(self._territory_engines.items())
                    world_ids = dict(self._territory_world_ids)
                    for territory_id, engine in engines_by_territory:
                        wid = world_ids.get(territory_id)
                        if engine is None or wid is None:
                            continue
                        try:
                            engine.orchestrator.run_tick(wid)
                        except (ConflictError, ValidationError, NotFoundError, OfflinePolicyError):
                            # Paused/not-yet-ready/etc. for this one territory --
                            # not a bug, just nothing to do there this wake-up.
                            continue
                        except Exception:  # noqa: BLE001 - one territory's failure must never stop the others or kill the thread
                            continue
            except Exception:  # noqa: BLE001 - the loop itself must survive anything
                continue

    def _advance_authoritative_water_clock(self) -> dict[str, Any]:
        """Advance TTL only from server monotonic time while exposed objects exist."""
        now = time.monotonic()
        delta = max(0.0, now - self._last_authoritative_water_tick)
        if not self._active_water_exposure_exists():
            self._last_authoritative_water_tick = now
            return {"status": "PASS", "advanced_s": 0.0, "active": False}
        if delta < 0.05:
            return {"status": "PASS", "advanced_s": 0.0, "active": True}
        sequence = self._next_result_sequence("AUTHORITATIVE_WATER_CLOCK")
        result = self._engine.stage16a(self.world_instance_id).advance_water_time(
            delta,
            event_ref=f"S16B-WATER-CLOCK-{sequence:012d}",
        )
        self._last_authoritative_water_tick = now
        return {**result, "advanced_s": delta, "server_clock": True}

    def _zone_living_state(self, block: dict[str, Any]) -> dict[str, Any]:
        """Compact, real, mutable Living summary for one SYSTEMIC zone's block.

        Reads directly from the same CountryScaleSystem.block(block_ref)
        structure CountryLivingDomainBridge.hunt_fauna() persists back to
        (fauna[].count/status) -- never a copy, never a fabricated
        placeholder. Deliberately coarse (G16B-09B Section 26): no per-NPC
        records, no full block serialization, just enough real, genuinely
        changeable state to prove the zone is Living, not merely labeled.
        """
        fauna = block.get("fauna") or []
        active_refs = sorted(str(f.get("id")) for f in fauna if str(f.get("status")) == "ACTIVE")
        extirpated_refs = sorted(str(f.get("id")) for f in fauna if str(f.get("status")) != "ACTIVE")
        climate = block.get("climate") or {}
        return {
            "block_ref": str(block.get("id", "")),
            "fauna_species_count": len(fauna),
            "fauna_active_species_refs": active_refs,
            "fauna_extirpated_species_refs": extirpated_refs,
            "fauna_total_population": sum(int(f.get("count", 0)) for f in fauna),
            "resource_richness": float(climate.get("resource_richness", 0.0)),
            "city_count": len(block.get("cities") or []),
            "authority": "COUNTRY_SCALE_BLOCK_LIVING_STATE_REAL",
        }

    def _streaming_projection(self) -> dict[str, Any]:
        """Authoritative ACTIVE/SYSTEMIC zone classification (G16B-09).

        Derived fresh on every call from the player's real current
        zone_ref -- never persisted (G16B-09B Section 1: phase is a
        function of authoritative position, not stored state) and never
        client-suppliable (Section 11: nothing here reads from params).

        zone_ref -> world_arpg.zone(zone_ref)["block_ref"] ->
        CountryScaleSystem.block(block_ref) is the real, pre-existing
        spatial/Living bridge this projection reuses (confirmed in
        G16B-09A: arpg_gathering_work_core.py already resolves
        zone["block_ref"] through self.country.block() the same way).

        Scope note (reported, not hidden -- Section 3): cell-level
        PRELOAD subdivision *within* the current zone is intentionally
        NOT computed here. No existing code binds a specific
        MAP_SCALE_POLICIES area_scale to a real zone_ref, and inventing
        one now would be exactly the arbitrary zone policy this round's
        Section 3 forbids. Only the zone-level ACTIVE (current zone) vs
        SYSTEMIC (every other real zone) split is implemented -- fully
        anchored in existing identity, no invented adjacency rule.
        """
        world_arpg = self._engine.world_arpg(self.world_instance_id)
        current_zone_ref = str(world_arpg.profile_state(self.profile_ref)["zone_ref"])
        country = self._engine.country(self.world_instance_id)
        zones_out: list[dict[str, Any]] = []
        for zone in world_arpg.list_zones():
            zone_ref = str(zone["zone_ref"])
            block_ref = str(zone["block_ref"])
            phase = "ACTIVE" if zone_ref == current_zone_ref else "SYSTEMIC"
            entry: dict[str, Any] = {
                "zone_ref": zone_ref,
                "block_ref": block_ref,
                "stream_phase": phase,
            }
            if phase == "SYSTEMIC":
                entry["zone_living_state"] = self._zone_living_state(country.block(block_ref))
            zones_out.append(entry)
        living_core = self._engine.living_arpg(self.world_instance_id)
        macro = living_core.snapshot()
        return {
            "current_zone_ref": current_zone_ref,
            "zones": zones_out,
            # Country-wide aggregate context ONLY -- deliberately kept
            # structurally separate from zone_living_state above so it can
            # never be mistaken for per-zone state (G16B-09B Section 7).
            "living_macro_context": {
                "country_ref": str(macro.get("country_ref", "")),
                "metrics": dict(macro.get("metrics", {})),
                "resilience_index": float(macro.get("resilience_index", 0.0)),
                "systemic_pressure": float(macro.get("systemic_pressure", 0.0)),
                "authority": living_core.AUTHORITY,
            },
            "cell_detail_within_active_zone": "NOT_YET_AUTHORITATIVE_SEE_G16B_09_SCOPE_NOTE",
            "client_supplied_phase_accepted": False,
            "server_authoritative": True,
            "authority": self.ADAPTER_AUTHORITY,
        }

    def snapshot(self, session_ref: Any) -> dict[str, Any]:
        with self._lock:
            normalized = str(session_ref or "").strip()
            if not normalized:
                return self._rejected("SESSION_REF_REQUIRED")
            if not SESSION_REF_RE.match(normalized):
                return self._rejected("INVALID_SESSION_REF")
            projection = self._godot().client_snapshot(normalized)
            if projection.get("status") != "PASS":
                return {
                    **projection,
                    "session_ref": normalized,
                    "server_authoritative": True,
                    "adapter_authority": self.ADAPTER_AUTHORITY,
                }
            invalid = self._validate_projection(projection)
            if invalid:
                return self._rejected(
                    "SNAPSHOT_PROJECTION_INVALID", detail=invalid, session_ref=normalized
                )
            water_clock = self._advance_authoritative_water_clock()
            # World-orchestrator ticking (ecology, NPC decide(), social
            # projection, consequence drain) runs on its own background
            # daemon thread (_orchestrator_tick_loop) -- deliberately never
            # inline here. An earlier inline attempt caused a real
            # regression: a long-idle catch-up burst of real ticks leaked
            # 0.07-0.15s of wall time into the water clock's sub-millisecond
            # precision tests, since both read the same time.monotonic() in
            # this same request path.
            stage16a = self._engine.stage16a(self.world_instance_id)
            preferences = stage16a.ensure_profile_preferences(self.profile_ref)
            weapon_loadout = stage16a.ensure_weapon_loadout(self.profile_ref)
            inventory = self._engine.items_arpg(self.world_instance_id).inventory_snapshot(
                self.profile_ref
            )
            ground_loot = []
            for drop in stage16a.ground_loot.active_drops():
                ground_loot.append(self._ground_loot_projection(drop))
            world_state = self._engine.world_arpg(self.world_instance_id).profile_state(
                self.profile_ref
            )
            current_zone_ref = str(world_state["zone_ref"])
            gathering = self._engine.gathering_arpg(self.world_instance_id)
            resources: list[dict[str, Any]] = []
            gathering_nodes: list[dict[str, Any]] = []
            logical_nodes_by_ref: dict[str, dict[str, Any]] = {}
            for node in gathering.list_nodes(zone_ref=current_zone_ref):
                logical_nodes_by_ref[str(node["node_ref"])] = node
                resource_kind = self._godot_resource_kind(node)
                source_meta = node.get("source_meta") or {}
                gathering_nodes.append(
                    {
                        "target_ref": str(node["node_ref"]),
                        "activity_type": str(node["activity_type"]),
                        "visual_resource_kind": resource_kind,
                        "state": "DEPLETED" if bool(node.get("depleted")) else "AVAILABLE",
                        "remaining_units": int(node["remaining_units"]),
                        "zone_ref": str(node["zone_ref"]),
                        "block_ref": str(node["block_ref"]),
                        "source_role": source_meta.get("role"),
                        "server_authoritative": True,
                        "authority": node.get("authority"),
                    }
                )
            if self.resource_placement_registry is not None:
                current_block_ref = str(
                    self._engine.world_arpg(self.world_instance_id)
                    .zone(current_zone_ref)["block_ref"]
                )
                for presentation_order, placement in enumerate(
                    self.resource_placement_registry.active_placements(
                        zone_ref=current_zone_ref, block_ref=current_block_ref
                    )
                ):
                    logical_ref = str(placement["logical_node_ref"])
                    node = logical_nodes_by_ref.get(logical_ref)
                    if node is None:
                        continue
                    source_meta = node.get("source_meta") or {}
                    resources.append(
                        {
                            "target_ref": str(placement["placement_ref"]),
                            "placement_ref": str(placement["placement_ref"]),
                            "logical_node_ref": logical_ref,
                            "target_kind": "RESOURCE",
                            "resource_kind": str(placement["resource_kind"]),
                            "activity_type": str(node["activity_type"]),
                            "display_name": str(
                                source_meta.get("name")
                                or node.get("output_item_ref")
                                or placement["resource_kind"].title()
                            ),
                            "state": "DEPLETED"
                            if bool(node.get("depleted"))
                            else "AVAILABLE",
                            "stream_phase": "ACTIVE",
                            "world_instance_id": self.world_instance_id,
                            "zone_ref": str(placement["zone_ref"]),
                            "block_ref": str(placement["block_ref"]),
                            "remaining_units": int(node["remaining_units"]),
                            "position": dict(placement["position"]),
                            "position_authority": str(
                                placement["position_authority"]
                            ),
                            "placement_revision": str(
                                placement["placement_revision"]
                            ),
                            "source_manifest_hash": str(
                                placement["source_manifest_hash"]
                            ),
                            "authoring_object_ref": str(
                                placement["authoring_object_ref"]
                            ),
                            "authoring_node_path": str(
                                placement["authoring_node_path"]
                            ),
                            "gather_range_m": GATHER_RANGE_M,
                            "presentation_order": presentation_order,
                            "server_authoritative": True,
                            "authority": PLACEMENT_AUTHORITY,
                            "logical_authority": node.get("authority"),
                            "runtime_godot_transform_authority": False,
                        }
                    )
            else:
                # Historical Stage16B compatibility mode.  Stage17 production is
                # launched with a canonical placement manifest and never uses this
                # placeholder projection for normal interaction.
                presentation_order = 0
                for node in logical_nodes_by_ref.values():
                    resource_kind = self._godot_resource_kind(node)
                    if resource_kind is None:
                        continue
                    source_meta = node.get("source_meta") or {}
                    resources.append(
                        {
                            "target_ref": str(node["node_ref"]),
                            "resource_kind": resource_kind,
                            "activity_type": str(node["activity_type"]),
                            "display_name": str(
                                source_meta.get("name")
                                or node.get("output_item_ref")
                                or resource_kind.title()
                            ),
                            "state": "DEPLETED"
                            if bool(node.get("depleted"))
                            else "AVAILABLE",
                            "stream_phase": "ACTIVE",
                            "zone_ref": str(node["zone_ref"]),
                            "block_ref": str(node["block_ref"]),
                            "remaining_units": int(node["remaining_units"]),
                            "presentation_order": presentation_order,
                            "position_authority": "GODOT_LOCAL_PLACEHOLDER_ONLY",
                            "server_authoritative": True,
                            "authority": node.get("authority"),
                        }
                    )
                    presentation_order += 1
            player_movement = self._engine.movement(self.world_instance_id).state(
                self._player_ref
            )
            stamina_value = float(player_movement["stamina"])
            combat_projection = self._combat_projection()
            inventory_projection = self._inventory_projection()
            vendor_stock = self._vendor_stock_projection()
            economy = self._engine.economy_arpg(self.world_instance_id)
            quest_projection = self._quest_projection()
            presentation_sequence = self._next_transport_sequence()
            profile_projection = {
                "presentation_sequence": presentation_sequence,
                "profile_preferences": {
                    "auto_pickup": bool(preferences["auto_pickup_enabled"]),
                    "reduced_motion": bool(preferences.get("reduced_motion", False)),
                    "preference_sequence": presentation_sequence,
                    "authority": preferences.get("authority"),
                },
                "weapon_loadout": weapon_loadout,
                "inventory": inventory,
                "equipment_modifiers": self._engine.items_arpg(
                    self.world_instance_id
                ).equipment_modifiers(self.profile_ref),
                "ground_loot": ground_loot,
                "resources": resources,
                "gathering_nodes": gathering_nodes,
                "combat_targets": combat_projection["targets"],
                "combat_presentation": combat_projection,
                "inventory_projection": inventory_projection,
                "vendor_stock": vendor_stock,
                "economy_projection": {
                    "wallet": economy.wallet(self.profile_ref),
                    "price_calculated_by_godot": False,
                    "authority": economy.AUTHORITY,
                },
                "quest_projection": quest_projection,
                "skill_projection": self._skill_projection(),
                "economy_faction_projection": self._economy_faction_projection(),
                "dialogue_npc_projection": self._dialogue_npc_projection(),
                "world_streaming": self._streaming_projection(),
                "dropped_bags": self._dropped_bag_entries(sequence=0),
                "death_recovery": self._death_recovery_projection(normalized, sequence=0),
                "water_clock": water_clock,
                "stamina": {
                    "value": stamina_value,
                    "maximum": 100.0,
                    "fraction": max(0.0, min(1.0, stamina_value / 100.0)),
                    "activity": "INACTIVE" if stamina_value >= 100.0 - 1e-9 else "CONSUMING",
                    "authority": "CONTINUOUS_MOVEMENT_SYSTEM_SERVER_AUTHORITATIVE",
                },
            }
            projection_with_profile = {**projection, **profile_projection}
            sequence, snapshot_id = self._advance_cursor(normalized, projection_with_profile)
            return {
                **projection_with_profile,
                "server_authoritative": True,
                "session_ref": normalized,
                "snapshot_id": snapshot_id,
                "snapshot_sequence": sequence,
                "identity": self.identity(),
                "adapter_authority": self.ADAPTER_AUTHORITY,
            }

    def resync(
        self,
        session_ref: Any,
        last_snapshot_sequence: Any = None,
        last_snapshot_id: Any = None,
    ) -> dict[str, Any]:
        with self._lock:
            normalized = str(session_ref or "").strip()
            if not normalized:
                return self._rejected("SESSION_REF_REQUIRED")
            if not SESSION_REF_RE.match(normalized):
                return self._rejected("INVALID_SESSION_REF")
            if self._godot()._session(normalized) is None:
                return self._rejected("UNKNOWN_OR_INACTIVE_SESSION", session_ref=normalized)
            cursor = self._evaluate_cursor(normalized, last_snapshot_sequence, last_snapshot_id)
            if cursor.get("cursor_status") == "INVALID_SNAPSHOT_SEQUENCE_TYPE":
                return self._rejected("INVALID_SNAPSHOT_SEQUENCE_TYPE", session_ref=normalized)
            fresh = self.snapshot(normalized)
            return {
                "status": fresh.get("status", "REJECTED"),
                "resync": True,
                "session_ref": normalized,
                "cursor": cursor,
                "snapshot": fresh,
                "adapter_authority": self.ADAPTER_AUTHORITY,
            }

    def _evaluate_cursor(
        self, session_ref: str, client_sequence: Any, client_snapshot_id: Any
    ) -> dict[str, Any]:
        server = self._cursor_state(session_ref)
        out: dict[str, Any] = {
            "server_last_sequence": server["last_snapshot_sequence"],
            "server_last_snapshot_id": server["last_snapshot_id"],
            "client_last_sequence": client_sequence,
            "client_last_snapshot_id": None if client_snapshot_id is None else str(client_snapshot_id),
        }
        if client_sequence is None:
            out["cursor_status"] = "NO_CLIENT_CURSOR"
            return out
        if not isinstance(client_sequence, int) or isinstance(client_sequence, bool):
            out["cursor_status"] = "INVALID_SNAPSHOT_SEQUENCE_TYPE"
            return out
        if server["last_snapshot_sequence"] is None:
            out["cursor_status"] = "UNKNOWN_SNAPSHOT_SEQUENCE"
            return out
        server_sequence = int(server["last_snapshot_sequence"])
        if client_sequence > server_sequence or client_sequence < 0:
            out["cursor_status"] = "UNKNOWN_SNAPSHOT_SEQUENCE"
            return out
        if client_sequence < server_sequence:
            out["cursor_status"] = "STALE_OR_DUPLICATE"
            return out
        if client_snapshot_id is not None and str(client_snapshot_id) != server["last_snapshot_id"]:
            out["cursor_status"] = "SNAPSHOT_ID_MISMATCH"
            return out
        out["cursor_status"] = "CURRENT"
        return out

    # ------------------------------------------------------------------ commands

    def _journal_row(self, command_ref: str):
        return self._engine.runtime.conn.execute(
            "SELECT session_ref,command,envelope_hash,result_json,result_hash"
            " FROM s16b_command_journal WHERE world_instance_id=? AND command_ref=?",
            (self.world_instance_id, command_ref),
        ).fetchone()

    def _next_result_sequence(self, scope_ref: str) -> int:
        """Persist a presentation-result cursor without deciding gameplay state."""
        normalized = str(scope_ref).strip()
        row = self._engine.runtime.conn.execute(
            "SELECT last_sequence,payload_hash FROM s16b_result_cursor"
            " WHERE world_instance_id=? AND scope_ref=?",
            (self.world_instance_id, normalized),
        ).fetchone()
        previous = -1
        if row is not None:
            previous = int(row["last_sequence"])
            expected = sha256_text(f"{self.world_instance_id}|{normalized}|{previous}")
            if expected != str(row["payload_hash"]):
                raise AuthorityBootError("RESULT_CURSOR_HASH_MISMATCH:" + normalized)
        sequence = previous + 1
        payload_hash = sha256_text(f"{self.world_instance_id}|{normalized}|{sequence}")
        with self._engine.runtime._write_lock:
            self._engine.runtime.conn.execute(
                "INSERT OR REPLACE INTO s16b_result_cursor"
                "(world_instance_id,scope_ref,last_sequence,payload_hash) VALUES(?,?,?,?)",
                (self.world_instance_id, normalized, sequence, payload_hash),
            )
        return sequence

    def _journal_write(
        self, command_ref: str, session_ref: str, command: str, envelope_hash: str, result: dict[str, Any]
    ) -> None:
        text = canonical_json(result)
        with self._engine.runtime._write_lock:
            self._engine.runtime.conn.execute(
                "INSERT OR REPLACE INTO s16b_command_journal"
                "(world_instance_id,command_ref,session_ref,command,envelope_hash,result_json,result_hash)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    self.world_instance_id,
                    command_ref,
                    session_ref,
                    command,
                    envelope_hash,
                    text,
                    sha256_text(text),
                ),
            )

    def command(self, envelope: Any) -> dict[str, Any]:
        with self._lock:
            return self._command(envelope)

    def _command(self, envelope: Any) -> dict[str, Any]:
        if not isinstance(envelope, dict):
            return self._rejected("INVALID_COMMAND_ENVELOPE")

        forbidden = self.find_forbidden_field(envelope)
        if forbidden:
            return self._rejected("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", field_path=forbidden)

        unexpected = sorted(set(envelope) - ALLOWED_ENVELOPE_KEYS)
        if unexpected:
            return self._rejected("UNEXPECTED_ENVELOPE_FIELD", field_path=f"$.{unexpected[0]}")

        session_ref = str(envelope.get("session_ref") or "").strip()
        if not session_ref:
            return self._rejected("SESSION_REF_REQUIRED")
        if not SESSION_REF_RE.match(session_ref):
            return self._rejected("INVALID_SESSION_REF")

        command = str(envelope.get("command") or "").strip().upper()
        if not COMMAND_NAME_RE.match(command):
            return self._rejected("INVALID_COMMAND_NAME")
        for token in FORBIDDEN_COMMAND_TOKENS:
            if token in command:
                return self._rejected("CLIENT_AUTHORITATIVE_COMMAND_FORBIDDEN", command=command)
        if command not in self.ENABLED_COMMANDS:
            return self._rejected(
                "COMMAND_NOT_ENABLED_IN_THIS_ROUND",
                command=command,
                enabled_commands=list(self.ENABLED_COMMANDS),
            )

        params = envelope.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._rejected("INVALID_COMMAND_PARAMS")

        command_ref = str(envelope.get("command_ref") or envelope.get("idempotency_key") or "").strip()
        if not command_ref:
            return self._rejected("COMMAND_REF_REQUIRED")
        if not COMMAND_REF_RE.match(command_ref):
            return self._rejected("INVALID_COMMAND_REF")

        session = self._godot()._session(session_ref)
        if session is None:
            return self._rejected("UNKNOWN_OR_INACTIVE_SESSION", session_ref=session_ref)

        envelope_hash = sha256_text(
            canonical_json({"session_ref": session_ref, "command": command, "params": params})
        )
        journal = self._journal_row(command_ref)
        if journal is not None:
            if str(journal["session_ref"]) != session_ref:
                return self._rejected("COMMAND_REF_SESSION_MISMATCH", command_ref=command_ref)
            if str(journal["envelope_hash"]) != envelope_hash:
                return self._rejected("COMMAND_REF_PAYLOAD_MISMATCH", command_ref=command_ref)
            if sha256_text(str(journal["result_json"])) != str(journal["result_hash"]):
                return self._rejected("COMMAND_JOURNAL_HASH_MISMATCH", command_ref=command_ref)
            replayed = json.loads(str(journal["result_json"]))
            replayed["idempotent_replay"] = True
            replayed["replay_suppressed"] = True
            return replayed

        result = self._dispatch(command, session_ref, session, params, command_ref)
        result.setdefault("command", command)
        result.setdefault("idempotent_replay", False)
        result["replay_suppressed"] = False
        result["command_ref"] = command_ref
        result["session_ref"] = session_ref
        result["adapter_authority"] = self.ADAPTER_AUTHORITY
        self._journal_write(command_ref, session_ref, command, envelope_hash, result)
        return result

    def _dispatch(
        self,
        command: str,
        session_ref: str,
        session: dict[str, Any],
        params: dict[str, Any],
        command_ref: str,
    ) -> dict[str, Any]:
        if command == "MOVE_TO_POINT":
            return self._move_to_point(session_ref, session, params)
        if command == "SET_AUTO_PICKUP":
            return self._set_auto_pickup(params, command_ref)
        if command == "ACTIVATE_WEAPON_SLOT":
            return self._activate_weapon_slot(params, command_ref)
        if command == "CYCLE_WEAPON_SLOT":
            return self._cycle_weapon_slot(params, command_ref)
        if command == "REQUEST_PICKUP":
            return self._request_pickup(session, params, command_ref)
        if command == "REPORT_TRAVERSAL_SAMPLE":
            return self._report_traversal_sample(params, command_ref)
        if command == "REQUEST_GATHER":
            return self._request_gather(session, params, command_ref)
        if command == "REQUEST_PLACE_PIECE":
            return self._request_place_piece(params, command_ref)
        if command == "CONFIRM_DROP_SETTLED":
            return self._confirm_drop_settled(params, command_ref)
        if command == "REQUEST_ATTACK":
            return self._request_attack(params, command_ref)
        if command == "REQUEST_TRADE_QUOTE":
            return self._request_trade_quote(params, command_ref)
        if command == "EXECUTE_TRADE":
            return self._execute_trade(params, command_ref)
        if command == "REQUEST_EQUIP_BAG":
            return self._request_equip_bag(params, command_ref)
        if command == "REQUEST_EQUIP_ITEM":
            return self._request_equip_item(params, command_ref)
        if command == "ACCEPT_QUEST":
            return self._accept_quest(params, command_ref)
        if command in {"REQUEST_SAVE", "REQUEST_AUTOSAVE"}:
            return self._request_save(command, params, command_ref)
        if command == "REQUEST_RELOAD_RESYNC":
            return self._request_reload_resync(session_ref, params, command_ref)
        if command == "REPORT_WATER_TRAVERSAL":
            return self._report_water_traversal(params, command_ref)
        if command == "REPORT_WATER_EXHAUSTION":
            return self._report_water_exhaustion(session_ref, params, command_ref)
        if command == "REPORT_GROUND_LOOT_WATER_STATE":
            return self._report_ground_loot_water_state(params, command_ref)
        if command == "REQUEST_BAG_RECOVERY":
            return self._request_bag_recovery(params, command_ref)
        if command == "REQUEST_RESPAWN":
            return self._request_respawn(session_ref, params, command_ref)
        if command == "ADVANCE_DEVELOPMENT_WATER_TIME":
            return self._advance_development_water_time(params, command_ref)
        if command == "ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY":
            return self._attempt_development_npc_bag_recovery(params, command_ref)
        if command == "ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC":
            return self._advance_development_living_systemic(params, command_ref)
        if command == "ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT":
            return self._attempt_development_systemic_zone_hunt(params, command_ref)
        if command == "REQUEST_NPC_DIALOGUE":
            return self._request_npc_dialogue(params, command_ref)
        if command == "REQUEST_USE_SKILL":
            return self._request_use_skill(params, command_ref)
        if command == "REQUEST_LEARN_SKILL":
            return self._request_learn_skill(params, command_ref)
        if command == "REQUEST_ASSIGN_ACTIVE_SKILL":
            return self._request_assign_active_skill(params, command_ref)
        if command == "REQUEST_ACTIVATE_PASSIVE_SKILL":
            return self._request_activate_passive_skill(params, command_ref)
        if command == "REQUEST_CROSS_TERRITORY_TRAVEL":
            return self._request_cross_territory_travel(session_ref, params, command_ref)
        return self._rejected("COMMAND_NOT_ENABLED_IN_THIS_ROUND", command=command)

    def _request_use_skill(self, params: dict[str, Any], command_ref: str) -> dict[str, Any]:
        skill_ref = params.get("skill_ref")
        if not isinstance(skill_ref, str) or not skill_ref.strip():
            return self._rejected("SKILL_REF_REQUIRED")
        active_slot = params.get("active_slot")
        if not isinstance(active_slot, int) or isinstance(active_slot, bool):
            return self._rejected("ACTIVE_SLOT_MUST_BE_INT")
        skills = self._engine.skills_arpg(self.world_instance_id)
        if not (1 <= active_slot <= skills.ACTIVE_SLOTS):
            return self._rejected("ACTIVE_SLOT_OUT_OF_RANGE")
        target_ref = params.get("target_ref")
        if target_ref is not None and not isinstance(target_ref, str):
            return self._rejected("INVALID_TARGET_REF")
        core = skills.use_skill(
            self.profile_ref,
            skill_ref.strip().upper(),
            event_ref=command_ref,
            target_ref=target_ref,
        )
        return {
            **core,
            "command": "REQUEST_USE_SKILL",
            "server_authoritative": True,
            "authority": skills.AUTHORITY,
        }

    def _request_learn_skill(self, params: dict[str, Any], command_ref: str) -> dict[str, Any]:
        skill_ref = params.get("skill_ref")
        if not isinstance(skill_ref, str) or not skill_ref.strip():
            return self._rejected("SKILL_REF_REQUIRED")
        skills = self._engine.skills_arpg(self.world_instance_id)
        # S17 causal bridge: training costs gold, scaled by territorial
        # wealth (see ANDROMEDA_CAUSAL_RULES_CATALOG_V1_0.md). Charged BEFORE
        # learn_skill -- skill_core has no gate of its own and no "unlearn",
        # so checking affordability after granting the skill would leave no
        # clean way to undo a skill already learned for free.
        try:
            economy = self._engine.economy_arpg(self.world_instance_id)
            skill_cost = self._causal_bridges.apply_skill_learn_cost(
                economy, self.profile_ref, self.active_territory_id
            )
        except Exception as exc:  # noqa: BLE001 - best-effort side effect
            skill_cost = {"status": "SKIPPED", "reason": str(exc)}
        if skill_cost.get("status") == "REJECTED":
            return {
                **self._rejected(
                    "SKILL_TRAINING_COST_REJECTED",
                    skill_cost=skill_cost,
                ),
                "command": "REQUEST_LEARN_SKILL",
                "server_authoritative": True,
            }
        core = skills.learn_skill(
            self.profile_ref,
            skill_ref.strip().upper(),
            event_ref=command_ref,
            source_type="TRAINING",
            source_ref="PLAYER_COMMAND",
        )
        return {
            **core,
            "command": "REQUEST_LEARN_SKILL",
            "skill_cost": skill_cost,
            "server_authoritative": True,
            "authority": skills.AUTHORITY,
        }

    def _request_assign_active_skill(self, params: dict[str, Any], command_ref: str) -> dict[str, Any]:
        skill_ref = params.get("skill_ref")
        if not isinstance(skill_ref, str) or not skill_ref.strip():
            return self._rejected("SKILL_REF_REQUIRED")
        slot = params.get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool):
            return self._rejected("SLOT_MUST_BE_INT")
        skills = self._engine.skills_arpg(self.world_instance_id)
        if not (1 <= slot <= skills.ACTIVE_SLOTS):
            return self._rejected("ACTIVE_SLOT_OUT_OF_RANGE")
        core = skills.assign_active(
            self.profile_ref, skill_ref.strip().upper(), slot, event_ref=command_ref
        )
        return {
            **core,
            "command": "REQUEST_ASSIGN_ACTIVE_SKILL",
            "server_authoritative": True,
            "authority": skills.AUTHORITY,
        }

    def _request_activate_passive_skill(self, params: dict[str, Any], command_ref: str) -> dict[str, Any]:
        skill_ref = params.get("skill_ref")
        if not isinstance(skill_ref, str) or not skill_ref.strip():
            return self._rejected("SKILL_REF_REQUIRED")
        slot = params.get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool):
            return self._rejected("SLOT_MUST_BE_INT")
        skills = self._engine.skills_arpg(self.world_instance_id)
        if not (1 <= slot <= skills.PASSIVE_SLOTS):
            return self._rejected("PASSIVE_SLOT_OUT_OF_RANGE")
        core = skills.activate_passive(
            self.profile_ref, skill_ref.strip().upper(), slot, event_ref=command_ref
        )
        return {
            **core,
            "command": "REQUEST_ACTIVATE_PASSIVE_SKILL",
            "server_authoritative": True,
            "authority": skills.AUTHORITY,
        }

    def _assign_transferred_weapons_to_loadout(self, command_ref: str) -> None:
        """Fase 8 (correcao pos-14/09): preenche os quick slots 1/2 com armas
        que ja chegaram no motor de destino via cross_territory_transfer,
        antes de _ensure_development_profile_loadout() conceder armas novas.
        Best-effort - falha em assign nao deve derrubar a travessia inteira,
        so deixa o slot pra o dev-bootstrap preencher como sempre fez."""
        items = self._engine.items_arpg(self.world_instance_id)
        stage16a = self._engine.stage16a(self.world_instance_id)
        snapshot = items.inventory_snapshot(self.profile_ref)
        weapon_instances = []
        for inst in snapshot.get("instances") or []:
            try:
                if items.definition(inst["item_ref"]).get("item_kind") == "WEAPON":
                    weapon_instances.append(inst["instance_ref"])
            except Exception:
                continue
        loadout = stage16a.ensure_weapon_loadout(self.profile_ref)
        slot_idx = 0
        for slot in (1, 2):
            if loadout.get("slots", {}).get(str(slot)):
                continue
            if slot_idx >= len(weapon_instances):
                break
            try:
                stage16a.assign_weapon_slot(
                    self.profile_ref, slot, weapon_instances[slot_idx],
                    event_ref=f"{command_ref}:XFER_LOADOUT:{slot}",
                )
            except Exception:
                pass
            slot_idx += 1

    def _request_cross_territory_travel(
        self, session_ref: str, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        route_ref = params.get("route_ref")
        if not isinstance(route_ref, str) or not route_ref.strip():
            return self._rejected("ROUTE_REF_REQUIRED")
        route_ref = route_ref.strip().upper()
        # Fase 8.6: destino resolvido dinamicamente - cada rota liga 2
        # territorios (endpoints), o destino e o lado que NAO e o territorio
        # ativo atual (rota pode ser percorrida nos 2 sentidos).
        endpoints = self._CONFIRMED_ROUTE_TERRITORIES.get(route_ref)
        if endpoints is None or self.active_territory_id not in endpoints:
            return self._rejected("BOUNDARY_ROUTE_DESTINATION_NOT_CONFIRMED", route_ref=route_ref)
        destination_territory_id = endpoints[0] if endpoints[1] == self.active_territory_id else endpoints[1]
        if destination_territory_id == self.active_territory_id:
            return self._rejected("ALREADY_IN_DESTINATION_TERRITORY", territory_id=destination_territory_id)

        source_engine, source_wid, source_territory_id = self._engine, self.world_instance_id, self.active_territory_id
        mobility = source_engine.mobility_arpg(source_wid)
        unlock = mobility.unlock_boundary_route(route_ref, destination_territory_id)
        if unlock.get("status") != "PASS":
            return {**unlock, "command": "REQUEST_CROSS_TERRITORY_TRAVEL"}

        from cross_territory_transfer import transfer_profile  # noqa: PLC0415

        dest_engine, dest_wid = self._territory_engine(destination_territory_id)
        transfer = transfer_profile(
            source_engine, source_wid, dest_engine, dest_wid, self.profile_ref
        )
        if transfer.get("status") != "PASS":
            return {**transfer, "command": "REQUEST_CROSS_TERRITORY_TRAVEL"}

        self.switch_active_territory(destination_territory_id)
        # A sessao e o _player_ref existiam so no motor de origem -
        # self._player_ref era o avatar_ref do profile ANTIGO (cada motor
        # cria seu proprio avatar novo dentro de create_profile); precisa
        # resolver de novo contra o profile recem-criado no motor de
        # destino antes de reabrir a sessao la, senao bind_session rejeita
        # com UNKNOWN_PLAYER_REF (achado ao testar ao vivo).
        self._player_ref = self._ensure_player_ref()
        # O profile novo no motor de destino nunca passou pelo bootstrap de
        # loadout/preferencias que _boot() roda pro motor original -
        # _inventory_projection()/snapshot() esperam isso ja existir
        # (achado ao testar ao vivo: TypeError em active_slot=None sem isso).
        # Mesmo metodo que _boot() ja usa, reaproveitado tal como esta - mas
        # primeiro tenta preencher os slots com armas JA transferidas (achado
        # ao testar ao vivo: sem isso, _ensure_development_profile_loadout()
        # concedia armas NOVAS por cima das ja transferidas, duplicando
        # WPN-001/002 no inventario). _ensure_development_profile_loadout()
        # so concede pra slot vazio (loadout.get('slots',{}).get(str(slot))),
        # entao preencher aqui primeiro evita a concessao redundante.
        self._assign_transferred_weapons_to_loadout(command_ref)
        if self.config.development_profile_bootstrap:
            self._ensure_development_profile_loadout()
        if self._godot()._session(session_ref) is None:
            self._godot().bind_session(session_ref, self._player_ref, role=self.SESSION_ROLE)
        return {
            "status": "PASS",
            "command": "REQUEST_CROSS_TERRITORY_TRAVEL",
            "route_ref": route_ref,
            "source_territory_id": source_territory_id,
            "destination_territory_id": destination_territory_id,
            "transfer": transfer,
            "server_authoritative": True,
            "authority": self.ADAPTER_AUTHORITY,
        }

    def _set_auto_pickup(self, params: dict[str, Any], command_ref: str) -> dict[str, Any]:
        enabled = params.get("enabled")
        if not isinstance(enabled, bool):
            return self._rejected("AUTO_PICKUP_ENABLED_BOOL_REQUIRED")
        core = self._engine.stage16a(self.world_instance_id).set_auto_pickup(
            self.profile_ref, enabled, event_ref=command_ref
        )
        return {
            **core,
            "command": "SET_AUTO_PICKUP",
            "server_authoritative": True,
            "authority": self._engine.stage16a(self.world_instance_id).AUTHORITY,
        }

    def _activate_weapon_slot(self, params: dict[str, Any], command_ref: str) -> dict[str, Any]:
        slot = params.get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool) or slot not in (1, 2):
            return self._rejected("WEAPON_QUICKSLOT_MUST_BE_1_OR_2")
        core = self._engine.stage16a(self.world_instance_id).activate_weapon_slot(
            self.profile_ref, slot, event_ref=command_ref
        )
        return {
            **core,
            "command": "ACTIVATE_WEAPON_SLOT",
            "server_authoritative": True,
            "authority": self._engine.stage16a(self.world_instance_id).AUTHORITY,
        }

    def _cycle_weapon_slot(self, params: dict[str, Any], command_ref: str) -> dict[str, Any]:
        direction = params.get("direction")
        if not isinstance(direction, int) or isinstance(direction, bool) or direction == 0:
            return self._rejected("WEAPON_CYCLE_DIRECTION_NONZERO_INT_REQUIRED")
        core = self._engine.stage16a(self.world_instance_id).cycle_weapon_slot(
            self.profile_ref, direction, event_ref=command_ref
        )
        return {
            **core,
            "command": "CYCLE_WEAPON_SLOT",
            "server_authoritative": True,
            "authority": self._engine.stage16a(self.world_instance_id).AUTHORITY,
        }

    def _request_pickup(
        self, session: dict[str, Any], params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Resolve pickup range and eligibility from persisted server state.

        The client supplies only the stable drop identity. Physical distance,
        settled/reachable state, inventory routing and item grant are all read or
        decided by the protected Stage16A authorities.
        """
        unexpected = sorted(set(params) - {"target_ref"})
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        drop_ref = str(params.get("target_ref") or "").strip()
        if not drop_ref:
            return self._rejected("GROUND_LOOT_TARGET_REF_REQUIRED")
        result_sequence = self._next_result_sequence("GROUND_LOOT:" + drop_ref)
        stage16a = self._engine.stage16a(self.world_instance_id)
        try:
            drop = stage16a.ground_loot.drop(drop_ref)
        except KeyError:
            return {
                **self._rejected("GROUND_LOOT_NOT_FOUND", target_ref=drop_ref),
                "command": "REQUEST_PICKUP",
                "result_sequence": result_sequence,
                "server_authoritative": True,
            }
        player_state = self._engine.movement(self.world_instance_id).state(
            str(session["player_ref"])
        )
        position = drop.get("settled_position") or drop.get("candidate_position") or {}
        try:
            dx = float(position["iso_x_m"]) - float(player_state["iso_x_m"])
            dy = float(position["iso_y_m"]) - float(player_state["iso_y_m"])
            dz = float(position.get("altitude_m", 0.0)) - float(
                player_state.get("altitude_m", 0.0)
            )
            physical_distance_m = math.sqrt(dx * dx + dy * dy + dz * dz)
        except (KeyError, TypeError, ValueError):
            physical_distance_m = float("inf")
        core = stage16a.pickup_drop(
            self.profile_ref,
            drop_ref,
            physical_distance_m=physical_distance_m,
            reachable_now=bool(drop.get("reachable", False)),
            event_ref=command_ref,
        )
        return {
            **core,
            "command": "REQUEST_PICKUP",
            "target_ref": drop_ref,
            "result_sequence": result_sequence,
            "physical_distance_m": physical_distance_m,
            "distance_evaluated_server_side": True,
            "settled_evaluated_server_side": True,
            "reachable_evaluated_server_side": True,
            "server_authoritative": True,
            "authority": stage16a.AUTHORITY,
        }

    def _report_traversal_sample(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Forward Godot's physical surface observation to Stage16A authority."""
        allowed = {"distance_m", "slope_deg", "surface_ref", "ascending"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        distance_m = params.get("distance_m")
        slope_deg = params.get("slope_deg")
        surface_ref = str(params.get("surface_ref") or "").strip().upper()
        ascending = params.get("ascending", True)
        if not _finite(distance_m) or float(distance_m) < 0.0:
            return self._rejected("INVALID_TRAVERSAL_DISTANCE")
        if not _finite(slope_deg):
            return self._rejected("INVALID_TRAVERSAL_SLOPE")
        if not surface_ref:
            return self._rejected("TRAVERSAL_SURFACE_REQUIRED")
        if not isinstance(ascending, bool):
            return self._rejected("TRAVERSAL_ASCENDING_BOOL_REQUIRED")
        stage16a = self._engine.stage16a(self.world_instance_id)
        try:
            core = stage16a.traversal_effect(
                self.profile_ref,
                distance_m=float(distance_m),
                slope_deg=float(slope_deg),
                surface_ref=surface_ref,
                ascending=ascending,
                event_ref=command_ref,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._rejected("TRAVERSAL_SAMPLE_REJECTED", detail=str(exc))
        return {
            **core,
            "command": "REPORT_TRAVERSAL_SAMPLE",
            "surface_observation_source": "GODOT_PHYSICS_TRAVERSAL_SURFACE",
            "load_evaluated_server_side": True,
            "stamina_evaluated_server_side": True,
            "server_authoritative": True,
            "authority": stage16a.AUTHORITY,
        }

    def _request_gather(
        self,
        session: dict[str, Any],
        params: dict[str, Any],
        command_ref: str,
    ) -> dict[str, Any]:
        """Delegate work/yield/depletion/tool checks to Stage09/Stage16A.

        The client supplies only a stable node identity and requested unit count.
        Worker identity, location, role, equipment, available source, yield and
        physical delivery are all resolved by protected authorities.
        """
        allowed = (
            {"placement_ref", "target_ref", "requested_units"}
            if self.resource_placement_registry is not None
            else {"target_ref", "requested_units"}
        )
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        gathering = self._engine.gathering_arpg(self.world_instance_id)
        placement: dict[str, Any] | None = None
        if self.resource_placement_registry is not None:
            placement_ref = str(params.get("placement_ref") or "").strip()
            supplied_logical = str(params.get("target_ref") or "").strip()
            if placement_ref:
                try:
                    placement = self.resource_placement_registry.placement(placement_ref)
                except KeyError:
                    return self._rejected(
                        "RESOURCE_PLACEMENT_NOT_FOUND", placement_ref=placement_ref
                    )
                if not bool(placement.get("active")):
                    return self._rejected(
                        "RESOURCE_PLACEMENT_INACTIVE", placement_ref=placement_ref
                    )
                node_ref = str(placement["logical_node_ref"])
                if supplied_logical and supplied_logical != node_ref:
                    return self._rejected(
                        "RESOURCE_PLACEMENT_LOGICAL_REF_MISMATCH",
                        placement_ref=placement_ref,
                    )
            else:
                # HUNTING/FISHING are authoritative gathering activities but are
                # not StaticBody3D Resource placements.  Preserve their protected
                # logical contract while forbidding every static-resource GTH from
                # silently falling back to the historical same-block-only path.
                if not supplied_logical:
                    return self._rejected("RESOURCE_PLACEMENT_REF_REQUIRED")
                try:
                    logical_candidate = gathering.node(supplied_logical)
                except (KeyError, ValueError):
                    return self._rejected("RESOURCE_PLACEMENT_REF_REQUIRED")
                if str(logical_candidate.get("activity_type") or "") not in {
                    "HUNTING",
                    "FISHING",
                }:
                    return self._rejected("RESOURCE_PLACEMENT_REF_REQUIRED")
                node_ref = supplied_logical
        else:
            placement_ref = ""
            node_ref = str(params.get("target_ref") or "").strip()
            if not node_ref:
                return self._rejected("RESOURCE_TARGET_REF_REQUIRED")
        requested_units = params.get("requested_units", 1)
        if (
            not isinstance(requested_units, int)
            or isinstance(requested_units, bool)
            or not 1 <= requested_units <= 100
        ):
            return self._rejected("GATHER_REQUESTED_UNITS_OUT_OF_RANGE")
        result_sequence = self._next_result_sequence("GATHERING:" + node_ref)
        stage16a = self._engine.stage16a(self.world_instance_id)
        try:
            node = gathering.node(node_ref)
        except (KeyError, ValueError) as exc:
            return {
                **self._rejected("RESOURCE_NODE_NOT_FOUND", target_ref=node_ref, detail=str(exc)),
                "command": "REQUEST_GATHER",
                "result_sequence": result_sequence,
                "server_authoritative": True,
            }
        metric_guard: dict[str, Any] | None = None
        if placement is not None and self.resource_placement_registry is not None:
            player_ref = str(session.get("player_ref") or "")
            try:
                player_position = self._engine.movement(self.world_instance_id).state(
                    player_ref
                )
            except (KeyError, TypeError, ValueError) as exc:
                return self._rejected(
                    "RESOURCE_GATHER_PLAYER_POSITION_UNAVAILABLE", detail=str(exc)
                )
            target_position = dict(placement["position"])
            distance_m = math.sqrt(
                (float(player_position["iso_x_m"]) - float(target_position["iso_x_m"])) ** 2
                + (float(player_position["iso_y_m"]) - float(target_position["iso_y_m"])) ** 2
                + (float(player_position["altitude_m"]) - float(target_position["altitude_m"])) ** 2
            )
            if not math.isfinite(distance_m):
                return self._rejected("RESOURCE_GATHER_DISTANCE_INVALID")
            if distance_m > GATHER_RANGE_M:
                return self._rejected(
                    "RESOURCE_GATHER_OUT_OF_RANGE",
                    placement_ref=placement_ref,
                    distance_m=distance_m,
                    gather_range_m=GATHER_RANGE_M,
                    mutation_applied=False,
                )
            los = self.resource_placement_registry.line_of_sight(
                player_position,
                target_position,
                zone_ref=str(placement["zone_ref"]),
                block_ref=str(placement["block_ref"]),
            )
            if not bool(los["clear"]):
                return self._rejected(
                    "RESOURCE_GATHER_BLOCKED_LOS",
                    placement_ref=placement_ref,
                    distance_m=distance_m,
                    gather_range_m=GATHER_RANGE_M,
                    blocked_by=list(los["blocked_by"]),
                    mutation_applied=False,
                    blocker_authority=los["authority"],
                )
            metric_guard = {
                "placement_ref": placement_ref,
                "logical_node_ref": node_ref,
                "distance_m": distance_m,
                "gather_range_m": GATHER_RANGE_M,
                "range_boundary_policy": "PASS_WHEN_DISTANCE_LESS_THAN_OR_EQUAL_TO_1_5_M",
                "los": los,
                "player_position_authority": player_position.get("authority"),
                "resource_position_authority": placement.get("position_authority"),
                "client_position_accepted": False,
                "server_authoritative": True,
            }
        try:
            core = stage16a.gather_to_ground_loot(
                self.profile_ref,
                node_ref,
                int(requested_units),
                event_ref=command_ref,
            )
        except (KeyError, TypeError, ValueError) as exc:
            core = self._rejected("GATHERING_COMMAND_REJECTED", detail=str(exc))
        output: dict[str, Any] | None = None
        drop_ref = str(core.get("drop_ref") or "").strip()
        if core.get("status") == "PASS" and drop_ref:
            drop = stage16a.ground_loot.drop(drop_ref)
            output = {**drop, "target_ref": drop_ref}
        regional_stock_reaction: dict[str, Any] | None = None
        if core.get("status") == "PASS":
            # S17 causal bridge: a completed personal gather also draws down
            # the macro regional resource of the same kind (see
            # ANDROMEDA_CAUSAL_RULES_CATALOG_V1_0.md) -- best-effort, never
            # blocks the gather itself.
            try:
                regional_stock_reaction = self._causal_bridges.apply_gathering_yield_to_regional_stock(
                    self._engine.country(self.world_instance_id),
                    str(node["block_ref"]),
                    str(self._godot_resource_kind(node) or ""),
                    int(requested_units),
                )
            except Exception as exc:  # noqa: BLE001 - best-effort side effect
                regional_stock_reaction = {"status": "SKIPPED", "reason": str(exc)}
        return {
            **core,
            "command": "REQUEST_GATHER",
            "target_ref": placement_ref or node_ref,
            "placement_ref": placement_ref or None,
            "logical_node_ref": node_ref,
            "resource_kind": self._godot_resource_kind(node),
            "activity_type": str(node["activity_type"]),
            "result_sequence": result_sequence,
            "regional_stock_reaction": regional_stock_reaction,
            "physical_output": output,
            "direct_to_inventory": False,
            "yield_evaluated_server_side": True,
            "tool_evaluated_server_side": True,
            "location_evaluated_server_side": True,
            "metric_spatial_guard": metric_guard,
            "depletion_evaluated_server_side": True,
            "server_authoritative": True,
            "authority": stage16a.AUTHORITY,
        }

    def _verify_drop_reachable(self, settled_position: dict[str, float], client_claimed: bool) -> tuple[bool, dict[str, Any]]:
        """S17-C3R5: independently re-derive reachability from the SAME
        offline-baked LOS-blocker constraint data already authoritative for
        resource gathering (ResourceMetricPlacementRegistry.line_of_sight),
        instead of storing whatever the client's own local raycast/navmesh
        observation claimed. GroundLoot presentation must never substitute
        for authority state (S17-C3R5 Section 16).

        The check only ever NARROWS the client's claim: a genuine blocker
        crossing between the player and the settled position forces
        reachable=false even if the client claimed true. A client claiming
        NOT reachable is honoured as-is -- this check has no basis to
        manufacture a positive the client itself did not observe, and the
        client-side navmesh/physics probe covers obstacle classes (terrain,
        dynamic props) the offline LOS-blocker table does not model.
        """
        evidence: dict[str, Any] = {"client_claimed": client_claimed, "server_los_checks": []}
        if not client_claimed or self.resource_placement_registry is None:
            evidence["verified"] = client_claimed
            evidence["reason"] = "NO_REGISTRY_OR_CLIENT_ALREADY_CLAIMS_UNREACHABLE"
            return client_claimed, evidence
        try:
            player_state = self._engine.movement(self.world_instance_id).state(self._player_ref)
            areas = {
                (str(p.get("zone_ref")), str(p.get("block_ref")))
                for p in self.resource_placement_registry.active_placements()
                if p.get("zone_ref") and p.get("block_ref")
            }
        except Exception as exc:
            evidence["verified"] = client_claimed
            evidence["reason"] = f"VERIFICATION_UNAVAILABLE:{exc}"
            return client_claimed, evidence
        start = {
            "iso_x_m": float(player_state["iso_x_m"]),
            "iso_y_m": float(player_state["iso_y_m"]),
            "altitude_m": float(player_state.get("altitude_m", 0.0)),
        }
        blocked_by: list[str] = []
        for zone_ref, block_ref in areas:
            try:
                los = self.resource_placement_registry.line_of_sight(
                    start, settled_position, zone_ref=zone_ref, block_ref=block_ref
                )
            except Exception:
                continue
            evidence["server_los_checks"].append({"zone_ref": zone_ref, "block_ref": block_ref, "result": los})
            blocked_by.extend(los.get("blocked_by", []))
        verified = client_claimed and not blocked_by
        evidence["verified"] = verified
        evidence["blocked_by"] = blocked_by
        evidence["reason"] = "SERVER_LOS_CLEAR" if verified else "SERVER_LOS_BLOCKED_OVERRIDES_CLIENT_CLAIM"
        return verified, evidence

    def _confirm_drop_settled(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Accept a Godot physics observation; Stage16A owns the state transition.

        S17-C3R5: `reachable` is no longer forwarded verbatim from the
        client -- it is independently re-verified server-side first (see
        _verify_drop_reachable). The client's raycast/navmesh probe remains
        prediction/UX only; a genuine offline-baked LOS blocker between the
        player and the settled position can never be defeated by a client
        that simply claims otherwise.
        """
        allowed = {"target_ref", "settled_position", "reachable"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        drop_ref = str(params.get("target_ref") or "").strip()
        position = params.get("settled_position")
        reachable_claimed = params.get("reachable")
        if not drop_ref:
            return self._rejected("GROUND_LOOT_TARGET_REF_REQUIRED")
        if not isinstance(position, dict):
            return self._rejected("SETTLED_POSITION_REQUIRED")
        expected_position_keys = {"iso_x_m", "iso_y_m", "altitude_m"}
        if set(position) != expected_position_keys:
            return self._rejected("INVALID_SETTLED_POSITION_FIELDS")
        if not all(_finite(position.get(key)) for key in expected_position_keys):
            return self._rejected("INVALID_SETTLED_POSITION")
        if not isinstance(reachable_claimed, bool):
            return self._rejected("SETTLED_REACHABLE_BOOL_REQUIRED")
        settled_position = {
            "iso_x_m": float(position["iso_x_m"]),
            "iso_y_m": float(position["iso_y_m"]),
            "altitude_m": float(position["altitude_m"]),
        }
        reachable, verification_evidence = self._verify_drop_reachable(settled_position, reachable_claimed)
        stage16a = self._engine.stage16a(self.world_instance_id)
        try:
            core = stage16a.confirm_drop_settled(
                drop_ref,
                settled_position=settled_position,
                reachable=reachable,
                event_ref=command_ref,
            )
        except (KeyError, TypeError, ValueError) as exc:
            core = self._rejected("DROP_SETTLE_CONFIRMATION_REJECTED", detail=str(exc))
        return {
            **core,
            "command": "CONFIRM_DROP_SETTLED",
            "target_ref": drop_ref,
            "physics_observation_source": "GODOT_RIGIDBODY3D",
            "reachable_verification": verification_evidence,
            "server_authoritative": True,
            "authority": stage16a.AUTHORITY,
        }

    def _advance_combat_runtime(self) -> dict[str, Any]:
        """Advance only the protected combat overlay by server-measured elapsed time.

        ARPGCombatCore exposes an explicit tick API and owns cooldown/status decay.
        The HTTP client supplies no delta.  A restart is deliberately conservative:
        downtime is not fabricated, so a persisted cooldown can never be bypassed.
        """
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_combat_pulse_monotonic)
        self._last_combat_pulse_monotonic = now
        remaining = min(elapsed, 60.0)
        ticks: list[dict[str, Any]] = []
        combat = self._engine.combat_arpg(self.world_instance_id)
        while remaining > 1e-9:
            delta = min(1.0, remaining)
            ticks.append(combat.tick_player(self.profile_ref, delta))
            remaining -= delta
        return {
            "status": "PASS",
            "server_elapsed_s": round(elapsed, 6),
            "applied_s": round(min(elapsed, 60.0), 6),
            "tick_count": len(ticks),
            "client_delta_accepted": False,
            "authority": combat.AUTHORITY,
        }

    def _request_attack(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Delegate hostility, range, hit, crit, damage, cooldown and defeat."""
        unexpected = sorted(set(params) - {"target_ref"})
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        target_ref = str(params.get("target_ref") or "").strip()
        if not target_ref:
            return self._rejected("COMBAT_TARGET_REF_REQUIRED")
        result_sequence = self._next_result_sequence("COMBAT:" + target_ref)
        combat = self._engine.combat_arpg(self.world_instance_id)
        actors = self._engine.actors_arpg(self.world_instance_id)
        try:
            hostility = actors.hostility_to_profile(target_ref, self.profile_ref)
        except Exception as exc:
            return {
                **self._rejected("COMBAT_TARGET_NOT_FOUND", target_ref=target_ref, detail=str(exc)),
                "command": "REQUEST_ATTACK",
                "result_sequence": result_sequence,
                "server_authoritative": True,
            }
        if not bool(hostility.get("hostile", False)):
            return {
                **self._rejected(
                    "TARGET_NOT_HOSTILE",
                    target_ref=target_ref,
                    disposition=hostility.get("disposition"),
                ),
                "command": "REQUEST_ATTACK",
                "result_sequence": result_sequence,
                "server_authoritative": True,
                "hostility_authority": actors.AUTHORITY,
            }
        pulse = self._advance_combat_runtime()
        try:
            core = combat.player_attack(
                self.profile_ref,
                target_ref,
                event_ref=command_ref,
            )
            target_state = combat.target_state(target_ref)
        except Exception as exc:
            core = self._rejected("COMBAT_COMMAND_REJECTED", detail=str(exc))
            target_state = combat.target_state(target_ref)
        physical_output: dict[str, Any] | None = None
        loot_status = "NO_DEFEAT_THIS_ATTACK"
        # "defeated" means defeated *by this attack*. A rejected attack against an
        # already-dead actor is not a defeat event and must not produce output.
        defeated = core.get("status") == "PASS" and str(
            (target_state or {}).get("life_state", "")
        ).upper() not in {"", "ALIVE"}
        faction_reaction: dict[str, Any] | None = None
        if defeated:
            physical_output, loot_status = self._enemy_death_physical_output(
                target_ref, command_ref
            )
            # S17 causal bridge: a hostile kill nudges factions PRESENT in the
            # player's current territory against them (see
            # ANDROMEDA_CAUSAL_RULES_CATALOG_V1_0.md). Best-effort: a kill is
            # never rejected or altered by this failing.
            if self._world_systems is not None:
                try:
                    faction_reaction = self._causal_bridges.apply_combat_kill_faction_reaction(
                        self._world_systems,
                        self._social_memory(),
                        self._planet_world_instance_id,
                        self.world_instance_id,
                        self._player_ref,
                        self.active_territory_id,
                        event_ref=command_ref,
                    )
                except Exception as exc:  # noqa: BLE001 - best-effort side effect
                    faction_reaction = {"status": "SKIPPED", "reason": str(exc)}
        return {
            **core,
            "command": "REQUEST_ATTACK",
            "target_ref": target_ref,
            "result_sequence": result_sequence,
            "hostility": hostility,
            "target_state": target_state,
            "runtime_pulse": pulse,
            "hit_evaluated_server_side": True,
            "critical_evaluated_server_side": True,
            "damage_evaluated_server_side": True,
            "range_evaluated_server_side": True,
            "cooldown_evaluated_server_side": True,
            "death_evaluated_server_side": True,
            "enemy_physical_output": physical_output,
            "enemy_loot_authority_status": loot_status,
            "enemy_defeated": defeated,
            "faction_reaction": faction_reaction,
            "server_authoritative": True,
            "authority": combat.AUTHORITY,
            "hostility_authority": actors.AUTHORITY,
        }

    def _request_trade_quote(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Ask Stage13 for a quote; the client never supplies owner or price."""
        allowed = {
            "request_ref",
            "vendor_ref",
            "item_ref",
            "direction",
            "quantity",
            "instance_ref",
            "client_presentation_only",
        }
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        vendor_ref = str(params.get("vendor_ref") or "").strip()
        item_ref = str(params.get("item_ref") or "").strip()
        direction = str(params.get("direction") or "").strip().upper()
        quantity = params.get("quantity")
        instance_ref = str(params.get("instance_ref") or "").strip() or None
        if not vendor_ref:
            return self._rejected("VENDOR_REF_REQUIRED")
        if not item_ref:
            return self._rejected("ITEM_REF_REQUIRED")
        if direction not in {"BUY", "SELL"}:
            return self._rejected("INVALID_TRADE_DIRECTION")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            return self._rejected("INVALID_TRADE_QUANTITY")
        economy = self._engine.economy_arpg(self.world_instance_id)
        sequence = self._next_result_sequence("TRADE_QUOTE:" + vendor_ref)
        try:
            core = economy.price_quote(
                self.profile_ref,
                vendor_ref,
                item_ref,
                int(quantity),
                direction=direction,
                instance_ref=instance_ref,
                event_ref=command_ref,
            )
        except Exception as exc:
            return {
                **self._rejected("TRADE_QUOTE_REJECTED", detail=str(exc)),
                "command": "REQUEST_TRADE_QUOTE",
                "quote_sequence": sequence,
                "server_authoritative": True,
                "authority": economy.AUTHORITY,
            }
        quote = dict(core.get("quote", {}))
        return {
            **core,
            **quote,
            "command": "REQUEST_TRADE_QUOTE",
            "operation": str(quote.get("direction", direction)),
            "quote_sequence": sequence,
            "active": core.get("status") == "PASS",
            "owner_resolved_server_side": True,
            "price_evaluated_server_side": True,
            "server_authoritative": True,
            "authority": economy.AUTHORITY,
        }

    def _execute_trade(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Execute only an explicit confirmation of the exact Stage13 quote."""
        allowed = {
            "quote_ref",
            "event_ref",
            "confirmation_ref",
            "vendor_ref",
            "item_ref",
            "direction",
            "quantity",
            "explicit_user_confirmation",
            "client_presentation_only",
        }
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        quote_ref = str(params.get("quote_ref") or "").strip()
        event_ref = str(params.get("event_ref") or "").strip()
        confirmation_ref = str(params.get("confirmation_ref") or "").strip()
        if not quote_ref:
            return self._rejected("QUOTE_REF_REQUIRED")
        if not event_ref:
            return self._rejected("TRADE_EVENT_REF_REQUIRED")
        if not confirmation_ref or params.get("explicit_user_confirmation") is not True:
            return self._rejected("EXPLICIT_USER_CONFIRMATION_REQUIRED")
        economy = self._engine.economy_arpg(self.world_instance_id)
        sequence = self._next_result_sequence("TRADE_EXECUTE:" + quote_ref)
        try:
            quote = economy._quote(quote_ref)
        except Exception as exc:
            return {
                **self._rejected("QUOTE_NOT_FOUND", detail=str(exc)),
                "command": "EXECUTE_TRADE",
                "quote_ref": quote_ref,
                "event_ref": event_ref,
                "result": "REJECTED",
                "result_sequence": sequence,
                "server_authoritative": True,
                "authority": economy.AUTHORITY,
            }
        if str(quote.get("owner_ref")) != self.profile_ref:
            reason = "QUOTE_OWNER_MISMATCH"
        elif str(params.get("vendor_ref") or "") != str(quote.get("vendor_ref")):
            reason = "QUOTE_VENDOR_REF_MISMATCH"
        elif str(params.get("item_ref") or "") != str(quote.get("item_ref")):
            reason = "QUOTE_ITEM_REF_MISMATCH"
        elif str(params.get("direction") or "").upper() != str(
            quote.get("direction")
        ).upper():
            reason = "QUOTE_DIRECTION_MISMATCH"
        elif (
            not isinstance(params.get("quantity"), int)
            or isinstance(params.get("quantity"), bool)
            or int(params["quantity"]) != int(quote.get("quantity", 0))
        ):
            reason = "QUOTE_QUANTITY_MISMATCH"
        else:
            reason = ""
        if reason:
            return {
                **self._rejected(reason),
                "command": "EXECUTE_TRADE",
                "quote_ref": quote_ref,
                "event_ref": event_ref,
                "result": "REJECTED",
                "result_sequence": sequence,
                "server_authoritative": True,
                "authority": economy.AUTHORITY,
            }
        stage16a = self._engine.stage16a(self.world_instance_id)
        try:
            core = stage16a.execute_trade_carried(
                self.profile_ref, quote_ref, event_ref=command_ref
            )
        except Exception as exc:
            core = self._rejected("TRADE_EXECUTION_REJECTED", detail=str(exc))
        accepted = core.get("status") == "PASS"
        return {
            **core,
            "command": "EXECUTE_TRADE",
            "quote_ref": quote_ref,
            "event_ref": event_ref,
            "confirmation_ref": confirmation_ref,
            "result": "ACCEPTED" if accepted else "REJECTED",
            "result_sequence": sequence,
            "wallet_revision": sequence,
            "inventory_revision": sequence,
            "explicit_user_confirmation_verified": True,
            "owner_routing_evaluated_server_side": True,
            "wallet_mutated_by_godot": False,
            "inventory_mutated_by_godot": False,
            "server_authoritative": True,
            "authority": stage16a.AUTHORITY,
        }

    def _request_equip_bag(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Delegate creation/equip/routing of the real Bag container to Stage16A."""
        allowed = {"request_ref", "bag_instance_ref", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        correlation_ref = str(params.get("bag_instance_ref") or "").strip()
        if not correlation_ref:
            return self._rejected("BAG_INSTANCE_REF_REQUIRED")
        stage16a = self._engine.stage16a(self.world_instance_id)
        try:
            core = stage16a.equip_bag(self.profile_ref, event_ref=command_ref)
        except Exception as exc:
            core = self._rejected("BAG_EQUIP_REJECTED", detail=str(exc))
        return {
            **core,
            "command": "REQUEST_EQUIP_BAG",
            "client_bag_instance_ref": correlation_ref,
            "client_bag_instance_ref_used_as_authority": False,
            "bag_created_and_routed_by_stage16a": core.get("status") == "PASS",
            "server_authoritative": True,
            "authority": stage16a.AUTHORITY,
        }

    def _request_equip_item(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Delegate a generic equip to the protected item core.

        The adapter decides nothing: ownership, item existence and slot
        compatibility are all validated and enforced by items.equip() itself.
        The client only names an instance_ref it already owns and a target slot;
        it cannot conjure an item it does not have, and it cannot choose an
        outcome the core would not already allow through ACTIVATE_WEAPON_SLOT/
        CYCLE_WEAPON_SLOT/REQUEST_EQUIP_BAG-style commands.
        """
        allowed = {"request_ref", "instance_ref", "slot", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        instance_ref = str(params.get("instance_ref") or "").strip()
        if not instance_ref:
            return self._rejected("EQUIP_INSTANCE_REF_REQUIRED")
        slot = str(params.get("slot") or "").strip().upper()
        if not slot:
            return self._rejected("EQUIP_SLOT_REQUIRED")
        items = self._engine.items_arpg(self.world_instance_id)
        try:
            core = items.equip(self.profile_ref, instance_ref, slot, event_ref=command_ref)
        except Exception as exc:
            core = self._rejected("ITEM_EQUIP_REJECTED", detail=str(exc))
        return {
            **core,
            "command": "REQUEST_EQUIP_ITEM",
            "server_authoritative": True,
            "authority": items.AUTHORITY,
        }

    def _accept_quest(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Delegate acceptance of an existing Stage12 template to Stage12."""
        allowed = {"request_ref", "quest_ref", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        quest_ref = str(params.get("quest_ref") or "").strip()
        if not quest_ref:
            return self._rejected("QUEST_REF_REQUIRED")
        narrative = self._engine.narrative_arpg(self.world_instance_id)
        sequence = self._next_result_sequence("QUEST:" + quest_ref)
        try:
            core = narrative.accept_quest(
                self.profile_ref, quest_ref, event_ref=command_ref
            )
        except Exception as exc:
            core = self._rejected("QUEST_ACCEPT_REJECTED", detail=str(exc))
        return {
            **core,
            "command": "ACCEPT_QUEST",
            "quest_ref": quest_ref,
            "result_sequence": sequence,
            "objective_mutated_by_godot": False,
            "completion_decided_by_godot": False,
            "reward_granted_by_godot": False,
            "server_authoritative": True,
            "authority": narrative.AUTHORITY,
        }

    def _select_dialogue_eligible_npc(self) -> str | None:
        """Deterministically pick one real, dialogue-eligible NPC.

        G16B-19B read-only preflight (see closure report): CountryScaleSystem
        NPCs carry no metric position of their own -- ``movement.state(ref)``
        does resolve real ``iso_x_m``/``iso_y_m``, but at CITY granularity
        (every NPC in one city shares the exact same point), and that point
        bears no reachable relationship to the player's own live position.
        A metric interaction radius (the CHOICE_RANGE_M_CANDIDATE=2.0 the
        protected RealtimeDialogueCore declares but never wires up) would
        therefore never be semantically meaningful here -- Section 3 of
        this round's authorization explicitly forbids hardcoding it without
        that justification, so it is not used.

        The real, already-proven eligibility rule this reuses instead is
        the same one CountryScaleSystem.can_target()/the Section07 combat
        encounter bootstrap already apply: real npc, not CHILD, not
        protection.protected, status ACTIVE. That is identity/class-based,
        not distance-based (Section 16 option C), and requires inventing
        nothing new. This never calls ensure_actor()/ensure_enemy() --
        pure read over _all_npc_records(), no mutation, no combat
        registration; it also never re-picks the world's existing combat
        target refs, so a dialogue NPC never doubles as a hostile target.
        """
        country = self._engine.country(self.world_instance_id)
        combat_refs = {
            str(self._bootstrap_get("combat_target_common_ref") or "").strip(),
            str(self._bootstrap_get("combat_target_alpha_ref") or "").strip(),
        }
        candidates: list[str] = []
        for npc in country._all_npc_records():
            ref = str(npc.get("id") or "").strip()
            protection = npc.get("protection") or {}
            if (
                not ref
                or ref in combat_refs
                or str(npc.get("status", "ACTIVE")).upper() != "ACTIVE"
                or str(npc.get("class") or "").upper() == "CHILD"
                or bool(protection.get("protected", False))
            ):
                continue
            candidates.append(ref)
        if not candidates:
            return None
        candidates.sort()
        return candidates[0]

    def _ensure_development_dialogue_npc(self) -> str | None:
        """Seed (or reuse) a stable dialogue_target_ref for test/dev callers.

        Section 5: this seeds identity for test/development convenience
        only, the same _bootstrap_set(...) mechanism already used for
        combat_target_{slot}_ref. REQUEST_NPC_DIALOGUE itself never
        requires this exact ref -- it revalidates any npc_target_ref the
        client supplies against the same real eligibility rule, so the
        command stays production-shaped and is not gated behind
        development_profile_bootstrap.
        """
        stored = str(self._bootstrap_get("dialogue_target_ref") or "").strip()
        if stored:
            try:
                npc = self._engine.country(self.world_instance_id).npc(stored)
                protection = npc.get("protection") or {}
                if (
                    str(npc.get("status", "ACTIVE")).upper() == "ACTIVE"
                    and str(npc.get("class") or "").upper() != "CHILD"
                    and not bool(protection.get("protected", False))
                ):
                    return stored
            except KeyError:
                pass
        chosen = self._select_dialogue_eligible_npc()
        if chosen:
            self._bootstrap_set("dialogue_target_ref", chosen)
        return chosen

    def _request_npc_dialogue(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """Production dialogue transport (G16B-19B).

        npc_target_ref -> country.npc() real identity validation ->
        eligibility (Section16: identity/class-based, see
        _select_dialogue_eligible_npc's docstring) -> fixed, server-owned
        dialogue_ref resolution -> narrative.dialogue_brief() real,
        integrity-checked read -> authority_npc_dialogue_content literal
        text bound to that same dialogue_ref -> related_quest_ref
        validated against narrative.list_quest_templates().

        Stateless/read-only throughout: no write-lock is ever taken, no
        event journal entry is recorded, nothing here can be duplicated by
        a replay because nothing here mutates.
        """
        allowed = {"request_ref", "npc_target_ref", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        npc_target_ref = str(params.get("npc_target_ref") or "").strip()
        if not npc_target_ref:
            return self._rejected("NPC_TARGET_REF_REQUIRED")

        country = self._engine.country(self.world_instance_id)
        try:
            npc = country.npc(npc_target_ref)
        except KeyError:
            return self._rejected("UNKNOWN_NPC_REF", npc_target_ref=npc_target_ref)

        protection = npc.get("protection") or {}
        if (
            str(npc.get("status", "ACTIVE")).upper() != "ACTIVE"
            or str(npc.get("class") or "").upper() == "CHILD"
            or bool(protection.get("protected", False))
        ):
            return self._rejected(
                "NPC_NOT_DIALOGUE_ELIGIBLE", npc_target_ref=npc_target_ref
            )

        # Fixed, server-owned dialogue_ref: the client never chooses which
        # brief it receives (Section 9/10). G16B-19B binds every eligible
        # real NPC to the one real brief this round stands up -- see
        # authority_npc_dialogue_content.py's own docstring for why no
        # per-NPC/anchor correlation is fabricated here.
        dialogue_ref = "DLG-S12-FRONTIER"
        narrative = self._engine.narrative_arpg(self.world_instance_id)
        try:
            brief = narrative.dialogue_brief(dialogue_ref)
        except Exception as exc:
            return self._rejected("DIALOGUE_BRIEF_NOT_FOUND", detail=str(exc))

        content = resolve_dialogue_content(dialogue_ref)
        if content is None:
            return self._rejected("DIALOGUE_CONTENT_NOT_PROVISIONED", dialogue_ref=dialogue_ref)
        if str(brief.get("copy_authority")) != str(content.get("copy_authority")):
            return self._rejected("DIALOGUE_COPY_AUTHORITY_MISMATCH", dialogue_ref=dialogue_ref)

        related_quest_ref = str(content.get("related_quest_ref") or "").strip()
        if related_quest_ref:
            known_quest_refs = {
                str(t["quest_ref"]) for t in narrative.list_quest_templates()
            }
            if related_quest_ref not in known_quest_refs:
                return self._rejected(
                    "DIALOGUE_RELATED_QUEST_TEMPLATE_NOT_FOUND",
                    related_quest_ref=related_quest_ref,
                )

        sequence = self._next_transport_sequence()
        return {
            "status": "PASS",
            "command": "REQUEST_NPC_DIALOGUE",
            "npc_ref": npc_target_ref,
            "dialogue_ref": dialogue_ref,
            "anchor_ref": str(brief.get("anchor_ref") or ""),
            "line": str(content["line"]),
            "speech_acts": list(brief.get("speech_acts", [])),
            "source_refs": list(brief.get("source_refs", [])),
            "related_quest_ref": related_quest_ref,
            "copy_authority": str(content["copy_authority"]),
            "choices": [],
            "branching_required": False,
            "npc_ref_client_supplied": True,
            "dialogue_ref_client_supplied": False,
            "line_client_supplied": False,
            "quest_ref_client_supplied": False,
            "canonical_mutation": False,
            "result_sequence": sequence,
            "server_authoritative": True,
            "authority": narrative.AUTHORITY,
        }

    @staticmethod
    def _validated_slot_ref(value: Any) -> str | None:
        slot = str(value or "").strip().lower()
        return slot if re.fullmatch(r"[a-z0-9_-]{1,40}", slot) else None

    def _request_save(
        self, command: str, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        allowed = {
            "request_ref", "slot_ref", "save_kind", "reason", "client_presentation_only"
        }
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        request_ref = str(params.get("request_ref") or "").strip()
        slot_ref = self._validated_slot_ref(params.get("slot_ref"))
        if not request_ref:
            return self._rejected("SAVE_REQUEST_REF_REQUIRED")
        if slot_ref is None:
            return self._rejected("INVALID_SAVE_SLOT_REF")
        expected_kind = "AUTOSAVE" if command == "REQUEST_AUTOSAVE" else "MANUAL"
        supplied_kind = str(params.get("save_kind") or expected_kind).upper()
        if supplied_kind != expected_kind:
            return self._rejected("SAVE_KIND_COMMAND_MISMATCH")
        save_sequence = self._next_result_sequence("SAVE_SEQUENCE:" + slot_ref)
        # Allocate the client-facing result cursor before the SQLite backup so a
        # restore of this very save cannot make the next confirmed result stale.
        result_sequence = self._next_result_sequence("SAVE_RESULT:" + self.profile_ref)
        save_ref = f"S16B-SAVE-{slot_ref.upper()}-{save_sequence:08d}"
        core = self._engine.save_recovery(self.world_instance_id).create_snapshot(
            slot_ref, kind=expected_kind
        )
        return {
            "status": "PASS",
            "command": command,
            "server_authoritative": True,
            "request_ref": request_ref,
            "result": "CONFIRMED",
            "reason": "",
            "save_ref": save_ref,
            "slot_ref": slot_ref,
            "save_sequence": save_sequence,
            "result_sequence": result_sequence,
            "snapshot_integrity": core,
            "success_fabricated_by_godot": False,
            "authority": self._engine.save_recovery(self.world_instance_id).AUTHORITY,
        }

    def _request_reload_resync(
        self, session_ref: str, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        allowed = {
            "request_ref", "slot_ref", "require_resync_before_ready",
            "client_presentation_only",
        }
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        request_ref = str(params.get("request_ref") or "").strip()
        slot_ref = self._validated_slot_ref(params.get("slot_ref"))
        if not request_ref:
            return self._rejected("RELOAD_REQUEST_REF_REQUIRED")
        if slot_ref is None:
            return self._rejected("INVALID_RELOAD_SLOT_REF")
        if params.get("require_resync_before_ready") is not True:
            return self._rejected("RELOAD_REQUIRES_RESYNC_BEFORE_READY")

        recovery = self._engine.save_recovery(self.world_instance_id)
        verified = recovery.verify_slot(slot_ref, generation="current")
        if verified.get("status") != "PASS":
            return self._rejected(
                "SAVE_SLOT_VERIFY_FAILED",
                server_authoritative=True,
                request_ref=request_ref,
                slot_ref=slot_ref,
                verification=verified,
                authority=recovery.AUTHORITY,
            )

        transport_state = self._capture_transport_state()
        db_path = Path(self.config.db_path).resolve()
        candidate = db_path.with_name(
            f".{db_path.name}.{sha256_text(command_ref)[:12]}.restore-candidate"
        )
        live_backup = db_path.with_name(f".{db_path.name}.pre-restore-recovery")
        recovery.restore_slot_to(slot_ref, candidate, generation="current")
        if live_backup.exists():
            live_backup.unlink()

        # A WAL checkpoint followed by a closed connection guarantees the file swap
        # cannot accidentally replay post-save pages over the restored database.
        self._engine.runtime.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._engine.runtime.close()
        self._engine = None
        try:
            os.replace(db_path, live_backup)
            for sidecar in (
                db_path.with_name(db_path.name + "-wal"),
                db_path.with_name(db_path.name + "-shm"),
            ):
                if sidecar.exists():
                    sidecar.unlink()
            os.replace(candidate, db_path)
            self._boot()
            self._merge_transport_state(transport_state)
            if self._godot()._session(session_ref) is None:
                rebound = self._godot().bind_session(
                    session_ref, self._player_ref, role=self.SESSION_ROLE
                )
                if rebound.get("status") != "PASS":
                    raise AuthorityBootError("RESTORED_SESSION_REBIND_FAILED")
            row = self._engine.runtime.conn.execute(
                "SELECT last_sequence FROM s16b_result_cursor "
                "WHERE world_instance_id=? AND scope_ref=?",
                (self.world_instance_id, "SAVE_SEQUENCE:" + slot_ref),
            ).fetchone()
            if row is None:
                raise AuthorityBootError("RESTORED_SAVE_SEQUENCE_MISSING")
            save_sequence = int(row["last_sequence"])
            restore_sequence = self._next_transport_sequence()
            restore_snapshot = self._restore_snapshot_payload(
                session_ref,
                slot_ref=slot_ref,
                save_sequence=save_sequence,
                restore_sequence=restore_sequence,
            )
            if live_backup.exists():
                live_backup.unlink()
        except Exception as exc:
            if self._engine is not None:
                self._engine.runtime.close()
                self._engine = None
            if live_backup.exists():
                if db_path.exists():
                    db_path.unlink()
                os.replace(live_backup, db_path)
                self._boot()
            raise AuthorityBootError(f"AUTHORITATIVE_RESTORE_FAILED:{type(exc).__name__}:{exc}") from exc
        finally:
            if candidate.exists():
                candidate.unlink()

        return {
            "status": "PASS",
            "command": "REQUEST_RELOAD_RESYNC",
            "server_authoritative": True,
            "request_ref": request_ref,
            "slot_ref": slot_ref,
            "restore_snapshot": restore_snapshot,
            "restore_sequence": restore_sequence,
            "save_sequence": save_sequence,
            "resync_before_ready": True,
            "restore_fabricated_by_godot": False,
            "authority": self._engine.save_recovery(self.world_instance_id).AUTHORITY,
        }

    def _report_water_traversal(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        allowed = {
            "request_ref", "volume_ref", "depth_m", "flow_speed_mps", "distance_m",
            "under_bridge", "actor_kind", "client_presentation_only",
        }
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        depth = params.get("depth_m")
        flow = params.get("flow_speed_mps")
        distance = params.get("distance_m")
        if not all(_finite(value) for value in (depth, flow, distance)):
            return self._rejected("INVALID_WATER_TRAVERSAL_SAMPLE")
        if not 0.0 <= float(depth) <= 8.0 or not 0.0 <= float(flow) <= 8.0:
            return self._rejected("WATER_SAMPLE_OUT_OF_CONTRACT_RANGE")
        if not 0.0 <= float(distance) <= 100.0:
            return self._rejected("WATER_DISTANCE_OUT_OF_SAMPLE_RANGE")
        # actor_kind is optional; its absence is the only case that defaults to
        # PLAYER (preserving every existing caller byte-for-byte). Any value
        # present but outside {PLAYER, VEHICLE} is rejected explicitly rather
        # than silently treated as PLAYER.
        if "actor_kind" in params:
            actor_kind = str(params.get("actor_kind") or "").strip().upper()
        else:
            actor_kind = "PLAYER"
        if actor_kind not in {"PLAYER", "VEHICLE"}:
            return self._rejected("UNSUPPORTED_WATER_TRAVERSAL_ACTOR_KIND")
        stage16a = self._engine.stage16a(self.world_instance_id)
        if actor_kind == "VEHICLE":
            # Existing, already-correct core route: no player stamina is ever
            # touched here. water_traversal_effect()/water_traversal_sample()/
            # VEHICLE_MAX_WADE_DEPTH_M are untouched by this branch.
            core = stage16a.vehicle_water_traversal(
                depth_m=float(depth),
                flow_speed_mps=float(flow),
                distance_m=float(distance),
                under_bridge=bool(params.get("under_bridge", False)),
            )
        else:
            core = stage16a.water_traversal_effect(
                self.profile_ref,
                depth_m=float(depth),
                flow_speed_mps=float(flow),
                distance_m=float(distance),
                under_bridge=bool(params.get("under_bridge", False)),
                event_ref=command_ref,
            )
        return {
            **core,
            "command": "REPORT_WATER_TRAVERSAL",
            "actor_kind": actor_kind,
            "result_sequence": self._next_result_sequence("WATER_TRAVERSAL:" + self.profile_ref),
            "server_authoritative": True,
            "stamina_decided_by_godot": False,
            "load_read_by_stage16a": True,
            "authority": stage16a.AUTHORITY,
        }

    def _report_water_exhaustion(
        self, session_ref: str, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        allowed = {"request_ref", "volume_ref", "in_water", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        if not isinstance(params.get("in_water"), bool):
            return self._rejected("IN_WATER_BOOL_REQUIRED")
        now = time.monotonic()
        previous = self._water_presence_monotonic.get(session_ref, now)
        in_water = bool(params["in_water"])
        delta = max(0.0, now - previous) if in_water else 0.0
        if in_water:
            self._water_presence_monotonic[session_ref] = now
        else:
            self._water_presence_monotonic.pop(session_ref, None)
        movement = self._engine.movement(self.world_instance_id).state(self._player_ref)
        position = {
            "iso_x_m": float(movement["iso_x_m"]),
            "iso_y_m": float(movement["iso_y_m"]),
            "altitude_m": float(movement.get("altitude_m", 0.0)),
        }
        stage16a = self._engine.stage16a(self.world_instance_id)
        core = stage16a.water_exhaustion_tick(
            self.profile_ref,
            actor_kind="PLAYER",
            stamina=float(movement["stamina"]),
            in_water=in_water,
            delta_s=delta,
            event_ref=command_ref,
            position=position,
        )
        exhaustion_sequence = self._next_transport_sequence()
        zero_time = float(core.get("zero_stamina_water_s", 0.0))
        grace = float(core.get("grace_s", 4.0))
        if not in_water or float(movement["stamina"]) > 1e-9:
            projected_state = "RECOVERED"
        elif bool(core.get("defeat_required", False)):
            projected_state = "DEFEAT_ELIGIBLE"
        else:
            projected_state = "STAMINA_ZERO_GRACE"
        exhaustion_snapshot = {
            "server_authoritative": True,
            "session_ref": session_ref,
            "exhaustion_sequence": exhaustion_sequence,
            "state": projected_state,
            "grace_remaining_s": max(0.0, grace - zero_time),
            "server_elapsed_s": delta,
            "authority": stage16a.water_bag.AUTHORITY,
        }
        death_event: dict[str, Any] = {}
        if bool(core.get("defeat_required", False)):
            death_sequence = self._next_transport_sequence()
            bag_drop = dict(core.get("bag_drop") or {})
            bag_entries: list[dict[str, Any]] = []
            if bag_drop.get("bag_dropped"):
                bag_entries.append(
                    self._bag_projection(dict(bag_drop["bag"]), sequence=death_sequence)
                )
                self._last_authoritative_water_tick = time.monotonic()
            death_event = {
                "server_authoritative": True,
                "session_ref": session_ref,
                "death_sequence": death_sequence,
                "death_ref": f"DEATH-WATER-{command_ref}",
                "state": "DEAD_AWAITING_RESPAWN",
                "retention": self._retention_projection(),
                "bag_drop": {
                    "dropped": bool(bag_drop.get("bag_dropped", False)),
                    "reason": str(bag_drop.get("reason") or "EQUIPPED_BAG_EXTERNAL_DROP"),
                    "single_container": bool(bag_drop.get("bag_dropped", False)),
                    "dropped_bag_snapshot": {
                        "server_authoritative": True,
                        "session_ref": session_ref,
                        "snapshot_sequence": death_sequence,
                        "dropped_bags": bag_entries,
                        "complete_projection": False,
                    } if bag_entries else {},
                },
                "authority": stage16a.AUTHORITY,
            }
        return {
            **core,
            "command": "REPORT_WATER_EXHAUSTION",
            "server_authoritative": True,
            "exhaustion_snapshot": exhaustion_snapshot,
            "death_event": death_event,
            "client_supplied_stamina": False,
            "client_supplied_elapsed_time": False,
            "death_decided_by_godot": False,
            "authority": stage16a.AUTHORITY,
        }

    def _report_ground_loot_water_state(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        allowed = {
            "request_ref", "target_ref", "drop_ref", "in_water", "flow_speed_mps",
            "client_presentation_only",
        }
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        drop_ref = str(params.get("target_ref") or params.get("drop_ref") or "").strip()
        if not drop_ref:
            return self._rejected("GROUND_LOOT_REF_REQUIRED")
        if params.get("target_ref") and params.get("drop_ref") and str(params["target_ref"]) != str(params["drop_ref"]):
            return self._rejected("GROUND_LOOT_TARGET_REF_MISMATCH")
        if not isinstance(params.get("in_water"), bool) or not _finite(params.get("flow_speed_mps", 0.0)):
            return self._rejected("INVALID_GROUND_LOOT_WATER_SAMPLE")
        stage16a = self._engine.stage16a(self.world_instance_id)
        core = stage16a.mark_drop_in_water(
            drop_ref,
            in_water=bool(params["in_water"]),
            flow_speed_mps=float(params.get("flow_speed_mps", 0.0)),
            event_ref=command_ref,
        )
        self._last_authoritative_water_tick = time.monotonic()
        return {
            **core,
            "command": "REPORT_GROUND_LOOT_WATER_STATE",
            "target_ref": drop_ref,
            "server_authoritative": True,
            "ttl_decided_by_godot": False,
            "authority": stage16a.water_bag.AUTHORITY,
        }

    def _advance_development_water_time(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """DEVELOPMENT-ONLY transport: advance the real water-exposure clock by
        an explicit, deterministic delta_s.

        This exists solely so G16B-27's TTL thresholds (900s ground-loot,
        1800s dropped-bag) can be proven live from Godot without literally
        waiting real wall-clock minutes. It does not create a second clock:
        the same stage16a.advance_water_time() the production real-time path
        (_advance_authoritative_water_clock(), called from every snapshot())
        already calls is called here too, applying the exact same SUNK rules
        already enforced by the protected ground-loot/bag cores -- nothing
        about the TTL thresholds or the SUNK transition is duplicated or
        reimplemented at this layer. The adapter validates transport shape
        only (delta_s present, finite, non-negative); it never decides who
        sinks or when.

        This command is listed in ENABLED_COMMANDS like every other command
        (there is no per-session capability filtering in this architecture,
        so its NAME is visible to any session's enabled_commands list), but
        it can only ever be invoked successfully when this world was booted
        with development_profile_bootstrap=True -- the same world-level,
        server-side, boot-time flag that already gates the entire
        development-profile loadout (weapons, CLOTHES, ITEM-OLD-KEY, etc.).
        A production-booted world (development_profile_bootstrap=False)
        rejects every call outright, before any parameter is even read,
        with zero mutation.
        """
        if not self.config.development_profile_bootstrap:
            return self._rejected(
                "DEV_WATER_TIME_COMMAND_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE"
            )
        allowed = {"request_ref", "delta_s", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        if "delta_s" not in params:
            return self._rejected("DEV_WATER_TIME_DELTA_S_REQUIRED")
        delta_s = params["delta_s"]
        if not _finite(delta_s):
            return self._rejected("DEV_WATER_TIME_DELTA_S_MUST_BE_FINITE_NUMBER")
        if float(delta_s) < 0.0:
            return self._rejected("DEV_WATER_TIME_DELTA_S_MUST_BE_NON_NEGATIVE")

        # Flush any pending REAL wall-clock delta through the normal
        # production path FIRST -- so it is resolved on its own, before this
        # deterministic synthetic advance, and never silently folded into (or
        # double counted against) the exact delta_s requested here. This also
        # re-anchors _last_authoritative_water_tick to "now", so the very next
        # snapshot()'s own _advance_authoritative_water_clock() call only ever
        # accounts for genuine real time elapsed AFTER this command returns --
        # never re-applying any part of this synthetic delta.
        flushed = self._advance_authoritative_water_clock()

        stage16a = self._engine.stage16a(self.world_instance_id)
        core = stage16a.advance_water_time(float(delta_s), event_ref=command_ref)
        return {
            **core,
            "command": "ADVANCE_DEVELOPMENT_WATER_TIME",
            "delta_s_requested": float(delta_s),
            "flushed_real_delta_s": flushed.get("advanced_s", 0.0),
            "server_authoritative": True,
            "development_only": True,
            "grants_nothing": True,
            "authority": stage16a.water_bag.AUTHORITY,
        }

    def _advance_development_living_systemic(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """DEVELOPMENT-ONLY transport: trigger ONE real Stage14 Living cycle
        so its effect on ``living_macro_context`` (see _streaming_projection)
        can be observed deterministically from a test/Godot, instead of
        waiting on real wall-clock/gameplay pacing.

        This handler simulates nothing itself. It validates transport shape
        and the development-profile gate only, then calls the one real
        production tick that already exists --
        ARPGLivingIntegrationCore.advance_and_reconcile() -- exactly once
        (G16B-09B Section 18: "1 comando = 1 production cycle"). The core
        decides everything: which metrics move, what signals/opportunities
        are recorded, what market effects apply. No zone_ref, stream_phase,
        fauna count, wallet balance or any other gameplay value is accepted
        as a parameter here (Section 17) -- there is nothing for a caller to
        set, choose or fabricate.

        advance_and_reconcile() has its own event_ref-keyed idempotency
        (arpg_living_events), on top of this adapter's own command_ref
        journal replay -- the same double layer ADVANCE_DEVELOPMENT_WATER_TIME
        already relies on above. A second call with the same command_ref
        never advances the cycle twice.

        Reachable only when this world was booted with
        development_profile_bootstrap=True, the same world-level, server-
        side, boot-time flag every other development-only surface in this
        file is gated by. A production-booted world rejects every call
        outright, before any parameter is even read, with zero mutation.
        """
        if not self.config.development_profile_bootstrap:
            return self._rejected(
                "DEV_LIVING_SYSTEMIC_COMMAND_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE"
            )
        allowed = {"request_ref", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        living_core = self._engine.living_arpg(self.world_instance_id)
        core = living_core.advance_and_reconcile(
            command_ref, living_steps=1, apply_consequences=True
        )
        return {
            **core,
            "command": "ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC",
            "server_authoritative": True,
            "development_only": True,
            "grants_nothing": True,
            "zone_or_phase_client_supplied": False,
            "authority": living_core.AUTHORITY,
        }

    def _attempt_development_systemic_zone_hunt(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """DEVELOPMENT-ONLY transport: exercise ONE real
        CountryLivingDomainBridge.hunt_fauna() action against a zone the
        authoritative streaming projection (_streaming_projection()) itself
        classifies SYSTEMIC -- proving a distant, unmaterialized zone's
        Living state can be genuinely mutated by a real per-zone domain
        action, not only by ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC's country-
        wide aggregate tick above (which never touches any specific
        zone/block -- confirmed by direct inspection of run_cycle() in
        G16B-09B: its effects land on fixed anchor refs, never a zone_ref).

        The client supplies ONLY zone_ref. block_ref, which NPC hunts, and
        which fauna species are all resolved server-side from real,
        already-existing data (CountryScaleSystem records) -- exactly like
        ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY resolves npc_target_ref
        against the same real NPC registry rather than trusting a client-
        supplied identity for anything beyond the single zone_ref anchor.
        The NPC and fauna picks are deterministic (first eligible match in
        each real, stably-ordered list) -- never retried against a second
        candidate if the first is rejected by the domain, so a legitimate
        domain-level rejection (e.g. NO_OWNED_WEAPON) is always returned
        verbatim, never silently routed around.

        All hunting rules (weapon requirement, CHILD protection, combat-
        targetable, fauna depletion, witness/memory) remain 100% inside
        CountryLivingDomainBridge.hunt_fauna() and the CombatSystem it
        delegates to -- this handler duplicates none of that; it only
        resolves zone->block, validates the zone is SYSTEMIC, and picks
        real npc_id/fauna_id/quantity=1 before calling the one real core
        method.

        Reachable only when this world was booted with
        development_profile_bootstrap=True, the same world-level, server-
        side, boot-time flag every other development-only surface in this
        file is gated by.
        """
        if not self.config.development_profile_bootstrap:
            return self._rejected("DEV_SYSTEMIC_HUNT_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE")
        allowed = {"request_ref", "zone_ref", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        zone_ref = str(params.get("zone_ref") or "").strip()
        if not zone_ref:
            return self._rejected("DEV_SYSTEMIC_HUNT_ZONE_REF_REQUIRED")

        # SYSTEMIC is validated against the SAME authoritative projection
        # world_streaming already exposes -- no client-supplied phase is
        # ever trusted, and there is no separate/duplicated phase check.
        projection = self._streaming_projection()
        zone_entry = next((z for z in projection["zones"] if z["zone_ref"] == zone_ref), None)
        if zone_entry is None:
            return self._rejected("DEV_SYSTEMIC_HUNT_UNKNOWN_ZONE_REF", zone_ref=zone_ref)
        if zone_entry["stream_phase"] != "SYSTEMIC":
            return self._rejected(
                "DEV_SYSTEMIC_HUNT_REQUIRES_AUTHORITATIVE_SYSTEMIC_PHASE",
                zone_ref=zone_ref,
                stream_phase=zone_entry["stream_phase"],
            )
        block_ref = zone_entry["block_ref"]

        country = self._engine.country(self.world_instance_id)
        block = country.block(block_ref)
        fauna_list = block.get("fauna") or []
        if not fauna_list:
            return self._rejected(
                "DEV_SYSTEMIC_HUNT_NO_FAUNA_IN_BLOCK", zone_ref=zone_ref, block_ref=block_ref
            )
        fauna_id = str(fauna_list[0]["id"])

        hunter_npc_id = None
        for npc in country._all_npc_records():
            if npc.get("id") == self._player_ref:
                continue
            if npc.get("block_id") != block_ref:
                continue
            if npc.get("class") == "CHILD":
                continue
            hunter_npc_id = str(npc["id"])
            break
        if hunter_npc_id is None:
            return self._rejected(
                "DEV_SYSTEMIC_HUNT_NO_ELIGIBLE_NPC_IN_BLOCK", zone_ref=zone_ref, block_ref=block_ref
            )

        bridge = self._engine.bridge(self.world_instance_id)
        core = bridge.hunt_fauna(npc_id=hunter_npc_id, block_id=block_ref, fauna_id=fauna_id, quantity=1)
        return {
            **core,
            "command": "ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT",
            "zone_ref": zone_ref,
            "block_ref": block_ref,
            "npc_ref": hunter_npc_id,
            "fauna_ref": fauna_id,
            "server_authoritative": True,
            "development_only": True,
            "zone_promoted_to_active": False,
            "authority": "COUNTRY_LIVING_DOMAIN_BRIDGE_VIA_DEV_TRANSPORT",
        }

    def _attempt_development_npc_bag_recovery(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        """DEVELOPMENT-ONLY transport: provoke a real bag-recovery attempt AS
        a specific NPC, to observe G16B-28 ownership/anti-theft enforcement
        live from Godot.

        This is deliberately narrow -- NOT a generic "act as any actor"
        surface. The client supplies only bag_ref and npc_target_ref;
        claimant_kind is fixed to "NPC" server-side and is never client-
        controlled. The core (stage16a.recover_bag()) is the only thing that
        decides whether the attempt passes or is rejected -- this handler
        duplicates none of that ownership/anti-theft logic, it only
        validates transport shape and that npc_target_ref genuinely names an
        NPC. (Named npc_target_ref rather than the more obvious npc_ref
        because the latter -- like actor_ref/entity_ref/owner_ref/player_ref
        -- is one of this adapter's own reserved, client-forbidden authority
        field names; find_forbidden_field() rejects any command envelope
        naming it, by design, before this handler would ever run.)

        npc_target_ref validation uses the same real NPC registry already
        relied on elsewhere in this file (development combat-encounter
        target selection) and in the existing Python test suite
        (test_stage16b_authority_save_death_water.py::test_10) --
        CountryScaleSystem._all_npc_records() -- rather than inventing a new
        registry. A ref that is not in that registry, or that is the
        player's own ref, is rejected before recover_bag() is ever called.

        Reachable only when this world was booted with
        development_profile_bootstrap=True, the same world-level, server-
        side, boot-time flag every other development-only surface in this
        file is gated by.
        """
        if not self.config.development_profile_bootstrap:
            return self._rejected(
                "DEV_NPC_BAG_RECOVERY_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE"
            )
        allowed = {"request_ref", "bag_ref", "npc_target_ref", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        bag_ref = str(params.get("bag_ref") or "").strip()
        if not bag_ref:
            return self._rejected("DEV_NPC_BAG_RECOVERY_BAG_REF_REQUIRED")
        npc_target_ref = str(params.get("npc_target_ref") or "").strip()
        if not npc_target_ref:
            return self._rejected("DEV_NPC_BAG_RECOVERY_NPC_REF_REQUIRED")
        if npc_target_ref == self._player_ref:
            return self._rejected("DEV_NPC_BAG_RECOVERY_REF_IS_PLAYER_NOT_NPC")

        known_npc_refs = {
            str(row.get("id") or "")
            for row in self._engine.country(self.world_instance_id)._all_npc_records()
        }
        if npc_target_ref not in known_npc_refs:
            return self._rejected("DEV_NPC_BAG_RECOVERY_UNKNOWN_NPC_REF")

        stage16a = self._engine.stage16a(self.world_instance_id)
        try:
            stage16a.water_bag.bag(bag_ref)
        except KeyError:
            return {
                **self._rejected("BAG_NOT_FOUND"),
                "command": "ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY",
                "server_authoritative": True,
                "development_only": True,
            }

        core = stage16a.recover_bag(
            bag_ref, npc_target_ref, claimant_kind="NPC", event_ref=command_ref
        )
        return {
            **core,
            "command": "ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY",
            "server_authoritative": True,
            "development_only": True,
            "grants_nothing": True,
            "authority": stage16a.AUTHORITY,
        }

    def _request_bag_recovery(
        self, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        allowed = {
            "request_ref", "bag_ref", "target_ref", "target_kind", "request_source",
            "physical_distance_m", "client_range_candidate_m", "client_guard_passed",
            "client_presentation_only",
        }
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        request_ref = str(params.get("request_ref") or "").strip()
        bag_ref = str(params.get("bag_ref") or "").strip()
        if not request_ref or not bag_ref:
            return self._rejected("BAG_AND_REQUEST_REF_REQUIRED")
        if str(params.get("target_ref") or bag_ref) != bag_ref:
            return self._rejected("DROPPED_BAG_TARGET_REF_MISMATCH")
        sequence = self._next_transport_sequence()
        stage16a = self._engine.stage16a(self.world_instance_id)
        try:
            before = stage16a.water_bag.bag(bag_ref)
        except KeyError:
            before = {}
        if not before:
            return {
                **self._rejected("BAG_NOT_FOUND"),
                "command": "REQUEST_BAG_RECOVERY",
                "server_authoritative": True,
                "request_ref": request_ref,
                "bag_ref": bag_ref,
                "result": "REJECTED",
                "result_sequence": sequence,
            }
        life_state = str(
            self._engine.character(self.world_instance_id)
            .ensure_profile(self.profile_ref)
            .get("vitals", {})
            .get("life_state", "ALIVE")
        ).upper()
        if life_state != "ALIVE":
            return {
                **self._rejected("BAG_RECOVERY_REQUIRES_LIVING_PLAYER"),
                "command": "REQUEST_BAG_RECOVERY",
                "server_authoritative": True,
                "request_ref": request_ref,
                "bag_ref": bag_ref,
                "result": "REJECTED",
                "result_sequence": sequence,
                "authority": stage16a.AUTHORITY,
            }
        # The spatial (distance/collision) precondition below only makes sense
        # while the bag is actually lying at a real world position -- i.e. the
        # exact two states stage16a.recover_bag() itself treats as spatially
        # "DROPPED" (see arpg_water_bag_survival_core.py::recover_bag()'s own
        # `bag.get("state") not in {"DROPPED_LAND","DROPPED_WATER_FLOATING"}`
        # check). Every other state (EQUIPPED, RECOVERED, RECOVERED_FOREIGN,
        # SUNK, ...) sets `position: None` by design once the bag stops being
        # a physical dropped object -- there is nothing left to measure a
        # distance to. Running the distance math anyway fed math.inf into the
        # response payload (`physical_distance_m`), and Starlette's
        # JSONResponse.render() calls json.dumps(..., allow_nan=False), which
        # raises ValueError on that inf -- surfacing as INTERNAL_ADAPTER_ERROR
        # for what should just be a normal, core-decided rejection (typically
        # BAG_NOT_RECOVERABLE). The core is, and remains, the only decider of
        # whether a recovery is accepted; this only decides whether the
        # spatial transport precondition applies before asking it.
        position = before.get("position") or {}
        spatially_dropped = str(before.get("state") or "") in {
            "DROPPED_LAND", "DROPPED_WATER_FLOATING",
        }
        distance: float | None = None
        if spatially_dropped:
            player = self._engine.movement(self.world_instance_id).state(self._player_ref)
            distance = math.hypot(
                float(position.get("iso_x_m", math.inf)) - float(player["iso_x_m"]),
                float(position.get("iso_y_m", math.inf)) - float(player["iso_y_m"]),
            )
            blocked = self._engine.collision(self.world_instance_id).point_blocked(
                self._player_ref,
                float(position.get("iso_x_m", math.inf)),
                float(position.get("iso_y_m", math.inf)),
            )
            if not math.isfinite(distance) or distance > 0.5 or blocked.get("blocked"):
                reason = "BAG_RECOVERY_DISTANCE_EXCEEDED" if distance > 0.5 else "BAG_RECOVERY_BLOCKED"
                return {
                    **self._rejected(reason),
                    "command": "REQUEST_BAG_RECOVERY",
                    "server_authoritative": True,
                    "request_ref": request_ref,
                    "bag_ref": bag_ref,
                    "result": "REJECTED",
                    "result_sequence": sequence,
                    "physical_distance_m": distance,
                    "blocker": blocked,
                    "authority": stage16a.AUTHORITY,
                }
        core = stage16a.recover_bag(
            bag_ref,
            self.profile_ref,
            claimant_kind="PLAYER",
            event_ref=command_ref,
        )
        accepted = core.get("status") == "PASS"
        bag_projection: dict[str, Any] = {}
        if accepted:
            state = "RECOVERED" if str(before.get("property_owner_ref")) == self.profile_ref else "RECOVERED_FOREIGN"
            environment = "WATER" if str(before.get("location_kind")).upper() == "WATER" else "LAND"
            bag_projection = self._bag_projection(
                dict(core["bag"]),
                sequence=sequence,
                state_override=state,
                environment_override=environment,
            )
        return {
            **core,
            "command": "REQUEST_BAG_RECOVERY",
            "server_authoritative": True,
            "request_ref": request_ref,
            "bag_ref": bag_ref,
            "result": "ACCEPTED" if accepted else "REJECTED",
            "reason": "" if accepted else str(core.get("reason", "BAG_RECOVERY_REJECTED")),
            "result_sequence": sequence,
            "bag_projection": bag_projection,
            "physical_distance_m": distance,
            "ownership_decided_by_godot": False,
            "authority": stage16a.AUTHORITY,
        }

    def _request_respawn(
        self, session_ref: str, params: dict[str, Any], command_ref: str
    ) -> dict[str, Any]:
        allowed = {"request_ref", "death_ref", "client_presentation_only"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            return self._rejected(
                "UNEXPECTED_COMMAND_PARAM", field_path=f"$.params.{unexpected[0]}"
            )
        request_ref = str(params.get("request_ref") or "").strip()
        if not request_ref:
            return self._rejected("RESPAWN_REQUEST_REF_REQUIRED")
        recovery_core = self._engine.save_recovery(self.world_instance_id)
        core = recovery_core.recover_death(self.profile_ref, event_ref=command_ref)
        if core.get("status") != "PASS":
            return {
                **core,
                "command": "REQUEST_RESPAWN",
                "server_authoritative": True,
                "request_ref": request_ref,
                "result_sequence": self._next_transport_sequence(),
                "authority": recovery_core.AUTHORITY,
            }
        waypoint = self._engine.world_arpg(self.world_instance_id)._waypoint(core["waypoint_ref"])
        sync = self._engine.movement(self.world_instance_id).sync_to_geodetic(
            self._player_ref,
            dict(waypoint["coordinate"]),
            reason="STAGE15_SAFE_WAYPOINT_RESPAWN",
        )
        position = self._engine.movement(self.world_instance_id).state(self._player_ref)
        post_respawn_save = recovery_core.create_snapshot(
            "autosave", kind="POST_RESPAWN_AUTOSAVE"
        )
        sequence = self._next_transport_sequence()
        return {
            **core,
            "command": "REQUEST_RESPAWN",
            "server_authoritative": True,
            "request_ref": request_ref,
            "result_sequence": sequence,
            "movement_sync": sync,
            "post_respawn_save": post_respawn_save,
            "respawn_snapshot": {
                "server_authoritative": True,
                "session_ref": session_ref,
                "respawn_sequence": sequence,
                "request_ref": request_ref,
                "state": "READY",
                "position": {
                    "iso_x_m": float(position["iso_x_m"]),
                    "iso_y_m": float(position["iso_y_m"]),
                    "altitude_m": float(position.get("altitude_m", 0.0)),
                },
                "safe_waypoint_ref": str(core["waypoint_ref"]),
                "authority": recovery_core.AUTHORITY,
            },
            "respawn_point_selected_by_godot": False,
            "authority": recovery_core.AUTHORITY,
        }

    def _move_to_point(
        self, session_ref: str, session: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate an absolute ground target into the core MOVE_VECTOR authority.

        The adapter computes only the vector and the step duration. Distance, stamina,
        collision, clock advance, chunk ownership and boundary rules stay in the core.
        """
        player_ref = str(session["player_ref"])
        target_x = params.get("iso_x_m")
        target_y = params.get("iso_y_m")
        if not _finite(target_x) or not _finite(target_y):
            return self._rejected("INVALID_TARGET_POINT")
        target_x = float(target_x)
        target_y = float(target_y)

        mode = str(params.get("mode", "WALK")).upper().strip()
        movement = self._engine.movement(self.world_instance_id)
        if mode not in movement.SPEEDS_MPS:
            return self._rejected("UNSUPPORTED_MOVE_MODE", mode=mode)

        raw_duration = params.get("duration_s", 0.25)
        if not _finite(raw_duration):
            return self._rejected("INVALID_STEP_DURATION")
        requested_duration = float(raw_duration)
        if requested_duration <= 0 or requested_duration > STEP_DURATION_MAX_S:
            return self._rejected("INVALID_STEP_DURATION", duration_s=requested_duration)

        state = movement.state(player_ref)
        dx = target_x - float(state["iso_x_m"])
        dy = target_y - float(state["iso_y_m"])
        remaining = math.hypot(dx, dy)

        applied_duration = requested_duration
        if remaining <= ARRIVAL_EPSILON_M:
            dx = 0.0
            dy = 0.0
        else:
            npc = self._engine.country(self.world_instance_id).npc(player_ref)
            env = self._engine.environment(self.world_instance_id).state_for_block(npc["block_id"])
            factor = min(ENV_FACTOR_MAX, max(ENV_FACTOR_MIN, float(env["movement_factor"])))
            speed = float(movement.SPEEDS_MPS[mode])
            reach = speed * requested_duration * factor
            if reach > remaining:
                applied_duration = remaining / (speed * factor)
            if applied_duration <= 0:
                dx = 0.0
                dy = 0.0
                applied_duration = requested_duration

        core = self._godot().client_command(
            session_ref,
            "MOVE_VECTOR",
            {"dx": dx, "dy": dy, "duration_s": applied_duration, "mode": mode},
        )
        result = dict(core)
        result["command"] = "MOVE_TO_POINT"
        result["delegated_core_command"] = "MOVE_VECTOR"
        result["target"] = {"iso_x_m": target_x, "iso_y_m": target_y}
        result["requested_duration_s"] = round(requested_duration, 9)
        result["applied_duration_s"] = round(applied_duration, 9)
        result["distance_before_m"] = round(remaining, 6)
        if result.get("status") == "PASS":
            after = movement.state(player_ref)
            left = math.hypot(target_x - float(after["iso_x_m"]), target_y - float(after["iso_y_m"]))
            result["remaining_distance_m"] = round(left, 6)
            result["arrived"] = left <= ARRIVAL_EPSILON_M
        return result
