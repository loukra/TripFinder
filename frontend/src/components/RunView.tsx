"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  cancelResearch,
  clarifyResearch,
  getPollIntervalMs,
  getResearch,
  getResults,
} from "@/lib/api";
import { ClarificationView } from "@/components/ClarificationView";
import { DiagnosticsSummary } from "@/components/DiagnosticsSummary";
import { ProgressView } from "@/components/ProgressView";
import { ResultsView } from "@/components/ResultsView";
import { RunStats } from "@/components/RunStats";
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
  query: string;
  statistics: Record<string, number>;
  diagnostics: ResearchDiagnostics;
  clarification: ClarificationRequest | null;
}

// How many status fetches in a row may fail before the page stops claiming
// to be watching a run. One is a blip; three is a page that has lost the run.
const MAX_POLL_FAILURES = 3;

/**
 * One research run, at its own URL (plan §2.15, Phase 14.9).
 *
 * Everything this view knows about the run it asks the API for, including
 * the question. That is what makes the URL worth having: the run outlives
 * the tab that started it, so a page reached from history, a bookmark or a
 * reload shows exactly what the page that started it showed — the same
 * ranking, the same statistics, the same diagnostics — without re-running
 * anything.
 */
export function RunView({ researchId }: { researchId: string }) {
  const [run, setRun] = useState<RunState | null>(null);
  const [results, setResults] = useState<ResearchResultsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  // Consecutive failed status fetches. A single blip — the API restarting,
  // a dropped connection — is not a reason to abandon a run that is still
  // working; several in a row are.
  const [pollFailures, setPollFailures] = useState(0);
  // Which run the page is currently showing. A status fetch started before
  // the user cancelled may land after it, and applying it would resurrect a
  // status the page has already left — a poll tick undoing a cancellation
  // the user watched happen.
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
          query: current.query,
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
        // A URL for a run that does not exist is its own outcome, not a
        // failed poll: there is nothing to keep checking on.
        if (err instanceof ApiError && err.status === 404) {
          setMissing(true);
          return null;
        }
        setPollFailures((previous) => previous + 1);
        setError(err instanceof ApiError ? err.message : "could not check research status");
        return null;
      }
    },
    [loadResults]
  );

  // The first fetch. A run reached by URL is not necessarily new — it may
  // have finished months ago — so nothing here assumes it is still moving.
  // Queued on the next tick rather than started inside the effect body: the
  // page is subscribing to a run, not computing state it could have
  // rendered (react-hooks/set-state-in-effect).
  useEffect(() => {
    const handle = setTimeout(() => void applyStatus(researchId), 0);
    return () => clearTimeout(handle);
  }, [researchId, applyStatus]);

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
        query: current.query,
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

  if (missing) {
    return (
      <main className="page page-run">
        <section className="terminal-state" aria-label="Research outcome">
          <p>
            There is no research with this id. It may have been started on a different
            installation, or the link may be mistyped.
          </p>
          <Link className="btn btn-secondary" href="/history">
            Back to history
          </Link>
        </section>
      </main>
    );
  }

  if (run === null) {
    return (
      <main className="page page-run">
        <section className="terminal-state" aria-label="Research outcome">
          <p className="text-muted">{error ?? "Opening this research…"}</p>
        </section>
      </main>
    );
  }

  const awaitingClarification = run.status === "needs_clarification" && run.clarification !== null;
  const showResults = results !== null;
  const showPlainTerminalMessage = !isRunning && !awaitingClarification && !showResults;

  // The progress column stays beside the ranking after the run finishes, so
  // that the top five does not jump up the page the moment it becomes final.
  // A run that stopped early leaves the column empty rather than guessing how
  // far it got.
  const showProgress = isRunning || RESULTS_READY_STATUSES.has(run.status);

  const kicker = awaitingClarification
    ? "Before we start"
    : isRunning
      ? "Researching"
      : showResults
        ? "Results"
        : "Research outcome";

  return (
    <main className="page page-run">
      <div className="run-head">
        <div className="section-head-main">
          <p className="text-muted section-kicker">{kicker}</p>
          <h1 className="section-query">{run.query}</h1>
        </div>
        <Link className="btn btn-secondary" href="/">
          New research
        </Link>
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
    </main>
  );
}
