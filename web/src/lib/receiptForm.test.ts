import { describe, expect, it } from "vitest";

import type { Correction } from "./api";
import { hasChanges, newLineItem, toCorrection, toDraft } from "./receiptForm";

const receipt: Correction = {
  vendor: "Cafe Uno",
  date: "2026-03-14",
  total_amount: "9.2",
  currency: "EUR",
  category: "Meals",
  line_items: [{ description: "Espresso", quantity: "2", unit_price: "1.899" }],
};

const unreadable: Correction = { vendor: null, date: null, total_amount: null, currency: null, category: null, line_items: [] };

describe("toDraft", () => {
  it("shows amounts to two decimals and keeps quantities as sent", () => {
    const draft = toDraft(receipt);

    expect([draft.total_amount, draft.line_items[0].quantity, draft.line_items[0].unit_price]).toEqual(["9.20", "2", "1.899"]);
  });

  it("shows unknown fields as empty", () => {
    expect(toDraft(unreadable)).toEqual({ vendor: "", date: "", total_amount: "", currency: "", category: "", line_items: [] });
  });
});

describe("toCorrection", () => {
  it("sends an untouched draft's values back unchanged", () => {
    expect(toCorrection(toDraft(receipt))).toEqual({ ...receipt, total_amount: "9.20" });
    expect(toCorrection(toDraft(unreadable))).toEqual(unreadable);
  });

  it("trims, sends empty fields as null, capitalizes the currency and reads a decimal comma", () => {
    const draft = { vendor: "  Bar  ", date: "", total_amount: " 12,50 ", currency: "usd", category: "", line_items: [
      { ...newLineItem(), description: " Tea ", quantity: "0,5", unit_price: "" },
    ] };

    expect(toCorrection(draft)).toEqual({ vendor: "Bar", date: null, total_amount: "12.50", currency: "USD", category: null, line_items: [
      { description: "Tea", quantity: "0.5", unit_price: null },
    ] });
  });

  it("sends the chosen category", () => {
    expect(toCorrection({ ...toDraft(receipt), category: "Software & Subscriptions" }).category).toBe("Software & Subscriptions");
  });

  it("leaves anything else for the backend to validate", () => {
    const draft = { ...toDraft(receipt), total_amount: "1,234.50", currency: "euro" };

    expect(toCorrection(draft)).toMatchObject({ total_amount: "1,234.50", currency: "EURO" });
  });
});

describe("hasChanges", () => {
  it("ignores the rows' keys", () => {
    expect(hasChanges(toDraft(receipt), toDraft(receipt))).toBe(false);
  });

  it("sees an edited field, an added row and a removed row", () => {
    const saved = toDraft(receipt);

    expect(hasChanges({ ...saved, vendor: "Cafe Due" }, saved)).toBe(true);
    expect(hasChanges({ ...saved, line_items: [...saved.line_items, newLineItem()] }, saved)).toBe(true);
    expect(hasChanges({ ...saved, line_items: [] }, saved)).toBe(true);
  });

  it("sees a changed or cleared category", () => {
    const saved = toDraft(receipt);

    expect(hasChanges({ ...saved, category: "Travel" }, saved)).toBe(true);
    expect(hasChanges({ ...saved, category: "" }, saved)).toBe(true);
  });
});
