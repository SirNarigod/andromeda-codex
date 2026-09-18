# CHANGELOG — ARPG Stage 07 V0.8.0

## ADDED
- Actor Core with explicit roles, dispositions, combat ranks and AI states.
- Authoritative runtime hostility and click-to-attack integration.
- Aggro, chase, attack, return/leash and PvE rank scaling.
- Lazy active-set/LOD actor materialization.
- Full Lore → Gameplay coverage registry for 1,660 canonical entities.
- Roadmap expansion for world/biomes, gathering/hunting/fishing/work, mobility, technology/robotics and lore completeness.

## GUARDED
- Canonical identity and relationships remain READ_ONLY.
- Protected identities/children cannot be silently made hostile.
- Fishing mechanic is gameplay-derived from supported canonical economic/geographic context; no new canonical institution was invented.

## FIXED
- Removed eager actor overlay bootstrap cost by lazy materialization.
- Split slow harness batches to produce conclusive regression results.

- Removed runtime world UUID from combat RNG entropy; stable rolls now use simulation world seed + immutable event reference + channel.
