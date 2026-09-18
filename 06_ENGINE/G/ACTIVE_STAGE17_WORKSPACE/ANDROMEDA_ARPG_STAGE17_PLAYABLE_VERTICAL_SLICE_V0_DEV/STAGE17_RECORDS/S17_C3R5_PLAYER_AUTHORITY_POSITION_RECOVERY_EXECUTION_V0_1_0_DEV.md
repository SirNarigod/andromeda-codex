# S17-C3R5 — Controlled Player Authority Position Recovery

Created at: `2026-08-29T15:58:58.7670295Z`

## Disposition

- Recovery execution: `PASS`
- `--apply` execution count: `1`
- `PLAYER_AUTHORITY_POSITION_RECOVERED`: `true`
- `MOVEMENT_OWNER_CONSISTENT`: `true`
- `STAGE17_CURRENT_WORLD_RESUMABLE`: `true`
- C3R5 acceptance closure: `FAIL_VALIDATION_GATE_C2_BLOCKED_SETUP`

The explicitly authorized mutation completed successfully and was not repeated. C3R5 cannot be closed as PASS because the post-recovery C2 smoke ended at `86/91`: its normal TREE and ORE paths passed, but the local NavigationAgent rejected the negative blocker setup destination before a MOVE_TO_POINT command could be submitted. Correcting that gate requires a Stage17 source change, which was prohibited in this execution-only round.

## Immutable inputs and guards

- Recovery tool: `STAGE17_TOOLS/recovery/repair_stage17_player_position.py`
- Tool SHA-256: `a33b0b7a50794ab58fa382becb52ffcc6eef52f0a718b09096bc44e09b039854`
- Canonical placement manifest file SHA-256: `88ab7eaff058120692c1412cc28f0c5f8b6a5accd8eebcb0ebaa55b4a85f71ad`
- Canonical manifest content hash: `f0c79305c4fe6adad277b4a026311124c5ce865db399e327750e55c2d660ec92`
- World guard: `PASS`
- Stored/manifest world: `rt:world:bd0f78f5-7018-4cc6-8f47-34f8f2875e47`
- Anchor kind: `SERVER_AUTHORITATIVE_PLAYER_MOTION_SNAPSHOT_DEV_AUTHORING_ANCHOR`
- Anchor: `(137108.156775035, -1336956.95467694, 0.0)`
- Profile resolved dynamically: `rt:player_profile:50db4148-ac36-403c-9d96-d2ccf6f90ea6`
- Avatar resolved dynamically: `PLY-455FEDE6124F42819BDA63A8E82355F4`
- Anchor-player provenance: `MATCH`
- Zone/block validation: `VALIDATED`

The dry run returned `DRY_RUN_VALIDATED_MANIFEST_AND_WORLD_GUARD_ONLY`, exit 0. The live DB SHA-256 remained `481d0eea38071ce3bdd93c580c93e6b44582fa216c1a99ae55812f3c747764e1`, with no WAL/SHM created.

## Fresh pre-apply backup

Path:

`STAGE17_RUNTIME_STATE/_archive_pre_s17_c3r5_player_recovery_20260829T154552Z_authority/stage17_world.sqlite`

- SHA-256: `481d0eea38071ce3bdd93c580c93e6b44582fa216c1a99ae55812f3c747764e1`
- Size: `15077376` bytes
- Byte-identical to the post-R4B live DB at copy time: `true`
- WAL/SHM at copy time: absent
- Opened read-only for validation
- Migration marker: `S17_GATHERING_NODE_MUTABLE_CAPACITY_MIGRATION_V1 / COMPLETE`
- Gathering nodes: `312`
- Allowed mutable drift: `0`
- Structural drift: `0`
- Unsupported drift: `0`
- Resource placements: `2` (`TREE` and `ORE` refs intact)
- Pre-apply Player distance from anchor: `2194278.2684396296 m`
- `movement.verify`: `PASS`, proven by byte identity with the accepted R4B final DB record

## Single authorized apply

Command executed exactly once:

`repair_stage17_player_position.py --apply`

- Exit code: `0`
- Final status: `RECOVERY_APPLIED`
- Mutation applied: `true`
- `movement.verify` before: `PASS`, `826` states, zero failures
- Before position: `(102897.27635042791, 857054.6075093196, 430.0)`
- Before distance: `2194278.2684396296 m`
- Before chunk: `CHK-+000165-+000130`
- `sync_to_geodetic`: `PASS` (the tool would abort on any non-PASS result)
- Expected/post-sync chunk: `CHK--000208--000255`
- Ownership transfer: required and completed for the resolved avatar only; before ownership differed and final ownership equals the computed chunk with `movement.verify = PASS`
- `movement.verify` after: `PASS`, `826` states, zero failures
- Immediate persisted position: `(137108.15677503493, -1336956.95467694, 0.0)`
- Immediate 3D error from anchor: `5.820766091346741e-11 m`
- Immediate ownership chunk: `CHK--000208--000255`
- Immediate post-apply DB SHA-256: `0c1c23070a3ffb0b95c85314f4d17a8771c253de093a3207e890292a4ba12264`

No second `--apply` execution occurred.

## Restart and persistence

- Launcher state: `READY`
- Backend PID: `9288`
- Observed startup: `7243.023 ms`
- `/health`: `PASS`
- `stage16a_health`: `PASS`
- Health failures: `[]`
- Session bind: `PASS`
- Snapshot: `PASS`, `server_authoritative = true`
- Snapshot immediately after restart preserved `(137108.15677503493, -1336956.95467694, 0.0)`
- Controlled shutdown: `STAGE17_AUTHORITY: OFF pid=9288 listener_8000=NONE`

The final post-smoke position is `(137112.656875171, -1336966.95467695, 0.0)`, `10.965897201308588 m` from the anchor and still in `CHK--000208--000255`. This local-area movement is from the permitted B2/C2 smokes, not a second recovery.

## Gathering and placement integrity

- Migration marker: `COMPLETE`
- Gathering nodes: `312`
- Allowed mutable capacity drift: `0`
- Structural drift: `0`
- Unsupported drift: `0`
- Country-scale state: self-consistent
- Migration dry-run status: `ALREADY_APPLIED`
- Dry-run main DB unchanged: `true`
- Placement count: `2`
- ORE: `RESOURCE-PLACEMENT-S17-3BDA3343A505268017CE` → `GTH-34AC1BC54C33917F0553`
- TREE: `RESOURCE-PLACEMENT-S17-DCC60BB7E7C256C1BF9E` → `GTH-CA3D9A47934BD64A24B4`
- Both placements retain canonical manifest hash `f0c79305c4fe6adad277b4a026311124c5ce865db399e327750e55c2d660ec92`.

## Allowed smoke results

- S17-B1: `36/36 PASS`, exit 0, clean rerun
- S17-B2: `73/73 PASS`, exit 0
- S17-C1: `64/64 PASS`, exit 0; TREE/ORE positions were locally reasonable and authority-mapped
- S17-C2: `86/91 FAIL`, exit 1
  - Normal TREE: PASS, server distance `1.07999942884507 m`, real drop `DROP-S16A-941DF422BD02B197AB34`
  - Normal ORE: PASS, server distance `1.08000001266765 m`, real drop `DROP-S16A-D296B96DE93CDFBD3273`
  - Boundary and outside-range authority checks passed
  - Five blocker checks failed because `BLOCKED` setup did not submit an authority move; subsequent gather was correctly rejected as `RESOURCE_GATHER_OUT_OF_RANGE` at `8.55872083559822 m`

Combat, C0, G19 and GroundLoot were not run in C3R5. Combat/C0/G19 remain unsafe while `S17_G19_COMMON_TARGET_UNBOUNDED_SELECTION_GAP` is open. GroundLoot remains preserved at historical `51/53`, including the valid null-Variant fix and the open auto-settle limitation.

## Historical limbo evidence

`HISTORICAL_GODOT_LIMBO_EVENT` is preserved as reported: during an earlier Codex test Godot kept attempting to connect, the author manually moved the Player, the Player fell into limbo, and Godot was closed. Its authoritative impact remains `UNPROVEN`. The large displacement is not attributed to that event; direct evidence exists of far COMMON-target pursuit.

## Source and protected integrity

- Stage17 source files modified during C3R5: `0`
- Runtime mutations: only the explicitly authorized Player/chunk recovery plus normal backend/gate runtime state
- Stage16B checkpoint SHA-256: `77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`
- Stage16B backup SHA-256: `77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`
- Stage16B status: `CLOSED / READ_ONLY`

## Housekeeping and open gaps

- Backend: OFF
- Listener 8000: NONE
- Godot headless runners: NONE
- Pre-existing editor: not running at C3R5 start; no editor process was killed
- Fresh recovery backup: PRESERVED
- Runtime DB/WAL/SHM: PRESERVED as a consistent SQLite set after normal gates

Open gaps:

1. `S17_C3R5_C2_BLOCKED_SETUP_NAV_DESTINATION_GAP` — the C2 negative blocker setup destination is not accepted by local navigation in the recovered playable-area mapping. Minimum next action: a source-authorized audit/fix of the test setup destination without weakening server LOS authority.
2. `S17_G19_COMMON_TARGET_UNBOUNDED_SELECTION_GAP` — COMMON target remains approximately 2195 km away.
3. `GROUND_LOOT_REACHABLE_AUTO_SETTLE_LIMITATION` — still open.

C3R6 must not start until the C2 validation gap is resolved and C3R5 can be rerun without another recovery mutation.
