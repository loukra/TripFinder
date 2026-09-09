from tripfinder.sources.arctic_shift.config import ArcticShiftConfig


def test_defaults_match_plan_8_politeness_ceiling() -> None:
    config = ArcticShiftConfig()

    assert config.base_url == "https://arctic-shift.photon-reddit.com"
    assert config.requests_per_second == 2.0
    assert config.bot_denylist == []


def test_every_field_is_overridable() -> None:
    config = ArcticShiftConfig(
        base_url="https://example.test",
        user_agent="custom-agent",
        requests_per_second=5.0,
        max_retries=1,
        backoff_base_seconds=0.5,
        timeout_seconds=10.0,
        health_check_timeout_seconds=2.0,
        page_size=50,
        bot_denylist=["some_known_bot"],
    )

    assert config.base_url == "https://example.test"
    assert config.max_retries == 1
    assert config.page_size == 50
    assert config.bot_denylist == ["some_known_bot"]
