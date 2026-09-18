# ANDRÔMEDA FIRST PLAYABLE V0.1.5

## FIXED
- Target approach no longer commits to a single poor standoff point near wildlife.
- Raised bridge collision no longer physically blocks a path that A* marks as valid.
- Open doors remain right-clickable through a persistent interaction Area3D and can close on the second interaction.
- Chairs now toggle SIT/STAND; movement clicks force STAND before pathing.
- AStarGrid2D is cached instead of rebuilt on every click/repath.

## PRESERVED
- Left click movement.
- Right click interaction.
- Right click auto-attack every 2 seconds.
- Living command envelopes.
- V0.1.4 retained as prior build.
