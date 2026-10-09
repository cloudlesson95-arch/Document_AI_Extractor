// Base URL of the FastAPI backend. NEXT_PUBLIC_ values are inlined at build time.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

// An extraction can take three model calls of up to 60 s (EXTRACTION_TIMEOUT_SECONDS), plus a Lambda cold start
export const REQUEST_TIMEOUT_MS = 240_000;

export type Health = {
  status: string;
  cloud_provider: string;
  revision: string | null;
};

/** A failed API call: the HTTP status, or 0 when no response arrived (network, CORS or timeout). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly retryAfter: number | null; // seconds, from a 429's Retry-After header

  constructor(status: number, detail: string, retryAfter: number | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

/** Turn a non-2xx response into an ApiError with FastAPI's detail message and any Retry-After seconds. */
export async function toApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText || `HTTP ${response.status}`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body?.detail)) {
      // FastAPI's 422: a list of validation errors
      detail = body.detail.map((error: { msg?: string }) => error.msg).filter(Boolean).join("; ");
    }
  } catch {
    // Not JSON: keep the status text
  }
  const retryAfter = Number(response.headers.get("Retry-After"));
  return new ApiError(response.status, detail, retryAfter > 0 ? retryAfter : null);
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

/** One function per endpoint. */
export const api = {
  health: () => request<Health>("/health", { cache: "no-store" }),
};
