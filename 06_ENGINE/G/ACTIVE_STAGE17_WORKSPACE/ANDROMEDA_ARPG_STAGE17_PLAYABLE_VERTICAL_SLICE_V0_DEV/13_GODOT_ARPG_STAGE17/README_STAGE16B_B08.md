# Stage 16B / B08 - Resource Nodes and Gathering to Ground Loot

Status: `PASS_APPLICABLE_B08_SCOPE_WITH_PARTIAL_AUTHORITATIVE_EVIDENCE`

B08 implements the Godot-side client foundation for resource nodes and
gathering. It presents externally supplied state, approaches a selected
resource through real navigation, prepares an intent envelope at valid physical
range, waits for external authority, and converts confirmed physical output to
the approved B07 Ground Loot pipeline. It never grants inventory or calculates
yield locally.

## Runtime architecture

- `ResourceNode.tscn` is a `StaticBody3D:ResourceNode` with body collision,
  `VisualRoot`, `InteractionSensor`, and `DropAnchor`.
- `AndromedaResourceNode` supports TREE, ROCK, ORE, FLORA, and AGRICULTURE with
  stable refs, externally projected availability, and ACTIVE/PRELOAD/SYSTEMIC
  presentation.
- `AndromedaGatheringClient` handles selection-to-approach orchestration, E and
  right-click interaction, physical range/path/blocker guards, request
  deduplication, external snapshots/results, and Ground Loot output projection.
- HUNTING, FISHING, and ENEMY outputs use the same universal B07 channel without
  turning their actors into ResourceNodes.

## Authority boundary

The client does not decide tool validity, work success, yield, quantity,
rarity, stamina, depletion, replenishment, respawn, ownership, inventory, XP,
profession progress, or economy. `REQUEST_GATHER` contains no client-supplied
`player_ref` and no grant fields. External projection fixtures in the B08 gate
validate client behavior only and are not presented as a live round-trip.

## Physical output contract

Externally confirmed TREE, ROCK, ORE, FLORA, AGRICULTURE, HUNTING, FISHING, and
ENEMY output is instantiated as physical B07 Ground Loot. Resource nodes use
their `DropAnchor`; actor pipelines use an externally authorized position.
Quantity and category arrive externally. Zero, invalid, duplicate, stale,
wrong-session, removed-source, simultaneous, stacked, terrain, and near-water
cases are guarded. No path delivers output directly to inventory.

## Evidence

- B08 headless: 475/475, exit 0, stderr empty.
- B08 Editor Bridge: 475/475, debugger 0 errors / 0 warnings.
- `Main.tscn` Editor Bridge: PASS; controlled stop `finalErrors: []`.
- B01 54/54; B02 90/90; B03 357/357; B04 156/156; B05 210/210;
  B06 265/265; B07 357/357. All final Godot runs exited 0 with empty stderr.
- Stage16A 209/209; stress 20/20.
- Living V1.5 runtime gate PASS and protected files 4/4.
- Stage16A checkpoint integrity 724/724, missing 0, mismatch 0.

Failed or warned attempts were discarded, corrected, and rerun. They are
documented in `B08_IMPLEMENTATION_LOG_V0_8_0.md`; final Bridge evidence is in
`B08_EDITOR_BRIDGE_DEBUGGER_V0_8_0.json`.

## Acceptance classification

G16B-05 remains `PARTIAL_EVIDENCE`. All eight required source kinds are proven
through the real Godot/B07 projection and physics path, but the backend at
`127.0.0.1:8000` has zero listeners, so live authoritative gathering/output is
not proven. Related gates retain their previous statuses; none was promoted by
a fixture.

There is no local B08 blocker. B09 was not started, no backend substitute was
created, and no final Stage16 backup was created.
