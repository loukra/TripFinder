"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  cancelResearch,
  clarifyResearch,
  createResearch,
  getPollIntervalMs,
  getResearch,
  getResults,
} from "@/lib/api";
import { ClarificationView } from "@/components/ClarificationView";
import { DiagnosticsSummary } from "@/components/DiagnosticsSummary";
import { ProgressView } from "@/components/ProgressView";
import { ResultsView } from "@/components/ResultsView";
import { SearchForm } from "@/components/SearchForm";
import {
  RESULTS_READY_STATUSES,
  STOP_POLLING_STATUSES,
  type ClarificationRequest,
  type EntityType,
  type ResearchDiagnostics,
  type ResearchResultsResponse,
  type ResearchStatus,
} from "@/lib/types";

interface RunState {
  id: string;
  status: ResearchStatus;
  message: string;
  statistics: Record<string, number>;
  diagnostics: ResearchDiagnostics;
  clarification: ClarificationRequest | null;
}

export default function Home() {
  const [run, setRun] = useState<RunState | null>(null);
  const [results, setResults] = useState<ResearchResultsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const pollHandle = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollHandle.current !== null) {
      clearInterval(pollHandle.current);
      pollHandle.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  // Returns the fetched status so callers can decide whether polling should
  // start at all — a research that already landed on a stop-polling status
  // (e.g. needs_clarification) on its very first fetch must never have an
  // interval started for it, or a fast-enough tick can race the user's next
  // action.
  const applyStatus = useCallback(
    async (id: string): Promise<ResearchStatus | null> => {
      try {
        const current = await getResearch(id);
        setRun({
          id,
          status: current.status,
          message: current.message,
          statistics: current.statistics,
          diagnostics: current.diagnostics,
          clarification: current.clarification,
        });

        if (STOP_POLLING_STATUSES.has(current.status)) {
          stopPolling();
          if (RESULTS_READY_STATUSES.has(current.status)) {
            const resultsBody = await getResults(id);
            setResults(resultsBody);
          }
        }
        return current.status;
      } catch (err) {
        stopPolling();
        setError(err instanceof ApiError ? err.message : "could not check research status");
        return null;
      }
    },
    [stopPolling]
  );

  function startPolling(id: string) {
    stopPolling();
    pollHandle.current = setInterval(() => {
      void applyStatus(id);
    }, getPollIntervalMs());
  }

  async function handleSearch(query: string) {
    setError(null);
    setResults(null);
    setRun(null);
    setSubmitting(true);
    try {
      const created = await createResearch(query);
      const status = await applyStatus(created.id);
      if (status !== null && !STOP_POLLING_STATUSES.has(status)) startPolling(created.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "could not start this research");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleClarify(entityGranularity: EntityType) {
    if (!run) return;
    setSubmitting(true);
    setError(null);
    try {
      await clarifyResearch(run.id, entityGranularity);
      const status = await applyStatus(run.id);
      if (status !== null && !STOP_POLLING_STATUSES.has(status)) startPolling(run.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "could not submit that answer");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel() {
    if (!run) return;
    setCancelling(true);
    try {
      // The cancel response is itself a full status snapshot (plan §11), so
      // this applies it directly rather than racing a follow-up poll tick.
      const current = await cancelResearch(run.id);
      stopPolling();
      setRun({
        id: run.id,
        status: current.status,
        message: current.message,
        statistics: current.statistics,
        diagnostics: current.diagnostics,
        clarification: current.clarification,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "could not cancel this research");
    } finally {
      setCancelling(false);
    }
  }

  const isRunning = run !== null && !STOP_POLLING_STATUSES.has(run.status);
  const awaitingClarification = run !== null && run.status === "needs_clarification" && run.clarification !== null;
  const showResults = run !== null && results !== null;
  const showPlainTerminalMessage = run !== null && !isRunning && !awaitingClarification && !showResults;

  return (
    <main className="page">
      <h1>TripFinder</h1>
      <p className="tagline">Opinion-based travel research, aggregated from real discussions.</p>

      <SearchForm onSubmit={handleSearch} disabled={submitting || isRunning} />

      {error && <p className="error">{error}</p>}

      {awaitingClarification && run.clarification && (
        <ClarificationView
          clarification={run.clarification}
          onAnswer={handleClarify}
          submitting={submitting}
        />
      )}

      {isRunning && run && (
        <ProgressView
          status={run.status}
          message={run.message}
          statistics={run.statistics}
          onCancel={handleCancel}
          cancelling={cancelling}
        />
      )}

      {showPlainTerminalMessage && run && (
        <section className="terminal-state" aria-label="Research outcome">
          <p>{run.message}</p>
        </section>
      )}

      {showResults && run && results && <ResultsView researchId={run.id} data={results} />}

      {run && !isRunning && <DiagnosticsSummary diagnostics={run.diagnostics} />}
    </main>
  );
}
