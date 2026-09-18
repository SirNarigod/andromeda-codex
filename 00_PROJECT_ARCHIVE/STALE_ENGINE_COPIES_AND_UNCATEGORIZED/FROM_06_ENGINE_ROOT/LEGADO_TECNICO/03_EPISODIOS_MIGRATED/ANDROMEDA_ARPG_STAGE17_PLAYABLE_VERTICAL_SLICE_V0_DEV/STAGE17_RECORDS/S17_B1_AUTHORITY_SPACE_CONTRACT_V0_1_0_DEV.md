# S17-B1 — Authority-Space Movement Contract V0.1.0 DEV

## Source of truth

- **Authority position:** `movement.state` in the Stage16A Python authority, expressed as global territorial isometric metres (`iso_x_m`, `iso_y_m`) plus projected `altitude_m`.
- **Local presentation:** the Stage17 Godot `CharacterBody3D` in scene-local metres (`global_position.x/y/z`).
- **Navigation:** Godot `NavigationAgent3D` is presentation/pathing only; it is not gameplay authority.
- **Mapping:** one Stage17 client mapper is the only conversion point. No caller sends raw Godot coordinates as territorial coordinates.

## Proven coordinate relation

The sealed Stage16B evidence `AUTHORITY_G16B_04_ROOT_CAUSE_V0_8_3` proved the relation with 30/30 live points and zero measured mapping error:

- local `+X` maps to authority `+iso_x_m`;
- local `+Z` maps to authority `+iso_y_m`;
- one Godot local unit maps to one authority metre;
- local `Y` maps to the projected altitude channel for presentation only;
- no rotation or sign inversion is present in the validated slice.

The origin is not hard-coded. It is established from the first real server-authoritative snapshot paired with the actual Stage17 Player node:

```text
authority = authority_origin + (local - local_origin)
local     = local_origin + (authority - authority_origin)
```

The anchor is scoped to `world_instance_id` and `session_ref`. A world identity change invalidates the old anchor.

## Numeric contract

- Mapper round-trip tolerance: `0.00001 m`.
- Final observed B1 local round-trip error: `0.0 m`.
- Final observed B1 authority round-trip error: `0.0 m`.
- Negative and positive values, multiple points, axes, signs, scale and finite-number guards are covered.
- No observed player spawn position or authority origin is embedded in source.

## Presentation reconciliation

The local presentation tolerance is `0.16 m`, inherited from the Player arrival tolerance and documented as a Stage17 presentation constant. It is not a backend gameplay rule. The authoritative result/snapshot is projected back into local space and the Player converges through navigation; there is no arbitrary teleport.

## Boundary preserved

Normal ground click movement is authoritative. Interaction approaches remain local presentation because the current NPC/resource/loot scene proxies do not yet have authoritative spatial bindings. Sending their local positions through the new mapper would be semantically false. The pending work is recorded as:

- `S17_INTERACTION_APPROACH_AUTHORITY_MIGRATION_PENDING` (P1)
- `S17_COMBAT_CHASE_AUTHORITY_MIGRATION_PENDING` (P1)

