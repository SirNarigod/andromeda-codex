# Stage16B B10 — Save / Death / Dropped Bag / Recovery / Respawn

Status: `PASS_APPLICABLE_B10_SCOPE_WITH_PARTIAL_AUTHORITATIVE_EVIDENCE`.

B10 implements the Godot-side orchestration and presentation for save/autosave requests, reload/resync reconstruction, externally confirmed death and respawn, semantically distinct `DroppedBag` world representation, own/NPC Bag recovery intents, land/water Bag state, and Ground Loot water-exposure continuity. It does not implement save, death, inventory, ownership, recovery, respawn-point, or TTL authority.

## Authority boundary

Godot prepares command envelopes, blocks or restores client input, rebuilds presentation from accepted external snapshots, and displays projected states. Stage16A/Living remains authoritative for death, retained/lost items, Bag contents and ownership, recovery outcome, save success, restored state, respawn point, 900/1800-second exposure transitions, economy, quest, XP, and canonical state.

No backend or endpoint was created. `127.0.0.1:8000` remained `NOT_AVAILABLE` with zero listeners, so live authoritative round-trips are deliberately classified as partial evidence.

## Runtime evidence

- B10 headless: 453/453, exit 0, stderr empty.
- B10 Editor Bridge: 453/453, debugger 0 errors / 0 warnings, controlled stop `finalErrors: []`.
- `Main.tscn`: PASS via Editor Bridge, six-second observation, controlled stop `finalErrors: []`.
- B01–B09: 54/54, 90/90, 357/357, 156/156, 210/210, 265/265, 357/357, 475/475, 379/379.
- Stage16A: 209/209; stress: 20/20.
- Stage16A integrity: 724/724, zero missing/mismatch.
- `06_GODOT_LIVING_V1_5`: runtime PASS and 4/4 byte integrity.

See [B10_ACCEPTANCE_RECORD_V0_8_0.json](B10_ACCEPTANCE_RECORD_V0_8_0.json), [B10_IMPLEMENTATION_LOG_V0_8_0.md](B10_IMPLEMENTATION_LOG_V0_8_0.md), [B10_EDITOR_BRIDGE_DEBUGGER_V0_8_0.json](B10_EDITOR_BRIDGE_DEBUGGER_V0_8_0.json), [B10_GODOT_RUNTIME.log](B10_GODOT_RUNTIME.log), [B10_BASELINE_INTEGRITY.log](B10_BASELINE_INTEGRITY.log), and [B10_INVALIDATED_RUNS.log](B10_INVALIDATED_RUNS.log).

## Acceptance position

G16B-17, G16B-18 and G16B-28 move from `NOT_EXECUTED` to `PARTIAL_EVIDENCE`. G16B-25, G16B-26 and G16B-27 receive stronger local projection/continuity evidence but remain partial. G16B-19 remains `NOT_EXECUTED` for B11. No gate was promoted to PASS from fixtures.

B11 was not started. No final Stage16 restore/checkpoint or backup was created.

