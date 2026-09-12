"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, listResearch } from "@/lib/api";
import type { ResearchListItem, ResearchStatus } from "@/lib/types";

const PAGE_SIZE = 20;

// A short label per outcome, for a list that has to be readable at a glance.
// Plan §0.1 rule 4 applies here as much as to the full §7.1 wording these
// stand in for: no two of them may describe different outcomes in the same
// words. A run that was cut short, one that could not reach the source and
// one that broke are three different things, and the list says which before
// the user spends a click finding out.
const OUTCOME_LABELS: Record<ResearchStatus, string> = {
  pending: "Queued",
  understanding: "Running",
  needs_clarification: "Needs an answer",
  rejected: "Not a research question",
  discovering: "Running",
  retrieving: "Running",
  analyzing: "Running",
  aggregating: "Running",
  completed: "Finished",
  completed_partial: "Stopped early",
  completed_degraded: "Source partly unreachable",
  source_unavailable: "Source unreachable",
  failed: "Failed",
  cancelled: "Cancelled",
};

const OUTCOME_TONE: Partial<Record<ResearchStatus, string>> = {
  completed: "history-badge-good",
  completed_partial: "history-badge-partial",
  completed_degraded: "history-badge-degraded",
  source_unavailable: "history-badge-broken",
  failed: "history-badge-broken",
  cancelled: "history-badge-partial",
  rejected: "history-badge-partial",
};

const WHEN = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" });

function when(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : WHEN.format(parsed);
}

/**
 * Past runs, newest first (plan §2.15, Phase 14.9).
 *
 * Reading this page costs a database query. Nothing here re-runs anything,
 * and every row is a link to a run that already exists — which is the point
 * of the phase: an answer bought once can be read again.
 */
export default function HistoryPage() {
  const [runs, setRuns] = useState<ResearchListItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async (offset: number): Promise<void> => {
    try {
      const page = await listResearch(PAGE_SIZE, offset);
      setTotal(page.total);
      setRuns((previous) => (offset === 0 ? page.runs : [...(previous ?? []), ...page.runs]));
      setError(null);
    } catch (err) {
      // An empty history and a history that could not be read are different
      // things, and the page must never show the first when it means the
      // second (plan §0.1).
      setError(err instanceof ApiError ? err.message : "could not load your past research");
    }
  }, []);

  // Queued on the next tick rather than started inside the effect body —
  // this is a read of something outside React, not state the first render
  // could have computed (react-hooks/set-state-in-effect).
  useEffect(() => {
    const handle = setTimeout(() => void load(0), 0);
    return () => clearTimeout(handle);
  }, [load]);

  async function handleMore() {
    setLoadingMore(true);
    await load(runs?.length ?? 0);
    setLoadingMore(false);
  }

  return (
    <main className="page">
      <div className="run-head">
        <div className="section-head-main">
          <p className="text-muted section-kicker">History</p>
          <h1 className="section-query">Research you have already run</h1>
        </div>
        <Link className="btn btn-secondary" href="/">
          New research
        </Link>
      </div>

      {error && <p className="error">{error}</p>}

      {runs === null && !error && <p className="text-muted empty-state">Loading your research…</p>}

      {runs !== null && runs.length === 0 && !error && (
        <p className="text-muted empty-state">
          No research yet. Ask a question and it will be listed here — every run is kept, so you
          never have to pay for the same answer twice.
        </p>
      )}

      {runs !== null && runs.length > 0 && (
        <>
          <ul className="history-list">
            {runs.map((run) => (
              <li key={run.id}>
                <Link className="history-row" href={`/research/${run.id}`}>
                  <span className="history-question">{run.query}</span>
                  <span className="history-meta">
                    <time dateTime={run.created_at}>{when(run.created_at)}</time>
                    <span
                      className={`history-badge ${OUTCOME_TONE[run.status] ?? "history-badge-running"}`}
                    >
                      {OUTCOME_LABELS[run.status]}
                    </span>
                    {run.result_count !== null && (
                      <span className="text-muted">
                        {run.result_count} ranked {run.result_count === 1 ? "place" : "places"}
                      </span>
                    )}
                  </span>
                  <span className="text-muted history-message">{run.message}</span>
                </Link>
              </li>
            ))}
          </ul>

          {runs.length < total && (
            <button
              type="button"
              className="btn btn-secondary history-more"
              onClick={handleMore}
              disabled={loadingMore}
            >
              {loadingMore ? "Loading…" : `Show older research (${total - runs.length} more)`}
            </button>
          )}
        </>
      )}
    </main>
  );
}
