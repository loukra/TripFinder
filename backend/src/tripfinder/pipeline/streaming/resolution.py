"""Names resolved while the run is still reading (plan §2.13, §2.14.2).

Plan §2.13 forbids a snapshot from calling the model — it runs after every
analysis batch, and a batch of model calls per snapshot is not a preview,
it is a second run. Entity resolution was therefore left with only its
deterministic half: normalisation plus the alias table.

That half is a catalogue, and the catalogue holds one tier — the fifty US
states. So for every question about anything else, a snapshot resolved
**nothing**, ranked nothing, and showed an empty list until the run
finished. Measured on a real run about national parks: 1120 surface forms,
``entity_forms_resolved_by_rule: 0``, and the first ranking the user saw was
the final one, six and a half minutes in. A provisional ranking that is
structurally empty for every question but one is not a feature with a gap,
it is a feature that does not exist.

The fix is not to let the snapshot ask. It is to have **already asked**.

A run resolves the same names whether it does so at the end or as it goes,
so this cache holds what the model has already said, filled in the
background while analysis continues. A snapshot reads it and calls nothing,
which keeps §2.13's rule exactly as it was written. The final resolution
step reads it too, and asks only for what is missing — so the sequential
tail that used to run after all analysis had stopped is mostly gone before
it starts.

**Forms are asked in whole batches.** A cache that asked after every
analysis batch would turn thirteen calls into seventy, and cost is the
other complaint this codebase has to answer. Whatever does not fill a batch
waits for the next one, and the final step sweeps up the remainder — the
same remainder it always asked for.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from tripfinder.analysis.entity_resolution import ResolvedName


@dataclass
class ResolutionCache:
    """What the model has already been asked, and what it said.

    ``asked`` is deliberately wider than ``answers``: a form the model
    returned nothing for is *settled*, not pending, and asking again every
    time a snapshot is taken would spend money to be told the same thing.
    """

    answers: dict[str, ResolvedName] = field(default_factory=dict)
    asked: set[str] = field(default_factory=set)

    def knows(self, surface_form: str) -> bool:
        """Whether this form has already been put to the model."""
        return surface_form in self.asked

    def answer(self, surface_form: str) -> ResolvedName | None:
        """What the model said, or ``None`` — which it also says, by saying nothing."""
        return self.answers.get(surface_form)

    def remember(self, asked: Iterable[str], answers: Mapping[str, ResolvedName]) -> None:
        self.asked.update(asked)
        self.answers.update(answers)

    def __len__(self) -> int:
        return len(self.asked)
