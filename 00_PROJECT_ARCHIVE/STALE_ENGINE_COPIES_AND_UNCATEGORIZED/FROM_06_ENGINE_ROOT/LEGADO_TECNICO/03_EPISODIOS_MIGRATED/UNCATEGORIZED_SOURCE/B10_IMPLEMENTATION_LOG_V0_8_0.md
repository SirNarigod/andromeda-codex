# Stage16B B10 Implementation Log V0.8.0

Captured: 2026-08-21T20:16:54.5399532-03:00

Final status: `PASS_APPLICABLE_B10_SCOPE_WITH_PARTIAL_AUTHORITATIVE_EVIDENCE`.

## Scope and authority

B10 was implemented only in `07_GODOT_ARPG_STAGE16B`. The required Stage16A manifest, acceptance matrix, pre-Godot contract, integrated engine, vertical-slice assembly, water/Bag survival, Ground Loot, save/recovery contracts, and B07/B09 client implementations were read before editing.

Godot owns client orchestration and presentation only. It can prepare save/reload/recovery/respawn intents, gate local input, present externally confirmed death and water states, and reconstruct scenes/UI from accepted snapshots. It cannot decide or persist death, save success, Bag drop/contents, retained items, ownership, TTL expiry/SUNK, recovery, respawn point, inventory, economy, quest, XP, or canon.

No backend, HTTP endpoint, authoritative timer, local save store, or canonical mutation was added. `127.0.0.1:8000` remained unavailable with zero listeners.

## Implementation

### Save, autosave, reload and resync

`AndromedaSaveReloadClient` prepares `REQUEST_SAVE`, `REQUEST_AUTOSAVE`, and `REQUEST_RELOAD_RESYNC` envelopes through the existing B01 bridge/session contract. It tracks pending requests only for anti-duplication and presentation. External results are checked for session, sequence, duplication, shape and request identity.

Restore is coordinated across Player transform/loadout/HP/protection/stamina presentation, world/streaming/resource-node projection, Ground Loot, Auto Pickup preference, B09 inventory/Bag/economy/quest state, DroppedBag registry and death/recovery state. Reconnect moves the client to `RESYNC_REQUIRED`; `READY` is restored only after a valid external snapshot is fully projected. No local file is used as a substitute for authoritative persistence.

### Death and respawn

`AndromedaDeathRespawnClient` accepts external death, water-exhaustion and respawn projections. It blocks world actions without pausing `SceneTree`, clears stale client targets, presents equipment/protected-item retention, and only repositions the Player from an accepted external respawn position. It does not calculate death, grace windows, lost items or safe waypoints.

### DroppedBag

`DroppedBag.tscn` remains semantically distinct from `GroundLoot.tscn`. The root is a `RigidBody3D` on the DroppedBag layer and exposes collision, placeholder visual, recovery sensor, interaction/float anchors, owner hint and water presenter. The projection preserves stable `bag_ref`, `target_ref`, `original_owner_ref`, origin/context, contents summary when supplied, LAND/WATER, recoverability, water exposure, current holder/recovery state, and ACTIVE/PRELOAD/SYSTEMIC identity.

Land Bags project no expiry and are never removed by a local timer. Water Bags display external exposure and `FLOATING`/`SUNK` states; the 1800-second value is metadata only. Ground Loot keeps the B07 900-second projection and is reconstructed without resetting exposure. Neither timer is authoritative in Godot.

### Recovery and NPC ownership

Manual Bag interaction performs physical distance, blocker and path checks, approaches when needed, emits `REQUEST_BAG_RECOVERY`, and waits for an external result. Anti-spam is client bookkeeping, not result authority. NPC-owned Bags preserve original property/context through Player recovery projection. Foreign NPC proximity/movement never triggers automatic theft or recovery.

### UI and input

The B10 overlay extends the white/off-white, rounded, gray/orange B05 family. Death, reload, save failure, recovery and respawn states remain legible while world actions are gated. The `InputRouter`, HUD and Main orchestration were evolved additively; no whole-world pause, ghost action, wheel regression, target swap or stale interaction survived the tests.

## Files created

- `scripts/interaction/dropped_bag.gd` and generated `.uid`: DroppedBag projection/presentation.
- `scripts/interaction/dropped_bag_client.gd` and generated `.uid`: registry, approach/recovery envelope, streaming and snapshot orchestration.
- `scripts/runtime/death_respawn_client.gd` and generated `.uid`: external death/exhaustion/respawn projection and input gate.
- `scripts/runtime/save_reload_client.gd` and generated `.uid`: save/autosave/reload intents and coordinated restore.
- `scripts/ui/death_recovery_overlay.gd` and generated `.uid`: B10 status presentation.
- `scenes/ui/DeathRecoveryOverlay.tscn`: minimal B10 overlay scene.
- `tests/godot/B10RuntimeGate.tscn` and `tests/godot/b10_runtime_gate.gd`: dedicated 453-check gate.
- B10 acceptance, implementation, debugger, runtime, integrity, invalidated-run and README records.

## Files modified

- `scenes/interaction/DroppedBag.tscn`: completed distinct Bag component architecture and removed fixture placeholder identity defaults.
- `scripts/input/input_router.gd`: death/reload input gating and B10 orchestration routing.
- `scripts/interaction/interaction_target.gd`: DroppedBag target kind compatibility.
- `scenes/ui/HUD.tscn`, `scripts/ui/hud_controller.gd`: additive B10 overlay/presentation binding.
- `scenes/Main.tscn`, `scripts/main.gd`: additive B10 clients, DroppedBag interaction, restore/death/respawn coordination.
- `project.godot`: B10 project label; existing main scene, bridge endpoint and input settings preserved.
- `tests/godot/b05_runtime_gate.gd` through `b09_runtime_gate.gd`: additive B10 project-label compatibility; B09 retains the same check count and conditionally accepts the later B10 components.

## Errors, corrections and retests

1. The first headless run stopped on parser/type errors in the DroppedBag body access and an impossible typed assertion. Dynamic presentation property access and a script-path assertion fixed the compile boundary.
2. The second run produced 211/252 plus 41 cascades because scene placeholder identity conflicted with immutable external identity. Empty scene defaults allow the first external projection to establish identity without weakening immutability.
3. The third run produced 452/453 because physics moved a blocker fixture before the final measurement. The test fixture now restores its measured position immediately before evaluation; runtime blocker/range policy is unchanged.
4. A complete 453/453 headless run was superseded when the first Editor Bridge run exposed nine warnings. Shadowing names, unnecessary awaits and nullable inference were corrected.
5. B10 was then rerun headless (453/453, exit 0, stderr empty), through Editor Bridge (453/453), and with `Main.tscn`; debugger and controlled stops were clean.
6. The first regression orchestration shell was rejected before any process started because it attempted to clean computed temp paths. A fresh GUID evidence directory with no deletion was used instead.

No discovered warning/error was ignored. The complete invalidation ledger is in `B10_INVALIDATED_RUNS.log`.

## Final test results

- B10 headless: 453/453 PASS; exit 0; stderr empty.
- B10 Editor Bridge: 453/453 PASS; debugger 0 errors / 0 warnings; `finalErrors: []`.
- `Main.tscn` Editor Bridge: PASS; six-second observation; `finalErrors: []`.
- B01–B09: 54/54, 90/90, 357/357, 156/156, 210/210, 265/265, 357/357, 475/475, 379/379; every process exit 0 and stderr empty.
- Stage16A: 209/209 PASS, `Ran 209 tests in 253.877s`, exit 0.
- Stage16A stress: 20/20 PASS, exit 0, stderr empty.
- `06_GODOT_LIVING_V1_5`: runtime marker PASS, exit 0, stderr empty.
- Stage16A checkpoint: 724/724 byte matches, missing 0, mismatch 0.
- Living protected files: 4/4, missing 0, mismatch 0.

## Acceptance Matrix

PASS remains unchanged: G16B-01, 02, 07, 10, 11, 12, 13, 15.

G16B-17, G16B-18 and G16B-28 move from `NOT_EXECUTED` to `PARTIAL_EVIDENCE`. G16B-25, G16B-26 and G16B-27 receive additional evidence but remain partial. G16B-19 remains `NOT_EXECUTED` for B11. All other prior partial statuses remain honest; fixtures/projections did not promote any gate.

## Blockers and watch items

There is no local blocker for the applicable B10 scope.

Watch items are the unavailable live authoritative round-trips for save/reload persistence, death policy, Bag contents/ownership/recovery, Ground Loot and Bag TTL transitions, respawn point and NPC-owned Bag recovery. G16B-19 and the complete 28-gate/vertical-slice decision remain B11 scope.

B11 was not started. No final Stage16 restore/checkpoint or backup was executed or created.

