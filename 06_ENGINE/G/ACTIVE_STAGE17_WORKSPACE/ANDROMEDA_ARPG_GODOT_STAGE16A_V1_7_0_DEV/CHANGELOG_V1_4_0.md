# CHANGELOG V1.4.0

## Added
- Atlas Country LOD 0–6.
- Reversible geodetic/local/isometric coordinates and signed chunk grid.
- Chunk load/unload/preload/prune and one-owner entity streaming.
- Process-safe `resume_world()` rehydration.
- Dungeon Graph V2 with rooms, levels, locks, keys, secrets and room coordinates.
- Read-only Godot chunk payload contract.
- Canonical-route Atlas layer sourced from Master V2.1.
- PUBLIC / PLAYER_RUNTIME / ADMIN projection guard.

## Fixed
- 16 V1.4 defects documented in `04_REPORTS/V1_4_0/BUG_CORRECTION_LEDGER_V1_4_0.json`.

## Compatibility
- Master V2.1 remains READ_ONLY.
- Historical Living regression: 776/776 PASS.
