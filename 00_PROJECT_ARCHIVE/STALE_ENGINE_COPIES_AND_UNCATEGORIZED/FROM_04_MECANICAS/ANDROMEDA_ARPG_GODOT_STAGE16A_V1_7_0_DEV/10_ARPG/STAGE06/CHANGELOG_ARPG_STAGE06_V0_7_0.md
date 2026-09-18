# CHANGELOG — ARPG Stage 06 V0.7.0

## Added
- Skill catalog, learned-skill state, active/passive loadouts and event ledger.
- Deterministic skill attacks and passive combat modifiers.
- Use-based mastery ranks and emergent build evidence axes.
- Game Core commands: LEARN_SKILL, ASSIGN_SKILL, ACTIVATE_PASSIVE, USE_SKILL.
- Client snapshot projection for skills.
- Read-only import of 30 canonical MAG records as non-auto-castable sources.

## Compatibility
- Preserved legacy CombatCore marker `DEFERRED_STAGE07` when SkillCore is absent.

## Canon guard
- No canonical MAG entry receives invented numeric gameplay mapping.
- Runes remain unmapped to sockets/skills in this stage.
