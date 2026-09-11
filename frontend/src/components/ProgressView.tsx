"use client";

import type { ResearchStatus } from "@/lib/types";

interface ProgressViewProps {
  status: ResearchStatus;
  message: string;
  statistics: Record<string, number>;
  onCancel: () => void;
  cancelling: boolean;
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

export function ProgressView({ status, message, statistics, onCancel, cancelling }: ProgressViewProps) {
  const statEntries = Object.entries(statistics);
  // `pending` is a real running status but sits before the first stage, so it
  // leaves every row waiting rather than claiming progress that has not happened.
  const activeIndex = PIPELINE_STAGES.findIndex((stage) => stage.status === status);
  const completedFraction = (activeIndex + 1) / PIPELINE_STAGES.length;

  return (
    <section className="section" aria-live="polite" aria-label="Research progress">
      <p className="progress-status">
        <span className="status-badge">{status}</span> {message}
      </p>

      <div className="progress-track" role="presentation">
        <div className="progress-fill" style={{ width: `${Math.round(completedFraction * 100)}%` }} />
      </div>

      <ol className="stage-list">
        {PIPELINE_STAGES.map((stage, index) => {
          const done = activeIndex >= 0 && index < activeIndex;
          const active = index === activeIndex;
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

      {statEntries.length > 0 && (
        <dl className="stat-grid">
          {statEntries.map(([key, value]) => (
            <div key={key} className="stat-card">
              <dd>{value.toLocaleString()}</dd>
              <dt className="text-muted">{key.replaceAll("_", " ")}</dt>
            </div>
          ))}
        </dl>
      )}

      <div className="progress-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={cancelling}>
          {cancelling ? "Cancelling…" : "Cancel"}
        </button>
      </div>
    </section>
  );
}
