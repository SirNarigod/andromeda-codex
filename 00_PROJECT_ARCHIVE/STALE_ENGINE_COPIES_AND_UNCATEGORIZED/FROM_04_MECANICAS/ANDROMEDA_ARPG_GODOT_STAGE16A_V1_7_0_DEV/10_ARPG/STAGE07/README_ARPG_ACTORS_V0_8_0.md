# ARPG Stage 07 — Actors / Hostility / PvE AI

Stage 07 adds the authoritative Actor Core for player/NPC/creature/robot roles, runtime hostility, PvE AI states, combat ranks, elite/boss scaling, persistence and lazy active-set materialization.

Canonical identity remains READ_ONLY. Runtime hostility and combat scaling are gameplay-derived overlays. Protected identities and children are never silently promoted to hostile combatants.

The lore-to-gameplay coverage registry maps all 1,660 canonical entities to a gameplay stage/system or explicit guard, with 0 unmapped entities.
