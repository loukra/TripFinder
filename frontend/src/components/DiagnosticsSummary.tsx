"use client";

import type { ResearchDiagnostics } from "@/lib/types";

const FLAG_LABELS: Record<string, string> = {
  low_polling_document_ratio: "Few of the discussions found were open questions — this run may be starved of votable evidence.",
  budget_limit_reached: "This research stopped because it hit a budget or time limit, not because evidence ran out.",
};

interface DiagnosticsSummaryProps {
  diagnostics: ResearchDiagnostics;
}

// Plan §0.1 rule 2: what a run suppressed must reach the UI, not just the
// logs. This renders nothing when there is nothing to disclose.
export function DiagnosticsSummary({ diagnostics }: DiagnosticsSummaryProps) {
  const { source_health: sourceHealth, suppressions, flags } = diagnostics;
  const hasContent = sourceHealth.length > 0 || suppressions.length > 0 || flags.length > 0;
  if (!hasContent) return null;

  return (
    <details className="diagnostics">
      <summary>Data quality details</summary>

      {flags.length > 0 && (
        <ul className="diagnostics-flags">
          {flags.map((flag) => (
            <li key={flag} className="flag">
              {FLAG_LABELS[flag] ?? flag}
            </li>
          ))}
        </ul>
      )}

      {sourceHealth.length > 0 && (
        <table className="diagnostics-table">
          <caption>Source health</caption>
          <thead>
            <tr>
              <th>Source</th>
              <th>Succeeded</th>
              <th>Failed</th>
              <th>Success rate</th>
            </tr>
          </thead>
          <tbody>
            {sourceHealth.map((health) => (
              <tr key={health.adapter}>
                <td>{health.adapter}</td>
                <td>{health.calls_succeeded}</td>
                <td>{health.calls_failed}</td>
                <td>{Math.round(health.success_rate * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {suppressions.length > 0 && (
        <table className="diagnostics-table">
          <caption>Evidence suppressed during this run</caption>
          <thead>
            <tr>
              <th>Step</th>
              <th>Reason</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            {suppressions.map((suppression, index) => (
              <tr key={`${suppression.step}-${suppression.reason}-${index}`}>
                <td>{suppression.step}</td>
                <td>{suppression.reason.replaceAll("_", " ")}</td>
                <td>{suppression.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}
