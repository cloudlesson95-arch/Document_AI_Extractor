import { afterEach, describe, expect, it, vi } from "vitest";

import { api, API_URL, ApiError, toApiError } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

describe("toApiError", () => {
  it("uses FastAPI's detail message and the Retry-After seconds", async () => {
    const error = await toApiError(jsonResponse(429, { detail: "Too many uploads" }, { "Retry-After": "12" }));

    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.detail, error.retryAfter]).toEqual([429, "Too many uploads", 12]);
  });

  it("joins the messages of a 422 validation error", async () => {
    const error = await toApiError(jsonResponse(422, { detail: [{ msg: "too long" }, { msg: "required" }] }));

    expect(error.detail).toBe("too long; required");
    expect(error.retryAfter).toBeNull();
  });

  it("falls back to the status text when the body isn't JSON", async () => {
    const error = await toApiError(new Response("<html>Bad Gateway</html>", { status: 502, statusText: "Bad Gateway" }));

    expect([error.status, error.detail]).toEqual([502, "Bad Gateway"]);
  });
});

describe("api", () => {
  it("gets /health from the configured backend", async () => {
    const health = { status: "ok", cloud_provider: "local", revision: null };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, health));
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.health();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_URL}/health`);
    expect(init.cache).toBe("no-store");
    expect(result).toEqual(health);
  });

  it("turns an HTTP error into an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(503, { detail: "Not available yet" })));

    await expect(api.health()).rejects.toMatchObject({ status: 503, detail: "Not available yet" });
  });

  it("reports a network failure as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(api.health()).rejects.toMatchObject({ status: 0 });
  });
});
