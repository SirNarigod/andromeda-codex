# B08 Implementation Log V0.8.0

## Scope and authority

B08 was implemented only inside `07_GODOT_ARPG_STAGE16B`. Master V2.0.1,
Living Simulation Engine, Stage16A, `06_GODOT_LIVING_V1_5`, the Stage16A
checkpoint, B01-B07, and the source Acceptance Matrix were preserved.

Godot owns resource presentation, target selection, navigation approach, local
range/blocker guards, input, feedback, external-state projection, and bridge
command orchestration. The implementation does not decide yield, quantity,
rarity, loot table, tool validity, stamina cost, depletion, replenishment,
respawn, ownership, inventory, XP, profession progress, economy, or grants.
Physical output appears only when an externally identified event is projected,
and is routed through the approved B07 Ground Loot snapshot path. No backend,
HTTP endpoint, listener, or parallel Living implementation was created.

## Files created

- `scripts/interaction/resource_node.gd`: specialized `StaticBody3D` resource
  presentation with stable identity, external state/sequence/session guards,
  interaction and drop anchors, feedback, and ACTIVE/PRELOAD/SYSTEMIC visuals.
- `scripts/interaction/gathering_client.gd`: resource registry, contextual input,
  physical approach, local path/range/blocker guards, `REQUEST_GATHER` envelope,
  external result/state/stamina projection, and external output to B07 Ground
  Loot conversion.
- `tests/godot/B08RuntimeGate.tscn` and
  `tests/godot/b08_runtime_gate.gd`: dedicated 475-check runtime gate.
- Godot-generated UID sidecars for the two new runtime scripts.
- B08 runtime/regression logs, baseline integrity log, debugger record,
  implementation log, README, and Acceptance Record.

## Files modified

- `scenes/interaction/ResourceNode.tscn`: evolved the existing placeholder
  additively to use `AndromedaResourceNode`; preserved the manifest root and
  required children, resource layer 32, and interaction layer 8.
- `scenes/Main.tscn`: added one `GatheringClient` and the missing AGRICULTURE
  placeholder beside the existing TREE/ROCK/ORE/FLORA nodes.
- `scripts/main.gd`: bound the gathering client, routed E and right-click
  resource intents, cleared removed target selection, and exposed explicit
  no-authority contract flags without changing B03 click semantics.
- `scripts/input/input_router.gd`: made contextual hostile/resource right-click
  mode explicitly `CLICK_ONLY`; no hold action was introduced.
- `project.godot`: updated the Stage16B application label to B08 and added the E
  `context_interact` action.
- `tests/godot/b05_runtime_gate.gd`, `tests/godot/b06_runtime_gate.gd`, and
  `tests/godot/b07_runtime_gate.gd`: accepted the exact B08 project label so the
  historical gates continue validating their original contracts.

No protected baseline or source Acceptance Matrix file was modified.

## ResourceNode coverage

`ResourceNode.tscn` remains rooted at `StaticBody3D:ResourceNode` with
`CollisionShape3D`, `Node3D:VisualRoot`, `Area3D:InteractionSensor`, and
`Marker3D:DropAnchor`. The five specialized placeholder instances are TREE,
ROCK, ORE, FLORA, and AGRICULTURE. Each keeps a stable `target_ref`, exact
`resource_kind`, interaction range, drop anchor, projected state, and stream
phase.

External state accepts AVAILABLE/ACTIVE, BUSY/IN_PROGRESS,
DEPLETED/UNAVAILABLE, and REMOVED. Session mismatch, stale/duplicate sequence,
out-of-order snapshots, kind/ref mismatch, and removed targets are rejected or
tombstoned. No local respawn/replenishment timer exists.

## Gathering flow

1. Left-click keeps B03 selection-only behavior for a resource.
2. E or contextual right-click begins approach or request processing.
3. Physical range, navigation path, blocker probe, target identity, active
   stream phase, and externally projected availability are checked locally.
4. At valid range, Godot builds only a `REQUEST_GATHER` command envelope. It
   supplies no `player_ref`, yield, quantity, inventory grant, tool verdict, or
   stamina mutation.
5. Godot waits for an external result. Accepted/rejected/unavailable feedback
   remains presentational.
6. Externally confirmed physical outputs are projected through
   `AndromedaGroundLootPickupClient.project_ground_loot_snapshot()`.
7. B07 settling, physical world presence, category presentation, water
   presenter, and the 0.5 m pickup contract remain intact.

TREE, ROCK, ORE, FLORA, and AGRICULTURE outputs use the source `DropAnchor`.
HUNTING, FISHING, and ENEMY remain actors/pipelines rather than artificial
ResourceNodes and use an externally authorized output position. All eight
source kinds preserve source context, externally supplied quantity, and Ground
Loot identity. These tests validate the Godot projection contract only; they do
not claim a live authoritative source loop.

## Streaming and interoperation

ACTIVE materializes the detailed placeholder; PRELOAD keeps only its reduced
representation and disables interaction; SYSTEMIC removes detailed visual and
collision materialization while retaining the external Living reference.
Transitions ACTIVE -> PRELOAD -> ACTIVE and ACTIVE -> SYSTEMIC -> ACTIVE reuse
the same identity and do not duplicate ResourceNodes or Ground Loot.

Auto Pickup remains passive and does not interrupt an in-flight gathering
request, movement, attack context, interaction, or selected resource. B06
combat feedback does not change the selected resource or logical distance. A
gathering stamina update is accepted only as an external Stage16A projection
into the existing B05 radial ring; no second stamina system was created.

## Errors, corrections, and invalidated executions

Every failed, warned, incomplete, or incorrectly rooted run below was discarded
and followed by an affected-test restart.

1. A direct PowerShell GUI launch returned the launcher rather than the Godot
   process and produced no retained runtime output/exit evidence. It was not
   counted; final headless runs use `Start-Process -Wait` with explicit logs.
2. `B08_PRECHECK_B03_R1` stopped at 153/165 with parser/runtime cascades caused
   by a duplicate inherited constant and an invalid custom-script cast. The
   constant and cast were corrected.
3. `B08_PRECHECK_B03_R2` reached 353/357: the new gathering rejection was
   overwriting B03's valid contextual input result. Main now preserves the
   approved input intent and attaches the B08 orchestration result separately.
   B03 then returned to 357/357 with empty stderr.
4. `B08_GATE_ATTEMPT_01` had a parser error because `preload` was used as a
   local variable name. It was renamed; the run was discarded.
5. `B08_GATE_ATTEMPT_02` reached 454/460 and exposed missing `CLICK_ONLY`
   metadata, a route-closure assertion, event-sequence fixture coupling, a
   blocker positioned before tree insertion, and two calls to nonexistent
   presentation helpers. Runtime and fixtures were corrected without relaxing
   authority or navigation guards.
6. `B08_GATE_ATTEMPT_03` reached 471/474. The remaining assertions used the
   wrong path comparison, a presentation distance sample, and an obsolete
   quick-slot contract field. They were aligned with the real B02/B05 APIs.
7. `B08_GATE_ATTEMPT_04` passed 475/475 headless. The first real Editor Bridge
   run also passed 475/475 functionally but exposed two warnings: an unnecessary
   `await` and a local `duplicate` name shadowing `Node.duplicate()`. That Bridge
   run was invalidated. The await was removed and the variable renamed.
8. Post-warning `B08_GATE_ATTEMPT_05`, final headless, and final Editor Bridge
   all passed 475/475 with no warning/error and clean controlled stops.
9. The first Stage16A and stress invocations lacked `ANDROMEDA_MASTER_RELEASE`
   and incorrectly fell back to `/mnt/data/...`; Stage16A stopped after 147
   tests and both processes exited 1. Neither was counted. Both were restarted
   with the protected Master path: 209/209 and 20/20, exit 0.
10. An integrity command initially used the wrong relative path for the source
    Acceptance Matrix and aborted before producing evidence. It changed
    nothing. The complete audit was restarted against
    `02_CONTRACTS/ARPG_STAGE16A/ARPG_STAGE16B_GODOT_ACCEPTANCE_MATRIX_V0_8_0.json`
    and passed 724/724.

The preserved raw Godot attempt logs are under `.godot/b08_*`. Final evidence
uses only the clean canonical B08 logs in the project root.

## Final test evidence

- B08 headless: 475/475, exit 0, stderr empty.
- B08 Editor Bridge: 475/475, debugger 0 errors / 0 warnings, controlled stop,
  `finalErrors: []`.
- `Main.tscn` Editor Bridge: PASS after 10 seconds of observation, debugger
  clean, controlled stop, `finalErrors: []`.
- B01 54/54; B02 90/90; B03 357/357; B04 156/156; B05 210/210;
  B06 265/265; B07 357/357. Every final Godot regression exited 0 with empty
  stderr.
- Stage16A: 209/209, `Ran 209 tests in 283.049s`, `OK`, process exit 0.
  Its verbose unittest report is written to stderr by design, not as a warning.
- Stage16A stress: 20/20, exit 0, stderr empty.
- `06_GODOT_LIVING_V1_5`: runtime gate PASS, exit 0, stderr empty; protected
  files 4/4.
- Baseline: 724/724, missing 0, mismatch 0.
- Backend: `127.0.0.1:8000` NOT_AVAILABLE, zero listeners.

## Integrity hashes

- Master V2.0.1:
  `6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2`
- Stage16A checkpoint:
  `21626A3152CB37E167EEE24BFF9D3142C5D389A8CA2827594B34211591525A6A`
- Source Acceptance Matrix:
  `9335E6C7A5FAA25F97991204787D2C77485592419AAA1F51641C01E31317454C`

## Acceptance result

No gate status changed in B08. G16B-05 remains `PARTIAL_EVIDENCE`: the Godot
client contract was proven for all eight required source kinds, always through
physical B07 Ground Loot before any inventory path, but no live authoritative
gathering/output round-trip was available. G16B-03, G16B-04, G16B-06,
G16B-08, G16B-09, and G16B-20 also remain partial for their recorded missing
authoritative/global evidence.

B08 is closed as
`PASS_APPLICABLE_B08_SCOPE_WITH_PARTIAL_AUTHORITATIVE_EVIDENCE`. There is no
local B08 blocker. B09 was not started, and no final Stage16 backup was created.
