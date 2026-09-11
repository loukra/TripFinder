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
  RESULTS_AVAILABLE_STATUSES,
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

const HOW_IT_WORKS = [
  {
    title: "Real discussions",
    body: "The agent searches communities for threads where people answer this kind of question.",
  },
  {
    title: "One person, one vote",
    body: "Repeat commenters are de-duplicated, so enthusiasm cannot inflate a place.",
  },
  {
    title: "Evidence attached",
    body: "Every ranking links back to the comments it was counted from.",
  },
];

export default function Home() {
  const [run, setRun] = useState<RunState | null>(null);
  const [query, setQuery] = useState("");
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

  // A run that is still analysing already has a ranking worth showing (plan
  // §2.13), so results are fetched on every tick from that point on, not only
  // once the run is finished. A provisional fetch is allowed to fail quietly:
  // the run is mid-flight, the snapshot may not be written yet, and a
  // cancelled run that never got as far as analysis has no results object at
  // all — none of which is a reason to tear the page down.
  const loadResults = useCallback(async (id: string, optional: boolean): Promise<void> => {
    try {
      setResults(await getResults(id));
    } catch (err) {
      if (optional) return;
      setError(err instanceof ApiError ? err.message : "could not load these results");
    }
  }, []);

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

        if (STOP_POLLING_STATUSES.has(current.status)) stopPolling();
        if (RESULTS_AVAILABLE_STATUSES.has(current.status)) {
          await loadResults(id, !RESULTS_READY_STATUSES.has(current.status));
        } else {
          // A run that had been showing provisional results and then failed,
          // or lost its source, has no results object any more (§8.1 rule 1,
          // §0.1 rule 3). Leaving the last snapshot on screen would let a
          // broken run keep displaying a ranking as though it had finished.
          setResults(null);
        }
        return current.status;
      } catch (err) {
        stopPolling();
        setError(err instanceof ApiError ? err.message : "could not check research status");
        return null;
      }
    },
    [loadResults, stopPolling]
  );

  function startPolling(id: string) {
    stopPolling();
    pollHandle.current = setInterval(() => {
      void applyStatus(id);
    }, getPollIntervalMs());
  }

  function handleReset() {
    stopPolling();
    setRun(null);
    setResults(null);
    setError(null);
    setQuery("");
  }

  async function handleSearch(submittedQuery: string) {
    setError(null);
    setResults(null);
    setRun(null);
    setQuery(submittedQuery);
    setSubmitting(true);
    try {
      const created = await createResearch(submittedQuery);
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
      // A run cancelled during analysis keeps the evidence it had paid for
      // (plan §2.13.3); one cancelled earlier has nothing, and says so by
      // 409, which is why this fetch is optional.
      if (RESULTS_AVAILABLE_STATUSES.has(current.status)) {
        await loadResults(run.id, true);
      }
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

  const kicker = awaitingClarification
    ? "Before we start"
    : isRunning
      ? "Researching"
      : showResults
        ? "Results"
        : "Research outcome";

  return (
    <>
      <header className="site-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">TripFinder</span>
        </div>
      </header>

      <main className="page">
        {run === null ? (
          <section className="hero">
            <p className="hero-kicker">Opinion research</p>
            <h1 className="hero-title">Ask the people who actually went.</h1>
            <p className="text-muted hero-lede">
              TripFinder reads real discussions, counts independent opinions and ranks what comes
              out. Nothing here is invented.
            </p>

            <SearchForm onSubmit={handleSearch} disabled={submitting} />

            {error && <p className="error">{error}</p>}

            <ul className="how-it-works">
              {HOW_IT_WORKS.map((item) => (
                <li key={item.title} className="how-card">
                  <span className="how-card-title">{item.title}</span>
                  <span className="text-muted how-card-body">{item.body}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <>
            <div className="run-head">
              <div className="section-head-main">
                <p className="text-muted section-kicker">{kicker}</p>
                <h1 className="section-query">{query}</h1>
              </div>
              <button type="button" className="btn btn-secondary" onClick={handleReset}>
                New research
              </button>
            </div>

            {error && <p className="error">{error}</p>}

            {awaitingClarification && run.clarification && (
              <ClarificationView
                clarification={run.clarification}
                onAnswer={handleClarify}
                submitting={submitting}
              />
            )}

            {isRunning && (
              <ProgressView
                status={run.status}
                message={run.message}
                statistics={run.statistics}
                onCancel={handleCancel}
                cancelling={cancelling}
              />
            )}

            {showPlainTerminalMessage && (
              <section className="terminal-state" aria-label="Research outcome">
                <p>{run.message}</p>
              </section>
            )}

            {showResults && results && <ResultsView researchId={run.id} data={results} />}

            {!isRunning && <DiagnosticsSummary diagnostics={run.diagnostics} />}
          </>
        )}
      </main>
    </>
  );
}
