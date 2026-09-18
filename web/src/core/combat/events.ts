// Battle Events: log tipado (UI e journal consomem; core nunca toca DOM).
import type { BattleEvent } from "./types";

export class EventLog {
  private seq = 0;
  events: BattleEvent[] = [];

  push(round: number, type: string, detail: Record<string, unknown> = {}, actor?: string, target?: string): BattleEvent {
    const ev: BattleEvent = { seq: this.seq++, round, type, actor, target, detail };
    this.events.push(ev);
    return ev;
  }

  clear(): void {
    this.seq = 0;
    this.events = [];
  }
}
