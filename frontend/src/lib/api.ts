// Thin client for the research API (plan §11). Every research state the
// backend can reach has a matching branch in app/page.tsx; this module only
// does transport and error typing, never interprets status meaning.

import type {
  ClarificationOption,
  ClarifyResponse,
  EntityType,
  EvidenceResponse,
  ResearchCreateResponse,
  ResearchListResponse,
  ResearchResultsResponse,
  ResearchStatusResponse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Overridable so tests don't have to wait out a real 2s interval; production
// always gets the default.
export function getPollIntervalMs(): number {
  const raw = process.env.NEXT_PUBLIC_POLL_INTERVAL_MS;
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 2000;
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    const message =
      typeof body === "object" && body !== null && "message" in body
        ? String((body as { message: unknown }).message)
        : `request failed with status ${status}`;
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Body wasn't JSON — ApiError falls back to a generic message.
    }
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as T;
}

// `fresh` asks for the work to be done again whatever has been answered
// before (plan §2.15 rule 2). It produces an ordinary run with a new id and
// leaves the old one in history — never a replacement, never an overwrite.
export function createResearch(
  query: string,
  options: { fresh?: boolean } = {}
): Promise<ResearchCreateResponse> {
  return fetchJson<ResearchCreateResponse>("/api/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, fresh: options.fresh ?? false }),
  });
}

// Past runs, newest first (plan §2.15). A pure read: listing history never
// starts a run and never costs a model call.
export function listResearch(limit: number, offset: number): Promise<ResearchListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return fetchJson<ResearchListResponse>(`/api/research?${params}`);
}

export function getResearch(id: string): Promise<ResearchStatusResponse> {
  return fetchJson<ResearchStatusResponse>(`/api/research/${id}`);
}

export function clarifyResearch(
  id: string,
  entity_granularity: EntityType
): Promise<ClarifyResponse> {
  return fetchJson<ClarifyResponse>(`/api/research/${id}/clarify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entity_granularity }),
  });
}

export function cancelResearch(id: string): Promise<ResearchStatusResponse> {
  return fetchJson<ResearchStatusResponse>(`/api/research/${id}/cancel`, {
    method: "POST",
  });
}

export function getResults(id: string): Promise<ResearchResultsResponse> {
  return fetchJson<ResearchResultsResponse>(`/api/research/${id}/results`);
}

export function getEvidence(
  id: string,
  entityId: string,
  limit: number,
  offset: number
): Promise<EvidenceResponse> {
  const params = new URLSearchParams({
    entity_id: entityId,
    limit: String(limit),
    offset: String(offset),
  });
  return fetchJson<EvidenceResponse>(`/api/research/${id}/evidence?${params}`);
}

export type { ClarificationOption };
