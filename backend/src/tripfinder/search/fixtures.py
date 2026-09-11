"""Canned web search hits for :class:`FakeSearchProvider` (plan §9).

Deliberately mixed: two real thread permalinks that hydrate against
``sources/fake/fixtures.py``, one comment permalink pointing at a thread
already listed (so deduplication has something to do), and one subreddit
landing page that names no post at all — the discovery step must drop it
without spending a hydrate call (plan §10 Phase 14.5 acceptance).
"""

from __future__ import annotations

from tripfinder.domain.ports import WebSearchHit

_BASE = "https://www.reddit.com/r/travel/comments"


def fixture_hits() -> list[WebSearchHit]:
    return [
        WebSearchHit(
            url=f"{_BASE}/post1/most_underrated_state_for_nature/",
            title="Most underrated state for nature? : r/travel",
            snippet="Alaska is amazing for nature, so underrated!",
        ),
        WebSearchHit(
            url=f"{_BASE}/post2/hidden_gem_national_parks/",
            title="Hidden gem national parks : r/travel",
            snippet="Alaska for sure, nothing beats it.",
        ),
        WebSearchHit(
            url=f"{_BASE}/post1/most_underrated_state_for_nature/c3/",
            title="Comment by u3 on Most underrated state for nature?",
            snippet="I'd say Oregon over Alaska honestly.",
        ),
        WebSearchHit(
            url="https://www.reddit.com/r/travel/",
            title="r/travel",
            snippet="A community about travel.",
        ),
    ]
