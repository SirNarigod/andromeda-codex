// App M1: telas Título → Criar → Mapa (+ Ficha, Inventário, NPC, Viagem, Saves).
import {
  createCharacter, levelForXp, toCombatant, PLAYABLE_CLASSES,
} from "../core/character";
import { applyBargain, priceForTier, quoteBuy, ShopSession, weaponPrice } from "../core/economy";
import { applyStatus, removeStatus } from "../core/combat/status";
import { DATA, byId } from "../data";
import { moveOnGrid, synthesizeGrid, TILE, type Grid } from "../world/grid";
import { browserStorage, deleteGame, listSlots, loadGame, saveGame } from "../world/save";
import { logJournal, newGame, type GameState } from "../world/store";
import { attachMovement, drawMap } from "./map-canvas";

const GRID_TERS = ["TER-011", "TER-001", "TER-012"];
const QUEST_REWARD = 30; // RUNTIME_ONLY (docs/runtime/balance-v1.md)

export class App {
  private root: HTMLElement;
  private state: GameState | null = null;
  private grids = new Map<string, Grid>();
  private detachMove: (() => void) | null = null;
  private shop = new ShopSession();

  constructor(root: HTMLElement) {
    this.root = root;
  }

  start(): void {
    this.showTitle();
  }

  // ---------- telas ----------
  private showTitle(): void {
    this.root.innerHTML = `<h1>Andrômeda — RPG (M1)</h1>
      <button id="new">Novo jogo</button>
      <button id="cont">Continuar</button>
      <div id="slots"></div>`;
    document.getElementById("new")!.onclick = () => this.showCreate();
    document.getElementById("cont")!.onclick = () => this.showSlots();
  }

  private showSlots(): void {
    const slots = listSlots(browserStorage());
    const host = document.getElementById("slots")!;
    host.innerHTML = slots.map((s, i) =>
      `<div>Slot ${i + 1}: ${s ? `${s.player.name} (${s.player.classId}) — ${s.pos.ter}` : "vazio"}
      ${s ? `<button data-load="${i + 1}">Carregar</button> <button data-del="${i + 1}">Apagar</button>` : ""}</div>`).join("");
    host.querySelectorAll("[data-load]").forEach((b) => {
      (b as HTMLElement).onclick = () => {
        const s = loadGame(browserStorage(), Number((b as HTMLElement).dataset.load));
        if (s) { this.state = s; this.showMap(); }
      };
    });
    host.querySelectorAll("[data-del]").forEach((b) => {
      (b as HTMLElement).onclick = () => {
        deleteGame(browserStorage(), Number((b as HTMLElement).dataset.del));
        this.showSlots();
      };
    });
  }

  private showCreate(): void {
    const clsOpts = PLAYABLE_CLASSES.map((c) => `<option>${c}</option>`).join("");
    this.root.innerHTML = `<h2>Criar personagem</h2>
      <label>Nome <input id="nm" value="Kenua" /></label><br/>
      <label>Classe <select id="cl">${clsOpts}</select></label>
      <p>Origem: TER-011 Terras Livres (Varga). Arma padrão da classe + Kit de Varga incluídos.</p>
      <button id="go">Começar</button>`;
    document.getElementById("go")!.onclick = () => {
      const name = (document.getElementById("nm") as HTMLInputElement).value || "Viajante";
      const classId = (document.getElementById("cl") as HTMLSelectElement).value;
      const cls = DATA.classes.find((c) => c.id === classId)!;
      const arsenal = DATA.arsenal.by_class.find((a) => a.class_name === classId);
      const weapon = DATA.weapons.find((w) => w.id === arsenal?.weapon_ids[0]);
      const pc = createCharacter(name, cls, "TER-011", weapon);
      pc.inventory.push("EQP-002", "KIT-VARGA");
      pc.packSlots = 20;
      const curativo = DATA.items.find((i) => (i.fx as { heal_pct?: number }).heal_pct === 30);
      if (curativo) pc.inventory.push(curativo.id);
      this.state = newGame(pc, "TER-011", -1, -1, `m1|${Date.now()}`);
      const g = this.gridFor("TER-011");
      this.state.pos = { ter: "TER-011", x: g.spawn.x, y: g.spawn.y };
      logJournal(this.state, `${name} (${classId}) parte de Varga.`);
      this.showMap();
    };
  }

  private gridFor(ter: string): Grid {
    let g = this.grids.get(ter);
    if (!g) {
      const territory = DATA.territories.find((t) => t.id === ter)!;
      const establishments = DATA.est.filter((e) => e.ter === ter);
      const routesFrom = DATA.routes.filter((r) => r.from === ter);
      const corrupted = ter === "TER-012";
      g = synthesizeGrid({
        territory, establishments, routesFrom, corrupted,
        corruptZone: ter === "TER-011" ? { cx: 18, cy: 18, r: 5 } : undefined, // SUB-011-006 Fendas da Névoa (runtime: posição na síntese)
      });
      this.grids.set(ter, g);
    }
    return g;
  }

  private showMap(): void {
    const s = this.state!;
    const ter = DATA.territories.find((t) => t.id === s.pos.ter)!;
    this.root.innerHTML = `<h2>${ter.name} <small>(${ter.id})</small></h2>
      <canvas id="map" width="480" height="480"></canvas>
      <div id="hud"></div>
      <div>
        <button id="b-sheet">Ficha</button>
        <button id="b-inv">Inventário</button>
        <button id="b-travel">Viajar</button>
        <button id="b-save">Salvar</button>
        <button id="b-title">Título</button>
      </div>
      <div id="panel"></div>
      <h3>Diário</h3><div id="journal"></div>`;
    const canvas = document.getElementById("map") as HTMLCanvasElement;
    const redraw = () => {
      drawMap(canvas, this.gridFor(s.pos.ter), s.pos.x, s.pos.y);
      this.renderHud();
    };
    document.getElementById("b-sheet")!.onclick = () => this.showSheet();
    document.getElementById("b-inv")!.onclick = () => this.showInventory();
    document.getElementById("b-travel")!.onclick = () => this.showTravel();
    document.getElementById("b-save")!.onclick = () => this.showSave();
    document.getElementById("b-title")!.onclick = () => { this.detach(); this.showTitle(); };
    this.detachMove = attachMovement((d) => {
      const delta = d === "up" ? [0, -1] : d === "down" ? [0, 1] : d === "left" ? [-1, 0] : [1, 0];
      const g = this.gridFor(s.pos.ter);
      const r = moveOnGrid(g, s.pos.x, s.pos.y, delta[0], delta[1]);
      if (!r.moved) return;
      s.pos.x = r.x; s.pos.y = r.y; s.turns += 1;
      this.onEnterTile(g);
      redraw();
    });
    redraw();
  }

  private onEnterTile(g: Grid): void {
    const s = this.state!;
    const t = g.tiles[s.pos.y][s.pos.x];
    if (t === TILE.CORRUPT) {
      s.player.hp = Math.max(1, s.player.hp - 2);
      if (!s.player.states.includes("corrompido")) s.player.states.push("corrompido");
      logJournal(s, "Pressão da corrupção: −2 PV (zona de Fendas da Névoa/contenção).");
    } else if (s.player.states.includes("corrompido") && t === TILE.OPEN) {
      // mantém até descansar (fora do escopo M1: remove ao visitar POI abrigo)
    }
    const poi = g.pois.find((p) => p.x === s.pos.x && p.y === s.pos.y);
    if (poi) this.showPoi(poi.estId);
    const exit = g.exits.find((e) => e.x === s.pos.x && e.y === s.pos.y);
    if (exit) this.showTravel(exit.to);
  }

  private renderHud(): void {
    const s = this.state!;
    document.getElementById("hud")!.innerHTML =
      `${s.player.name} · ${s.player.classId} nv${s.player.level} · PV ${s.player.hp}/${s.player.maxHp} · ${s.player.stavias} st · pos ${s.pos.x},${s.pos.y}`;
    document.getElementById("journal")!.innerHTML = s.journal.slice(-6).map((j) => `<div>${j}</div>`).join("");
  }

  private showPoi(estId: string): void {
    const s = this.state!;
    const e = DATA.est.find((x) => x.id === estId)!;
    const panel = document.getElementById("panel")!;
    const subs = DATA.landscapes.filter((l) => l.ter === s.pos.ter).map((l) => l.sub);
    const npcs = DATA.npcs.filter((n) => n.sub !== null && subs.includes(n.sub)).slice(0, 6);
    const civs = DATA.civilians.filter((c) => c.est === estId).slice(0, 4);
    panel.innerHTML = `<h3>${e.name}</h3><p>${e.fn}</p>
      <h4>Presentes</h4>${npcs.map((n) => `<div><b>${n.name}</b> (${n.role}, ${n.cls}) <button data-npc="${n.id}">Falar</button></div>`).join("")}
      ${civs.map((c) => `<div>${c.name} — ${c.job}</div>`).join("")}
      ${e.id === "EST-005" ? `<h4>Quadro de Travessia</h4><div id="quests"></div>` : ""}
      <button id="rest">Descansar (cura 30%, limpa corrompido)</button>`;
    panel.querySelectorAll("[data-npc]").forEach((b) => {
      (b as HTMLElement).onclick = () => this.showNpc((b as HTMLElement).dataset.npc!);
    });
    if (e.id === "EST-005") this.renderQuests(panel.querySelector("#quests") as HTMLElement);
    (document.getElementById("rest") as HTMLElement).onclick = () => {
      const heal = Math.floor(s.player.maxHp * 0.3);
      s.player.hp = Math.min(s.player.maxHp, s.player.hp + heal);
      s.player.states = s.player.states.filter((x) => x !== "corrompido");
      logJournal(s, `Descanso em ${e.name}: +${heal} PV.`);
      this.renderHud();
    };
  }

  private showNpc(npcId: string): void {
    const s = this.state!;
    const n = DATA.npcs.find((x) => x.id === npcId)!;
    const panel = document.getElementById("panel")!;
    panel.innerHTML = `<h3>${n.name}</h3><p>Papel: ${n.role} · Classe: ${n.cls} · Tier: ${n.tier}</p>
      <p>Habilidade: ${n.as ?? "—"} · Passiva: ${n.ps ?? "—"}</p>      <button id="back">Voltar</button>`;
    (document.getElementById("back") as HTMLElement).onclick = () => { panel.innerHTML = ""; };
    logJournal(s, `Falou com ${n.name}.`);
    this.renderHud();
  }

  private renderQuests(host: HTMLElement): void {
    const s = this.state!;
    const subs = DATA.landscapes.filter((l) => l.ter === s.pos.ter).map((l) => l.sub);
    const available = DATA.quests.filter((q) => subs.includes(q.loc));
    host.innerHTML = available.map((q) => {
      const st = s.quests.find((x) => x.id === q.id);
      if (!st) return `<div><b>${q.title}</b> — ${q.premise} <button data-acc="${q.id}">Aceitar</button></div>`;
      if (st.phase === "DONE") return `<div><b>${q.title}</b> — concluída (${st.resolution}).</div>`;
      return `<div><b>${q.title}</b> — fase ${st.phase}
        ${q.res.map((r) => `<button data-res="${q.id}:${r.id}">${r.t}</button>`).join("")}</div>`;
    }).join("");
    host.querySelectorAll("[data-acc]").forEach((b) => {
      (b as HTMLElement).onclick = () => {
        s.quests.push({ id: (b as HTMLElement).dataset.acc!, phase: "DECISION" });
        logJournal(s, `Contrato aceito.`);
        this.renderQuests(host);
      };
    });
    host.querySelectorAll("[data-res]").forEach((b) => {
      (b as HTMLElement).onclick = () => {
        const [qid, rid] = (b as HTMLElement).dataset.res!.split(":");
        const st = s.quests.find((x) => x.id === qid)!;
        st.phase = "DONE"; st.resolution = rid;
        s.player.stavias += QUEST_REWARD;
        s.player.xp += 20;
        s.player.level = levelForXp(s.player.xp);
        logJournal(s, `Contrato ${qid} resolvido (${rid}): +${QUEST_REWARD} st, +20 XP.`);
        this.renderQuests(host); this.renderHud();
      };
    });
  }

  private showSheet(): void {
    const s = this.state!;
    const cls = DATA.classes.find((c) => c.id === s.player.classId)!;
    const weapon = DATA.weapons.find((w) => w.id === s.player.weaponId);
    const armor = DATA.items.find((i) => i.id === s.player.armorId);
    const c = toCombatant(s.player, cls, weapon, armor);
    const panel = document.getElementById("panel")!;
    panel.innerHTML = `<h3>Ficha — ${s.player.name}</h3>
      <p>${cls.name} · Origem ${s.player.origin} · Nv ${s.player.level} (${s.player.xp} XP)</p>
      <p>FOR ${cls.attrs.FOR} AGI ${cls.attrs.AGI} VIT ${cls.attrs.VIT} TEC ${cls.attrs.TEC} MAG ${cls.attrs.MAG} DEF ${cls.attrs.DEF}</p>
      <p>PV ${s.player.hp}/${s.player.maxHp} · SP ${s.player.sp} · ${s.player.stavias} st · Mochila ${s.player.packSlots} slots</p>
      <p>Afinidades TEC ${s.player.affinities.TEC} MAG ${s.player.affinities.MAG} · Estados: ${s.player.states.join(", ") || "—"}</p>
      <p>Derivado: precisão ${c.accuracy} evasão ${c.evasion} armadura ${c.armor} dano ${c.baseDamage} crit ${c.critChance}% ×${c.critMultiplier}</p>
      <p>Arma: ${weapon?.name ?? "—"} · Armadura: ${armor?.name ?? "—"}</p>`;
  }

  private showInventory(): void {
    const s = this.state!;
    const byIdMap = byId(DATA.items);
    const panel = document.getElementById("panel")!;
    const items = s.player.inventory.map((id) => byIdMap.get(id)).filter(Boolean);
    panel.innerHTML = `<h3>Inventário (${items.length}/${s.player.packSlots})</h3>` +
      items.map((i) => `<div>${i!.name} <small>${i!.cat}</small>
        ${(i!.fx as { heal_pct?: number }).heal_pct ? ` <button data-use="${i!.id}">Usar</button>` : ""}
        ${(i!.fx as { armor?: number }).armor !== undefined ? ` <button data-eq="${i!.id}">Equipar</button>` : ""}
      </div>`).join("");
    panel.querySelectorAll("[data-use]").forEach((b) => {
      (b as HTMLElement).onclick = () => {
        const item = byIdMap.get((b as HTMLElement).dataset.use!)!;
        const fx = item.fx as { heal_pct?: number };
        const heal = Math.floor(s.player.maxHp * (fx.heal_pct! / 100));
        s.player.hp = Math.min(s.player.maxHp, s.player.hp + heal);
        s.player.inventory = s.player.inventory.filter((x) => x !== item.id);
        logJournal(s, `Usou ${item.name}: +${heal} PV.`);
        this.showInventory(); this.renderHud();
      };
    });
    panel.querySelectorAll("[data-eq]").forEach((b) => {
      (b as HTMLElement).onclick = () => {
        s.player.armorId = (b as HTMLElement).dataset.eq!;
        logJournal(s, `Equipou armadura.`);
        this.showInventory(); this.renderHud();
      };
    });
  }

  private showTravel(preselect?: string): void {
    const s = this.state!;
    const outgoing = DATA.routes.filter((r) => r.from === s.pos.ter);
    const panel = document.getElementById("panel")!;
    const dest = preselect ?? outgoing[0]?.to;
    if (!dest) { panel.innerHTML = "<p>Sem rotas daqui.</p>"; return; }
    if (GRID_TERS.includes(dest)) {
      const g = this.gridFor(dest);
      s.pos = { ter: dest, x: g.spawn.x, y: g.spawn.y };
      if (!s.visited.includes(dest)) s.visited.push(dest);
      logJournal(s, `Viagem para ${dest}.`);
      this.showMap();
      return;
    }
    // placeholder com dados válidos
    const t = DATA.territories.find((x) => x.id === dest)!;
    const ests = DATA.est.filter((e) => e.ter === dest);
    const fauna = DATA.fauna.filter((f) => f.ter === dest);
    panel.innerHTML = `<h3>${t.name} (em expansão)</h3>
      <p>Terreno ${t.terrain} · Transporte ${t.transport}</p>
      <p>Estabelecimentos: ${ests.map((e) => e.name).join("; ") || "—"}</p>
      <p>Fauna: ${fauna.map((f) => f.cri).join(", ") || "—"}</p>
      <p><i>Grid explorável chega após o M1. Viagem registrada; retorno a ${s.pos.ter}.</i></p>`;
    if (!s.visited.includes(dest)) s.visited.push(dest);
    logJournal(s, `Visitou ${dest} (placeholder).`);
  }

  private showSave(): void {
    const s = this.state!;
    const panel = document.getElementById("panel")!;
    panel.innerHTML = `<h3>Salvar</h3>` + [1, 2, 3].map((i) =>
      `<button data-save="${i}">Slot ${i}</button>`).join("");
    panel.querySelectorAll("[data-save]").forEach((b) => {
      (b as HTMLElement).onclick = () => {
        saveGame(browserStorage(), Number((b as HTMLElement).dataset.save), s);
        logJournal(s, `Jogo salvo.`);
        this.renderHud();
      };
    });
  }

  private detach(): void {
    this.detachMove?.();
    this.detachMove = null;
  }
}
