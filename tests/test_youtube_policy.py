"""M3B.1 offline tests: pacing/anti-ban policy (no network, no sleeps)."""

from editor_assistant.workflow import youtube_policy as P


def test_defaults_are_conservative_and_offline():
    policy = P.load_policy({})
    assert policy.nightly_cap == 5
    assert policy.delay_min_s <= policy.delay_max_s
    assert policy.max_attempts == 5
    assert policy.block_cooldown_h == 12
    # OFF by default: the fallback sends the video id to an unrelated third
    # party and the live probe found 0/9 instances serving captions.
    assert policy.fallback_enabled is False
    assert policy.impersonate == ""  # optional extra, off by default
    assert policy.player_clients == P.DEFAULT_PLAYER_CLIENTS
    assert policy.invidious_instances == P.DEFAULT_INVIDIOUS_INSTANCES
    assert policy.warnings == ()  # a clean environment adjusts nothing


def test_env_overrides_are_read():
    policy = P.load_policy(
        {
            "YOUTUBE_NIGHTLY_CAP": "3",
            "YOUTUBE_DELAY_MIN_S": "90",
            "YOUTUBE_DELAY_MAX_S": "300",
            "YOUTUBE_MAX_ATTEMPTS": "2",
            "YOUTUBE_BLOCK_COOLDOWN_H": "24",
            "YOUTUBE_PLAYER_CLIENTS": "tv_simply, web_safari ,default",
            "YOUTUBE_IMPERSONATE": "chrome",
            "YOUTUBE_FALLBACK": "off",
            "YOUTUBE_INVIDIOUS_INSTANCES": "https://example.invalid",
        }
    )
    assert policy.nightly_cap == 3
    assert policy.delay_min_s == 90 and policy.delay_max_s == 300
    assert policy.max_attempts == 2
    assert policy.block_cooldown_h == 24
    assert policy.player_clients == ("tv_simply", "web_safari", "default")
    assert policy.impersonate == "chrome"
    assert policy.fallback_enabled is False
    assert policy.invidious_instances == ("https://example.invalid",)


def test_hand_edited_garbage_never_reaches_random_randint():
    policy = P.load_policy(
        {
            "YOUTUBE_DELAY_MIN_S": "not-a-number",
            "YOUTUBE_DELAY_MAX_S": "-5",
            "YOUTUBE_NIGHTLY_CAP": "99999",
            "YOUTUBE_MAX_ATTEMPTS": "0",
        }
    )
    assert policy.delay_min_s == P.DEFAULTS["delay_min_s"]
    assert policy.delay_max_s == P.DEFAULTS["delay_max_s"]
    assert policy.nightly_cap == P.MAX_NIGHTLY_CAP  # clamped, not unbounded
    assert policy.max_attempts == P.DEFAULTS["max_attempts"]


def test_a_clamped_value_is_reported_not_silent():
    """`YOUTUBE_NIGHTLY_CAP=99999` must not make the operator think it applied."""
    policy = P.load_policy({"YOUTUBE_NIGHTLY_CAP": "99999"})
    assert policy.nightly_cap == P.MAX_NIGHTLY_CAP
    (warning,) = policy.warnings
    assert "YOUTUBE_NIGHTLY_CAP=99999" in warning
    assert str(P.MAX_NIGHTLY_CAP) in warning


def test_malformed_and_below_minimum_values_are_reported():
    policy = P.load_policy({"YOUTUBE_MAX_ATTEMPTS": "lots", "YOUTUBE_BLOCK_COOLDOWN_H": "0"})
    assert policy.max_attempts == P.DEFAULTS["max_attempts"]
    assert policy.block_cooldown_h == P.DEFAULTS["block_cooldown_h"]
    joined = " | ".join(policy.warnings)
    assert "YOUTUBE_MAX_ATTEMPTS='lots'" in joined
    assert "YOUTUBE_BLOCK_COOLDOWN_H=0" in joined


def test_policy_warnings_never_leak_a_value_that_could_be_a_secret():
    policy = P.load_policy({"YOUTUBE_PROXY": "http://user:secret@proxy.example:8080"})
    assert "secret" not in " | ".join(policy.warnings)


def test_inverted_min_max_is_normalized():
    policy = P.load_policy({"YOUTUBE_DELAY_MIN_S": "300", "YOUTUBE_DELAY_MAX_S": "60"})
    assert policy.delay_min_s == policy.delay_max_s == 60
    assert any("delay_min_s=300" in warning for warning in policy.warnings)


def test_empty_player_clients_falls_back_to_default():
    policy = P.load_policy({"YOUTUBE_PLAYER_CLIENTS": " , "})
    assert policy.player_clients == P.DEFAULT_PLAYER_CLIENTS


def test_describe_never_leaks_a_proxy_credential():
    policy = P.load_policy({"YOUTUBE_PROXY": "http://user:secret@proxy.example:8080"})
    described = policy.describe()
    assert "secret" not in described
    assert "proxy: set" in described


def test_backoff_ladder_is_progressive_and_capped():
    delays = [P.backoff_seconds(n) for n in range(1, 7)]
    assert delays[:4] == list(P.BACKOFF_SECONDS)
    assert delays[4] == delays[5] == P.BACKOFF_SECONDS[-1]
    assert delays[0] < delays[1] < delays[2] < delays[3]


def test_backoff_of_zero_attempts_is_the_first_rung():
    assert P.backoff_seconds(0) == P.BACKOFF_SECONDS[0]
