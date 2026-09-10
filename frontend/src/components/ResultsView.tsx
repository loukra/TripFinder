"use client";

import { useState } from "react";
import { EvidencePanel } from "./EvidencePanel";
import type { ResearchResultsResponse, ResultItem } from "@/lib/types";

interface ResultsViewProps {
  researchId: string;
  data: ResearchResultsResponse;
}

export function ResultsView({ researchId, data }: ResultsViewProps) {
  const { results, message, percentages_suppressed: percentagesSuppressed } = data;

  if (results.length === 0) {
    return (
      <section className="results" aria-label="Results">
        <p>{message}</p>
        <p className="empty-state">
          No entities gathered enough independent supporters to be reported as a strong
          recommendation this time.
        </p>
      </section>
    );
  }

  const maxSupporterCount = Math.max(...results.map((r) => r.supporter_count));

  return (
    <section className="results" aria-label="Results">
      <p>{message}</p>
      {percentagesSuppressed && (
        <p className="banner banner-degraded">
          Percentages are withheld for this run — see the message above for why.
        </p>
      )}
      <ol className="result-list">
        {results.map((result, index) => (
          <ResultRow
            key={result.entity_id}
            researchId={researchId}
            result={result}
            rank={index + 1}
            maxSupporterCount={maxSupporterCount}
          />
        ))}
      </ol>
    </section>
  );
}

interface ResultRowProps {
  researchId: string;
  result: ResultItem;
  rank: number;
  maxSupporterCount: number;
}

function ResultRow({ researchId, result, rank, maxSupporterCount }: ResultRowProps) {
  const [showEvidence, setShowEvidence] = useState(false);
  const barWidthPercent =
    maxSupporterCount > 0 ? (result.supporter_count / maxSupporterCount) * 100 : 0;

  return (
    <li className="result-row">
      <div className="result-header">
        <span className="result-rank">{rank}.</span>
        <span className="result-name">{result.entity_name}</span>
      </div>

      <div className="result-bar-track" role="presentation">
        <div className="result-bar-fill" style={{ width: `${barWidthPercent}%` }} />
      </div>

      <p className="result-counts">
        <strong>{result.supporter_count}</strong> people recommended this.
        {result.share !== null
          ? ` ${Math.round(result.share * 100)}% of people who answered mentioned this.`
          : " Percentage withheld."}
      </p>
      <p className="result-denominator">
        Based on {result.respondent_pool_size} people across {result.discussion_count} discussion
        {result.discussion_count === 1 ? "" : "s"}.
      </p>

      {result.explanation && <p className="result-explanation">{result.explanation}</p>}

      <button type="button" onClick={() => setShowEvidence((prev) => !prev)}>
        {showEvidence ? "Hide evidence" : "View evidence"}
      </button>

      {showEvidence && (
        <EvidencePanel
          researchId={researchId}
          entityId={result.entity_id}
          entityName={result.entity_name}
        />
      )}
    </li>
  );
}
