# Stage 16B / B07 — Universal Ground Loot

Status: `PASS_APPLICABLE_B07_SCOPE_WITH_PARTIAL_AUTHORITATIVE_EVIDENCE`

B07 implements the Godot-side physical and interactive foundation for universal
Ground Loot. It does not grant items, mutate inventory, choose quantities,
persist profile preferences, advance authoritative water TTL, or replace the
legacy backend.

## Runtime architecture

- `GroundLoot.tscn` remains a `RigidBody3D:GroundLoot` with physical collision,
  placeholder mesh, `Area3D:PickupSensor`, minimal `Label3D`, hover/selection
  feedback, and the existing water-world presenter.
- `AndromedaGroundLoot` owns only local settling/presentation and projects
  externally supplied identity, quantity, lifecycle and water exposure.
- `AndromedaGroundLootPickupClient` registers drops by stable `target_ref`,
  validates local pickup preconditions, approaches manual targets, deduplicates
  requests, and prepares bridge command envelopes. It never grants an item.
- The source-kind contract accepts `ENEMY`, `TREE`, `ROCK`, `ORE`, `FLORA`,
  `AGRICULTURE`, `HUNTING`, `FISHING`, `CONTAINER`,
  `PHYSICAL_PRODUCTION`, and `PLAYER_DROP`.
- Category placeholders are shared by category/type; there is no final art or
  item-by-item icon set.

## Pickup contract

Manual left or right click on Ground Loot beyond 0.5 m keeps the selected
`target_ref` and requests navigation/approach. A pickup request envelope can be
prepared only at physical distance `<= 0.5 m`, with a valid path, no blocker,
an active drop, and completed local/authoritative settling. `0.5001 m` is
rejected. Click spam, stale refs, wrong-session refs, removed targets and
duplicate results are rejected or deduplicated.

Auto Pickup OFF never reacts to proximity. Auto Pickup ON scans passively only
inside the same valid 0.5 m range, preserves movement, attack, interaction,
chase and selection state, and has one in-flight request per `target_ref`.
Preference state is projected by session/sequence and connected to the B05 UI;
authoritative persistence remains external.

## Water exposure

Godot presents `ACTIVE`, `RECOVERABLE_IN_WATER` and `SUNK` states and a
client-side exposure projection against the 900 s contract. The client does not
advance the exposure clock and never sinks/removes a drop because a local timer
elapsed. `SUNK` blocks pickup only after an externally authoritative snapshot or
result projects that state. Bag 30-minute rules and timer save/reload are not B07
scope.

## Evidence

- B07 headless: 357/357, exit 0, stderr empty.
- B07 Editor Bridge: 357/357, debugger 0 errors / 0 warnings.
- `Main.tscn` Editor Bridge: PASS, debugger clean, controlled stop with
  `finalErrors: []`.
- B01 54/54; B02 90/90; B03 357/357; B04 156/156; B05 210/210;
  B06 265/265. All final headless regressions used exit code 0 and empty stderr.
- Stage16A 209/209 and stress 20/20.
- Living V1.5 historical runtime gate PASS.
- Checkpoint integrity 724/724, missing 0, mismatch 0; Living files 4/4.

The first Editor Bridge run was invalidated because it exposed four compiler
warnings. They were corrected and every affected test was restarted. Earlier
functional failures and any invocation without a retained exit code are listed
in `B07_IMPLEMENTATION_LOG_V0_8_0.md`; none is counted as evidence.

## Acceptance classification

`G16B-04`, `G16B-06`, and `G16B-27` remain `PARTIAL_EVIDENCE` because the live
authoritative round-trips/persistence are unavailable. `G16B-05` moves from
`NOT_EXECUTED` to `PARTIAL_EVIDENCE`: all universal source kinds are supported
by the infrastructure, but B08 gathering/source loops have not been started.

There is no local B07 blocker. `127.0.0.1:8000` remains `NOT_AVAILABLE` with
zero listeners. B08 was not started, and no final Stage16 backup was created.
