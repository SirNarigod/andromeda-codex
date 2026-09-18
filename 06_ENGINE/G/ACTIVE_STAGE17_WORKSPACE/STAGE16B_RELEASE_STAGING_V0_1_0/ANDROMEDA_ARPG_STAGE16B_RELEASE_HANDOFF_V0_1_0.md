# Andrômeda Códex ARPG — Stage16B Release Handoff V0.1.0

Status: **STAGE16B CLOSED**  
Functional acceptance: **28 PASS / 0 PARTIAL_EVIDENCE**  
Final audit: **PASS**  
Checkpoint: **VALIDATED**  
Restore: **VALIDATED**  
Backup: **VALIDATED**, byte-identical to the checkpoint  
Stage17: **READY_TO_START / NOT_STARTED**

## Immutable release identity

- Checkpoint: `ANDROMEDA_ARPG_STAGE16B_AUTHORITY_GODOT_CHECKPOINT_V0_1_0.zip`
- Backup: `ANDROMEDA_ARPG_STAGE16B_AUTHORITY_GODOT_BACKUP_V0_1_0.zip`
- SHA-256 (both): `77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`
- Size: `852793` bytes
- ZIP entries: `304`
- ZIP integrity: `CLEAN`

The backup is a binary copy of the already validated checkpoint. It was not rebuilt, recompressed, or modified. Release metadata is detached.

## Protected baselines

- Stage16A V0.8.1: `03bc6b621a5ae8e0bf6542803412611855b32503154221ec7ea1b7aaf28befc4`
- Stage16A V0.8.0: `21626a3152cb37e167eee24bff9d3142c5d389a8ca2827594b34211591525a6a`
- Master V2.0.1: `6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2`
- Living Simulation Engine V1.0.0: `6f12c9db0976e234ef55cdfe23b998c07240fa8d80eb0d0c247d12bbd16ebabc`
- Stage16A tree: `724/724`, `0 missing`, `0 divergent`

## Key evidence

- Godot: Dialogue 30/30; G19 71/71 ×2; G09 51/51; G17 103/103; slot guard 32/32; save/death 194/194; NPC ownership 62/62; water TTL 19/19, 26/26, 22/22, 30/30, 28/28; combat 91/91; Ground Loot 53/53; gathering 77/77; B01 54/54; B03 357/357; B04 156/156; B11 343/343 historical presentation regression; debugger 0/0.
- Backend: full validation PASS with 0 failures; dialogue 36/36; G09 26/26; Stage16A regression 209/209.

## Historical dispositions

- B08: `HISTORICAL_PRESENTATION_REGRESSION_SUPERSEDED`. It has no acceptance-scope PASS, is presentation/client orchestration only, executed no authoritative round-trip, and retains eight historical local geometric snap failures. It was superseded by later live-authoritative gates and was not edited.
- B11: `HISTORICAL_PRESENTATION_REGRESSION`, `SUPERSEDED_AS_G16B19_AUTHORITY_BY_G19_LIVE_GATE`. B11 remains 343/343 and keeps its internal historical `g16b19_status = PARTIAL_EVIDENCE`. Final G16B-19 authority is the live `authority_vertical_slice_runtime_gate`, 71/71 ×2.

## Non-blocking limitations

- `QUEST_PROGRESSION_TRANSPORT_GAP`
- `DIALOGUE_METRIC_PROXIMITY_AUTHORITY_NOT_AVAILABLE`
- `GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE`
- `NPC_CIT001_SPATIAL_BINDING_NOT_AUTHORITATIVE`
- `CROSS_ZONE_PROMOTION_OBSERVATION_NOT_REQUIRED`
- `NON_DEV_PROFILE_SNAPSHOT_LIMITATION`
- `GROUND_LOOT_REACHABLE_AUTO_SETTLE_LIMITATION`
- `OPERATIONAL_TEST_ENVIRONMENT_CONSTRAINT`: do not run heavy backend validation simultaneously with timing-sensitive Godot gates.

## Resolved issues

- `SAVE_RELOAD_CLIENT_GLOBAL_SEQUENCE_GUARD`
- `SAVE_RELOAD_CLIENT_REJECTION_STUCK_PENDING`
- `BAG_RECOVERY_NONSPATIAL_INF_JSON`
- `G16B_09_LIVING_SYSTEMIC_INTEGRATION_GAP`
- `DIALOGUE_TRANSPORT_GAP`
- `DIALOGUE_TARGET_IDENTITY_PROJECTION_GAP`
- `G16B19_FIXTURE_ONLY_VERTICAL_SLICE` — resolved by the live authority gate.

## Command surface

Production command confirmed: `REQUEST_NPC_DIALOGUE`.

Development-only commands:

- `ADVANCE_DEVELOPMENT_WATER_TIME`
- `ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY`
- `ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC`
- `ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT`

The complete 27-command surface is defined by `ENABLED_COMMANDS` in `12_AUTHORITY_BACKEND/andromeda_authority_adapter.py`; do not reconstruct it from this summary.

## Critical source paths

Backend:

- `12_AUTHORITY_BACKEND/andromeda_authority_adapter.py`
- `12_AUTHORITY_BACKEND/authority_npc_dialogue_content.py`
- `12_AUTHORITY_BACKEND/tests/test_stage16b_authority_npc_dialogue.py`
- `12_AUTHORITY_BACKEND/run_stage16b_authority_validation.py`

Godot:

- `07_GODOT_ARPG_STAGE16B/scripts/interaction/npc_dialogue_client.gd`
- `07_GODOT_ARPG_STAGE16B/scripts/world/streaming_manager.gd`
- `07_GODOT_ARPG_STAGE16B/scripts/runtime/save_reload_client.gd`
- `07_GODOT_ARPG_STAGE16B/tests/godot/authority_npc_dialogue_runtime_gate.gd`
- `07_GODOT_ARPG_STAGE16B/tests/godot/authority_vertical_slice_runtime_gate.gd`
- `07_GODOT_ARPG_STAGE16B/tests/godot/authority_living_systemic_runtime_gate.gd`
- `07_GODOT_ARPG_STAGE16B/tests/godot/authority_save_reload_resync_runtime_gate.gd`
- `07_GODOT_ARPG_STAGE16B/tests/godot/authority_save_reload_client_slot_guard_gate.gd`

## Next permitted transition

`STAGE17_READY_TO_START = true`  
`STAGE17_EXECUTION = NOT_STARTED`

Recommended next process: **STAGE17 / ETAPA 31 — FOUNDATION TRANSITION + PLAYABLE VERTICAL SLICE PASS**. This handoff does not start Stage17.
