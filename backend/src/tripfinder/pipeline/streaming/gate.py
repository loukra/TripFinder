"""The health gate (plan §2.14.2).

§8.1's assessment used to be a barrier: retrieval finished, the corpus was
weighed, and only then did the expensive step run on it. That ordering was
not bureaucracy — it is what stops a run paying to analyse a corpus a broken
source produced, and §0.1's rule that a failure must never look like a
finding is what it protects.

A pipeline cannot keep the barrier, so it keeps the guarantee differently:
**no analysis call is admitted until the source has proved itself**, by
returning ``minPostsRetrieved`` documents. After that the assessment is
re-read as the run proceeds, which ``assess_source_health`` already supports
— it is a pure function over the recorder's snapshot.

The gate must never be the reason a run hangs, which is the whole of its
design. It opens on success, and it also opens once discovery has finished
and no fetch is still outstanding: a run that will never reach the floor
finds that out and proceeds to fail honestly, rather than waiting for a
document that is not coming.
"""

from __future__ import annotations

import asyncio


class HealthGate:
    """Holds analysis until the source has produced enough to be trusted."""

    def __init__(self, *, minimum_documents: int) -> None:
        self._minimum = minimum_documents
        self._successes = 0
        self._fetches_outstanding = 0
        self._discovery_finished = False
        self._open = asyncio.Event()
        if minimum_documents <= 0:
            self._open.set()

    def fetch_started(self) -> None:
        self._fetches_outstanding += 1

    def fetch_finished(self, *, ok: bool) -> None:
        self._fetches_outstanding -= 1
        if ok:
            self._successes += 1
        self._settle()

    def discovery_finished(self) -> None:
        self._discovery_finished = True
        self._settle()

    async def wait(self) -> None:
        await self._open.wait()

    @property
    def is_open(self) -> bool:
        return self._open.is_set()

    def _settle(self) -> None:
        if self._successes >= self._minimum:
            self._open.set()
        elif self._discovery_finished and self._fetches_outstanding <= 0:
            # Nothing more is coming. Opening lets the run reach §8.1's
            # assessment, which is the thing entitled to fail it.
            self._open.set()
