"""The reuse key: what makes two questions the same question (plan §2.15).

Raw text cannot be the key. *"best states for nature"* and *"Best states for
nature?"* are one question and would miss each other, and two people asking
the same thing in different words would each pay for the same hundred and
thirty model calls. The key is the **plan** — what Query Understanding
decided the question *means* — which costs exactly one call to obtain and
has the property raw text cannot have: two differently worded questions that
mean the same thing land on the same answer.

**What is in the key, and what is deliberately not.**

In: the normalized query, the scope, the entity granularity, the topic, and
the criteria. Plan §2.15 names the first four; criteria are here because a
question asking for *quiet* parks and one asking for *cheap* parks are
answered by different counts over the same corpus, and returning one for the
other would be a wrong answer wearing a right answer's clothes.

Out: ``seed_queries`` and ``candidate_subreddits``. Both are the model's
*suggestions for how to go looking*, not statements about what was asked,
and discovery is an agentic loop that proposes different queries every run
(§2.14.4). Including them would make the fingerprint change on almost every
run and the cache would never hit — a feature that silently does nothing,
which is worse than one that is absent.

Out too: ``granularity_confidence``. How sure the model was is a fact about
the model on that day, not about the question.

The digest is a plain SHA-256 over a canonical JSON encoding. It is a
lookup key, never a secret and never a security boundary — a collision
would return the wrong answer, which is why the encoding is explicit and
ordered rather than ``hash()`` over a tuple, whose value does not survive a
process restart.
"""

from __future__ import annotations

import hashlib
import json
import re

from tripfinder.domain.models import ResearchPlan

_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCTUATION = "?!.,;: \t\n"

FINGERPRINT_VERSION = 1
"""Bumped when the encoding below changes.

It is part of the digest, so changing what the key covers retires every
fingerprint already stored instead of matching a new plan against an old
key that meant something else. Old rows keep their answers and simply stop
being reusable, which is the safe direction.
"""


def _normalize(text: str) -> str:
    """Case, spacing and a trailing question mark are not part of a question."""
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return collapsed.rstrip(_TRAILING_PUNCTUATION).casefold()


def plan_fingerprint(plan: ResearchPlan) -> str:
    """The reuse key for a plan: equal plans give equal keys, and only those.

    Criteria are sorted, because *"quiet, cheap"* and *"cheap, quiet"* ask
    for the same thing and the model does not promise an order. Duplicates
    are collapsed for the same reason.
    """
    payload = {
        "version": FINGERPRINT_VERSION,
        "normalized_query": _normalize(plan.normalized_query),
        "scope_type": _normalize(plan.scope.type),
        "scope_value": _normalize(plan.scope.value),
        "entity_granularity": plan.entity_granularity.value,
        "topic": _normalize(plan.topic),
        "criteria": sorted({_normalize(criterion) for criterion in plan.criteria}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
