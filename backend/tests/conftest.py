"""Suite-wide rules (plan §9).

**No live LLM or network calls in the normal test suite.** Every layer below
answers its question offline:

* unit — mocks and stubs, no I/O;
* integration — a real, throwaway Postgres, with a **faked source and LLM**;
* cassettes — recorded Arctic Shift JSON, replayed through a mock transport;
* evaluation — real model calls. Marked ``@pytest.mark.evaluation``, and
  excluded from every normal run by ``addopts`` in ``pyproject.toml``.

The distinction is what a test is actually asking. *Does our code behave
correctly?* is answerable offline — a mock transport still exercises real
request building, real schema conversion, and real error mapping, for zero
tokens. *Does the model behave well enough?* — accuracy, cost, latency — is
a measurement, and it belongs in the evaluation tier where it is opted into
deliberately (plan §10 Phase 15).

So: if a new test needs an ``LLMProvider``, reach for ``FakeLLMProvider`` or
stub the transport. Reaching for a real client means the test belongs in the
evaluation tier instead.

Opting in, with a key in the environment:

    set -a; . .env; set +a; uv run pytest -m evaluation

``make test`` deliberately does not load ``.env``, so no ordinary run can
reach a paid model even by accident.
"""

from __future__ import annotations
