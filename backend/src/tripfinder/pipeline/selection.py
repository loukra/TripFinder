"""Which comments a document gives up (plan §2.14.2).

One rule, used by both the sequential retrieval step and 14.8's strands, so
that the corpus does not depend on which of the two fetched it.

The cap is what turns a bigger budget into a **broader** corpus rather than a
deeper one. §2.12.3's finding 1 measured the alternative directly: comments
were taken in document order until ``maxComments`` ran out, so thirteen
threads supplied an entire run's evidence while the rest were never opened.
Each thread is a different population — r/AskAnAmerican, r/hiking and
r/mountainbiking are not the same people answering — so a deeper sample of
the same threads buys mostly the same voices again. The measured run that
doubled its budget bore this out: respondents per analysed comment *fell*
from 0.496 to 0.427.
"""

from __future__ import annotations

from collections.abc import Sequence

from tripfinder.domain.models import Comment


def best_comments(comments: Sequence[Comment], cap: int) -> list[Comment]:
    """The ``cap`` highest-scoring comments, or all of them if there are fewer.

    Comments whose source reported no score keep the order the adapter left
    them in: unknown is not zero, but it has to sort somewhere, and "as
    fetched" invents no ranking of its own.
    """
    if cap <= 0 or len(comments) <= cap:
        return list(comments)
    return sorted(comments, key=lambda comment: -(comment.score or 0))[:cap]
