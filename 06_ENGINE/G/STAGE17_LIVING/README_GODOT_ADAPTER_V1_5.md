# LivingWorldClient V1.5

Godot 4 client-side adapter for the Andrômeda Living V1.5 server contract.

Authority rule: Godot is never world-authoritative. It submits commands using a server-bound `session_ref`, then applies snapshots returned by `GodotIsometricAdapterV15`.

Supported commands: `MOVE_VECTOR`, `INTERACT`, `DISCOVER`, `PATH_PLAN`, `DUNGEON_MOVE`.

Units: isometric positions are meters. Rendering may convert meters to pixels locally; that conversion is visual only.

Security: the client never sends a `player_ref`; the server resolves the player from `session_ref`.

## External runtime gate

This package includes `project.godot` and `GodotRuntimeGate.gd`. On a machine with Godot 4, run the gate headlessly from this directory. The expected terminal marker is:

`ANDROMEDA_GODOT_V1_5_RUNTIME_GATE: PASS`

This gate has **not** been executed in the current build environment because no Godot 4 executable is installed there.
