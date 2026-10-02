// Base URL of the FastAPI backend. NEXT_PUBLIC_ values are inlined at build time.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Health = {
  status: string;
  cloud_provider: string;
};

export async function getHealth(): Promise<Health> {
  const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /health failed with ${res.status}`);
  }
  return res.json();
}
