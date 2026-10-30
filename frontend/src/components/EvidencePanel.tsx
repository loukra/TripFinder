"use client";

import { useEffect, useState } from "react";
import { ApiError, getEvidence } from "@/lib/api";

const PAGE_SIZE = 10;

// `/r/<community>/comments/<post id>/<title slug>/<comment id>/`
const REDDIT_COMMENT = /^\/r\/([^/]+)\/comments\/([^/]+)\/([^/]+)\/([^/]+)\/?$/;

interface DescribedPermalink {
  /** Same for every comment in one thread. */
  threadKey: string;
  thread: string;
  community: string;
}

/**
 * A comment permalink as a reader would name it: the thread it was written
 * in and where. The link itself is unchanged; only its text is. Anything
 * that is not a Reddit comment URL keeps its raw address — an unfamiliar
 * link shown as-is is better than one shown under a guessed name.
 */
export function describePermalink(link: string): DescribedPermalink | null {
  let path: string;
  try {
    path = new URL(link).pathname;
  } catch {
    return null;
  }
  const match = REDDIT_COMMENT.exec(path);
  if (!match) return null;
  const thread = match[3].replaceAll("_", " ").trim();
  if (thread === "") return null;
  return {
    threadKey: `${match[1]}/${match[2]}`,
    thread: thread[0].toUpperCase() + thread.slice(1),
    community: `r/${match[1]}`,
  };
}

type EvidenceGroup =
  | { kind: "thread"; key: string; thread: string; community: string; links: string[] }
  | { kind: "raw"; key: string; link: string };

// Several supporters often answered in the same thread. Listed one per row,
// the thread title repeats down the panel; grouped, each thread is named
// once and every comment keeps its own link — one person, one link, as
// counted. Groups keep the order their first comment arrived in.
function groupByThread(permalinks: string[]): EvidenceGroup[] {
  const groups: EvidenceGroup[] = [];
  const byThread = new Map<string, Extract<EvidenceGroup, { kind: "thread" }>>();
  for (const link of permalinks) {
    const described = describePermalink(link);
    if (!described) {
      groups.push({ kind: "raw", key: link, link });
      continue;
    }
    const existing = byThread.get(described.threadKey);
    if (existing) {
      existing.links.push(link);
      continue;
    }
    const group = {
      kind: "thread" as const,
      key: described.threadKey,
      thread: described.thread,
      community: described.community,
      links: [link],
    };
    byThread.set(described.threadKey, group);
    groups.push(group);
  }
  return groups;
}

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
                {total} comment{total === 1 ? "" : "s"} cited as evidence
              </p>
              <ul className="evidence-list">
                {groupByThread(permalinks).map((group) =>
                  group.kind === "raw" ? (
                    <li key={group.key}>
                      <a
                        className="evidence-raw"
                        href={group.link}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {group.link}
                      </a>
                    </li>
                  ) : (
                    <li key={group.key} className="evidence-thread-card">
                      <span className="evidence-thread">{group.thread}</span>
                      <span className="evidence-meta">
                        <span className="text-muted">{group.community}</span>
                        {group.links.map((link, index) => (
                          <a
                            key={link}
                            className="evidence-comment"
                            href={link}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`Comment ${index + 1} in "${group.thread}"`}
                          >
                            comment {index + 1} ↗
                          </a>
                        ))}
                      </span>
                    </li>
                  )
                )}
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
