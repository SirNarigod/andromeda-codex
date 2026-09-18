import { describe, expect, it } from "vitest";
import { sha256Hex, stableRoll } from "./rng";

describe("rng (paridade com hashlib.sha256 do Python)", () => {
  it("sha256('abc') = vetor conhecido", () => {
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
  it("stableRoll reproduz u64/(2^64-1) do Python", () => {
    expect(stableRoll(1, "EVT1", "HIT")).toBeCloseTo(0.8457675030869042, 12);
    expect(stableRoll("TER-011", "tile", "5,5")).toBeCloseTo(0.6761595072211444, 12);
  });
  it("determinístico", () => {
    expect(stableRoll("s", "e", "c")).toBe(stableRoll("s", "e", "c"));
  });
});
