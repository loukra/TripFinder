"use client";

interface RunStatsProps {
  statistics: Record<string, number>;
}

// The run's own counters, beside the ranking rather than above it, so that
// what the numbers are made of stays visible while they grow — and so the
// ranking keeps its position on the page when the run finishes and these
// become the final tallies.
export function RunStats({ statistics }: RunStatsProps) {
  const entries = Object.entries(statistics);
  if (entries.length === 0) return null;

  return (
    <section className="run-stats" aria-label="What this run has read">
      <h2 className="run-side-heading">Corpus</h2>
      <dl className="stat-grid">
        {entries.map(([key, value]) => (
          <div key={key} className="stat-card">
            <dd>{value.toLocaleString()}</dd>
            <dt className="text-muted">{key.replaceAll("_", " ")}</dt>
          </div>
        ))}
      </dl>
    </section>
  );
}
