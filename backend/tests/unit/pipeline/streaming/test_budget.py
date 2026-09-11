"""The shared purse (plan §2.14.2, §10 Phase 14.8).

What is proven here: a strand never waits for an answer; one document
cannot spend the run; §4.5's topical material gets a reserved share rather
than leftovers; and every refusal is counted, because a corpus that shrank
for budget reasons must stay distinguishable from one that was genuinely
small (§0.1).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tripfinder.pipeline.streaming.budget import CommentClass, RunBudget

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _budget(**overrides: object) -> RunBudget:
    settings: dict[str, object] = {
        "max_comments": 1000,
        "max_analysis_items": 500,
        "max_concurrent_calls": 8,
    }
    settings.update(overrides)
    return RunBudget(**settings)  # type: ignore[arg-type]


class TestTheCommentAllowance:
    def test_a_strand_gets_what_it_asks_for_while_there_is_room(self) -> None:
        budget = _budget()
        assert budget.reserve_comments(60, comment_class=CommentClass.COUNTED) == 60

    def test_no_single_document_can_spend_the_run(self) -> None:
        """§2.12.3's finding 1, as a rule rather than an observation: one
        4000-comment thread took the whole budget in document order."""
        budget = _budget(max_comments=1000, topical_quota=0.0)
        assert budget.reserve_comments(4000, comment_class=CommentClass.COUNTED) == 1000
        assert budget.reserve_comments(60, comment_class=CommentClass.COUNTED) == 0

    def test_a_refusal_is_counted_not_just_denied(self) -> None:
        budget = _budget(max_comments=100, topical_quota=0.0)
        budget.reserve_comments(80, comment_class=CommentClass.COUNTED)
        budget.reserve_comments(50, comment_class=CommentClass.COUNTED)
        assert budget.comments_refused[CommentClass.COUNTED] == 30

    def test_asking_for_nothing_is_not_an_error(self) -> None:
        assert _budget().reserve_comments(0, comment_class=CommentClass.COUNTED) == 0


class TestTheTopicalQuota:
    def test_evidence_material_cannot_spend_the_counted_corpus(self) -> None:
        """Plan §4.5's binding rule: topical threads may not buy capacity
        away from the corpus that decides the ranking."""
        budget = _budget(max_comments=1000, topical_quota=0.20)
        assert budget.reserve_comments(1000, comment_class=CommentClass.EVIDENCE) == 200
        assert budget.reserve_comments(800, comment_class=CommentClass.COUNTED) == 800

    def test_the_counted_corpus_cannot_starve_the_evidence_one(self) -> None:
        """The failure this replaces: in the measured run polling documents
        consumed everything first and `topical_comments_retrieved` was 0."""
        budget = _budget(max_comments=1000, topical_quota=0.20)
        assert budget.reserve_comments(5000, comment_class=CommentClass.COUNTED) == 800
        assert budget.reserve_comments(150, comment_class=CommentClass.EVIDENCE) == 150

    def test_a_zero_quota_gives_evidence_nothing_rather_than_everything(self) -> None:
        budget = _budget(max_comments=1000, topical_quota=0.0)
        assert budget.reserve_comments(10, comment_class=CommentClass.EVIDENCE) == 0


class TestAdmittingAnalysisCalls:
    def test_calls_are_admitted_up_to_the_analysis_item_budget(self) -> None:
        budget = _budget(max_analysis_items=40)
        assert budget.admit_analysis_batch(20) is True
        assert budget.admit_analysis_batch(20) is True
        assert budget.admit_analysis_batch(20) is False
        assert budget.analysis_items_spent == 40

    def test_a_batch_refused_for_budget_is_not_confused_with_one_refused_for_time(self) -> None:
        """Two different causes with two different fixes, so §0.1 wants them
        counted apart, not merged into 'not analysed'."""
        budget = _budget(max_analysis_items=20)
        budget.admit_analysis_batch(20)
        budget.admit_analysis_batch(20)
        assert budget.items_refused_for_budget == 20
        assert budget.items_refused_for_deadline == 0

    def test_nothing_is_started_after_the_dispatch_deadline(self) -> None:
        clock = NOW
        budget = _budget(deadline=NOW + timedelta(seconds=30), clock=lambda: clock)
        assert budget.admit_analysis_batch(20) is True
        clock = NOW + timedelta(seconds=31)
        assert budget.admit_analysis_batch(20) is False
        assert budget.items_refused_for_deadline == 20

    def test_a_refused_batch_spends_nothing(self) -> None:
        """A refusal that still charged the account would make the budget
        shrink for work never done."""
        clock = NOW + timedelta(seconds=99)
        budget = _budget(deadline=NOW, clock=lambda: clock)
        budget.admit_analysis_batch(20)
        assert budget.analysis_items_spent == 0
