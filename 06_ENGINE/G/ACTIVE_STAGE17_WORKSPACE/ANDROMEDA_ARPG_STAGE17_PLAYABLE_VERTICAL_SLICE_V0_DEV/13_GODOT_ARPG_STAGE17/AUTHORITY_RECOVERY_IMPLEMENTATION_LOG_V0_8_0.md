# Stage16B — Authority Integration Recovery V0.8.0

Captured: 2026-08-21T22:30:45.3065332-03:00

## Classification

- Recovery scope: `PASS_APPLICABLE_AUTHORITY_INTEGRATION_RECOVERY_LOCAL_GAPS_WITH_BACKEND_INCOMPATIBLE`.
- Stage16B global: `NOT_PASS`.
- Acceptance moved from 9 PASS / 19 PARTIAL_EVIDENCE to 11 PASS / 17 PARTIAL_EVIDENCE.
- G16B-14 and G16B-23 moved individually to PASS.
- No other gate was promoted.

## Authority boundary

Godot remains input, scene, physics/navigation orchestration, camera, UI, feedback and external-state projection. The crafting test source is explicitly named `AUTHORITY_RECOVERY_PRESENTATION_FIXTURE_NOT_LIVE_AUTHORITY`. It cannot calculate a recipe, yield, ingredient consumption, inventory grant, stamina result or craft result. The occlusion component only duplicates presentation materials and never changes collision, navigation or targeting.

No backend, HTTP endpoint, gameplay authority or canonical data was created. Master V2.0.1, Living, Stage16A, Stage15 history and the source Acceptance Matrix remained read-only.

## G16B-14 — real camera occluder fade

`CameraOccluder.tscn` and `camera_occluder.gd` implement a reusable placeholder occluder component on collision layer 256. It duplicates each mesh's `StandardMaterial3D` per instance, blends alpha toward 0.20 over a configurable 0.16 s, holds release for 0.06 s to avoid edge flicker, and restores the exact original material override when clear.

`isometric_camera_rig.gd` now performs repeated direct-space ray queries between camera and the Player focus point. It excludes each hit and continues until it has collected all compatible occluders, up to a configurable cap. The resulting presentation set is stable across frames; leaving occluders are restored without touching collision layers, masks, Player target state or the raycast result already used by input.

The Main placeholder includes independent tree, wall and tall-object occluders. The dedicated real-Godot gate validates individual and simultaneous fades, smooth entry/exit, original material restoration, unchanged collision, stable selection, no flicker and Reduced Motion independence.

## G16B-23 — crafting UI runtime coverage

`CraftingPanel.tscn` and `crafting_panel.gd` extend the B05 visual language with a non-permanent crafting modal: white/off-white rounded panel, rounded legible gray text, soft-orange important state, ingredient rows, quantity, output, availability and a separate explicit craft action.

The panel accepts only externally validated projections with matching session and monotonically newer sequence. It emits a `REQUEST_CRAFT` client intent; it never consumes ingredients or grants output. `hud_controller.gd` supplies modal/input isolation, menu scroll, and an intent envelope without transport or result fabrication. The wheel cannot swap weapons or zoom while this modal owns input.

## Files created

- `scripts/camera/camera_occluder.gd`
- `scenes/camera/CameraOccluder.tscn`
- `scripts/ui/crafting_panel.gd`
- `scenes/ui/CraftingPanel.tscn`
- `tests/godot/authority_recovery_runtime_gate.gd`
- `tests/godot/AuthorityRecoveryRuntimeGate.tscn`
- recovery evidence records listed in `README_STAGE16B_AUTHORITY_RECOVERY.md`

Godot generated `.uid` files for the new scripts inside the permitted Stage16B area.

## Files modified

- `scripts/camera/isometric_camera_rig.gd`: material-occluder collection and presentation calls.
- `scenes/Main.tscn`: three functional placeholder occluders.
- `scenes/ui/HUD.tscn`: CraftingPanel instance.
- `scripts/ui/hud_controller.gd`: crafting modal, projection, input ownership and intent envelope.
- `tests/godot/b11_runtime_gate.gd`: two historical absence assertions replaced by additive recovered-feature assertions; historical count remains 343.

Godot also refreshed permitted `.godot` cache/editor metadata while importing the new scripts. No protected file was changed.

## Backend investigation

An exhaustive search found one real historical server:

- entrypoint: `C:/Users/thall/ANDROMEDA_PRODUCT/ANDROMEDA_LIVING_BRIDGE_DEV/living_api.py`
- Python: `C:/Users/thall/ANDROMEDA_PRODUCT/.venv/Scripts/python.exe` (3.14.6)
- command: `python -m uvicorn living_api:app --host 127.0.0.1 --port 8000`
- routes: `GET /health`, `GET /snapshot`, `POST /command`
- health: HTTP 200, service `ANDROMEDA_LIVING_BRIDGE`, `living_v15=PASS`

This is not the missing Stage16B authority. It imports `IntegratedLivingEngineV15`, not `integrated_arpg_engine_v16a`. Its Stage16A copies of `integrated_engine_v15.py` and `godot_adapter_v15.py` are byte-identical, but its `living_runtime.py` differs from the protected Stage16A copy. Its own tests cannot be approved because `test_v15_core`, static audit and readiness scripts hard-code a missing Linux Master V2.1 path.

The live probe exposed decisive protocol gaps:

- `MOVE_TO_POINT` is rejected as `UNSUPPORTED_GODOT_COMMAND`.
- Historical `MOVE_VECTOR` works, but an identical replay is applied again.
- A deliberately wrong `session_ref` is accepted and applied because the server uses a hard-coded session.
- The snapshot declares `server_authoritative=true` but contains no `session_ref`, `snapshot_id` or sequence.
- Client-supplied session/player authority fields are not rejected strictly.

Because the backend failed its own validation and lacks the Stage16B session/snapshot/command contract, it was not connected to Godot. The process was shut down cleanly and port 8000 returned to zero listeners. No configuration was changed.

## Corrections and invalidated runs

The first material fade used `_process`, while the deterministic gate advanced physics frames; this produced 22 timing failures. The fade moved to `_physics_process`, then passed.

The first Editor Bridge run was 154/154 functionally but invalid because the debugger reported an unnecessary `await`. It was removed, then headless and Bridge were both rerun cleanly.

Several orchestration-only attempts were discarded before evidence: unavailable `ProcessStartInfo.ArgumentList`, an embedded wrapper parse issue, an unavailable .NET hex helper, and a malformed read-only backend search command. None mutated source. Stage16A was also first launched without `ANDROMEDA_MASTER_RELEASE`; its 147-test/7-error result was discarded, the real Master hash was verified, and all 209 tests were rerun successfully.

See `AUTHORITY_RECOVERY_INVALIDATED_RUNS.log` for the full audit trail.

## Final tests

- Authority Recovery headless: 154/154 PASS, exit 0, stderr empty.
- Authority Recovery Editor Bridge: 154/154 PASS, debugger 0/0, stop `finalErrors: []`.
- Main.tscn Editor Bridge: PASS after eight seconds, debugger 0/0, stop `finalErrors: []`.
- B01 54/54; B02 90/90; B03 357/357; B04 156/156; B05 210/210.
- B06 265/265; B07 357/357; B08 475/475; B09 379/379; B10 453/453; B11 343/343.
- Every final Godot regression exited 0 with empty stderr and no warning/error diagnostic.
- Stage16A: 209/209, `Ran 209 tests in 270.095s`, `OK`, exit 0.
- Stage16A stress: 20/20, exit 0, stderr empty.
- Living V1.5 runtime gate: PASS, exit 0.
- Stage16A checkpoint: 724/724 byte matches, missing 0, mismatch 0.
- Living protected files: 4/4.

## Protected hashes

- Master V2.0.1: `6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2`.
- Stage16A checkpoint: `21626A3152CB37E167EEE24BFF9D3142C5D389A8CA2827594B34211591525A6A`.
- Source Acceptance Matrix: `9335E6C7A5FAA25F97991204787D2C77485592419AAA1F51641C01E31317454C`.

## Remaining blockers and watch items

The blocker is now precise: there is no tested server entrypoint that combines the existing Stage01–16A ARPG authority with the Stage16B B01 session/snapshot protocol. The historical V1.5 service is real, but not compatible or safe enough to stand in for it. Therefore 17 authoritative gates remain PARTIAL_EVIDENCE.

Performance remains a watch item. The prior B11 capture lasted approximately 0.812 s and observed a 141.950 ms maximum frame; the current headless B11 capture lasted approximately 0.625 s and observed 133.333 ms. No threshold was invented. A multi-minute soak remains required after a compatible authority exists.

Stage17 was not started. No final checkpoint or restore was executed. No final Stage16 backup was created.

