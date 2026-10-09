import { afterEach, describe, expect, it, vi } from "vitest";

import { api, API_URL, ApiError, fileUrl, toApiError } from "./api";

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

  it("keys a 422's first message per field by its path, without Pydantic's 'Value error' prefix", async () => {
    const error = await toApiError(jsonResponse(422, { detail: [
      { loc: ["body", "currency"], msg: "Value error, must be a 3-letter ISO 4217 code such as USD" },
      { loc: ["body", "line_items", 1, "quantity"], msg: "Input should be greater than 0" },
      { loc: ["body", "line_items", 1, "quantity"], msg: "a second message" },
      { loc: ["body"], msg: "not about one field" },
    ] }));

    expect(error.fieldErrors).toEqual({
      currency: "must be a 3-letter ISO 4217 code such as USD",
      "line_items.1.quantity": "Input should be greater than 0",
    });
  });

  it("has no field errors for other errors", async () => {
    const error = await toApiError(jsonResponse(404, { detail: "Receipt not found" }));

    expect(error.fieldErrors).toEqual({});
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

  it("uploads a receipt as the multipart field 'file'", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, { id: "abc" }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["%PDF-"], "receipt.pdf", { type: "application/pdf" });

    await api.uploadReceipt(file);

    const [url, init] = fetchMock.mock.calls[0];
    expect([url, init.method]).toEqual([`${API_URL}/receipts`, "POST"]);
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("lists receipts with only the filters that are set", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(200, []));
    vi.stubGlobal("fetch", fetchMock);

    await api.listReceipts({ vendor_contains: " café ", date_from: "2026-01-01", date_to: "", max_total: undefined });
    await api.listReceipts();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${API_URL}/receipts?vendor_contains=caf%C3%A9&date_from=2026-01-01`,
      `${API_URL}/receipts`,
    ]);
  });

  it("sends a correction as JSON to the receipt's URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { id: "a/b" }));
    vi.stubGlobal("fetch", fetchMock);

    await api.correctReceipt("a/b", { total_amount: "9.50" });

    const [url, init] = fetchMock.mock.calls[0];
    expect([url, init.method, init.headers["Content-Type"]]).toEqual([`${API_URL}/receipts/a%2Fb`, "PATCH", "application/json"]);
    expect(JSON.parse(init.body)).toEqual({ total_amount: "9.50" });
  });

  it("builds the original file's URL from the API's URL", () => {
    expect(fileUrl({ file_url: "/receipts/abc/file" })).toBe(`${API_URL}/receipts/abc/file`);
  });
});
