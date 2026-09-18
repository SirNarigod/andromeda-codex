# ARPG Stage 01 V0.2.0

## Added
- First-class player profiles: CREATED and CANONICAL.
- Runtime PLAYER_AVATAR layer with no canon promotion.
- Emergent class contract (`emergent_class = null` at creation).
- Mouse pointer move intent and pointer-primary routing.
- Persistent selected target, action state and movement intent.
- Server-authoritative command stream with ownership and client sequencing.
- Idempotent command replay and sequence-conflict rejection.
- Per-controller character activation for multiplayer-ready architecture.
- Pause/resume and persistent process restoration.

## Fixed
- Country inventory reconciliation now indexes NPC locality once per reconciliation instead of repeatedly scanning all NPCs for every city/block.
- Duplicate canonical-character profiles are rejected.

## Preserved
- Andrômeda Códex Master V2.0.1: READ_ONLY, zero mutations.
- Living Simulation Engine V1.0.0 baseline.
- Art pipeline remains locked until Stage 17 passes.
