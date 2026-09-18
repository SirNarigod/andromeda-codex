// IA inimiga (M1): curar aliado <50% se tiver cura; senão atacar alvo aleatório da party.
import type { CombatAction, Combatant } from "./types";

export function chooseFoeAction(foe: Combatant, battle: { combatants: Combatant[] }, roll: () => number): CombatAction {
  const allies = battle.combatants.filter((c) => c.side === foe.side && c.alive && c.ref !== foe.ref);
  const wounded = allies.find((a) => a.hp < a.maxHp / 2);
  if (wounded && foe.cooldowns["heal"] === 0) {
    return { kind: "skill", actorRef: foe.ref, targetRef: wounded.ref, skillId: "heal" };
  }
  const targets = battle.combatants.filter((c) => c.side === "party" && c.alive);
  if (!targets.length) return { kind: "defend", actorRef: foe.ref };
  const target = targets[Math.floor(roll() * targets.length)];
  return { kind: "attack", actorRef: foe.ref, targetRef: target.ref };
}
