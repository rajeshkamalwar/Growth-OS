from dataclasses import FrozenInstanceError, fields
from enum import StrEnum

import pytest

from growth_os.robots import (
    RobotsDecision,
    RobotsDecisionReason,
    RobotsPolicyError,
    RobotsPolicyErrorCode,
    evaluate_robots,
)


def decision(
    allowed: bool,
    reason: RobotsDecisionReason,
    agent: str | None = None,
    rule: str | None = None,
) -> RobotsDecision:
    return RobotsDecision(allowed, reason, agent, rule)


def test_public_contract_is_value_backed_immutable_and_keyword_only() -> None:
    assert issubclass(RobotsPolicyErrorCode, StrEnum)
    assert issubclass(RobotsDecisionReason, StrEnum)
    assert [field.name for field in fields(RobotsDecision)] == [
        "allowed",
        "reason",
        "matched_user_agent",
        "matched_rule",
    ]
    result = evaluate_robots(robots_txt=b"", target_path="/")
    assert result == decision(True, RobotsDecisionReason.NO_MATCHING_GROUP)
    with pytest.raises(FrozenInstanceError):
        result.allowed = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        evaluate_robots(b"", "/")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("robots_txt", "target_path", "code", "message"),
    [
        ("", "/", RobotsPolicyErrorCode.INVALID_INPUT, "Invalid robots policy input."),
        (bytearray(), "/", RobotsPolicyErrorCode.INVALID_INPUT, "Invalid robots policy input."),
        (b"", b"/", RobotsPolicyErrorCode.INVALID_INPUT, "Invalid robots policy input."),
        (b"\xff", "/", RobotsPolicyErrorCode.INVALID_ENCODING, "Invalid robots.txt encoding."),
        (b" " * 512_001, "/", RobotsPolicyErrorCode.TOO_LARGE, "Robots.txt is too large."),
    ],
)
def test_errors_have_stable_redacted_codes_and_messages(
    robots_txt: object,
    target_path: object,
    code: RobotsPolicyErrorCode,
    message: str,
) -> None:
    with pytest.raises(RobotsPolicyError) as caught:
        evaluate_robots(robots_txt=robots_txt, target_path=target_path)  # type: ignore[arg-type]
    assert caught.value.code is code
    assert str(caught.value) == message
    assert caught.value.args == (message,)


def test_size_boundary_is_checked_before_encoding() -> None:
    assert evaluate_robots(robots_txt=b" " * 512_000, target_path="/").allowed
    with pytest.raises(RobotsPolicyError) as caught:
        evaluate_robots(robots_txt=b" " * 512_000 + b"\xff", target_path="/")
    assert caught.value.code is RobotsPolicyErrorCode.TOO_LARGE


@pytest.mark.parametrize(
    "target",
    [
        "",
        "relative",
        "//authority/path",
        "/path#fragment",
        "/bad%",
        "/bad%2",
        "/bad%XZ",
        "/\x00",
        "/\x1f",
        "/\x7f",
        "/\ud800",
    ],
)
def test_invalid_target_paths_are_rejected(target: str) -> None:
    with pytest.raises(RobotsPolicyError) as caught:
        evaluate_robots(robots_txt=b"", target_path=target)
    assert caught.value.code is RobotsPolicyErrorCode.INVALID_INPUT


def test_exact_groups_merge_and_override_merged_wildcard_groups() -> None:
    robots = b"""User-Agent: *
Disallow: /wild-one
user-agent: *
Disallow: /wild-two
USER-AGENT: growthosbot
Disallow: /private
User-Agent: Other
User-Agent: GrowthOSBot
Allow: /private/public
"""
    assert evaluate_robots(robots_txt=robots, target_path="/private/x") == decision(
        False, RobotsDecisionReason.MATCHED_DISALLOW, "GrowthOSBot", "/private"
    )
    assert evaluate_robots(robots_txt=robots, target_path="/private/public") == decision(
        True, RobotsDecisionReason.MATCHED_ALLOW, "GrowthOSBot", "/private/public"
    )
    assert evaluate_robots(robots_txt=robots, target_path="/wild-one") == decision(
        True, RobotsDecisionReason.NO_MATCHING_RULE, "GrowthOSBot"
    )


def test_wildcard_groups_merge_only_as_fallback_and_product_match_is_exact() -> None:
    robots = b"User-agent: *\rDisallow: /a\nuser-agent:\t*\r\nDisallow: /b\r\n"
    assert evaluate_robots(robots_txt=robots, target_path="/a") == decision(
        False, RobotsDecisionReason.MATCHED_DISALLOW, "*", "/a"
    )
    assert evaluate_robots(robots_txt=robots, target_path="/b") == decision(
        False, RobotsDecisionReason.MATCHED_DISALLOW, "*", "/b"
    )
    non_matches = b"User-agent: Growth\nDisallow: /\nUser-agent: GrowthOSBotMobile\nDisallow: /\n"
    assert evaluate_robots(robots_txt=non_matches, target_path="/") == decision(
        True, RobotsDecisionReason.NO_MATCHING_GROUP
    )


def test_comments_ascii_whitespace_unknown_records_and_group_state() -> None:
    robots = b""" allow: /outside
User-Agent: GrowthOSBot # exact
Sitemap: https://example.test/sitemap.xml
Host: example.test
Crawl-delay: 99
Request-rate: 1/99
Disalow: /
Disallow:\t/private # comment

Unknown: ignored
User-Agent: Other
Disallow: /
"""
    assert evaluate_robots(robots_txt=robots, target_path="/private") == decision(
        False, RobotsDecisionReason.MATCHED_DISALLOW, "GrowthOSBot", "/private"
    )


def test_only_cr_lf_and_crlf_are_record_separators_and_encoded_hash_is_data() -> None:
    robots = b"User-agent: GrowthOSBot\vDisallow: /vertical-tab\nDisallow: /hash%23value\n"
    assert evaluate_robots(robots_txt=robots, target_path="/vertical-tab").reason is (
        RobotsDecisionReason.NO_MATCHING_GROUP
    )
    valid = b"User-agent: GrowthOSBot\nDisallow: /hash%23value\n"
    assert not evaluate_robots(robots_txt=valid, target_path="/hash%23value").allowed


@pytest.mark.parametrize(
    "invalid_line",
    [
        b"nocolon",
        b"User-agent: Growth.OS.Bot",
        b"User-agent: GrowthOSBot/1.0",
        b"User-agent: ",
    ],
)
def test_invalid_lines_and_tokens_are_ignored(invalid_line: bytes) -> None:
    robots = invalid_line + b"\nDisallow: /\n"
    assert (
        evaluate_robots(robots_txt=robots, target_path="/").reason
        is RobotsDecisionReason.NO_MATCHING_GROUP
    )


def test_invalid_and_empty_rules_are_ignored_without_terminating_group() -> None:
    robots = b"""User-agent: GrowthOSBot
Disallow:
Allow: *.gif$
Disallow: relative
Allow: /bad%
Allow: /bad space
Other: value
Disallow: /valid
"""
    assert evaluate_robots(robots_txt=robots, target_path="/image.gif") == decision(
        True, RobotsDecisionReason.NO_MATCHING_RULE, "GrowthOSBot"
    )
    assert not evaluate_robots(robots_txt=robots, target_path="/valid").allowed


@pytest.mark.parametrize(
    ("rule", "target", "allowed"),
    [
        ("/prefix", "/prefix/child", False),
        ("/fish*heads", "/fishXYZheads/more", False),
        ("/fish*heads", "/fishheads", False),
        ("/exact$", "/exact", False),
        ("/exact$", "/exact/more", True),
        ("/*.gif$", "/images/cat.gif", False),
        ("/*.gif$", "/images/cat.gif?x=1", True),
        ("/Case", "/case", True),
        ("/search?secret", "/search?secret=yes", False),
    ],
)
def test_prefix_wildcard_anchor_case_and_query_matching(
    rule: str, target: str, allowed: bool
) -> None:
    robots = f"User-agent: GrowthOSBot\nDisallow: {rule}\n".encode()
    assert evaluate_robots(robots_txt=robots, target_path=target).allowed is allowed


def test_percent_encoded_star_and_dollar_are_literals() -> None:
    robots = b"User-agent: GrowthOSBot\nDisallow: /literal%2astar%24\n"
    assert not evaluate_robots(robots_txt=robots, target_path="/literal%2Astar%24").allowed
    assert evaluate_robots(robots_txt=robots, target_path="/literalZZstar").allowed


@pytest.mark.parametrize(
    ("rule", "target", "normalized"),
    [
        ("/caf\u00e9", "/caf%C3%A9", "/caf%C3%A9"),
        ("/caf%c3%a9", "/caf\u00e9", "/caf%C3%A9"),
        ("/%7euser", "/~user", "/~user"),
        ("/a%2fb", "/a%2Fb", "/a%2Fb"),
        ("/a//b", "/a//b", "/a//b"),
        ("/a/../b", "/a/../b", "/a/../b"),
    ],
)
def test_rfc_octet_normalization_preserves_required_structure(
    rule: str, target: str, normalized: str
) -> None:
    robots = f"User-agent: GrowthOSBot\nDisallow: {rule}\n".encode()
    assert evaluate_robots(robots_txt=robots, target_path=target) == decision(
        False, RobotsDecisionReason.MATCHED_DISALLOW, "GrowthOSBot", normalized
    )


def test_reserved_encoded_separator_is_not_decoded_or_equal_to_raw_separator() -> None:
    robots = b"User-agent: GrowthOSBot\nDisallow: /a%2Fb\n"
    assert evaluate_robots(robots_txt=robots, target_path="/a/b").allowed


def test_slashes_and_dot_segments_are_not_collapsed_or_resolved() -> None:
    robots = b"User-agent: GrowthOSBot\nDisallow: /a//b\nDisallow: /a/../c\n"
    assert evaluate_robots(robots_txt=robots, target_path="/a/b").allowed
    assert evaluate_robots(robots_txt=robots, target_path="/c").allowed


def test_empty_exact_group_is_selected_with_no_matching_rule() -> None:
    robots = b"User-agent: GrowthOSBot\n"
    assert evaluate_robots(robots_txt=robots, target_path="/") == decision(
        True, RobotsDecisionReason.NO_MATCHING_RULE, "GrowthOSBot"
    )


def test_longest_normalized_octet_rule_wins_and_allow_wins_tie() -> None:
    robots = """User-agent: GrowthOSBot
Disallow: /caf%C3%A9
Allow: /caf\u00e9/menu
Disallow: /same
Allow: /same
Allow: /same
""".encode()
    assert evaluate_robots(robots_txt=robots, target_path="/caf\u00e9/menu") == decision(
        True, RobotsDecisionReason.MATCHED_ALLOW, "GrowthOSBot", "/caf%C3%A9/menu"
    )
    assert evaluate_robots(robots_txt=robots, target_path="/same") == decision(
        True, RobotsDecisionReason.MATCHED_ALLOW, "GrowthOSBot", "/same"
    )


def test_equal_directive_ties_have_deterministic_first_rule_provenance() -> None:
    robots = b"""User-agent: GrowthOSBot
Disallow: /a*c
Disallow: /ab*
"""
    expected = decision(False, RobotsDecisionReason.MATCHED_DISALLOW, "GrowthOSBot", "/a*c")
    assert evaluate_robots(robots_txt=robots, target_path="/abc") == expected
    assert evaluate_robots(robots_txt=robots, target_path="/abc") == expected


def test_no_group_no_rule_and_robots_uri_provenance() -> None:
    no_group = evaluate_robots(robots_txt=b"User-agent: Other\nDisallow: /", target_path="/")
    assert no_group == decision(True, RobotsDecisionReason.NO_MATCHING_GROUP)
    robots = b"User-agent: GrowthOSBot\nDisallow: /private\n"
    assert evaluate_robots(robots_txt=robots, target_path="/public") == decision(
        True, RobotsDecisionReason.NO_MATCHING_RULE, "GrowthOSBot"
    )
    for target in ("/robots.txt", "/robots.txt?x=1"):
        result = evaluate_robots(robots_txt=b"User-agent: *\nDisallow: /", target_path=target)
        assert result == decision(True, RobotsDecisionReason.ROBOTS_URI)
    assert not evaluate_robots(
        robots_txt=b"User-agent: *\nDisallow: /", target_path="/robots.txt/child"
    ).allowed
    assert not evaluate_robots(
        robots_txt=b"User-agent: *\nDisallow: /", target_path="/Robots.txt"
    ).allowed


def test_large_adversarial_input_is_deterministic_and_does_not_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    robots = (b"User-agent: GrowthOSBot\nDisallow: /*a*a*a*a*a*a*a*a*$\n" * 4_000)[:512_000]
    first = evaluate_robots(robots_txt=robots, target_path="/" + "a" * 5_000)
    second = evaluate_robots(robots_txt=robots, target_path="/" + "a" * 5_000)
    assert first == second
    assert caplog.records == []
