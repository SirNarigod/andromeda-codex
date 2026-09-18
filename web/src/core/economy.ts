// Economia runtime: quote→execute idempotente (padrão commerce_system.py).
// Preços RUNTIME_ONLY — ver docs/runtime/balance-v1.md.
import type { Commerce } from "../data/schemas";

export interface Quote {
  key: string;
  itemId: string;
  price: number;
  kind: "buy" | "sell";
}

export function priceForTier(commerce: Commerce, tier: string | null): number {
  if (!tier) return 0;
  return commerce.runtime_prices[tier] ?? 0;
}

/** Preço de arma pelo overall (regra da Mesa fase 81). */
export function weaponPrice(ovr: number): number {
  if (ovr <= 40) return 0;
  if (ovr <= 48) return 25;
  if (ovr <= 56) return 60;
  return 150;
}

export function quoteBuy(key: string, itemId: string, price: number): Quote {
  return { key, itemId, price, kind: "buy" };
}

export function applyBargain(price: number, success: boolean): number {
  return success ? Math.floor(price * 0.8) : price;
}

export class ShopSession {
  private applied = new Set<string>();

  /** Executa compra uma única vez por chave (idempotente). Retorna true se aplicou. */
  executeBuy(q: Quote, purse: { stavias: number }): boolean {
    if (this.applied.has(q.key)) return false;
    if (purse.stavias < q.price) return false;
    purse.stavias -= q.price;
    this.applied.add(q.key);
    return true;
  }

  executeSell(q: Quote, purse: { stavias: number }): boolean {
    if (this.applied.has(q.key)) return false;
    purse.stavias += q.price;
    this.applied.add(q.key);
    return true;
  }
}
