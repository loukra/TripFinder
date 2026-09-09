"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_INTERVAL_MS = 2000;

const TERMINAL_STATUSES = new Set([
  "completed",
  "completed_partial",
  "completed_degraded",
  "source_unavailable",
  "rejected",
  "failed",
  "cancelled",
]);

const RESULTS_STATUSES = new Set([
  "completed",
  "completed_partial",
  "completed_degraded",
]);

type ResearchCreateResponse = {
  id: string;
  status: string;
};

type ResearchStatusResponse = {
  id: string;
  status: string;
  statistics: Record<string, number>;
};

type Result = {
  entity_id: string;
  entity_name: string;
  supporter_count: number;
  share: number;
  respondent_pool_size: number;
  discussion_count: number;
  weighted_score: number;
  confidence: number;
};

type ResearchResultsResponse = {
  id: string;
  status: string;
  results: Result[];
};

async function fetchJson<T>(url: string, errorLabel: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${errorLabel}: ${response.status}`);
  return (await response.json()) as T;
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [researchId, setResearchId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [results, setResults] = useState<Result[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollHandle = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollHandle.current !== null) clearInterval(pollHandle.current);
    };
  }, []);

  async function pollOnce(id: string) {
    try {
      const current = await fetchJson<ResearchStatusResponse>(
        `${API_URL}/api/research/${id}`,
        "status check failed"
      );
      setStatus(current.status);

      if (!TERMINAL_STATUSES.has(current.status)) return;

      if (pollHandle.current !== null) {
        clearInterval(pollHandle.current);
        pollHandle.current = null;
      }

      if (!RESULTS_STATUSES.has(current.status)) return;

      const body = await fetchJson<ResearchResultsResponse>(
        `${API_URL}/api/research/${id}/results`,
        "results fetch failed"
      );
      setResults(body.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "something went wrong");
    }
  }

  function startPolling(id: string) {
    if (pollHandle.current !== null) clearInterval(pollHandle.current);
    pollHandle.current = setInterval(() => {
      void pollOnce(id);
    }, POLL_INTERVAL_MS);
  }

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResults(null);
    setStatus(null);
    setResearchId(null);

    try {
      const created = await fetchJson<ResearchCreateResponse>(
        `${API_URL}/api/research`,
        "request failed",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query }),
        }
      );
      setResearchId(created.id);
      setStatus(created.status);
      startPolling(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "something went wrong");
    }
  }

  return (
    <main style={{ fontFamily: "sans-serif", maxWidth: 640, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>TripFinder</h1>

      <form onSubmit={submitQuery}>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="e.g. most underrated US states for nature"
          style={{ width: "100%", padding: "0.5rem" }}
          required
        />
        <button type="submit" style={{ marginTop: "0.5rem" }}>
          Search
        </button>
      </form>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {researchId && (
        <p>
          Research <code>{researchId}</code> — status: <strong>{status}</strong>
        </p>
      )}

      {results && results.length > 0 && (
        <ol>
          {results.map((result) => (
            <li key={result.entity_id}>
              {result.entity_name} — {result.supporter_count} supporters (
              {Math.round(result.share * 100)}% of {result.respondent_pool_size})
            </li>
          ))}
        </ol>
      )}

      {results && results.length === 0 && <p>No results.</p>}
    </main>
  );
}
