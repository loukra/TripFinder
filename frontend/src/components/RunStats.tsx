"use client";

interface RunStatsProps {
  statistics: Record<string, number>;
}

// The counters a reader needs to judge the ranking: how much was read and how
// many independent people it was counted from. Everything else the run
// reports is real but diagnostic, and sixty tiles of it beside the ranking
// bury these four.
const HEADLINE_STATS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "documents_retrieved", label: "discussions read" },
  { key: "comments_analyzed", label: "comments analysed" },
  { key: "respondent_pool_size", label: "people who answered" },
  { key: "opinions_counted", label: "opinions counted" },
];

const HEADLINE_KEYS = new Set(HEADLINE_STATS.map((stat) => stat.key));

// The run's own counters, beside the ranking rather than above it, so that
// what the numbers are made of stays visible while they grow — and so the
// ranking keeps its position on the page when the run finishes and these
// become the final tallies.
export function RunStats({ statistics }: RunStatsProps) {
  const entries = Object.entries(statistics);
  if (entries.length === 0) return null;

  const headline = HEADLINE_STATS.filter((stat) => stat.key in statistics);
  // Nothing is dropped: the rest stays one click away, under the names the
  // backend reports them by.
  const rest = entries.filter(([key]) => !HEADLINE_KEYS.has(key));

  return (
    <section className="run-stats" aria-label="What this run has read">
      <h2 className="run-side-heading">Corpus</h2>
      {headline.length > 0 && (
        <dl className="stat-grid">
          {headline.map(({ key, label }) => (
            <div key={key} className="stat-card">
              <dd>{statistics[key].toLocaleString()}</dd>
              <dt className="text-muted">{label}</dt>
            </div>
          ))}
        </dl>
      )}
      {rest.length > 0 && (
        <details className="stat-more" open={headline.length === 0}>
          <summary>All counters ({rest.length})</summary>
          <dl className="stat-list">
            {rest.map(([key, value]) => (
              <div key={key} className="stat-list-row">
                <dt className="text-muted">{key.replaceAll("_", " ")}</dt>
                <dd>{value.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </section>
  );
}
