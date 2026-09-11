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
  // A provisional list reorders as counts grow (plan §2.13.1), which is
  // honest — except at the moment it moves a row out from under someone who
  // has opened its evidence. So an open evidence panel holds the view where
  // it was, and it takes the newest data the moment the panel closes.
  //
  // **Two bounds, both of them learned the hard way.** The first version
  // also held on hover and on focus, and held the *data* rather than the
  // provisional data — so a pointer resting anywhere on the list froze the
  // page, and the freeze outlived the run: the final answer arrived and was
  // never shown, under a banner still promising that the numbers were
  // growing. A view that withholds the finished result is worse than one
  // that reorders under a cursor, and a banner that describes a state the
  // page is no longer in is exactly the §0.1 failure in miniature. So:
  // nothing holds a finished run, and only a deliberate act — opening
  // evidence — holds an unfinished one.
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

  // A finished run is the answer. It always lands, whatever is being read.
  const shown = data.provisional ? (hold.frozen ?? data) : data;
  const { results, weak_results: weakResults, message, provisional } = shown;
  const percentagesSuppressed = shown.percentages_suppressed;
  const threshold = shown.minimum_independent_users;

  // While a run is provisional the weak list is shown alongside the strong
  // one: after the first batches nobody has cleared §4.4's five supporters,
  // and padding the strong list to fill the page is exactly what §4.4
  // forbids. A finished run keeps the headline list it always had.
  const candidates = provisional ? weakResults : [];

  // Two different reasons an entity is not in the headline list, and they
  // say opposite things about it: one has too few independent people to
  // count yet, the other has plenty and merely lost a seat to §4.4's cap of
  // five. Labelling the second as the first states something false about a
  // real count — which is the whole §0.1 failure mode, in miniature.
  const belowCap = candidates.filter((result) => result.supporter_count >= threshold);
  const belowThreshold = candidates.filter((result) => result.supporter_count < threshold);

  // The respondent pool is the same number on every row — it is the run's
  // denominator, not a fact about any one entity — so while there is no
  // percentage to explain it, it is stated once for the page instead of
  // being repeated beside counts it could be mistaken for.
  const pool = [...results, ...candidates][0]?.respondent_pool_size ?? 0;

  if (results.length === 0 && candidates.length === 0) {
    return (
      <section className="section" aria-label="Results">
        {provisional && (
          <p className="banner banner-provisional">
            <strong>Provisional result</strong> — still counting.
          </p>
        )}
        <div className="panel">
          <p>{message}</p>
          <p className="text-muted empty-state">
            {provisional
              ? "Nothing counted yet. The first comments are still being read — anything that appears here will be something somebody actually wrote."
              : "No entities gathered enough independent supporters to be reported as a strong recommendation this time."}
          </p>
        </div>
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
      {/* The provisional ranking is drawn exactly like the finished one —
          same rows, same ranks, same place on the page — and says what it is
          in a banner above rather than in a different layout. Plan §2.13.1
          allows this: the order may still move, and a list under an explicit
          provisional label is behaving as promised. */}
      {provisional && (
        <p className="banner banner-provisional">
          <strong>Provisional result</strong> — still counting, and these numbers can only grow.
          {pool > 0 && ` ${pool} people have given an opinion we can count so far.`}
        </p>
      )}

      <p className="results-note">{message}</p>

      {percentagesSuppressed && !provisional && (
        <p className="banner banner-degraded">
          Percentages are withheld for this run — see the message above for why.
        </p>
      )}

      {results.length > 0 && (
        <ol className="result-list">
          {results.map((result, index) => (
            <ResultRow
              key={result.entity_id}
              researchId={researchId}
              result={result}
              rank={index + 1}
              provisional={provisional}
              maxSupporterCount={maxSupporterCount}
              onHoldChange={setRowHeld}
            />
          ))}
        </ol>
      )}

      {belowCap.length > 0 && (
        <CandidateGroup
          researchId={researchId}
          heading="Also ranked"
          note={`Enough different people have recommended each of these to count, but the list above shows at most five.`}
          results={belowCap}
          maxSupporterCount={maxSupporterCount}
          onHoldChange={setRowHeld}
        />
      )}

      {belowThreshold.length > 0 && (
        <CandidateGroup
          researchId={researchId}
          heading="Not enough people yet"
          note={`Fewer than ${threshold} different people have recommended each of these so far, so none of them counts as a recommendation yet. Nothing here is padding out the list above.`}
          results={belowThreshold}
          maxSupporterCount={maxSupporterCount}
          onHoldChange={setRowHeld}
        />
      )}
    </section>
  );
}

interface CandidateGroupProps {
  researchId: string;
  heading: string;
  note: string;
  results: ResultItem[];
  maxSupporterCount: number;
  onHoldChange: (key: string, held: boolean) => void;
}

function CandidateGroup({
  researchId,
  heading,
  note,
  results,
  maxSupporterCount,
  onHoldChange,
}: CandidateGroupProps) {
  return (
    <>
      <h2 className="results-group-heading">{heading}</h2>
      <p className="text-muted results-group-note">{note}</p>
      <ol className="result-list">
        {results.map((result) => (
          <ResultRow
            key={result.entity_id}
            researchId={researchId}
            result={result}
            rank={null}
            provisional
            maxSupporterCount={maxSupporterCount}
            onHoldChange={onHoldChange}
          />
        ))}
      </ol>
    </>
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
    <li className="result-row">
      <div className="result-main">
        <div className="result-figure">
          <div className="result-count">{result.supporter_count}</div>
          <div className="text-muted result-count-label">people</div>
        </div>

        <div className="result-body">
          <div className="result-header">
            {/* The rank is the list's current order, provisional or not; the
                banner above says which of the two it is. */}
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
              {provisional ? (
                // The pool is stated once for the page, above: repeating it
                // here, beside a count of this entity's own supporters,
                // invites reading one as the other.
                <>
                  Recommended in {result.discussion_count} discussion
                  {result.discussion_count === 1 ? "" : "s"} so far.
                </>
              ) : (
                <>
                  Based on {result.respondent_pool_size} people across {result.discussion_count}{" "}
                  discussion{result.discussion_count === 1 ? "" : "s"}.
                </>
              )}
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
