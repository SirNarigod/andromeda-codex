# Stage 16B / B09 — Implementation Log V0.8.0

Captured: `2026-08-21T18:55:56.0006967-03:00`

Status: `PASS_APPLICABLE_B09_SCOPE_WITH_PARTIAL_AUTHORITATIVE_EVIDENCE`

## Scope and protected authority

B09 implements only the Godot client layer for vendor, living inventory/Bag presentation, and the applicable quest loop. It does not implement B10 or B11.

Before editing, the current B01–B08 records and the following protected contracts were read again:

- `ARPG_GODOT_HANDOFF_MANIFEST_V0_8_0.json`
- `ARPG_STAGE16B_GODOT_ACCEPTANCE_MATRIX_V0_8_0.json`
- `ARPG_STAGE16A_PRE_GODOT_CONTRACT_V0_8_0.json`
- Stage13 economy/vendor contracts and runtime tests
- Stage12 quest contracts and runtime tests
- Stage16A inventory, Bag, quick-slot, Ground Loot, session, stale-event and authority contracts

The source Acceptance Matrix was not edited. Master V2.0.1, Living, Stage15 history, Stage16A, `06_GODOT_LIVING_V1_5`, and B01–B08 remain protected.

Godot remains presentation, input, scenes, local physics/navigation, UI, external state projection, and client orchestration only. The new scripts do not determine price, wallet balance, inventory mutation, Bag ownership/content, stack authority, capacity, equip authorization, quest progress/completion/reward, XP, economy, or canonical state.

## Vendor implementation

`VendorNPC.tscn` evolves an NPC/interactable into a physical vendor placeholder while preserving hover, deterministic `target_ref`, right-click/E contextual approach, and real interaction range.

`vendor_target.gd` adds vendor presentation metadata without changing NPC identity into another gameplay type. The Stage13 service reference `SHOP-S13-91CDF9F934810A65B2` and `POI-002` are preserved; no merchant biography, price, stock authority, or new canonical identity was invented.

`vendor_client.gd` implements the client state machine:

`SELECT / APPROACH / OPEN UI -> REQUEST_QUOTE -> PROJECT EXTERNAL QUOTE -> EXPLICIT USER CONFIRMATION -> EXECUTE_TRADE -> PROJECT EXTERNAL RESULT`

Important guarantees:

- click, approach, opening the panel, item selection, and quote never execute a purchase;
- quote and execute use separate envelopes;
- execute requires a current externally projected quote and explicit confirmation;
- vendor, item, BUY/SELL operation, quantity, quote reference, session, and sequence are checked;
- stale, duplicate, wrong-session, wrong-vendor, wrong-item, wrong-operation, malformed, and replaced quotes are rejected;
- reconnect revokes sensitive state until external stock/inventory/quest resync;
- accepted/rejected trade results are presentation only;
- no wallet, inventory, ownership, stack, capacity, or currency field is mutated locally;
- BUY and SELL preserve effective-container routing supplied by external state;
- retry uses the same client request identity rather than creating speculative grants.

## Inventory and Bag implementation

`inventory_client.gd` projects externally supplied inventory state:

- reduced base inventory;
- `NO_BAG` and `BAG_EQUIPPED`;
- Bag container and externally supplied contents/capacity/load;
- equipment;
- exactly two weapon quick-slots with exactly one active;
- protected/critical item presentation when supplied;
- effective carry routing from the external snapshot.

Equip intents are envelopes only. Bag unequip is reported as `NOT_CONTRACTED` rather than invented. No item is moved between base inventory, Bag, equipment, or quick-slots by local authority. No death/drop/recovery/timer/save logic exists in B09.

The B05 inventory shell was evolved additively. `I` opens/closes it, it is not permanent HUD, and wheel inside the menu scrolls without weapon swap or zoom. Its off-white, rounded, gray and light-orange family remains shared with the existing HUD.

## Quest implementation

`quest_client.gd` accepts only external quest offers, snapshots, objective updates, choice projections, completion and reward projections guarded by session and ordered sequence.

Only existing Stage12 quest IDs are recognized:

- `QST-S12-VARGA-MEDIATION`
- `QST-S12-BRIDGE-CONTINUITY`
- `QST-S12-WORKSHOP-CIRCUIT`
- `QST-S12-FRONTIER-SUPPLY`
- `QST-S12-VARGA-ORIENTATION`

Godot can emit accept/interaction/choice intents and present externally confirmed states. It never counts kills, pickups, gathering, or vendor actions to complete objectives; never completes a quest locally; never grants reward/XP; and never creates narrative or canon. Decline remains `NOT_CONTRACTED` where the read contracts do not define a matching command.

`QuestPanel.tscn` and `quest_panel.gd` provide a small, rounded, world-first projection. Quest feedback uses the existing semantic priority and maximum-three-feedback policy.

## Input modality and integrations

`HUD.tscn`, `hud_controller.gd`, `Inventory.tscn`, `inventory_shell.gd`, `input_router.gd`, `Main.tscn`, and `main.gd` bind the three new client projections and modal panels.

When vendor/inventory/quest UI consumes input:

- clicks do not reach the world behind the panel;
- wheel is UI scroll only;
- weapon swapping and zoom are suppressed;
- Space/E do not leak to world actions;
- ESC closes only the applicable layer;
- the SceneTree is never globally paused;
- closing UI does not mutate gameplay state.

B03 deterministic targeting, B05 quick-slots and dialogue, B06 feedback priority/target stability, B07 Ground Loot/Auto Pickup, and B08 gathering remain intact. Vendor or quest presentation does not create a direct physical-output-to-inventory path.

## Files created

- `scripts/interaction/vendor_target.gd` and Godot `.uid`
- `scripts/interaction/vendor_client.gd` and Godot `.uid`
- `scripts/inventory/inventory_client.gd` and Godot `.uid`
- `scripts/quest/quest_client.gd` and Godot `.uid`
- `scripts/ui/vendor_panel.gd` and Godot `.uid`
- `scripts/ui/quest_panel.gd` and Godot `.uid`
- `scenes/actors/VendorNPC.tscn`
- `scenes/ui/Vendor.tscn`
- `scenes/ui/QuestPanel.tscn`
- `tests/godot/B09RuntimeGate.tscn`
- `tests/godot/b09_runtime_gate.gd`
- `B09_INVALIDATED_RUNS.log`
- B09 evidence and handoff records listed in `B09_ACCEPTANCE_RECORD_V0_8_0.json`

## Files modified

- `project.godot`: B09 project label and preserved input/runtime configuration.
- `scenes/Main.tscn`: additive VendorClient, InventoryClient, QuestClient and placeholder vendor integration.
- `scripts/main.gd`: B09 binding and contextual orchestration only.
- `scripts/input/input_router.gd`: modal-consumption routing without gameplay authority.
- `scenes/ui/HUD.tscn` and `scripts/ui/hud_controller.gd`: bind vendor, inventory and quest panels plus priority-limited feedback.
- `scenes/ui/Inventory.tscn` and `scripts/ui/inventory_shell.gd`: external base/Bag/equipment/stack projection and UI scrolling.
- `tests/godot/b05_runtime_gate.gd`, `b06_runtime_gate.gd`, `b07_runtime_gate.gd`, and `b08_runtime_gate.gd`: exact B09 project-label compatibility only, followed by full regressions.

No historical production authority was rewritten.

## Errors, corrections, and invalidated evidence

Every incomplete or faulty run was discarded:

1. Post-B09 B08 regression exposed a `quest_client.gd` static cast from a custom target script to `CollisionObject3D`; RID access was changed to dynamic capability checks, then B08 and affected gates were restarted.
2. B09 R1 reached 377/379. Reconnect stock reconstruction did not preserve the typed `Array[Dictionary]`, and two stamina regression assertions used non-contract labels. Typed reconstruction and the real B05 `CIRCLE_RADIAL` / `SOFT_YELLOW` contracts fixed both checks; B09 was restarted.
3. A combined B02–B04 capture did not retain independent complete exit evidence; it was discarded and each gate was rerun separately.
4. The first integrity script used unavailable Windows PowerShell `Convert.ToHexString`; it was discarded and repeated with `BitConverter`, literal paths, and terminating error handling.
5. Direct GUI-style Godot invocation did not retain complete process evidence; discarded.
6. Final recapture R1 used unavailable `ProcessStartInfo.ArgumentList`; no valid gate was started; discarded.
7. Final recapture R2 used a non-contract `--scene` switch and left an incomplete child process; only the exact spawned process was stopped, the existing editor was preserved, and the run was discarded.
8. Final recapture R3 reached 379/379 but retained the 240-second Editor Bridge linger and had no exit code inside the capture window; discarded and repeated with the headless `--gate-success-linger=0` user argument.
9. The first final source-matrix hash recheck targeted a nonexistent `01_CONTRACTS` path and returned no hash. It was discarded; the protected matrix was located under `02_CONTRACTS/ARPG_STAGE16A`, then rechecked with terminating error handling and matched the expected SHA-256 exactly.

The accepted recapture is 379/379, exit 0, `stderr_bytes=0`.

## Final tests

- B09 headless: 379/379 PASS, exit 0, stderr empty.
- B09 Editor Bridge: 379/379 PASS.
- `Main.tscn` Editor Bridge: PASS.
- Final debugger: 0 errors / 0 warnings.
- Controlled stop: `finalErrors: []`.
- B01: 54/54 PASS.
- B02: 90/90 PASS.
- B03: 357/357 PASS.
- B04: 156/156 PASS.
- B05: 210/210 PASS.
- B06: 265/265 PASS.
- B07: 357/357 PASS.
- B08: 475/475 PASS.
- Stage16A: 209/209 PASS, exit 0.
- Stage16A stress: 20/20 PASS, exit 0.
- `06_GODOT_LIVING_V1_5` runtime gate: PASS.
- Stage16A byte integrity: 724/724, missing 0, mismatch 0.

## Acceptance classification

No gate was promoted to PASS from fixture/projection evidence.

- PASS remains: G16B-01, 02, 07, 10, 11, 12, 13, 15.
- G16B-16 moves from NOT_EXECUTED to PARTIAL_EVIDENCE.
- G16B-23 and G16B-26 gain B09 evidence but remain PARTIAL_EVIDENCE.
- G16B-03 and G16B-06 remain PARTIAL_EVIDENCE.
- G16B-17, 18, 19 and 28 remain NOT_EXECUTED.

There is no local blocker for the applicable B09 client scope. Live economy, inventory, Bag, vendor quote/trade, and quest round-trips remain unavailable because `127.0.0.1:8000` has zero listeners.

B10 was not started. No final Stage16 backup was created.
