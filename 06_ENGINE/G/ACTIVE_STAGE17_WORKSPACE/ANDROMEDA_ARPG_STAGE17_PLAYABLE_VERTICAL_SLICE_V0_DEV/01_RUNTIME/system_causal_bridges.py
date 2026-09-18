"""Stage17 causal bridges between systems that otherwise never talk.

Each function here composes over existing protected/unprotected cores --
none of them reimplement game logic, they just carry an already-decided
outcome from one system into another that has no native trigger for it.

This is NOT routed through ConsequenceEngine (see
ANDROMEDA_CAUSAL_RULES_CATALOG_V1_0.md for why: ConsequenceEngine walks
`causal_relations` between generic `register_entity()` rows, but NPCs,
vendors and country_scale resources all live in their own domain tables,
never registered as generic entities). These are direct, composed bridges,
matching the existing pattern used by fauna_territorial_migration.py and
cross_territory_transfer.py.
"""

from __future__ import annotations

import hashlib
from typing import Any

from living_runtime import clock_point, new_runtime_id

AUTHORITY = "STAGE17_SYSTEM_CAUSAL_BRIDGE"


# Only these NPC classes can be assigned a faction (guard/soldier-type
# roles) -- design decision approved for this bridge, not a discovered fact.
# NATIVE/WORKER/CHILD/MAGE/ROBOT never carry a faction_ref.
FACTION_ELIGIBLE_NPC_CLASSES: frozenset[str] = frozenset({"WARRIOR", "MERCENARY"})


def assign_npc_faction_membership(
    country: Any,
    world_systems: Any,
    faction_world_instance_id: str,
) -> dict[str, Any]:
    """country_scale.py's NPCs have no faction_ref at all today (only a
    territory-wide, presence-based FACTION_RUNTIME with no membership
    roster). Assigns faction_ref only to eligible NPC classes, only in a
    territory where a faction actually has presence, weighted by that
    faction's influence -- deterministic (hashed NPC id, not `random`), so
    running this twice on the same generated world produces the same
    assignment. NPCs of ineligible classes get faction_ref=None explicitly
    (never left absent) so downstream code can tell "checked, not eligible"
    apart from "never processed".
    """
    factions = [
        e
        for e in world_systems.runtime.list_entities(faction_world_instance_id)
        if e.get("entity_kind") == "FACTION_RUNTIME"
        and str((e.get("data") or {}).get("territory_ref") or "") == country.country_territory_id
        and e.get("lifecycle") == "ACTIVE"
    ]
    if not factions:
        return {"status": "SKIPPED", "reason": "NO_FACTION_PRESENT_IN_TERRITORY", "authority": AUTHORITY}
    weights = [(str(f["data"]["faction_ref"]), max(0.01, float(f["data"].get("influence", 0.0)))) for f in factions]
    total_weight = sum(w for _, w in weights)
    assigned = 0
    eligible_seen = 0
    for state in country.world["country"]["states"]:
        for block in state["blocks"]:
            for city in block["cities"]:
                for npc in city["npcs"]:
                    if npc.get("class") not in FACTION_ELIGIBLE_NPC_CLASSES:
                        npc["faction_ref"] = None
                        continue
                    eligible_seen += 1
                    # Deterministic weighted pick from a stable hash of the
                    # NPC's own id -- same world, same seed, same result.
                    roll = (int(hashlib.sha256(npc["id"].encode("utf-8")).hexdigest(), 16) % 10_000) / 10_000.0
                    cumulative = 0.0
                    pick = weights[-1][0]
                    for faction_ref, weight in weights:
                        cumulative += weight / total_weight
                        if roll <= cumulative:
                            pick = faction_ref
                            break
                    npc["faction_ref"] = pick
                    assigned += 1
    return {
        "status": "PASS",
        "territory_id": country.country_territory_id,
        "factions_considered": [f for f, _ in weights],
        "eligible_npcs_seen": eligible_seen,
        "assigned": assigned,
        "authority": AUTHORITY,
    }


# Minimal viable needs so validate_agent_state() passes (requires a
# non-empty data.needs dict of 0-100 numbers) -- not tuned gameplay balance,
# just enough for decide() to run safely. Real need-modeling (hunger drains
# over time, etc.) is a separate, later concern.
NPC_AGENT_DEFAULT_NEEDS: dict[str, float] = {"safety": 60.0, "sustenance": 60.0}


def register_npc_as_agent_participant(
    runtime: Any,
    orchestrator: Any,
    world_instance_id: str,
    npc: dict[str, Any],
) -> dict[str, Any]:
    """The real missing link for #7/tick "empty ecosystem": PerceptionSystem
    and AgentBrain are both correct and composed (perceive_and_record_for_agent
    above), and the tick loop now genuinely runs -- but _phase_npc only acts
    on entities already registered as an orchestrator "NPC" participant, and
    country_scale.py's procedural NPCs were never mirrored into the generic
    entity system at all. This does both steps for one NPC: register it as a
    generic AGENT entity (idempotent -- looks up by data.npc_id first, never
    creates a duplicate mirror on repeat calls) and register that entity as
    an orchestrator NPC participant (register_participant is itself
    idempotent by (world, entity_ref, subsystem) unique key).
    """
    npc_id = str(npc["id"])
    existing = next(
        (
            e
            for e in runtime.list_entities(world_instance_id)
            if e.get("entity_kind") == "AGENT" and (e.get("data") or {}).get("npc_id") == npc_id
        ),
        None,
    )
    if existing is not None:
        agent_ref = str(existing["entity_runtime_id"])
        created = False
    else:
        world = runtime.get_world(world_instance_id)
        clock = world["clock_state"]
        state = {
            "state_id": new_runtime_id("state"),
            "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"],
            "entity_runtime_id": new_runtime_id("agent"),
            "origin": "RUNTIME_BORN",
            "entity_kind": "AGENT",
            "lifecycle": "ACTIVE",
            "version": 0,
            "updated_at": clock_point(clock["day"], clock["tick"]),
            "data": {
                "npc_id": npc_id,
                "npc_class": npc.get("class"),
                "block_id": npc.get("block_id"),
                "needs": dict(NPC_AGENT_DEFAULT_NEEDS),
                "risk_tolerance": 50.0,
                "goals": {},
            },
        }
        runtime.register_entity(world_instance_id, state)
        agent_ref = str(state["entity_runtime_id"])
        created = True
    already_participant = orchestrator.conn.execute(
        "SELECT 1 FROM orchestration_participants WHERE world_instance_id=? AND entity_ref=? AND subsystem='NPC'",
        (world_instance_id, agent_ref),
    ).fetchone()
    participant = (
        {"status": "ALREADY_REGISTERED"}
        if already_participant
        else orchestrator.register_participant(world_instance_id, agent_ref, "NPC", cadence_ticks=1)
    )
    return {
        "status": "PASS",
        "npc_id": npc_id,
        "agent_ref": agent_ref,
        "agent_entity_created": created,
        "participant": participant,
        "authority": AUTHORITY,
    }


def register_block_npcs_as_agents(
    runtime: Any,
    orchestrator: Any,
    world_instance_id: str,
    block: dict[str, Any],
) -> dict[str, Any]:
    """Registers every NPC in one country_scale.py block (all its cities'
    rosters combined) as an agent-brain participant. Block-scoped, not
    world-scoped, deliberately: registering every NPC across all 13
    territories at once would be real, needless load for NPCs nowhere near
    any player -- call this per block as players actually reach it.
    """
    registered: list[dict[str, Any]] = []
    for city in block.get("cities", []):
        for npc in city.get("npcs", []):
            registered.append(
                register_npc_as_agent_participant(
                    runtime, orchestrator, world_instance_id, npc
                )
            )
    return {
        "status": "PASS",
        "block_id": str(block.get("id", "")),
        "npc_count": len(registered),
        "created_count": sum(1 for r in registered if r["agent_entity_created"]),
        "authority": AUTHORITY,
    }


def perceive_and_record_for_agent(
    perception: Any,
    agent_brain: Any,
    world_instance_id: str,
    observer_actor_ref: str,
    target_ref: str,
    *,
    observer_heading_deg: float,
) -> dict[str, Any]:
    """The real missing link for #7: perception_system.py (geometric
    SEEN/SUSPICIOUS/UNAWARE) and agent_brain.py (record_perception() /
    decide()) never talk -- agent_brain's decisions only ever see whatever
    an outside caller chooses to record_perception() with, and nothing in
    the codebase calls that from real geometry. This runs one geometric
    check and, only when the observer actually perceived something (SEEN or
    SUSPICIOUS -- UNAWARE/IGNORED record nothing, an agent shouldn't "recall"
    a target it never noticed), feeds it to record_perception() so decide()
    can act on real perception. confidence is lower for SUSPICIOUS (heard,
    not seen) than SEEN.

    Bigger finding while building this: neither PerceptionSystem nor
    AgentBrain is instantiated anywhere in the production adapter today --
    hostility in REQUEST_ATTACK is decided purely from static disposition
    (arpg_actor_core.hostility_to_profile), with no perception or brain
    ticking running in production at all. This bridge is correct and ready,
    but has no live NPC-tick loop to be called from yet; that loop is a
    separate, larger piece of infrastructure, not a data-mapping gap like
    the earlier bridges hit.
    """
    perception_result = perception.check(
        observer_actor_ref,
        target_ref,
        observer_heading_deg=observer_heading_deg,
        can_go_hostile=True,
    )
    state = perception_result.get("state")
    if state not in {"SEEN", "SUSPICIOUS"}:
        return {"status": "SKIPPED", "reason": "NOT_PERCEIVED", "perception": perception_result, "authority": AUTHORITY}
    recorded = agent_brain.record_perception(
        world_instance_id,
        observer_actor_ref,
        [
            {
                "target_ref": target_ref,
                "perceived_kind": "ACTOR",
                "facts": {
                    "perception_state": state,
                    "distance_m": perception_result.get("distance_m"),
                },
                "confidence": 1.0 if state == "SEEN" else 0.5,
            }
        ],
        source="SENSORY",
    )
    return {"status": "PASS", "perception": perception_result, "recorded_perception": recorded, "authority": AUTHORITY}


def apply_combat_kill_faction_reaction(
    world_systems: Any,
    social_memory: Any,
    faction_world_instance_id: str,
    player_world_instance_id: str,
    player_ref: str,
    territory_ref: str,
    *,
    event_ref: str,
    base_delta: float = -3.0,
) -> dict[str, Any]:
    """A hostile kill in a territory nudges every faction PRESENT there
    against the player, weighted by that faction's own influence (a faction
    barely present cares less than one that dominates the area). No per-NPC
    faction membership is invented -- this reflects the real data model
    (WorldSystems models faction PRESENCE by territory reach, not rosters).

    Two world ids because, in production, faction presence lives on the one
    shared planet-macro runtime (`WorldSystems`) while the player and its
    reputation ledger (`SocialMemorySystem`) live on that player's currently
    active per-territory engine runtime -- fase 8.2/8.3/8.7's split. Tests
    that keep everything on one runtime just pass the same id twice.
    """
    factions = [
        e
        for e in world_systems.runtime.list_entities(faction_world_instance_id)
        if e.get("entity_kind") == "FACTION_RUNTIME"
        and str((e.get("data") or {}).get("territory_ref") or "") == territory_ref
        and e.get("lifecycle") == "ACTIVE"
    ]
    applied: list[dict[str, Any]] = []
    for entity in factions:
        faction_ref = str(entity["data"]["faction_ref"])
        influence = float(entity["data"].get("influence", 50.0))
        weighted_delta = base_delta * max(0.1, min(1.0, influence / 100.0))
        result = social_memory.apply_reputation_delta(
            player_world_instance_id,
            player_ref,
            weighted_delta,
            scope_type="FACTION",
            scope_ref=faction_ref,
            reason="HOSTILE_KILL_IN_TERRITORY",
            idempotency_key=f"{event_ref}:{faction_ref}",
        )
        applied.append({"faction_ref": faction_ref, "delta": weighted_delta, "result": result})
    return {
        "status": "PASS",
        "territory_ref": territory_ref,
        "factions_reacted": len(applied),
        "applied": applied,
        "authority": AUTHORITY,
    }


def apply_gathering_yield_to_regional_stock(
    country: Any,
    block_ref: str,
    resource_kind: str,
    quantity: int,
) -> dict[str, Any]:
    """A player's personal gather (arpg_gathering_work_core's logical node)
    also draws down the macro regional resource of the same *kind* in
    country_scale.py -- today player gathering never touches the block's
    aggregate resource table at all, so a fully-gathered node has zero
    effect on regional scarcity/vendor stock upstream.

    Matches by `kind` (e.g. "MINERAL"), not by exact resource id: the two
    systems use independent id namespaces with no 1:1 mapping, but every
    block always carries at most a handful of resources per kind, so this
    stays deterministic and never invents a resource that isn't there.
    """
    if quantity <= 0:
        return {"status": "SKIPPED", "reason": "NON_POSITIVE_QUANTITY", "authority": AUTHORITY}
    try:
        block = country.block(block_ref)
    except (KeyError, ValueError):
        return {"status": "SKIPPED", "reason": "BLOCK_NOT_FOUND", "authority": AUTHORITY}
    candidates = [
        r for r in block.get("resources", [])
        if str(r.get("kind", "")).upper() == resource_kind.upper()
        and r.get("remaining_units", 0) > 0
    ]
    if not candidates:
        return {"status": "SKIPPED", "reason": "NO_MATCHING_REGIONAL_RESOURCE", "authority": AUTHORITY}
    # Deterministic pick: richest matching deposit first, same tie-break the
    # block's own generation already uses (highest remaining_units).
    target = max(candidates, key=lambda r: r["remaining_units"])
    mined = country.mine(block_ref, target["id"], min(quantity, target["remaining_units"]))
    return {"status": "PASS", "resource_id": target["id"], **mined, "authority": AUTHORITY}


# Material -> country_scale.py mineral `kind` mapping, proposed and approved
# for this bridge (STELLAR_BUILDING_PIECES_CATALOG_DEV_V1_0.json's 5 distinct
# input refs; there is no canon table connecting the two catalogs, so this is
# a deliberate design choice, not a discovered fact).
CONSTRUCTION_MATERIAL_TO_RESOURCE_KIND: dict[str, str] = {
    "MIN-IRON": "METAL",
    "MIN-STONE": "STONE",
    "MIN-CRYSTAL": "MAGIC_MINERAL",
    "RUNA-003": "MAGIC_MINERAL",
}
# MAT-001 (Madeira de Copas) has no mineral `kind` counterpart at all --
# country_scale.py's flora list carries no `kind` field, only a
# biome-dependent `species_ref`, so wood draws from whichever flora entry in
# the block has the most remaining_units, regardless of species.
CONSTRUCTION_WOOD_MATERIAL_REFS: frozenset[str] = frozenset({"MAT-001"})


def apply_construction_material_cost(
    country: Any,
    block_ref: str,
    material_refs: list[str],
    *,
    quantity_per_material: int = 10,
) -> dict[str, Any]:
    """Placing a piece should draw down the region's raw materials --
    construction_placement_system.py's place_piece() never touches
    country_scale.py at all today, so building is currently free to the
    regional economy no matter how much gets built.

    NOT wired into the adapter: construction isn't exposed as a player
    command in production yet (ConstructionPlacementSystem is never
    instantiated there), so there is no live call site for this today. Ready
    for whenever REQUEST_PLACE_PIECE (or equivalent) is added -- call this
    right after a successful place_piece() with that piece's catalog
    `inputs[].resource_id` list.
    """
    try:
        block = country.block(block_ref)
    except (KeyError, ValueError):
        return {"status": "SKIPPED", "reason": "BLOCK_NOT_FOUND", "authority": AUTHORITY}
    spent: list[dict[str, Any]] = []
    for material_ref in material_refs:
        if material_ref in CONSTRUCTION_WOOD_MATERIAL_REFS:
            candidates = [f for f in block.get("flora", []) if f.get("remaining_units", 0) > 0]
            if not candidates:
                spent.append({"material_ref": material_ref, "status": "SKIPPED", "reason": "NO_FLORA_AVAILABLE"})
                continue
            target = max(candidates, key=lambda f: f["remaining_units"])
            taken = min(quantity_per_material, target["remaining_units"])
            target["remaining_units"] -= taken
            country.reconcile_country_inventory()
            spent.append({"material_ref": material_ref, "status": "PASS", "flora_id": target["id"], "consumed": taken})
            continue
        kind = CONSTRUCTION_MATERIAL_TO_RESOURCE_KIND.get(material_ref)
        if kind is None:
            spent.append({"material_ref": material_ref, "status": "SKIPPED", "reason": "NO_KIND_MAPPING"})
            continue
        spent.append({"material_ref": material_ref, **apply_gathering_yield_to_regional_stock(country, block_ref, kind, quantity_per_material)})
    return {"status": "PASS", "block_ref": block_ref, "materials": spent, "authority": AUTHORITY}


def apply_skill_learn_cost(
    economy: Any,
    profile_ref: str,
    territory_id: str,
    *,
    base_cost: float = 50.0,
) -> dict[str, Any]:
    """learn_skill() (arpg_skill_core.py) has no gold gate at all today --
    training is free everywhere. Charges gold BEFORE the caller invokes
    learn_skill, scaled inversely to the territory's own wealth tier
    (vendor_wealth_economy.tier_for_territory: poorer territory, pricier
    training -- fewer good trainers around). Must be called before
    learn_skill, never after: skill_core has no "unlearn" to roll back a
    skill already granted for free if payment were checked afterward.

    Uses economy._set_balance() directly -- the same private accessor
    vendor_wealth_economy.py already documents as safe to call from outside
    (confirmed there: plain read/write on arpg_economy_wallets, no hidden
    side effect), not a new pattern.
    """
    from vendor_wealth_economy import tier_for_territory  # noqa: PLC0415

    _, multiplier = tier_for_territory(territory_id)
    cost = round(base_cost / max(0.1, multiplier), 2)
    wallet = economy.wallet(profile_ref)
    balance = float(wallet["balance"])
    if balance < cost:
        return {
            "status": "REJECTED",
            "reason": "INSUFFICIENT_FUNDS_FOR_TRAINING",
            "cost": cost,
            "balance": balance,
            "authority": AUTHORITY,
        }
    economy._set_balance(profile_ref, round(balance - cost, 2))
    return {
        "status": "PASS",
        "cost": cost,
        "balance_before": balance,
        "balance_after": round(balance - cost, 2),
        "territory_id": territory_id,
        "authority": AUTHORITY,
    }


def apply_player_death_social_reaction(
    world_systems: Any,
    social_memory: Any,
    faction_world_instance_id: str,
    player_world_instance_id: str,
    player_ref: str,
    territory_ref: str,
    *,
    event_ref: str,
    base_delta: float = 1.5,
) -> dict[str, Any]:
    """The player dying in a territory reads as weakness, not tragedy, to the
    factions present there: their confidence (reputation *toward* them, from
    the player's perspective, tracks the same ledger both directions) rises
    slightly, weighted by influence exactly like the kill reaction -- a
    faction that barely holds the territory shrugs, a dominant one notices.
    Mirrors apply_combat_kill_faction_reaction's shape and idempotency.
    """
    result = apply_combat_kill_faction_reaction(
        world_systems,
        social_memory,
        faction_world_instance_id,
        player_world_instance_id,
        player_ref,
        territory_ref,
        event_ref=event_ref,
        base_delta=abs(base_delta),
    )
    return {**result, "trigger": "PLAYER_DEATH"}


def climate_vendor_price_multiplier(
    country: Any,
    territory_ref: str,
) -> dict[str, Any]:
    """Same shape and intent as corruption_vendor_price_multiplier, driven by
    a territory's own generated climate (country_scale.py's per-block
    rainfall_mm_y/humidity_pct -- real, already-generated data, nothing new
    invented) instead of corruption. A dry/arid territory pressures vendor
    supply the same way a corrupted one does.

    1500mm/y rainfall and 55% humidity are treated as the comfortable
    baseline (mid-range across the generated climate spread); dryness below
    that scales the multiplier down toward the same 0.4 floor used for
    corruption, for the same reason (never fully cut off).
    """
    if territory_ref != country.country_territory_id:
        return {"status": "SKIPPED", "reason": "TERRITORY_NOT_THIS_COUNTRY_INSTANCE", "authority": AUTHORITY}
    blocks = [b for s in country.world["country"]["states"] for b in s["blocks"]]
    if not blocks:
        return {"status": "PASS", "territory_ref": territory_ref, "dryness_fraction": 0.0, "multiplier": 1.0, "authority": AUTHORITY}
    rainfall_avg = sum(float(b["climate"]["rainfall_mm_y"]) for b in blocks) / len(blocks)
    humidity_avg = sum(float(b["climate"]["humidity_pct"]) for b in blocks) / len(blocks)
    rainfall_dryness = max(0.0, min(1.0, 1.0 - rainfall_avg / 1500.0))
    humidity_dryness = max(0.0, min(1.0, 1.0 - humidity_avg / 55.0))
    dryness = (rainfall_dryness + humidity_dryness) / 2.0
    multiplier = 1.0 - dryness * 0.6
    return {
        "status": "PASS",
        "territory_ref": territory_ref,
        "blocks_considered": len(blocks),
        "dryness_fraction": round(dryness, 4),
        "multiplier": round(multiplier, 4),
        "authority": AUTHORITY,
    }


def corruption_vendor_price_multiplier(
    root_corruption: Any,
    territory_ref: str,
) -> dict[str, Any]:
    """A vendor's effective wallet ceiling should shrink as its territory
    corrupts (scarcity/supply-chain pressure) -- vendor_wealth_economy.py has
    no notion of corruption today. Returns the multiplier to apply against
    `tier_for_territory()`'s wallet_cap; does not mutate vendor state itself
    (register_vendor/replenish are the only legitimate wallet mutators, and
    both already take territory_id as their scaling input, so the intended
    call site is `wallet_cap = base_wallet_cap * multiplier` right before
    those calls -- a 1-line change at each of those 2 call sites).

    0% corrupted subregions -> multiplier 1.0 (no pressure).
    100% corrupted -> multiplier 0.4 (severe but never zero: even a
    corrupted territory still has *some* trade, per the game's existing
    containment_principle that no territory is ever fully cut off).
    """
    subregions = root_corruption.corrupted_subregions(territory_ref)
    if not subregions:
        return {"status": "PASS", "territory_ref": territory_ref, "corruption_fraction": 0.0, "multiplier": 1.0, "authority": AUTHORITY}
    intensity_weight = {"LOW": 0.25, "MEDIUM": 0.55, "HIGH": 0.85, "SEVERE": 1.0}
    total = sum(intensity_weight.get(str(s.get("intensity", "")).upper(), 0.5) for s in subregions)
    fraction = total / max(1, len(subregions))
    multiplier = 1.0 - fraction * 0.6
    return {
        "status": "PASS",
        "territory_ref": territory_ref,
        "corrupted_subregion_count": len(subregions),
        "corruption_fraction": round(fraction, 4),
        "multiplier": round(multiplier, 4),
        "authority": AUTHORITY,
    }
