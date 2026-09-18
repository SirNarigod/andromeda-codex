# B07 Implementation Log V0.8.0

## Scope and authority

B07 was implemented only inside `07_GODOT_ARPG_STAGE16B`. Master V2.0.1,
Living Simulation Engine, Stage16A, `06_GODOT_LIVING_V1_5`, the Stage16A
checkpoint and the source Acceptance Matrix were treated as READ_ONLY.

Godot performs physical presentation, pointer resolution, navigation approach,
local blocker/range checks, UI projection and bridge-envelope orchestration.
The implementation contains no item grant, inventory/currency/ownership
mutation, loot roll, authoritative quantity calculation, preference persistence
or TTL authority. Server snapshots/results must identify themselves as external
authoritative projections. No backend, endpoint or listener was created.

## Files created

- `scripts/interaction/ground_loot.gd`: physical Ground Loot projection,
  deterministic settling, stable identity, stack/category presentation and
  water lifecycle projection.
- `scripts/interaction/ground_loot_pickup_client.gd`: registry, manual approach,
  0.5 m guards, blocker/path checks, anti-spam, Auto Pickup orchestration,
  preference projection, snapshot/result handling and tombstones.
- `tests/godot/B07RuntimeGate.tscn` and
  `tests/godot/b07_runtime_gate.gd`: dedicated 357-check B07 runtime gate.
- Godot-generated UID sidecars for the two new runtime scripts.
- B07 evidence logs and the four B07 handoff/acceptance records.

## Files modified

- `scenes/interaction/GroundLoot.tscn`: completed the required
  `RigidBody3D:GroundLoot` architecture with physical body collision,
  placeholder visual, pickup sensor, minimal label, feedback and safe damping/
  continuous collision detection.
- `scenes/Main.tscn`: added one `GroundLootPickupClient` orchestration node.
- `scripts/main.gd`: connected B03 pointer intents to the B07 client while
  preserving move/select rules and reporting explicit no-authority flags.
- `scripts/input/input_router.gd`: made overlapping target resolution use each
  target's stable visual pointer anchor, with a 0.25 px depth tie tolerance;
  type remains only the final tie-breaker.
- `project.godot`: updated only the Stage16B application label to B07.
- `tests/godot/b05_runtime_gate.gd` and
  `tests/godot/b06_runtime_gate.gd`: allowed the exact approved/current B07
  label so historical regression assertions remain meaningful.

No Stage16A, Master, Living or `06_GODOT_LIVING_V1_5` file was modified.

## Implemented client behavior

1. A drop can begin as dynamic physics, settle after deterministic low linear/
   angular velocity frames, then sleep/freeze without losing interaction.
2. Manual click farther than 0.5 m produces approach/navigation, not pickup.
   At `<= 0.5 m`, only a `REQUEST_PICKUP` command envelope is prepared.
3. Invalid path, blocker, unsettled/non-active state, wrong/stale/session-mismatched
   identity and `0.5001 m` all block request creation.
4. A single target can have only one in-flight request. Duplicate events and
   snapshots are sequence/session guarded; external removal creates a tombstone.
5. Inventory-full projection leaves the drop active and does not grant or
   remove anything locally.
6. Auto Pickup follows B05 ON/OFF UI state but acts only passively within range.
   Its scan snapshots and verifies movement, selection and combat/interaction
   context and cannot replace them.
7. Quantities and shared category visuals are projections. Invalid quantities
   and stale quantity snapshots are rejected.
8. Water exposure is shown for 0, 1, 899, 900 and values above 900 seconds, but
   no local clock changes authoritative state. Only external `SUNK` makes the
   drop non-active and non-pickable.

## Errors, corrections and invalidated executions

Every run below was discarded and repeated after correction.

1. `B07_PRECHECK_B03`: the first compile exposed a duplicate inherited
   `AUTHORITY` member and invalid static casts from the custom target script to
   `RigidBody3D`; B03 consequently stopped at 294/299. The constant was renamed
   and RigidBody-only fields were accessed through the actual runtime object's
   properties. B03 returned to 357/357.
2. `B07_GODOT_GATE_R1`: 345/353 plus runtime errors from setting global
   position before entering the tree and testing freed typed references. The
   spawn path now sets local position before insertion; validity is checked
   before type tests, and temporary nodes are deterministically cleaned up.
3. `B03_AFTER_CURSOR_FIX`: 351/357. Treating tiny screen deltas as depth ties
   revealed that a nearby target could win using a physics-hit point rather
   than its visual anchor. The interim result was discarded.
4. `B07_R2`: 350/353. Blocker, water-state and duplicate-snapshot fixtures did
   not isolate the intended rule. Fixtures were corrected without relaxing the
   runtime guards.
5. `B03_AFTER_ANCHOR_FIX`: 354/357. Using the root origin as the anchor fixed
   one overlap but regressed the approved physical-overlap case. It was replaced
   with `pointer_world_position()`, preserving the target's authored anchor.
6. `B07_R3`: 354/357. The overlap fixture and water settling assertion sampled
   before the required physics frames. The fixture used the precise authored
   anchors and the gate waits for two physics frames after presenter state.
7. `B07_R4` and the affected B03 regression then passed, both with empty stderr.
8. `B07_EDITOR_BRIDGE_R1` produced 357/357 functionally but exposed four
   GDScript warnings: two incompatible ternaries and two unnecessary awaits.
   The run was invalidated, the values/types were made explicit, and the awaits
   were removed. Post-fix headless and Editor Bridge were restarted and clean.
9. Early launcher-only commands that did not retain the actual Godot process
   exit code were not counted; final headless runs use `Start-Process -Wait`
   with explicit stdout/stderr files.
10. The first B07 stress invocation wrote 20/20 but did not return a usable
    process handle/exit code. It was not counted. A fresh run retained the
    handle and closed 20/20, exit 0, stderr empty.

## Final test evidence

- B07 headless: 357/357, exit 0, stderr empty.
- B07 Editor Bridge: 357/357, debugger 0 errors / 0 warnings, controlled stop,
  `finalErrors: []`.
- `Main.tscn` Editor Bridge: PASS after five seconds of observation, debugger
  clean, controlled stop, `finalErrors: []`.
- B01: 54/54; B02: 90/90; B03: 357/357; B04: 156/156;
  B05: 210/210; B06: 265/265. Each final run: exit 0, stderr empty.
- Stage16A: 209/209, `Ran 209 tests in 261.634s`, `OK`, process exit 0.
- Stage16A stress: 20/20, exit 0, stderr empty.
- `06_GODOT_LIVING_V1_5`: historical runtime marker PASS, exit 0, stderr empty.
- Baseline: 724/724, missing 0, mismatch 0; Living files 4/4.
- Backend: `127.0.0.1:8000` NOT_AVAILABLE, zero listeners.

## Integrity hashes

- Master V2.0.1:
  `6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2`
- Stage16A checkpoint:
  `21626A3152CB37E167EEE24BFF9D3142C5D389A8CA2827594B34211591525A6A`
- Source Acceptance Matrix:
  `9335E6C7A5FAA25F97991204787D2C77485592419AAA1F51641C01E31317454C`

## Acceptance result

PASS remains unchanged for G16B-01, 02, 07, 10, 11, 12, 13 and 15.
G16B-05 advances only from NOT_EXECUTED to PARTIAL_EVIDENCE. G16B-04, 06 and
27 remain PARTIAL_EVIDENCE. No gate was promoted on mock/local projection in
place of missing live authority.

B07 is closed in its applicable local scope with partial authoritative
evidence. B08 was not started. No final Stage16 backup was created.
