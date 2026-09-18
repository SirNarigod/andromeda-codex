# ANDRÔMEDA ARPG — STAGE 01 GAME CORE V0.2.0

Stage 01 establishes the non-visual playable runtime foundation.

## Fixed authorial decisions

- Player model: created characters plus canonical characters.
- Class model: classes emerge from player choices; no fixed class is assigned at creation.
- Primary control: mouse pointer, Diablo II-like interaction model.
- Delivery: single-player first, command architecture prepared for future multiplayer.
- Itemization direction: Andrômeda-specific rules built on ARPG mathematical principles; itemization itself begins in Stage 05.

## Stage 01 runtime authority

The client is not gameplay authority. It sends intents. `ARPGGameCore` validates ownership and client sequence, persists the command stream, then routes gameplay to the existing Living/Country/Godot adapter layers.

The Master V2.0.1 and Living Simulation Engine V1.0.0 remain protected baselines. Player-created profiles, avatar records, numeric placeholder health, command state, target selection and movement intent are GAMEPLAY_DERIVED and are not canon.

## No-art rule

Stage 01 requires no conceptual art, sprites, meshes, materials, animations, VFX or final UI. The runtime is designed to operate with placeholders until Stage 17 passes.
