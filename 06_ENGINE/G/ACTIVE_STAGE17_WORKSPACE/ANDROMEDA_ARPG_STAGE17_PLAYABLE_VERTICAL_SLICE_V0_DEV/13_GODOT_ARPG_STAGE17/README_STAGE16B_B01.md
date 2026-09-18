# Andrômeda Códex ARPG — Stage 16B — B01

This folder is the isolated Godot 4.7 runtime area for Stage 16B. The sealed Stage16A
Python gameplay authorities and `06_GODOT_LIVING_V1_5` historical gate are not modified.

## B01 scope

- `ClientSession` owns only the local session token and snapshot cursor.
- `AndromedaBridge` uses the existing discovered transport address
  `http://127.0.0.1:8000` with `/snapshot` and `/command`.
- Command envelopes preserve the V1.5 shape: `session_ref`, `command`, `params`.
- `player_ref` and gameplay-result fields are rejected on the Godot-to-backend path.
- Snapshots must declare `server_authoritative: true`; malformed, mismatched, duplicate,
  and stale sequenced snapshots are rejected.
- V1.5 snapshots without a server sequence remain accepted in explicit
  `LEGACY_RECEIVE_ORDER` compatibility mode.
- Reconnection state requires a fresh authoritative snapshot before returning to READY.

The main scene is temporarily the B01 runtime gate. B02 will replace it with the first
vertical-slice composition scene after B01 is accepted.

## Non-goals

No gameplay authority, final art, final audio, movement scene, combat scene, inventory
grant, damage resolution, currency result, quest completion, death resolution, Bag
contents, authoritative TTL, or canon mutation is implemented here.

