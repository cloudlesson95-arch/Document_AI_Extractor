import { ApiError } from "./api";

/** An exact amount from the API with at least two decimals ("9.2" -> "9.20"; "1.899" stays), or a dash when unknown. */
export function formatAmount(amount: string | null | undefined): string {
  if (amount == null || amount === "") return "–";
  const match = /^(-?\d+)(?:\.(\d*))?$/.exec(amount);
  if (!match) return amount; // e.g. exponent notation: show it as sent rather than guess
  return `${match[1]}.${(match[2] ?? "").padEnd(2, "0")}`;
}

/** "9.20 EUR", just the amount when the currency is unknown, or a dash when the amount is. */
export function formatMoney(amount: string | null | undefined, currency: string | null | undefined): string {
  const formatted = formatAmount(amount);
  return formatted !== "–" && currency ? `${formatted} ${currency}` : formatted;
}

/** A Retry-After wait, rounded up: "45 s", "12 min" or "9 h" (the daily upload limit waits until UTC midnight). */
function formatWait(seconds: number): string {
  if (seconds < 120) return `${seconds} s`;
  if (seconds < 7200) return `${Math.ceil(seconds / 60)} min`;
  return `${Math.ceil(seconds / 3600)} h`;
}

/** A message for a failed request that tells the user what to do. */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return String(error);
  if (error.status === 500) return "The backend failed unexpectedly; its log has the details.";
  if (error.retryAfter) return `${error.detail} (in ${formatWait(error.retryAfter)})`;
  return error.detail;
}
