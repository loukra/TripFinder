"""Turning a web search result URL into a Reddit post id (plan §2.11).

Discovery's whole contribution is addresses: a search provider returns
URLs, and only the ones that name a *post* can be hydrated through
``/api/posts/ids``. Everything else — subreddit landing pages, user
profiles, wikis, other hosts entirely — is discarded here, before a hydrate
call is spent on it (plan §10 Phase 14.5 acceptance).

A comment permalink is *not* discarded: it still names its parent post, and
that post is what we want. Reading the id out of the path is the only
reliable way to get it, since the slug and the trailing comment id vary.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_REDDIT_HOSTS = frozenset(
    {
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "new.reddit.com",
        "np.reddit.com",
        "i.reddit.com",
        "m.reddit.com",
        "amp.reddit.com",
    }
)
_SHORTLINK_HOSTS = frozenset({"redd.it", "www.redd.it"})

# Reddit ids are base36. Six characters was the norm for years, seven is
# now common, and the length is not contractually fixed — so bound it
# loosely rather than pin it and silently drop future posts.
_POST_ID = re.compile(r"^[a-z0-9]{4,12}$")


def post_id_from_url(url: str) -> str | None:
    """The Reddit post id this URL addresses, or ``None`` if it addresses no post.

    Handles the ``/r/<sub>/comments/<id>/…`` and ``/comments/<id>/…`` forms
    on every Reddit host, plus ``redd.it/<id>`` shortlinks. Returns ``None``
    for any other host, and for Reddit URLs that name a subreddit, a user, a
    wiki page, or a search — none of which can be hydrated as a post.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None

    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    segments = [segment for segment in parts.path.split("/") if segment]

    if host in _SHORTLINK_HOSTS:
        # redd.it/<id> — the whole path is the id.
        return segments[0].lower() if len(segments) == 1 and _is_post_id(segments[0]) else None

    if host not in _REDDIT_HOSTS:
        return None

    try:
        index = segments.index("comments")
    except ValueError:
        return None

    candidate = segments[index + 1] if index + 1 < len(segments) else None
    return candidate.lower() if candidate is not None and _is_post_id(candidate) else None


def _is_post_id(segment: str) -> bool:
    return bool(_POST_ID.match(segment.lower()))
