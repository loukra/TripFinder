"use client";

import { RESULTS_READY_STATUSES, type ResearchStatus } from "@/lib/types";

interface ProgressViewProps {
  status: ResearchStatus;
  message: string;
  /** Omitted once the run is over — there is nothing left to cancel. */
  onCancel?: () => void;
  cancelling?: boolean;
}

// The pipeline stages a running research passes through, in the order of
// plan §4.6. Each entry is a real `ResearchStatus`, so the checklist is
// driven by what the backend reports rather than by a timer — a stage is
// only ever marked done because the run has moved past it.
const PIPELINE_STAGES: ReadonlyArray<{ status: ResearchStatus; label: string }> = [
  { status: "understanding", label: "Understanding the question" },
  { status: "discovering", label: "Searching discussions" },
  { status: "retrieving", label: "Retrieving comments" },
  { status: "analyzing", label: "Analysing opinions" },
  { status: "aggregating", label: "Counting independent people" },
];

// What the badge says. The backend's status names are identifiers, not words
// a reader should have to decode — and a partial or degraded run must still
// say so here, in the reader's language, not only in a code.
const STATUS_LABELS: Record<ResearchStatus, string> = {
  pending: "Queued",
  understanding: "Understanding",
  needs_clarification: "Needs an answer",
  rejected: "Rejected",
  discovering: "Searching",
  retrieving: "Retrieving",
  analyzing: "Analysing",
  aggregating: "Counting",
  completed: "Complete",
  completed_partial: "Partial result",
  completed_degraded: "Degraded result",
  source_unavailable: "Source unavailable",
  failed: "Failed",
  cancelled: "Cancelled",
};

// This column stays beside the results after the run ends, so that the
// ranking does not move on the page at the moment it becomes final. A
// finished run has therefore passed every stage, and says so; a run that
// stopped early never reaches here (the page leaves the column empty), so
// the checklist never has to guess how far a failure got.
export function ProgressView({ status, message, onCancel, cancelling = false }: ProgressViewProps) {
  const finished = RESULTS_READY_STATUSES.has(status);
  // `pending` is a real running status but sits before the first stage, so it
  // leaves every row waiting rather than claiming progress that has not happened.
  const activeIndex = finished ? -1 : PIPELINE_STAGES.findIndex((stage) => stage.status === status);
  const completedFraction = finished ? 1 : (activeIndex + 1) / PIPELINE_STAGES.length;

  return (
    <section className="run-progress" aria-live="polite" aria-label="Research progress">
      {/* A finished run's message heads the ranking itself; repeating it
          here would print the same paragraph twice side by side. */}
      <p className="progress-status">
        <span className="status-badge">{STATUS_LABELS[status]}</span>
        {!finished && ` ${message}`}
      </p>

      <div className="progress-track" role="presentation">
        <div className="progress-fill" style={{ width: `${Math.round(completedFraction * 100)}%` }} />
      </div>

      <ol className="stage-list">
        {PIPELINE_STAGES.map((stage, index) => {
          const done = finished || (activeIndex >= 0 && index < activeIndex);
          const active = !finished && index === activeIndex;
          const state = done ? "Done" : active ? "In progress" : "Waiting";
          return (
            <li
              key={stage.status}
              className={`stage-row${done ? " is-done" : ""}${active ? " is-active" : ""}`}
            >
              <span className="stage-mark" aria-hidden="true">
                {done ? "✓" : active ? "•" : ""}
              </span>
              <span className="stage-label">{stage.label}</span>
              <span className="text-muted stage-state">{state}</span>
            </li>
          );
        })}
      </ol>

      {onCancel && (
        <div className="progress-actions">
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={cancelling}>
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        </div>
      )}
    </section>
  );
}
