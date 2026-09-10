"use client";

import type { ResearchStatus } from "@/lib/types";

interface ProgressViewProps {
  status: ResearchStatus;
  message: string;
  statistics: Record<string, number>;
  onCancel: () => void;
  cancelling: boolean;
}

export function ProgressView({ status, message, statistics, onCancel, cancelling }: ProgressViewProps) {
  const statEntries = Object.entries(statistics);

  return (
    <section className="progress" aria-live="polite" aria-label="Research progress">
      <p className="progress-status">
        <span className="status-badge">{status}</span> {message}
      </p>

      {statEntries.length > 0 && (
        <dl className="progress-stats">
          {statEntries.map(([key, value]) => (
            <div key={key} className="progress-stat">
              <dt>{key.replaceAll("_", " ")}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <button type="button" onClick={onCancel} disabled={cancelling}>
        {cancelling ? "Cancelling…" : "Cancel"}
      </button>
    </section>
  );
}
