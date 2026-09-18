import { describe, expect, it } from "vitest";
import { applyBargain, priceForTier, quoteBuy, ShopSession, weaponPrice } from "./economy";
import { DATA } from "../data";

describe("economy (RUNTIME_ONLY)", () => {
  it("tiers → preços do commerce", () => {
    expect(priceForTier(DATA.commerce, "MÉDIO")).toBe(25);
    expect(priceForTier(DATA.commerce, "MUITO_ALTO")).toBe(150);
    expect(priceForTier(DATA.commerce, null)).toBe(0);
  });
  it("arma por overall (regra Mesa f81)", () => {
    expect(weaponPrice(40)).toBe(0);
    expect(weaponPrice(45)).toBe(25);
    expect(weaponPrice(55)).toBe(60);
    expect(weaponPrice(70)).toBe(150);
  });
  it("barganha −20% no sucesso", () => {
    expect(applyBargain(100, true)).toBe(80);
    expect(applyBargain(100, false)).toBe(100);
  });
  it("execute idempotente: mesma chave debita uma vez", () => {
    const shop = new ShopSession();
    const purse = { stavias: 60 };
    const q = quoteBuy("k1", "KIT-VARGA", 25);
    expect(shop.executeBuy(q, purse)).toBe(true);
    expect(shop.executeBuy(q, purse)).toBe(false);
    expect(purse.stavias).toBe(35);
  });
  it("sem saldo não executa", () => {
    const shop = new ShopSession();
    const purse = { stavias: 5 };
    expect(shop.executeBuy(quoteBuy("k2", "x", 25), purse)).toBe(false);
    expect(purse.stavias).toBe(5);
  });
});
