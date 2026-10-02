"use client";

import { useEffect, useState } from "react";
import { API_URL, getHealth, type Health } from "@/lib/api";

// Calls the backend from the browser, so a green status also proves CORS is configured
export default function BackendStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <p className="text-red-600 dark:text-red-400">
        Backend unreachable at {API_URL}: {error}
      </p>
    );
  }
  if (!health) {
    return <p className="text-zinc-500">Checking backend at {API_URL}...</p>;
  }
  return (
    <p className="text-green-600 dark:text-green-400">
      Backend {health.status} at {API_URL} (provider: {health.cloud_provider})
    </p>
  );
}
