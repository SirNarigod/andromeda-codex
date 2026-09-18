# Andrômeda Códex ARPG — Stage16B B09

Status: `PASS_APPLICABLE_B09_SCOPE_WITH_PARTIAL_AUTHORITATIVE_EVIDENCE`

B09 adds only the Godot client presentation/orchestration layer for:

- a physical NPC vendor with approach and explicit `REQUEST_QUOTE -> user confirmation -> EXECUTE_TRADE` phases;
- BUY/SELL envelopes and externally projected quote/trade results;
- externally projected base inventory, equipped Bag container, equipment, stacks, and the existing two weapon quick-slots;
- Stage12 quest offer, choice, objective, completion, and reward presentation without local completion or grant authority;
- modal vendor/inventory/quest input consumption using the existing off-white, rounded UI family.

The implementation never changes wallet, inventory, ownership, Bag contents, price, stack, capacity, quest completion, reward, XP, or canon locally. The backend remains `NOT_AVAILABLE`; projections and fixtures are not counted as authoritative round-trip evidence.

## Verified result

- B09 headless: 379/379 PASS, exit 0, stderr empty.
- B09 Editor Bridge: 379/379 PASS.
- `Main.tscn`: PASS.
- Debugger: 0 errors / 0 warnings.
- Controlled stop: `finalErrors: []`.
- B01–B08 regressions: all PASS at their approved counts.
- Stage16A: 209/209 PASS.
- Stress: 20/20 PASS.
- Stage16A integrity: 724/724, no missing or mismatch.
- `06_GODOT_LIVING_V1_5`: runtime and byte audit PASS.
- Master, Stage16A checkpoint, and source Acceptance Matrix hashes preserved.

## Acceptance consequence

G16B-16 now has `PARTIAL_EVIDENCE`; quote/execute separation, explicit confirmation, no automatic purchase, session/stale guards, and no local economy mutation are proven in the real Godot runtime, but no live authoritative vendor/economy round-trip exists. G16B-23 and G16B-26 receive additional evidence and remain partial. No gate was promoted improperly.

Detailed evidence:

- [B09 Acceptance Record](B09_ACCEPTANCE_RECORD_V0_8_0.json)
- [B09 Implementation Log](B09_IMPLEMENTATION_LOG_V0_8_0.md)
- [B09 Editor Bridge Debugger](B09_EDITOR_BRIDGE_DEBUGGER_V0_8_0.json)
- [B09 Runtime Log](B09_GODOT_RUNTIME.log)
- [B09 Invalidated Runs](B09_INVALIDATED_RUNS.log)
- [B09 Baseline Integrity](B09_BASELINE_INTEGRITY.log)

B10 was not started. No final Stage16 backup was created.
