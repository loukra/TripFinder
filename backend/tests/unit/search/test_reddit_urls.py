"""Resolving a search result URL to a Reddit post id (plan §2.11).

This is the discard gate: everything that reaches hydration comes through
here, and everything that does not name a post must be rejected *before* a
request is spent on it (plan §10 Phase 14.5 acceptance).
"""

from __future__ import annotations

import pytest

from tripfinder.search.reddit_urls import post_id_from_url


class TestUrlsThatNameAPost:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.reddit.com/r/travel/comments/1wbve58/most_underrated_state/",
            "https://reddit.com/r/travel/comments/1wbve58/most_underrated_state/",
            "https://old.reddit.com/r/travel/comments/1wbve58/most_underrated_state/",
            "https://np.reddit.com/r/travel/comments/1wbve58/x/",
            "https://www.reddit.com/r/travel/comments/1wbve58",
            "https://www.reddit.com/comments/1wbve58/",
            "https://redd.it/1wbve58",
            "  https://www.reddit.com/r/travel/comments/1wbve58/x/  ",
        ],
    )
    def test_the_post_id_is_read_out_of_the_path(self, url: str) -> None:
        assert post_id_from_url(url) == "1wbve58"

    def test_a_comment_permalink_resolves_to_its_parent_post(self) -> None:
        """A comment link still names the thread we want to hydrate."""
        url = "https://www.reddit.com/r/travel/comments/1wbve58/most_underrated/p8t0od8/"

        assert post_id_from_url(url) == "1wbve58"

    def test_a_query_string_or_fragment_does_not_confuse_it(self) -> None:
        url = "https://www.reddit.com/r/travel/comments/1wbve58/x/?sort=top&utm_source=share#c1"

        assert post_id_from_url(url) == "1wbve58"

    def test_the_id_is_normalised_to_lower_case(self) -> None:
        url = "https://www.reddit.com/r/travel/comments/1WBVE58/x/"

        assert post_id_from_url(url) == "1wbve58"


class TestUrlsThatNameNoPost:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.reddit.com/r/travel/",
            "https://www.reddit.com/r/travel/top/?t=year",
            "https://www.reddit.com/user/someone/",
            "https://www.reddit.com/r/travel/wiki/index/",
            "https://www.reddit.com/search/?q=underrated",
            "https://www.reddit.com/",
            "https://example.com/r/travel/comments/1wbve58/x/",
            "https://notreddit.com/r/travel/comments/1wbve58/x/",
            "https://redd.it/",
            "https://redd.it/1wbve58/extra/",
            "not a url at all",
            "",
        ],
    )
    def test_they_are_discarded(self, url: str) -> None:
        assert post_id_from_url(url) is None

    def test_a_lookalike_host_is_not_reddit(self) -> None:
        """``reddit.com.evil.test`` is a different site, and must not be hydrated."""
        assert post_id_from_url("https://reddit.com.evil.test/r/t/comments/1wbve58/x/") is None

    def test_a_comments_segment_with_nothing_after_it_names_no_post(self) -> None:
        assert post_id_from_url("https://www.reddit.com/r/travel/comments/") is None

    def test_a_segment_too_short_to_be_an_id_is_rejected(self) -> None:
        assert post_id_from_url("https://www.reddit.com/r/travel/comments/ab/x/") is None
