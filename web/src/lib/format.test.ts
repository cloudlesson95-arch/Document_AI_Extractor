import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { errorMessage, formatAmount, formatMoney } from "./format";

describe("formatAmount", () => {
  it("pads to two decimals without rounding away more precise ones", () => {
    expect(["9.2", "9", "-1.5", "1.899", "0.10"].map(formatAmount)).toEqual(["9.20", "9.00", "-1.50", "1.899", "0.10"]);
  });

  it("shows a dash when unknown, and anything unexpected as it was sent", () => {
    expect([formatAmount(null), formatAmount(undefined), formatAmount(""), formatAmount("1E+2")]).toEqual(["–", "–", "–", "1E+2"]);
  });
});

describe("formatMoney", () => {
  it("adds the currency when both are known", () => {
    expect([formatMoney("9.2", "EUR"), formatMoney("9.2", null), formatMoney(null, "EUR")]).toEqual(["9.20 EUR", "9.20", "–"]);
  });
});

describe("errorMessage", () => {
  it("says when to retry, hides a 500's generic detail, and passes other details through", () => {
    expect(errorMessage(new ApiError(429, "Too many uploads, try again shortly", 12))).toBe("Too many uploads, try again shortly (in 12 s)");
    expect(errorMessage(new ApiError(500, "Internal server error"))).toContain("log");
    expect(errorMessage(new ApiError(413, "The file is larger than 4 MB"))).toBe("The file is larger than 4 MB");
    expect(errorMessage(new Error("boom"))).toBe("Error: boom");
  });
});
