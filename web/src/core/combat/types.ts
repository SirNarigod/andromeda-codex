// Tipos do Combat Engine (turnos; sem DOM/Canvas).
export type Side = "party" | "foes";
export type ActionKind = "attack" | "skill" | "item" | "defend" | "flee";

export interface Combatant {
  ref: string;
  name: string;
  side: Side;
  hp: number;
  maxHp: number;
  armor: number;
  evasion: number;
  accuracy: number;
  baseDamage: number;
  critChance: number; // %
  critMultiplier: number;
  level: number;
  agility: number; // ordem de turno
  damageType?: string; // default PHYSICAL
  resistance?: number; // resistência ao damageType recebido (não-PHYSICAL)
  statuses: StatusState[];
  defending: boolean;
  alive: boolean;
  cooldowns: Record<string, number>; // skillId -> rodadas restantes
  isPlayer?: boolean;
}

export interface StatusState {
  id: string; // CONTENCAO | OFUSCADO | ESPORO | RAIZ | ferido | exausto | corrompido
  roundsLeft: number | null; // null = até removido
  atkMod: number;
  evmMult: number;
  dot: number;
}

export interface CombatAction {
  kind: ActionKind;
  actorRef: string;
  targetRef?: string;
  skillId?: string;
  itemId?: string;
}

export interface AttackResult {
  hit: boolean;
  critical: boolean;
  hitChance: number;
  damage: number;
  mitigationPct: number;
  killed: boolean;
  blocked?: string; // motivo (ex.: OUT_OF_RANGE)
}

export interface BattleEvent {
  seq: number;
  round: number;
  type: string;
  actor?: string;
  target?: string;
  detail: Record<string, unknown>;
}
