"use client";

import { useCallback, useState } from "react";
import { EvidencePanel } from "./EvidencePanel";
import type { ResearchResultsResponse, ResultItem } from "@/lib/types";

interface ResultsViewProps {
  researchId: string;
  data: ResearchResultsResponse;
}

interface Hold {
  keys: ReadonlySet<string>;
  frozen: ResearchResultsResponse | null;
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
  // What the reader is currently busy with: a row hovered or focused, or an
  // evidence panel open. A provisional list reorders as counts grow (plan
  // §2.13.1), which is honest — except at the moment it moves a row out from
  // under someone reading it. So while anything is held the view keeps
  // showing what was on screen when the hold began, and takes the newest
  // data the moment the hold ends.
  const [hold, setHold] = useState<Hold>(() => ({ keys: new Set(), frozen: null }));

  const setRowHeld = useCallback(
    (key: string, held: boolean) => {
      setHold((previous) => {
        if (previous.keys.has(key) === held) return previous;
        const keys = new Set(previous.keys);
        if (held) keys.add(key);
        else keys.delete(key);
        // The freeze captures what is on screen when the first hold starts
        // and is released when the last one ends.
        return { keys, frozen: keys.size === 0 ? null : (previous.frozen ?? data) };
      });
    },
    [data]
  );

  const shown = hold.frozen ?? data;
  const { results, weak_results: weakResults, message, provisional } = shown;
  const percentagesSuppressed = shown.percentages_suppressed;

  // While a run is provisional the weak list is shown alongside the strong
  // one: after the first batches nobody has cleared §4.4's five supporters,
  // and padding the strong list to fill the page is exactly what §4.4
  // forbids. A finished run keeps the headline list it always had.
  const candidates = provisional ? weakResults : [];

  if (results.length === 0 && candidates.length === 0) {
    return (
      <section className="section" aria-label="Results">
        <p>{message}</p>
        <p className="text-muted empty-state">
          {provisional
            ? "Nothing counted yet. The first comments are still being read — anything that appears here will be something somebody actually wrote."
            : "No entities gathered enough independent supporters to be reported as a strong recommendation this time."}
        </p>
      </section>
    );
  }

  // Bars are scaled against the largest count on the page, so the strong and
  // candidate lists stay on one scale and a candidate never draws a longer
  // bar than a result above it.
  const maxSupporterCount = Math.max(
    1,
    ...[...results, ...candidates].map((result) => result.supporter_count)
  );

  return (
    <section className="section rise" aria-label="Results">
      {provisional && (
        <p className="banner banner-provisional">
          Still counting — these numbers can only grow.
        </p>
      )}

      <p className="results-note">{message}</p>

      {percentagesSuppressed && !provisional && (
        <p className="banner banner-degraded">
          Percentages are withheld for this run — see the message above for why.
        </p>
      )}

      {results.length > 0 && (
        <>
          {provisional && (
            <h2 className="results-group-heading">Ahead so far</h2>
          )}
          <ol className="result-list">
            {results.map((result, index) => (
              <ResultRow
                key={result.entity_id}
                researchId={researchId}
                result={result}
                rank={provisional ? null : index + 1}
                provisional={provisional}
                maxSupporterCount={maxSupporterCount}
                onHoldChange={setRowHeld}
              />
            ))}
          </ol>
        </>
      )}

      {candidates.length > 0 && (
        <>
          <h2 className="results-group-heading">Candidates so far</h2>
          <p className="text-muted results-group-note">
            Fewer than five different people have recommended each of these yet, so none of them
            counts as a recommendation. Nothing here is padding out the list above.
          </p>
          <ol className="result-list">
            {candidates.map((result) => (
              <ResultRow
                key={result.entity_id}
                researchId={researchId}
                result={result}
                rank={null}
                provisional
                maxSupporterCount={maxSupporterCount}
                onHoldChange={setRowHeld}
              />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

interface ResultRowProps {
  researchId: string;
  result: ResultItem;
  rank: number | null;
  provisional: boolean;
  maxSupporterCount: number;
  onHoldChange: (key: string, held: boolean) => void;
}

function ResultRow({
  researchId,
  result,
  rank,
  provisional,
  maxSupporterCount,
  onHoldChange,
}: ResultRowProps) {
  const [showEvidence, setShowEvidence] = useState(false);
  // Two reasons a row can be held, tracked separately: the mouse can leave a
  // row whose evidence panel is still open, and that row is still being read.
  const pointerKey = `${result.entity_id}:pointer`;
  const evidenceKey = `${result.entity_id}:evidence`;

  function toggleEvidence() {
    const next = !showEvidence;
    setShowEvidence(next);
    onHoldChange(evidenceKey, next);
  }

  // Bars are scaled by supporter count, never by share: the count is always
  // present, so the chart still reads correctly on a run whose percentages
  // are suppressed (plan §4.4 — bars only, never a pie).
  const barWidthPercent =
    maxSupporterCount > 0 ? (result.supporter_count / maxSupporterCount) * 100 : 0;
  const confidence = confidenceBand(result.confidence);

  return (
    <li
      className="result-row"
      onMouseEnter={() => onHoldChange(pointerKey, true)}
      onMouseLeave={() => onHoldChange(pointerKey, false)}
      onFocus={() => onHoldChange(pointerKey, true)}
      onBlur={() => onHoldChange(pointerKey, false)}
    >
      <div className="result-main">
        <div className="result-figure">
          <div className="result-count">{result.supporter_count}</div>
          <div className="text-muted result-count-label">people</div>
        </div>

        <div className="result-body">
          <div className="result-header">
            {/* No rank number while the list is still moving: a podium
                position is a claim the counts cannot support yet. */}
            {rank !== null && <span className="text-muted result-rank">#{rank}</span>}
            <h3 className="result-name">{result.entity_name}</h3>
            <span className={`${confidence.tagClass} result-confidence`}>{confidence.label}</span>
          </div>

          <div className="result-bar-track" role="presentation">
            <div className="result-bar-fill" style={{ width: `${barWidthPercent}%` }} />
          </div>

          {result.explanation && <p className="result-explanation">{result.explanation}</p>}

          <p className="result-share">
            {result.share !== null
              ? `${Math.round(result.share * 100)}% of people who answered mentioned this.`
              : provisional
                ? "No percentage yet — we can only work one out once every comment has been read."
                : "Percentage withheld."}
          </p>

          <div className="result-meta">
            <p className="text-muted result-denominator">
              Based on {result.respondent_pool_size} people across {result.discussion_count} discussion
              {result.discussion_count === 1 ? "" : "s"}
              {provisional ? " so far." : "."}
            </p>
            <button
              type="button"
              className="btn btn-ghost result-evidence-toggle"
              onClick={toggleEvidence}
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
