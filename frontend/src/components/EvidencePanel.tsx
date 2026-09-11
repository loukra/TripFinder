"use client";

import { useEffect, useState } from "react";
import { ApiError, getEvidence } from "@/lib/api";

const PAGE_SIZE = 10;

interface EvidencePanelProps {
  researchId: string;
  entityId: string;
  entityName: string;
}

// Rendered only once a row's "View evidence" toggle is on (ResultsView), so
// it loads its first page as soon as it mounts rather than gating behind a
// second click.
export function EvidencePanel({ researchId, entityId, entityName }: EvidencePanelProps) {
  const [permalinks, setPermalinks] = useState<string[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  // Starts true: the effect below fetches immediately on mount, and every
  // state setter it uses runs only after that fetch's `await` settles —
  // never synchronously within the effect (react-hooks/set-state-in-effect).
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchPage(nextOffset: number) {
    try {
      const page = await getEvidence(researchId, entityId, PAGE_SIZE, nextOffset);
      setPermalinks((prev) => (nextOffset === 0 ? page.permalinks : [...prev, ...page.permalinks]));
      setTotal(page.total);
      setOffset(nextOffset + page.permalinks.length);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "could not load evidence");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // Deliberate fetch-on-mount: every setState this reaches happens after
    // `fetchPage`'s `await`, not synchronously in the effect body, but the
    // compiler's set-state-in-effect check can't see past that boundary. No
    // data-fetching library is set up in this project yet (plan §10 Phase
    // 14 scope), so this is the plain effect pattern for now.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchPage(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [researchId, entityId]);

  function handleLoadMore() {
    setLoading(true);
    void fetchPage(offset);
  }

  const hasLoaded = total !== null;
  const hasMore = hasLoaded && offset < (total ?? 0);

  return (
    <div className="evidence-panel rise" aria-label={`Evidence for ${entityName}`}>
      {loading && permalinks.length === 0 && <p className="text-muted evidence-count">Loading…</p>}

      {error && <p className="error">{error}</p>}

      {hasLoaded && (
        <>
          {total === 0 ? (
            <p className="text-muted evidence-count">
              No evidence links were retained for this entity.
            </p>
          ) : (
            <>
              <p className="text-muted evidence-count">
                {total} discussion{total === 1 ? "" : "s"} cited as evidence
              </p>
              <ul className="evidence-list">
                {permalinks.map((link) => (
                  <li key={link}>
                    <a href={link} target="_blank" rel="noopener noreferrer">
                      {link}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          )}

          {hasMore && (
            <button
              type="button"
              className="btn btn-secondary evidence-more"
              onClick={handleLoadMore}
              disabled={loading}
            >
              {loading ? "Loading…" : "Load more"}
            </button>
          )}
        </>
      )}
    </div>
  );
}
