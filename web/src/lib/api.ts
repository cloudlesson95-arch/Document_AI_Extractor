// Base URL of the FastAPI backend. NEXT_PUBLIC_ values are inlined at build time.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

// An extraction can take three model calls of up to 60 s (EXTRACTION_TIMEOUT_SECONDS), plus a Lambda cold start
export const REQUEST_TIMEOUT_MS = 240_000;

export type Health = {
  status: string;
  cloud_provider: string;
  revision: string | null;
};

// Amounts and quantities are exact decimals, sent as strings without padding: "9.2", "1.899"
export type LineItem = {
  description: string;
  quantity: string;
  unit_price: string | null;
};

/** The fields the model extracts and a person can correct; unreadable ones are null. */
export type ExtractedReceipt = {
  vendor: string | null;
  date: string | null; // YYYY-MM-DD
  total_amount: string | null;
  currency: string | null; // ISO 4217, e.g. EUR
  line_items: LineItem[];
};

export type Receipt = ExtractedReceipt & {
  id: string;
  file_key: string;
  mime_type: string;
  corrected: boolean; // true once a correction changed a value
  created_at: string;
  updated_at: string;
  file_url: string; // relative to API_URL; see fileUrl()
};

/** GET /receipts filters: bounds are inclusive, and empty values are left out of the query. */
export type ReceiptFilters = {
  vendor_contains?: string;
  date_from?: string; // YYYY-MM-DD
  date_to?: string;
  min_total?: string;
  max_total?: string;
};

/** A failed API call: the HTTP status, or 0 when no response arrived (network, CORS or timeout). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly retryAfter: number | null; // seconds, from a 429's Retry-After header
  readonly fieldErrors: Record<string, string>; // a 422's messages by field path, e.g. "line_items.0.quantity"

  constructor(status: number, detail: string, retryAfter: number | null = null, fieldErrors: Record<string, string> = {}) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
    this.fieldErrors = fieldErrors;
  }
}

type ValidationError = { loc?: (string | number)[]; msg?: string };

// ["body", "line_items", 0, "quantity"] -> "line_items.0.quantity", keeping the first message per field.
// Pydantic starts the message of a custom validator with "Value error, ", which a form doesn't need.
function fieldErrorsOf(errors: ValidationError[]): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const { loc, msg } of errors) {
    if (loc && loc.length > 1 && msg) {
      fields[loc.slice(1).join(".")] ??= msg.replace(/^Value error, /, "");
    }
  }
  return fields;
}

/** Turn a non-2xx response into an ApiError with FastAPI's detail message and any Retry-After seconds. */
export async function toApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText || `HTTP ${response.status}`;
  let fieldErrors: Record<string, string> = {};
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body?.detail)) {
      // FastAPI's 422: a list of validation errors, each locating its field in `loc`
      detail = body.detail.map((error: ValidationError) => error.msg).filter(Boolean).join("; ");
      fieldErrors = fieldErrorsOf(body.detail);
    }
  } catch {
    // Not JSON: keep the status text
  }
  const retryAfter = Number(response.headers.get("Retry-After"));
  return new ApiError(response.status, detail, retryAfter > 0 ? retryAfter : null, fieldErrors);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    throw new ApiError(0, timedOut
      ? `The backend didn't answer within ${REQUEST_TIMEOUT_MS / 60_000} minutes`
      : "Can't reach the backend (offline, still starting, or blocked by CORS)");
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

/** "?vendor_contains=cafe&date_from=2026-01-01" from the filters that are set, or "" when none are. */
export function toQuery(filters: ReceiptFilters): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) {
    if (value?.trim()) {
      params.set(name, value.trim());
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** Absolute URL of a receipt's original upload; the API sends it relative to its own URL. */
export function fileUrl(receipt: Pick<Receipt, "file_url">): string {
  return `${API_URL}${receipt.file_url}`;
}

/** One function per endpoint. */
export const api = {
  health: () => request<Health>("/health", { cache: "no-store" }),

  /** Upload a JPEG, PNG, WebP or PDF; the backend extracts its fields, then stores the file and the record. */
  uploadReceipt: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<Receipt>("/receipts", { method: "POST", body });
  },

  /** Receipts matching every filter that is set, newest first. */
  listReceipts: (filters: ReceiptFilters = {}) => request<Receipt[]>(`/receipts${toQuery(filters)}`, { cache: "no-store" }),

  getReceipt: (id: string) => request<Receipt>(`/receipts/${encodeURIComponent(id)}`, { cache: "no-store" }),

  /** New values for some extracted fields; the backend marks the receipt corrected only if a value changes. */
  correctReceipt: (id: string, fields: Partial<ExtractedReceipt>) =>
    request<Receipt>(`/receipts/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }),
};
