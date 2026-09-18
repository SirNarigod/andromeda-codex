# Stage17 S17-B1/B2 Implementation Log — V0.1.0 DEV

Created at: `2026-08-28T00:22:27.5521144-03:00`

## Result

- `S17_B1_AUTHORITY_SPACE_CONTRACT = PASS` — 36/36.
- `S17_B2_AUTHORITATIVE_CLICK_TO_MOVE = PASS` — 73/73 headless and 73/73 through the real Editor Bridge.
- Stage16B remains closed and read-only.
- No Stage17 backup was created.
- No later Stage17 block was opened.

## Read-only backend findings

`MOVE_TO_POINT` consumes an absolute territorial destination in `iso_x_m/iso_y_m`. The adapter computes only a bounded step duration and delegates collision, movement factor, stamina, time, chunk and final motion state to the protected Stage16A core. Position is persisted in `v15_motion_state` and returned in command results and authoritative snapshots.

The Godot world is a local presentation frame in X/Z metres. The valid relationship was already proved in sealed Stage16B evidence: `+X ↔ +iso_x_m`, `+Z ↔ +iso_y_m`, scale 1:1. Stage17 now obtains the translation anchor dynamically from the first real snapshot and the actual Player node.

## Files created

- `13_GODOT_ARPG_STAGE17/scripts/runtime/authority_space_mapper.gd`
- `13_GODOT_ARPG_STAGE17/scripts/runtime/movement_authority_client.gd`
- `13_GODOT_ARPG_STAGE17/tests/godot/S17B1CoordinateMappingGate.tscn`
- `13_GODOT_ARPG_STAGE17/tests/godot/s17b1_coordinate_mapping_gate.gd`
- `13_GODOT_ARPG_STAGE17/tests/godot/S17B2MovementAuthorityGate.tscn`
- `13_GODOT_ARPG_STAGE17/tests/godot/s17b2_movement_authority_gate.gd`
- `13_GODOT_ARPG_STAGE17/tests/godot/S17B2MovementPerformanceSmoke.tscn`
- `13_GODOT_ARPG_STAGE17/tests/godot/s17b2_movement_performance_smoke.gd`

Godot generated `.uid` and editor cache files while importing the new scripts. Those are derivative editor artifacts, not authority or gameplay data.

## Files modified

- `13_GODOT_ARPG_STAGE17/scenes/Main.tscn` — adds the one mapper and movement client nodes.
- `13_GODOT_ARPG_STAGE17/scripts/main.gd` — binds both clients; ground movement uses authoritative submission; Ground Loot approach remains explicit presentation approach.
- `13_GODOT_ARPG_STAGE17/scripts/actors/player_controller.gd` — authoritative ground submission, local prediction, cancellation and smooth reconciliation; adds explicit local presentation-approach API.
- `13_GODOT_ARPG_STAGE17/scripts/interaction/combat_authority_client.gd`
- `13_GODOT_ARPG_STAGE17/scripts/interaction/gathering_client.gd`
- `13_GODOT_ARPG_STAGE17/scripts/interaction/vendor_client.gd`
- `13_GODOT_ARPG_STAGE17/scripts/interaction/dropped_bag_client.gd`
- `13_GODOT_ARPG_STAGE17/scripts/quest/quest_client.gd`

The five interaction clients were changed only to call the explicit presentation-approach API. This prevents false territorial movement until authoritative spatial binding exists.

## Submission and correlation

- Exactly one `MOVE_TO_POINT` is sent per explicit ground destination.
- Left and right ground clicks share the same route.
- Every destination receives a fresh `command_ref`.
- Same `command_ref` plus same payload is replay-safe; the authority journal suppresses a second world mutation.
- A monotonically increasing local submission serial identifies the latest destination.
- A result for an older destination is observed and discarded; it cannot resurrect the old navigation target.
- Raw bridge command results are filtered by `command_ref`, preventing unrelated traversal results from being treated as movement confirmation.

## Reconciliation policies

- **Accepted:** convert the real result/snapshot position back to local space and converge through `NavigationAgent3D`.
- **Rejected:** cancel local navigation and reconcile to the last valid authoritative position.
- **Reconnect:** stop local movement, clear active destination intent, submit no movement while disconnected, wait for a fresh snapshot, rebuild the anchor if necessary, then reconcile. Idempotent bridge retries remain safe.
- **Transient SYNCING:** session-bound and anchored movement is allowed because ordinary authoritative snapshots briefly place the bridge in SYNCING; DISCONNECTED, CONNECTING and RECONNECT_WAIT remain blocked.

## Live movement evidence

Final accepted B2 run (`S17_B2_ACCEPTANCE_RETEST_SETTLED.log`):

- D1 short: local `(-5.75, 0, 0)` → authority `(137109.221342601, -1336957.03593386)`; final visual error `0.15555477 m`.
- D2 medium: local `(-7, 0, 2)` → authority `(137107.971342601, -1336955.03593386)`; final visual error `0.11434078 m`.
- D3 opposite: local `(-8, 0, -1.5)` → authority `(137106.971342601, -1336958.53593386)`; final visual error `0.08254158 m`.
- Rapid A/B: A arrived after B and was ignored as stale; B remained the active destination.
- Deliberate invalid mode `FLY`: rejected; local movement cancelled and authoritative reconciliation applied.
- Disconnect/reconnect: one reconnect, fresh snapshot, no old destination replayed.
- Metrics: submitted 6, accepted-result signals 4, rejected 1, stale ignored 1, reconnects 1, pending 0.

The larger intermediate error values in the evidence are the distance to the new authority destination at the instant confirmation arrived. They were corrected by smooth navigation; the final destination errors were all at or below `0.16 m`.

## Performance smoke

60.001659 seconds, 8,693 frames:

- observed FPS: `144.8793274`;
- average frame time: `6.90229495 ms`;
- p95 frame time: `7.274 ms`;
- max frame time: `22.265 ms`;
- MOVE_TO_POINT count: 6;
- authority accepts: 6;
- rejects: 0;
- reconciliations: 31;
- maximum observed reconciliation error: `1.16042638 m`, converged without snap;
- node count: 804 → 804;
- no numeric performance threshold was invented.

## Final tests

- S17-B1 headless: 36/36 PASS.
- S17-B2 headless: 73/73 PASS.
- S17-B2 Editor Bridge: 73/73 PASS, debugger 0 errors / 0 warnings; gate exited normally.
- Main.tscn Editor Bridge smoke: PASS; connection/snapshot ready, normal movement route active, camera follow preserved; controlled stop `finalErrors: []`.
- S17-00: 22/22 PASS.
- S17-A live: 17/17 PASS.
- S17-A offline failure path: 9/9 PASS. Accumulated S17-A: 26/26.
- B01: 54/54 PASS.
- G19: 71/71 PASS on a clean isolated Stage17 runtime.
- Combat: 91/91 PASS after the spatial-binding boundary correction.
- Ground Loot: 53/53 PASS.
- Gathering: 77/77 PASS.
- Performance: 12/12 PASS.

The Windows headless executable emitted the known external platform message `Failed to read the root certificate store`. It is preserved in the logs and was not counted as a debugger-clean Godot run. The real Editor Bridge runs reported zero debugger errors and zero warnings.

## Runtime and protected baseline

- Backend shut down through the launcher-owned PID 15032.
- Listener `127.0.0.1:8000`: none after shutdown.
- Pre-existing Godot editor PID 11316: preserved.
- Stage17 runtime evidence and invalidated worlds are preserved under `STAGE17_RUNTIME_STATE`; no broad deletion was used.
- Stage16B checkpoint SHA-256: `77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`.
- Stage16B backup SHA-256: `77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`.

## Pending work / next block

- `S17_INTERACTION_APPROACH_AUTHORITY_MIGRATION_PENDING` (P1): requires authoritative target spatial bindings before NPC/resource/loot/vendor/quest approaches can safely move the territorial avatar.
- `S17_COMBAT_CHASE_AUTHORITY_MIGRATION_PENDING` (P1): design chase updates without per-frame command spam after spatial binding exists.

Recommended next block: a narrow Stage17 spatial-binding contract for interaction targets, followed by migration of one representative approach path. Do not open water, dialogue, loot behavior, save or death in that same change.

