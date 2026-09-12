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
import { RunStats } from "@/components/RunStats";
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

// How many status fetches in a row may fail before the page stops claiming
// to be watching a run. One is a blip; three is a page that has lost the run.
const MAX_POLL_FAILURES = 3;

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
  // Consecutive failed status fetches. A single blip — the API restarting,
  // a dropped connection — is not a reason to abandon a run that is still
  // working; several in a row are.
  const [pollFailures, setPollFailures] = useState(0);
  // Which run the page is currently showing. A status fetch started before
  // the user cancelled, reset or searched again may land after it, and
  // applying it would resurrect a status the page has already left — a poll
  // tick undoing a cancellation the user watched happen.
  const generation = useRef(0);
  // A run the page has already seen finish, cancel or fail. A status fetch
  // in flight when that happened returns the older, still-running status,
  // and applying it would put a cancelled run back on screen as a live one.
  // The backend never walks a terminal status backwards; neither may this.
  const settled = useRef<string | null>(null);

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
      const mine = generation.current;
      try {
        const current = await getResearch(id);
        if (mine !== generation.current || settled.current === id) return null;
        if (STOP_POLLING_STATUSES.has(current.status)) settled.current = id;
        setRun({
          id,
          status: current.status,
          message: current.message,
          statistics: current.statistics,
          diagnostics: current.diagnostics,
          clarification: current.clarification,
        });

        setPollFailures(0);
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
        if (mine !== generation.current) return null;
        setPollFailures((previous) => previous + 1);
        setError(err instanceof ApiError ? err.message : "could not check research status");
        return null;
      }
    },
    [loadResults]
  );

  function handleReset() {
    generation.current += 1;
    settled.current = null;
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
    generation.current += 1;
    settled.current = null;
    try {
      const created = await createResearch(submittedQuery);
      setPollFailures(0);
      await applyStatus(created.id);
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
      // `needs_clarification` halts a run without ending it (plan §6): the
      // answer is exactly what un-settles it.
      settled.current = null;
      setPollFailures(0);
      await applyStatus(run.id);
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
      // The cancel response is the newest truth about this run; anything
      // still in flight, or still to be dispatched by an interval that has
      // not been torn down yet, is older than it.
      generation.current += 1;
      if (STOP_POLLING_STATUSES.has(current.status)) settled.current = run.id;
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

  const runId = run?.id ?? null;
  const isRunning = run !== null && !STOP_POLLING_STATUSES.has(run.status);
  const lostTheRun = pollFailures >= MAX_POLL_FAILURES;

  // **The interval belongs to the run, not to the click that started it.**
  // Started from an event handler, it is orphaned by anything that remounts
  // the page — a hot reload in development, an error boundary retry — and
  // the page then sits on its last snapshot for ever, under a banner still
  // promising that the numbers are growing. That is §0.1's failure mode
  // wearing a UI: a stalled page that looks like a live one. Owned here, a
  // mounted page showing a running research is by construction polling one.
  useEffect(() => {
    if (runId === null || !isRunning || lostTheRun) return;
    const handle = setInterval(() => void applyStatus(runId), getPollIntervalMs());
    return () => clearInterval(handle);
  }, [runId, isRunning, lostTheRun, applyStatus]);

  const awaitingClarification = run !== null && run.status === "needs_clarification" && run.clarification !== null;
  const showResults = run !== null && results !== null;
  const showPlainTerminalMessage = run !== null && !isRunning && !awaitingClarification && !showResults;

  // The progress column stays beside the ranking after the run finishes, so
  // that the top five does not jump up the page the moment it becomes final.
  // A run that stopped early leaves the column empty rather than guessing how
  // far it got.
  const showProgress = isRunning || (run !== null && RESULTS_READY_STATUSES.has(run.status));

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

      <main className={`page${run === null ? "" : " page-run"}`}>
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

            {/* One layout for the whole run: the ranking holds the middle
                column from the first provisional snapshot to the final
                answer, with where-we-are on its left and what-we-have-read
                on its right. */}
            <div className="run-layout">
              <aside className="run-side">
                {showProgress && (
                  <ProgressView
                    status={run.status}
                    message={run.message}
                    onCancel={isRunning ? handleCancel : undefined}
                    cancelling={cancelling}
                  />
                )}
              </aside>

              <div className="run-main">
                {awaitingClarification && run.clarification && (
                  <ClarificationView
                    clarification={run.clarification}
                    onAnswer={handleClarify}
                    submitting={submitting}
                  />
                )}

                {showPlainTerminalMessage && (
                  <section className="terminal-state" aria-label="Research outcome">
                    <p>{run.message}</p>
                  </section>
                )}

                {lostTheRun && isRunning && (
                  <p className="banner banner-degraded">
                    This page stopped getting updates from the research. What is below is the last
                    ranking it received, not a finished result — the research itself may still be
                    running.{" "}
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => {
                        setPollFailures(0);
                        setError(null);
                        void applyStatus(run.id);
                      }}
                    >
                      Check again
                    </button>
                  </p>
                )}

                {showResults && results && (
                  <ResultsView researchId={run.id} data={results} live={!lostTheRun} />
                )}

                {isRunning && !showResults && !awaitingClarification && (
                  <section className="section" aria-label="Results">
                    <p className="banner banner-provisional">
                      <strong>Provisional result</strong> — still counting.
                    </p>
                    <div className="panel">
                      <p className="text-muted empty-state">
                        Nothing counted yet. The first comments are still being read — anything that
                        appears here will be something somebody actually wrote.
                      </p>
                    </div>
                  </section>
                )}

                {!isRunning && <DiagnosticsSummary diagnostics={run.diagnostics} />}
              </div>

              <aside className="run-side">
                <RunStats statistics={run.statistics} />
              </aside>
            </div>
          </>
        )}
      </main>
    </>
  );
}
