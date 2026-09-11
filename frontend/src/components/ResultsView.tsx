"use client";

import { useState } from "react";
import { EvidencePanel } from "./EvidencePanel";
import type { ResearchResultsResponse, ResultItem } from "@/lib/types";

interface ResultsViewProps {
  researchId: string;
  data: ResearchResultsResponse;
}

// Presentation-only banding of the numeric `confidence` the API already
// returns. The plan does not fix these cut-points; they exist so the badge
// reads as a word rather than a decimal, and they change nothing about the
// ranking, which stays deterministic and count-ordered (plan §4.3).
function confidenceBand(confidence: number): { label: string; tagClass: string } {
  if (confidence >= 0.66) return { label: "high confidence", tagClass: "tag tag-accent-2" };
  if (confidence >= 0.33) return { label: "medium confidence", tagClass: "tag tag-neutral" };
  return { label: "low confidence", tagClass: "tag tag-outline" };
}

export function ResultsView({ researchId, data }: ResultsViewProps) {
  const { results, message, percentages_suppressed: percentagesSuppressed } = data;

  if (results.length === 0) {
    return (
      <section className="section" aria-label="Results">
        <p>{message}</p>
        <p className="text-muted empty-state">
          No entities gathered enough independent supporters to be reported as a strong
          recommendation this time.
        </p>
      </section>
    );
  }

  const maxSupporterCount = Math.max(...results.map((r) => r.supporter_count));

  return (
    <section className="section rise" aria-label="Results">
      <p className="results-note">{message}</p>

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
  // Bars are scaled by supporter count, never by share: the count is always
  // present, so the chart still reads correctly on a run whose percentages
  // are suppressed (plan §4.4 — bars only, never a pie).
  const barWidthPercent =
    maxSupporterCount > 0 ? (result.supporter_count / maxSupporterCount) * 100 : 0;
  const confidence = confidenceBand(result.confidence);

  return (
    <li className="result-row">
      <div className="result-main">
        <div className="result-figure">
          <div className="result-count">{result.supporter_count}</div>
          <div className="text-muted result-count-label">people</div>
        </div>

        <div className="result-body">
          <div className="result-header">
            <span className="text-muted result-rank">#{rank}</span>
            <h2 className="result-name">{result.entity_name}</h2>
            <span className={`${confidence.tagClass} result-confidence`}>{confidence.label}</span>
          </div>

          <div className="result-bar-track" role="presentation">
            <div className="result-bar-fill" style={{ width: `${barWidthPercent}%` }} />
          </div>

          {result.explanation && <p className="result-explanation">{result.explanation}</p>}

          <p className="result-share">
            {result.share !== null
              ? `${Math.round(result.share * 100)}% of people who answered mentioned this.`
              : "Percentage withheld."}
          </p>

          <div className="result-meta">
            <p className="text-muted result-denominator">
              Based on {result.respondent_pool_size} people across {result.discussion_count} discussion
              {result.discussion_count === 1 ? "" : "s"}.
            </p>
            <button
              type="button"
              className="btn btn-ghost result-evidence-toggle"
              onClick={() => setShowEvidence((prev) => !prev)}
            >
              {showEvidence ? "Hide evidence" : "View evidence"}
            </button>
          </div>
        </div>
      </div>

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
