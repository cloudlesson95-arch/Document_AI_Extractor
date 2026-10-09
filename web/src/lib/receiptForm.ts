import type { ExtractedReceipt } from "./api";
import { formatAmount } from "./format";

// The review form's values: strings, "" when unknown. `key` keeps React's rows stable as items are added and removed.
export type LineItemDraft = { key: string; description: string; quantity: string; unit_price: string };

export type ReceiptDraft = {
  vendor: string;
  date: string; // YYYY-MM-DD, as <input type="date"> uses it
  total_amount: string;
  currency: string;
  line_items: LineItemDraft[];
};

let nextKey = 0;

export function newLineItem(): LineItemDraft {
  return { key: `item-${nextKey++}`, description: "", quantity: "1", unit_price: "" };
}

/** The form's starting values for a receipt, with amounts shown to two decimals. */
export function toDraft(receipt: ExtractedReceipt): ReceiptDraft {
  return {
    vendor: receipt.vendor ?? "",
    date: receipt.date ?? "",
    total_amount: receipt.total_amount == null ? "" : formatAmount(receipt.total_amount),
    currency: receipt.currency ?? "",
    line_items: receipt.line_items.map((item) => ({
      ...newLineItem(),
      description: item.description,
      quantity: item.quantity,
      unit_price: item.unit_price == null ? "" : formatAmount(item.unit_price),
    })),
  };
}

// Trimmed, with a decimal comma as a point ("9,20" -> "9.20"); the backend validates the rest
function decimal(value: string): string {
  return value.trim().replace(/^(-?\d+),(\d+)$/, "$1.$2");
}

/**
 * The PATCH body for a draft. It sends every field: the backend compares the values (9.2 equals 9.20)
 * and marks the receipt corrected only if one changes, so unchanged fields cost nothing.
 */
export function toCorrection(draft: ReceiptDraft): ExtractedReceipt {
  return {
    vendor: draft.vendor.trim() || null,
    date: draft.date || null,
    total_amount: decimal(draft.total_amount) || null,
    currency: draft.currency.trim().toUpperCase() || null,
    line_items: draft.line_items.map((item) => ({
      description: item.description.trim(),
      quantity: decimal(item.quantity),
      unit_price: decimal(item.unit_price) || null,
    })),
  };
}

/** Whether saving the draft would send different values than saving the last saved one. */
export function hasChanges(draft: ReceiptDraft, saved: ReceiptDraft): boolean {
  return JSON.stringify(toCorrection(draft)) !== JSON.stringify(toCorrection(saved));
}
