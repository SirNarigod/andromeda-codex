import { describe, expect, it } from "vitest";
import { checkRange, resolveAttack } from "./action-resolver";
import { chooseFoeAction } from "./ai";
import { applyStatus, effectiveAccuracy, isImmobilized, tickStatuses, updateWounded } from "./status";
import { checkEnd, nextTurn, startBattle, tryFlee } from "./turn-manager";
import { DATA } from "../../data";
import type { Combatant } from "./types";

const bands = DATA.bands;

function mk(over: Partial<Combatant> = {}): Combatant {
  return {
    ref: "a", name: "A", side: "party", hp: 28, maxHp: 28, armor: 10, evasion: 20,
    accuracy: 60, baseDamage: 10, critChance: 10, critMultiplier: 1.5, level: 1,
    agility: 44, statuses: [], defending: false, alive: true, cooldowns: {}, ...over,
  };
}

describe("action-resolver (bandas MAR)", () => {
  it("tiro bloqueado no CLINCH; corpo-a-corpo bloqueado no LONG", () => {
    expect(checkRange(bands, 1.0, false).allowed).toBe(false);
    expect(checkRange(bands, 1.0, true).allowed).toBe(true);
    expect(checkRange(bands, 100, true).allowed).toBe(false);
    expect(checkRange(bands, 100, false).allowed).toBe(true);
  });
  it("ataque bloqueado retorna blocked sem dano", () => {
    const a = mk();
    const t = mk({ ref: "t", side: "foes" });
    const r = resolveAttack({ attacker: a, target: t, seed: 1, eventRef: "e", bands, distanceM: 1, melee: false, roll: () => 0 });
    expect(r.blocked).toBe("TIRO_BLOQUEADO");
    expect(t.hp).toBe(28);
  });
  it("acerto determinístico com roll injetado aplica dano e pode matar", () => {
    const a = mk({ baseDamage: 100 });
    const t = mk({ ref: "t", side: "foes", hp: 5 });
    const r = resolveAttack({ attacker: a, target: t, seed: 1, eventRef: "e", bands, distanceM: 2.5, melee: true, roll: () => 0 });
    expect(r.hit).toBe(true);
    expect(r.killed).toBe(true);
    expect(t.alive).toBe(false);
  });
  it("erro com roll alto não dá dano", () => {
    const a = mk({ accuracy: 0 });
    const t = mk({ ref: "t", side: "foes", evasion: 500 });
    const r = resolveAttack({ attacker: a, target: t, seed: 1, eventRef: "e", bands, distanceM: 2.5, melee: true, roll: () => 0.9999 });
    expect(r.hit).toBe(false);
    expect(t.hp).toBe(28);
  });
});

describe("status", () => {
  it("RAIZ imobiliza; ESPORO dá DoT e expira em 3 ticks", () => {
    const c = mk();
    applyStatus(c, "RAIZ");
    expect(isImmobilized(c)).toBe(true);
    applyStatus(c, "ESPORO");
    tickStatuses(c); tickStatuses(c);
    const t3 = tickStatuses(c);
    expect(t3.expired).toContain("ESPORO");
    // RAIZ (dot 2) + ESPORO (dot 2) × 3 ticks = 12
    expect(c.hp).toBe(28 - 12);
  });
  it("OFUSCADO reduz precisão em 5", () => {
    const c = mk();
    applyStatus(c, "OFUSCADO");
    expect(effectiveAccuracy(c)).toBe(55);
  });
  it("ferido marca <50% PV e limpa ao curar", () => {
    const c = mk();
    c.hp = 10;
    updateWounded(c);
    expect(c.statuses.some((s) => s.id === "ferido")).toBe(true);
    c.hp = 20;
    updateWounded(c);
    expect(c.statuses.some((s) => s.id === "ferido")).toBe(false);
  });
});

describe("turn-manager", () => {
  it("ordem por agilidade; fim quando um lado morre", () => {
    const fast = mk({ ref: "f", agility: 60 });
    const slow = mk({ ref: "s", side: "foes", agility: 10 });
    const b = startBattle([slow, fast]);
    expect(b.order[0]).toBe("f");
    expect(checkEnd(b)).toBeNull();
    slow.alive = false;
    expect(checkEnd(b)).toBe("party");
    expect(b.over).toBe(true);
  });
  it("nextTurn avança e incrementa rodada", () => {
    const b = startBattle([mk({ ref: "a" }), mk({ ref: "b", side: "foes" })]);
    const first = b.order[0];
    nextTurn(b);
    expect(b.order[b.cursor]).not.toBe(first);
    nextTurn(b);
    expect(b.round).toBe(2);
  });
  it("fuga quase certa com AGI alta, quase impossível zerada — limitada a [0,0.95]", () => {
    expect(tryFlee(mk({ agility: 1000 }), () => 0.94)).toBe(true);
    expect(tryFlee(mk({ agility: 0 }), () => 0.51)).toBe(false);
  });
});

describe("ai", () => {
  it("ataca alvo da party quando ninguém ferido", () => {
    const foe = mk({ ref: "foe", side: "foes" });
    const hero = mk({ ref: "hero" });
    const act = chooseFoeAction(foe, { combatants: [foe, hero] }, () => 0);
    expect(act.kind).toBe("attack");
    expect(act.targetRef).toBe("hero");
  });
  it("defende se não há alvos vivos", () => {
    const foe = mk({ ref: "foe", side: "foes" });
    const dead = mk({ ref: "d", alive: false, hp: 0 });
    const act = chooseFoeAction(foe, { combatants: [foe, dead] }, () => 0);
    expect(act.kind).toBe("defend");
  });
});
